import datetime
import logging
import re
from rest_framework.views import APIView
from rest_framework.response import Response
from django.conf import settings
from django.http import HttpResponse
from twilio.twiml.messaging_response import MessagingResponse
from apps.standup.permissions import TwilioSignaturePermission
from apps.standup.models import StandupEntry

logger = logging.getLogger(__name__)

NEXT_MEETING_TRIGGERS = {'next meeting', 'next', "what's next", 'whats next'}
FREE_TODAY_TRIGGERS = {'free today', 'am i free', 'free time', 'when am i free'}
HELP_TRIGGERS = {'help', '?', '/help'}

MENU_TRIGGERS = {'menu', 'options', 'calendar', '0'}

MENU_TEXT = (
    "\U0001f4c5 Calendar menu:\n"
    "1. Today's meetings\n"
    "2. Tomorrow's meetings\n"
    "3. This week\n"
    "4. Next meeting\n"
    "5. Free time today\n"
    "6. Help\n"
    "7. Set timezone\n"
    "\n"
    "Send 0 or 'menu' anytime to return here."
)

TIMEZONE_SHORTCUTS = {
    'jerusalem': 'Asia/Jerusalem',
    'tel aviv': 'Asia/Jerusalem',
    'london': 'Europe/London',
    'nyc': 'America/New_York',
    'new york': 'America/New_York',
}

TIMEZONE_SUB_MENU = (
    "\U0001f550 Set your timezone. Reply with your city:\n"
    "\u2022 Jerusalem\n"
    "\u2022 London\n"
    "\u2022 New York\n"
    "\n"
    "Or type: set timezone Europe/Paris (for other cities)"
)

WORKDAY_START_HOUR = 8
WORKDAY_END_HOUR = 19
MIN_FREE_SLOT_MINUTES = 30

HELP_TEXT = (
    "\U0001f4c5 Your calendar assistant:\n"
    "\n"
    "Queries:\n"
    '\u2022 "today" / "meetings" \u2014 today\'s schedule\n'
    '\u2022 "tomorrow" \u2014 tomorrow\'s meetings\n'
    '\u2022 "friday" / "meetings thursday" \u2014 any day this week\n'
    '\u2022 "next monday" \u2014 following week\n'
    '\u2022 "this week" \u2014 full week view (Mon\u2013Sun)\n'
    '\u2022 "next meeting" \u2014 your next upcoming event\n'
    '\u2022 "free today" \u2014 free slots today\n'
    "\n"
    "Create:\n"
    '\u2022 "block tomorrow 2-4pm" \u2014 block time\n'
    '\u2022 "block friday 10am Deep work" \u2014 named block\n'
    "\n"
    "Accounts:\n"
    '\u2022 "connect calendar" \u2014 add another Google account\n'
    '\u2022 "my calendars" \u2014 list connected accounts\n'
    '\u2022 "remove calendar [email or label]" \u2014 remove an account\n'
    "\n"
    "Settings:\n"
    '\u2022 "set digest 7:30am" \u2014 change briefing time\n'
    '\u2022 "set digest off" \u2014 turn off morning digest\n'
    '\u2022 "set timezone Europe/London" \u2014 set your timezone\n'
    "\n"
    "Send 0 or 'menu' to see the quick menu."
)

# Short hint shown when a connected user sends something unrecognised
_UNRECOGNIZED_HINT = "Didn't understand that. Send *0* for the menu."


class WhatsAppWebhookView(APIView):
    permission_classes = [TwilioSignaturePermission]

    def post(self, request, *args, **kwargs):
        from_number = request.data.get('From', '')
        body = request.data.get('Body', '')
        body_lower = body.strip().lower()

        # Log every incoming webhook request
        logger.info(
            'Incoming webhook: phone=%s body=%.50r',
            from_number,
            body,
        )

        # Handle /summary command BEFORE any saving
        if body_lower == '/summary':
            logger.info('Routing to summary handler: phone=%s', from_number)
            return self._handle_summary(from_number)

        # Handle help command
        if body_lower in HELP_TRIGGERS:
            logger.info('Routing to help handler: phone=%s', from_number)
            return self._handle_help()

        # Handle menu (including '0' shortcut)
        if body_lower in MENU_TRIGGERS:
            logger.info('Routing to menu handler: phone=%s', from_number)
            return self._handle_menu()

        # Handle digit shortcuts 1-7
        if body.strip() in {'1', '2', '3', '4', '5', '6', '7'}:
            logger.info('Routing digit %s for phone=%s', body.strip(), from_number)
            return self._handle_menu_digit(request, from_number, body.strip())

        # Handle connect calendar / add calendar
        if body_lower in ('connect calendar', 'add calendar'):
            logger.info('Routing to connect_calendar handler: phone=%s', from_number)
            return self._handle_connect_calendar(request, from_number)

        # Handle my calendars
        if body_lower == 'my calendars':
            logger.info('Routing to my_calendars handler: phone=%s', from_number)
            return self._handle_my_calendars(from_number)

        # Handle remove calendar [email or label]
        if body_lower.startswith('remove calendar'):
            logger.info('Routing to remove_calendar handler: phone=%s', from_number)
            return self._handle_remove_calendar(from_number, body_lower)

        # Handle timezone city shortcuts (Jerusalem, London, NYC, New York)
        if body_lower in TIMEZONE_SHORTCUTS:
            tz_name = TIMEZONE_SHORTCUTS[body_lower]
            logger.info('Routing to timezone shortcut: phone=%s tz=%s', from_number, tz_name)
            return self._handle_set_timezone(from_number, f'set timezone {tz_name}')

        # Handle set timezone command
        if body_lower.startswith('set timezone '):
            logger.info('Routing to set_timezone handler: phone=%s', from_number)
            return self._handle_set_timezone(from_number, body)

        # Handle set digest command
        if body_lower.startswith('set digest'):
            logger.info('Routing to set_digest handler: phone=%s', from_number)
            return self._handle_set_digest(from_number, body_lower)

        # Handle block time command
        if body_lower.startswith('block ') or body_lower.startswith('add meeting '):
            logger.info('Routing to block_command handler: phone=%s', from_number)
            return self._handle_block_command(from_number, body)

        # Handle YES confirmation for pending block
        if body.strip().upper() == 'YES':
            logger.info('Routing to YES confirmation handler: phone=%s', from_number)
            yes_result = self._handle_yes_confirmation(from_number)
            if yes_result is not None:
                return yes_result

        # Handle instant queries: next meeting
        if body_lower in NEXT_MEETING_TRIGGERS:
            logger.info('Routing to next_meeting query: phone=%s', from_number)
            result = self._try_next_meeting(from_number)
            if result is not None:
                return result

        # Handle instant queries: free today
        if body_lower in FREE_TODAY_TRIGGERS:
            logger.info('Routing to free_today query: phone=%s', from_number)
            result = self._try_free_today(from_number)
            if result is not None:
                return result

        # Handle day queries
        day_result = self._try_day_query(from_number, body_lower)
        if day_result is not None:
            return day_result

        if not body.strip():
            logger.warning('Received empty body from phone=%s', from_number)
            return Response({'error': 'Body cannot be empty.'}, status=400)

        # --- Fallthrough: unrecognized message ---
        logger.info(
            'Unrecognized message, routing to onboarding/hint: phone=%s body=%.50r',
            from_number,
            body,
        )
        return self._handle_unrecognized(request, from_number)

    # ------------------------------------------------------------------ #
    # Multi-account calendar commands
    # ------------------------------------------------------------------ #

    def _handle_connect_calendar(self, request, from_number):
        """Reply with the OAuth link for connecting another Google Calendar account."""
        webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', '')
        if webhook_base_url:
            auth_url = webhook_base_url.rstrip('/') + f'/calendar/auth/start/?phone={from_number}'
        else:
            auth_url = request.build_absolute_uri(f'/calendar/auth/start/?phone={from_number}')

        response = MessagingResponse()
        response.message(
            f'Connect your Google Calendar here:\n{auth_url}\n\n'
            '\u26a0\ufe0f Google may show a safety warning. Tap \'Advanced\' \u2192 \'Go to app (unsafe)\' to continue.\n\n'
            'To add a second account, visit the same link after connecting the first.'
        )
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_my_calendars(self, from_number):
        """List all connected CalendarToken rows for this phone."""
        from apps.calendar_bot.models import CalendarToken

        tokens = list(
            CalendarToken.objects.filter(phone_number=from_number).order_by('created_at')
        )

        response = MessagingResponse()
        if not tokens:
            response.message(
                'No Google Calendar accounts connected. '
                'Send "connect calendar" to add one.'
            )
        else:
            lines = [f'Connected calendars ({len(tokens)}):']
            for i, token in enumerate(tokens, start=1):
                email_display = token.account_email or '(unknown email)'
                label_display = token.account_label or 'primary'
                lines.append(f'{i}. {label_display}: {email_display}')
            response.message('\n'.join(lines))
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_remove_calendar(self, from_number, body_lower):
        """Remove a connected calendar by email or label."""
        from apps.calendar_bot.models import CalendarToken

        # Extract the identifier after 'remove calendar'
        arg = body_lower[len('remove calendar'):].strip()

        if not arg:
            response = MessagingResponse()
            response.message(
                'Please specify which calendar to remove.\n'
                'Example: "remove calendar work" or "remove calendar user@gmail.com"'
            )
            return HttpResponse(str(response), content_type='application/xml')

        # Try matching by email first, then by label
        qs = CalendarToken.objects.filter(phone_number=from_number)
        token = qs.filter(account_email__iexact=arg).first()
        if token is None:
            token = qs.filter(account_label__iexact=arg).first()

        response = MessagingResponse()
        if token is None:
            response.message(
                f'No connected calendar found matching "{arg}".\n'
                'Send "my calendars" to see connected accounts.'
            )
        else:
            email_display = token.account_email or token.account_label
            token.delete()  # CASCADE removes associated watch channels and snapshots
            logger.info(
                'Calendar token removed: phone=%s email=%s label=%s',
                from_number,
                token.account_email,
                token.account_label,
            )
            response.message(f'Removed calendar: {email_display}')
        return HttpResponse(str(response), content_type='application/xml')

    # ------------------------------------------------------------------ #
    # Block time command handling
    # ------------------------------------------------------------------ #

    def _handle_block_command(self, from_number, body):
        from apps.calendar_bot.calendar_service import handle_block_command
        from apps.calendar_bot.models import CalendarToken

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()

        if token is None or not token.access_token:
            logger.warning(
                 'Block command requested but no calendar connected: phone=%s',
                from_number,
            )
            response = MessagingResponse()
            response.message(
                'Please connect your Google Calendar first. '
                'Send "connect calendar" to get started.'
            )
            return HttpResponse(str(response), content_type='application/xml')

        reply_text = handle_block_command(from_number, body)
        response = MessagingResponse()
        response.message(reply_text)
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_yes_confirmation(self, from_number):
        from apps.calendar_bot.models import PendingBlockConfirmation
        from apps.calendar_bot.calendar_service import confirm_block_command

        try:
            PendingBlockConfirmation.objects.get(phone_number=from_number)
        except PendingBlockConfirmation.DoesNotExist:
            return None  # Not a YES for pending block, fall through

        logger.info('Processing YES confirmation for pending block: phone=%s', from_number)
        reply_text = confirm_block_command(from_number)
        response = MessagingResponse()
        response.message(reply_text)
        return HttpResponse(str(response), content_type='application/xml')

    # ------------------------------------------------------------------ #
    # Help, menu and onboarding
    # ------------------------------------------------------------------ #

    def _handle_help(self):
        response = MessagingResponse()
        response.message(HELP_TEXT)
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_menu(self):
        response = MessagingResponse()
        response.message(MENU_TEXT)
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_timezone_menu(self):
        response = MessagingResponse()
        response.message(TIMEZONE_SUB_MENU)
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_menu_digit(self, request, from_number, digit):
        digit_map = {
            '1': 'today',
            '2': 'tomorrow',
            '3': 'this week',
            '4': 'next',
            '5': 'free today',
            '6': 'help',
            '7': 'timezone',
        }
        body_lower = digit_map[digit]

        if body_lower == 'help':
            return self._handle_help()

        if body_lower == 'timezone':
            return self._handle_timezone_menu()

        # Calendar queries require a connected account
        from apps.calendar_bot.models import CalendarToken
        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return self._handle_connect_calendar(request, from_number)

        if body_lower == 'next':
            result = self._try_next_meeting(from_number)
            return result if result is not None else self._handle_menu()
        if body_lower == 'free today':
            result = self._try_free_today(from_number)
            return result if result is not None else self._handle_menu()
        # day query ('today', 'tomorrow', 'this week')
        result = self._try_day_query(from_number, body_lower)
        return result if result is not None else self._handle_menu()

    def _handle_unrecognized(self, request, from_number):
        """
        Unrecognized message handler:
        - No calendar connected → onboarding message with connect link
        - Calendar connected    → short hint to use the menu
        """
        from apps.calendar_bot.models import CalendarToken

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        has_calendar = bool(token and token.access_token)

        if not has_calendar:
            logger.info('Sending onboarding message to unconfigured user: phone=%s', from_number)
            webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', '')
            if webhook_base_url:
                auth_url = webhook_base_url.rstrip('/') + f'/calendar/auth/start/?phone={from_number}'
            else:
                auth_url = request.build_absolute_uri(
                    f'/calendar/auth/start/?phone={from_number}'
                )
            onboarding_text = (
                "Hi! I'm your WhatsApp calendar assistant.\n"
                "\n"
                "To get started, connect your Google Calendar:\n"
                f"{auth_url}\n"
                "\n"
                "Once connected, send *0* or *menu* to see what I can do."
            )
            response = MessagingResponse()
            response.message(onboarding_text)
            return HttpResponse(str(response), content_type='application/xml')

        # Connected user sent something unrecognised → brief hint only
        logger.info('Connected user sent unrecognized message, sending hint: phone=%s', from_number)
        response = MessagingResponse()
        response.message(_UNRECOGNIZED_HINT)
        return HttpResponse(str(response), content_type='application/xml')

    # keep for backwards-compat
    def _maybe_onboarding(self, request, from_number):
        return self._handle_unrecognized(request, from_number)

    # ------------------------------------------------------------------ #
    # Instant queries
    # ------------------------------------------------------------------ #

    def _try_next_meeting(self, from_number):
        """Find the next upcoming meeting from now."""
        from apps.calendar_bot.calendar_service import get_user_tz, get_events_for_date
        from apps.calendar_bot.models import CalendarToken

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return None

        user_tz = get_user_tz(from_number)
        now_local = datetime.datetime.now(tz=user_tz)
        today = now_local.date()

        response = MessagingResponse()

        for days_offset in range(8):
            check_date = today + datetime.timedelta(days=days_offset)
            try:
                events = get_events_for_date(from_number, check_date, exclude_birthdays=True)
            except Exception:
                logger.exception(
                    'Calendar API error fetching next meeting for phone=%s date=%s',
                    from_number,
                    check_date,
                )
                events = []

            for ev in events:
                if ev['start'] is None:
                    continue
                event_dt = ev['start']
                if event_dt > now_local:
                    time_until = event_dt - now_local
                    minutes_until = int(time_until.total_seconds() / 60)

                    if minutes_until < 60:
                        until_str = f'in {minutes_until} minutes'
                    elif minutes_until < 120:
                        until_str = f'in {minutes_until // 60} hour {minutes_until % 60} minutes'
                    else:
                        hours = minutes_until // 60
                        until_str = f'in {hours} hours'

                    if days_offset == 0:
                        msg = (
                            f'Your next meeting: {ev["summary"]} at '
                            f'{ev["start_str"]} ({until_str})'
                        )
                    elif days_offset == 1:
                        msg = (
                            f'No more meetings today. '
                            f'First tomorrow: {ev["start_str"]} {ev["summary"]}'
                        )
                    else:
                        day_label = event_dt.strftime('%A, %b %-d')
                        msg = f'No more meetings soon. Next: {ev["start_str"]} {ev["summary"]} on {day_label}'

                    logger.info(
                        'Next meeting found for phone=%s: %r days_offset=%d',
                        from_number,
                        ev['summary'],
                        days_offset,
                    )
                    response.message(msg)
                    return HttpResponse(str(response), content_type='application/xml')

        logger.info('No upcoming meetings found for phone=%s', from_number)
        response.message('No more meetings this week.')
        return HttpResponse(str(response), content_type='application/xml')

    def _try_free_today(self, from_number):
        """Calculate free slots >= 30 min within working hours 08:00-19:00."""
        from apps.calendar_bot.calendar_service import get_user_tz, get_events_for_date
        from apps.calendar_bot.models import CalendarToken

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return None

        user_tz = get_user_tz(from_number)
        today = datetime.datetime.now(tz=user_tz).date()

        logger.info('Calculating free slots for phone=%s date=%s', from_number, today)

        try:
            events = get_events_for_date(from_number, today, exclude_birthdays=True)
        except Exception:
            logger.exception('Calendar API error fetching events for phone=%s date=%s', from_number, today)
            response = MessagingResponse()
            response.message('Could not fetch your calendar right now. Please try again later.')
            return HttpResponse(str(response), content_type='application/xml')

        timed_events = [ev for ev in events if ev['start'] is not None]

        work_start = user_tz.localize(
            datetime.datetime(today.year, today.month, today.day, WORKDAY_START_HOUR, 0, 0)
        )
        work_end = user_tz.localize(
            datetime.datetime(today.year, today.month, today.day, WORKDAY_END_HOUR, 0, 0)
        )

        response = MessagingResponse()

        if not timed_events:
            logger.info('No timed events for phone=%s date=%s -- fully free', from_number, today)
            response.message("You're completely free today.")
            return HttpResponse(str(response), content_type='application/xml')

        busy = []
        for ev in timed_events:
            ev_start = ev['start']
            ev_end_raw = ev.get('end')
            if ev_end_raw:
                try:
                    ev_end = datetime.datetime.fromisoformat(ev_end_raw).astimezone(user_tz)
                except (ValueError, TypeError):
                    ev_end = ev_start + datetime.timedelta(hours=1)
            else:
                ev_end = ev_start + datetime.timedelta(hours=1)
            clipped_start = max(ev_start, work_start)
            clipped_end = min(ev_end, work_end)
            if clipped_start < clipped_end:
                busy.append((clipped_start, clipped_end))

        busy.sort(key=lambda x: x[0])
        merged = []
        for start, end in busy:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        free_slots = []
        cursor = work_start
        for busy_start, busy_end in merged:
            if cursor < busy_start:
                slot_minutes = int((busy_start - cursor).total_seconds() / 60)
                if slot_minutes >= MIN_FREE_SLOT_MINUTES:
                    free_slots.append((cursor, busy_start, slot_minutes))
            cursor = max(cursor, busy_end)

        if cursor < work_end:
            slot_minutes = int((work_end - cursor).total_seconds() / 60)
            if slot_minutes >= MIN_FREE_SLOT_MINUTES:
                free_slots.append((cursor, work_end, slot_minutes))

        logger.info(
            'Free slots computed for phone=%s date=%s: %d slot(s) found',
            from_number,
            today,
            len(free_slots),
        )

        if not free_slots:
            response.message('Pretty packed today \u2014 no free slots over 30 minutes.')
            return HttpResponse(str(response), content_type='application/xml')

        lines = ['Free slots today:']
        for slot_start, slot_end, slot_minutes in free_slots:
            hours = slot_minutes // 60
            mins = slot_minutes % 60
            if hours > 0 and mins > 0:
                dur_str = f'{hours}.{mins // 6}0 hrs' if mins == 30 else f'{hours}h {mins}m'
            elif hours > 0:
                dur_str = f'{hours} hrs' if hours > 1 else '1 hr'
            else:
                dur_str = f'{slot_minutes} min'
            lines.append(
                f'\u2022 {slot_start.strftime("%H:%M")}\u2013{slot_end.strftime("%H:%M")} ({dur_str})'
            )

        response.message('\n'.join(lines))
        return HttpResponse(str(response), content_type='application/xml')

    # ------------------------------------------------------------------ #
    # Day query handling
    # ------------------------------------------------------------------ #

    def _try_day_query(self, from_number, body_lower, exclude_birthdays=False):
        """Returns an HttpResponse if the message is a calendar day query, else None."""
        from apps.calendar_bot.calendar_service import get_user_tz, get_events_for_date
        from apps.calendar_bot.query_helpers import resolve_day, format_events_for_day, format_week_view
        from apps.calendar_bot.models import CalendarToken

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return None

        user_tz = get_user_tz(from_number)
        today = datetime.datetime.now(tz=user_tz).date()

        target, label = resolve_day(body_lower, today)

        if target is None:
            return None

        logger.info(
            'Day query: phone=%s body=%.50r resolved_target=%s label=%r exclude_birthdays=%s',
            from_number,
            body_lower,
            target,
            label,
            exclude_birthdays,
        )

        response = MessagingResponse()

        if target == 'week':
            week_start = today - datetime.timedelta(days=today.weekday())
            week_end = week_start + datetime.timedelta(days=6)
            week_events = {}
            current = week_start
            while current <= week_end:
                try:
                    evs = get_events_for_date(from_number, current, exclude_birthdays=exclude_birthdays)
                except Exception:
                    logger.exception(
                        'Calendar API error for week view: phone=%s date=%s',
                        from_number,
                        current,
                    )
                    evs = []
                week_events[current] = evs
                current += datetime.timedelta(days=1)
            msg = format_week_view(week_events, week_start, week_end)
        else:
            try:
                events = get_events_for_date(from_number, target, exclude_birthdays=exclude_birthdays)
            except Exception:
                logger.exception(
                    'Calendar API error for day query: phone=%s date=%s',
                    from_number,
                    target,
                )
                response.message('Could not fetch your calendar right now. Please try again later.')
                return HttpResponse(str(response), content_type='application/xml')
            logger.info(
                'Day query result: phone=%s date=%s events=%d',
                from_number,
                target,
                len(events),
            )
            msg = format_events_for_day(events, label)

        response.message(msg)
        return HttpResponse(str(response), content_type='application/xml')

    # ------------------------------------------------------------------ #
    # Settings commands
    # ------------------------------------------------------------------ #

    def _handle_set_digest(self, from_number, body_lower):
        from apps.calendar_bot.models import CalendarToken

        if not CalendarToken.objects.filter(phone_number=from_number).exists():
            CalendarToken.objects.create(
                phone_number=from_number,
                account_email='',
                access_token='',
                refresh_token='',
            )

        arg = body_lower[len('set digest'):].strip()

        response = MessagingResponse()

        if arg == 'off':
            CalendarToken.objects.filter(phone_number=from_number).update(digest_enabled=False)
            logger.info('Digest disabled for phone=%s', from_number)
            response.message('Morning digest turned off.')
            return HttpResponse(str(response), content_type='application/xml')

        if arg == 'on':
            CalendarToken.objects.filter(phone_number=from_number).update(digest_enabled=True)
            logger.info('Digest enabled for phone=%s', from_number)
            response.message('Morning digest turned on.')
            return HttpResponse(str(response), content_type='application/xml')

        if arg == 'always':
            CalendarToken.objects.filter(phone_number=from_number).update(digest_always=True)
            logger.info('Digest set to always-send for phone=%s', from_number)
            response.message('Morning digest will be sent even on days with no meetings.')
            return HttpResponse(str(response), content_type='application/xml')

        parsed = _parse_digest_time(arg)
        if parsed is not None:
            hour, minute = parsed
            CalendarToken.objects.filter(phone_number=from_number).update(
                digest_hour=hour,
                digest_minute=minute,
                digest_enabled=True,
            )
            logger.info('Digest time set to %02d:%02d for phone=%s', hour, minute, from_number)
            response.message(f'Morning digest scheduled for {hour:02d}:{minute:02d} in your timezone.')
            return HttpResponse(str(response), content_type='application/xml')

        logger.warning(
            'Could not parse digest setting %r for phone=%s',
            arg,
            from_number,
        )
        response.message(
            'Could not understand digest setting. '
            'Try: "set digest 7:30am", "set digest off", "set digest on", "set digest always".'
        )
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_set_timezone(self, from_number, body):
        import pytz
        from apps.calendar_bot.models import CalendarToken

        tz_name = body[len('set timezone '):].strip()

        try:
            pytz.timezone(tz_name)
        except Exception:
            logger.warning('Invalid timezone %r from phone=%s', tz_name, from_number)
            response = MessagingResponse()
            response.message(
                f"Unknown timezone '{tz_name}'. "
                "Please use a valid tz name, e.g. 'Europe/London' or 'America/New_York'."
            )
            return HttpResponse(str(response), content_type='application/xml')

        if not CalendarToken.objects.filter(phone_number=from_number).exists():
            CalendarToken.objects.create(
                phone_number=from_number,
                account_email='',
                access_token='',
                refresh_token='',
            )

        CalendarToken.objects.filter(phone_number=from_number).update(timezone=tz_name)

        logger.info('Timezone set to %s for phone=%s', tz_name, from_number)
        response = MessagingResponse()
        response.message(f"Timezone set to {tz_name}.")
        return HttpResponse(str(response), content_type='application/xml')

    def _handle_summary(self, from_number):
        current_week = datetime.datetime.now().isocalendar()[1]

        entries = StandupEntry.objects.filter(
            phone_number=from_number,
            week_number=current_week,
        ).order_by('created_at')

        logger.info(
            'Summary requested: phone=%s week=%d entries=%d',
            from_number,
            current_week,
            entries.count(),
        )

        response = MessagingResponse()

        if not entries.exists():
            response.message("No entries yet this week.")
        else:
            lines = [f"Week {current_week} summary:\n"]
            for entry in entries:
                date_str = entry.created_at.strftime('%Y-%m-%d')
                lines.append(f"{date_str}: {entry.message}")
            reply_text = "\n".join(lines)
            response.message(reply_text)

        return HttpResponse(str(response), content_type='application/xml')


def _parse_digest_time(arg):
    """
    Parse time strings like '7:30am', '9am', '14:00', '9:00pm'.
    Returns (hour, minute) in 24-hour format, or None if unparseable.
    """
    arg = arg.strip().lower().replace(' ', '')
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)?$', arg)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    ampm = m.group(3)

    if ampm == 'pm' and hour != 12:
        hour += 12
    elif ampm == 'am' and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour, minute
