"""
NLP-driven WhatsApp bot — replaces the digit-based state machine with open
Hebrew natural language understood by Claude (tool-use API).

Request flow:
  POST /standup/webhook/
    → onboarding check (new/mid-onboarding users handled before Claude)
    → ask_claude_with_tools(message, history)
    → if tool_use → execute_tool → ask_claude_with_result → final reply
    → save 6-turn conversation history in UserMenuState.pending_data
    → _xml(reply) → Twilio → WhatsApp

What stays from the old state machine:
  _xml(), _query_meetings_msg(), _query_next_meeting_msg(),
  _query_free_time_msg(), _query_birthdays_msg(), _handle_connect_calendar(),
  _handle_name_collection(), _handle_summary(), _parse_date_input(),
  _parse_time_hhmm(), _format_date_he().

What was removed:
  _handle_root(), _handle_main_menu_pick(), _handle_menu_state(),
  _handle_schedule_step(), _get_state(), _set_state(), _clear_state(),
  TZ_MAP, _main_menu_text(), _settings_menu_text().
"""
import datetime
import logging
import re

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from twilio.twiml.messaging_response import MessagingResponse

from apps.standup.permissions import TwilioSignaturePermission
from apps.standup.models import StandupEntry

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Back-compat module-level constants (imported by existing tests)
# --------------------------------------------------------------------------- #

import apps.standup.strings_he as _strings_he

MENU_TEXT = _strings_he.MAIN_MENU_TEXT
HELP_TEXT = _strings_he.HELP_TEXT
MENU_TRIGGERS = {'menu', 'options', 'calendar', '0'}


# --------------------------------------------------------------------------- #
# Helper: send a TwiML XML response
# --------------------------------------------------------------------------- #

def _xml(text):
    resp = MessagingResponse()
    resp.message(text)
    return HttpResponse(str(resp), content_type='application/xml')


# --------------------------------------------------------------------------- #
# Date/time helpers (kept for create_event parsing)
# --------------------------------------------------------------------------- #

def _parse_date_input(text, user_tz):
    """
    Accept: Hebrew/English words for today/tomorrow, DD/MM, DD/MM/YYYY.
    Returns datetime.date or None.
    """
    text = text.strip()
    now_local = datetime.datetime.now(tz=user_tz)
    today = now_local.date()

    if text in ('היום', 'today'):
        return today
    if text in ('מחר', 'tomorrow'):
        return today + datetime.timedelta(days=1)

    m = re.match(r'^(\d{1,2})/(\d{1,2})$', text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            d = datetime.date(year, month, day)
            if d < today:
                d = datetime.date(year + 1, month, day)
            return d
        except ValueError:
            return None

    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None

    return None


def _parse_time_hhmm(text):
    """Accept HH:MM or H:MM (24h). Returns (h, m) tuple or None."""
    text = text.strip()
    m = re.match(r'^(\d{1,2}):(\d{2})$', text)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mn <= 59:
        return h, mn
    return None


def _format_date_he(d):
    """Format date as DD/MM/YYYY for Hebrew display."""
    return d.strftime('%d/%m/%Y')


# --------------------------------------------------------------------------- #
# State helpers — stubs kept for back-compat with remaining tests
# (The digit-menu state machine is removed; these write to UserMenuState but
#  the new NLP handler does not read pending_action/pending_step.)
# --------------------------------------------------------------------------- #

def _set_state(phone_number, action, step, data):
    from apps.calendar_bot.models import UserMenuState
    UserMenuState.objects.update_or_create(
        phone_number=phone_number,
        defaults={'pending_action': action, 'pending_step': step, 'pending_data': data or {}},
    )


def _get_state(phone_number):
    from apps.calendar_bot.models import UserMenuState
    try:
        s = UserMenuState.objects.get(phone_number=phone_number)
        return s.pending_action, s.pending_step, s.pending_data or {}
    except UserMenuState.DoesNotExist:
        return None, None, {}


def _clear_state(phone_number):
    from apps.calendar_bot.models import UserMenuState
    UserMenuState.objects.filter(phone_number=phone_number).delete()


# --------------------------------------------------------------------------- #
# Conversation history helpers (stored in UserMenuState.pending_data)
# --------------------------------------------------------------------------- #

def _get_conversation_history(phone_number):
    """Return the last N conversation turns as a list of message dicts."""
    from apps.calendar_bot.models import UserMenuState
    try:
        s = UserMenuState.objects.get(phone_number=phone_number)
        data = s.pending_data or {}
        return data.get('history', [])
    except UserMenuState.DoesNotExist:
        return []


def _save_conversation_history(phone_number, user_message, assistant_message):
    """Append the latest exchange and persist (keep last 6 turns = 12 messages)."""
    from apps.calendar_bot.models import UserMenuState
    try:
        s = UserMenuState.objects.get(phone_number=phone_number)
        data = s.pending_data or {}
    except UserMenuState.DoesNotExist:
        data = {}

    history = data.get('history', [])
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_message})
    if len(history) > 12:
        history = history[-12:]

    data['history'] = history
    UserMenuState.objects.update_or_create(
        phone_number=phone_number,
        defaults={'pending_action': None, 'pending_step': None, 'pending_data': data},
    )


# --------------------------------------------------------------------------- #
# Main webhook view
# --------------------------------------------------------------------------- #

class WhatsAppWebhookView(APIView):
    permission_classes = [TwilioSignaturePermission]

    def post(self, request, *args, **kwargs):
        from_number = request.data.get('From', '')
        body = (request.data.get('Body', '') or '').strip()

        logger.info('Incoming webhook: phone=%s body=%.50r', from_number, body)

        if not body:
            return Response(status=400)

        # Legacy /summary command
        if body.lower() == '/summary':
            return self._handle_summary(from_number)

        # Onboarding: new users or users mid-onboarding
        onboarding_reply = self._try_onboarding(request, from_number, body)
        if onboarding_reply is not None:
            return onboarding_reply

        # NLP handler: pass message to Claude with tool use
        try:
            from apps.standup.claude_helper import ask_claude_with_tools, ask_claude_with_result
            history = _get_conversation_history(from_number)
            result = ask_claude_with_tools(body, history)

            if result['type'] == 'tool_use':
                tool_result = self._execute_tool(
                    result['name'], result['input'], from_number, request
                )
                final_reply = ask_claude_with_result(body, result, tool_result, history)
            else:
                final_reply = result['content']

            _save_conversation_history(from_number, body, final_reply)
            return _xml(final_reply)

        except Exception:
            logger.exception('Claude API error for phone=%s', from_number)
            return _xml('מצטער, אירעה שגיאה. נסה שוב מאוחר יותר.')

    # ----------------------------------------------------------------------- #
    # Onboarding gate — called before Claude for every message
    # ----------------------------------------------------------------------- #

    def _try_onboarding(self, request, from_number, body):
        """
        Returns an HttpResponse if this message should be handled by onboarding,
        or None if the user is connected and should go to Claude.
        """
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken, OnboardingState

        # Mid-onboarding: awaiting the user's name
        try:
            onboarding = OnboardingState.objects.get(phone_number=from_number)
            if onboarding.step == OnboardingState.STEP_AWAITING_NAME:
                return self._handle_name_collection(request, from_number, body)
        except OnboardingState.DoesNotExist:
            pass

        # Check whether the user has a calendar connected
        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        has_calendar = bool(token and token.access_token)

        if not has_calendar:
            if not OnboardingState.objects.filter(phone_number=from_number).exists():
                logger.info('First contact — starting onboarding: phone=%s', from_number)
                OnboardingState.objects.get_or_create(phone_number=from_number)
                return _xml(s.ONBOARDING_GREETING)
            return _xml(s.ONBOARDING_NAME_REPROMPT)

        # Connected user — no onboarding, let Claude handle it
        return None

    # ----------------------------------------------------------------------- #
    # Tool executor — maps Claude tool_use calls to Python/DB functions
    # ----------------------------------------------------------------------- #

    def _execute_tool(self, tool_name, tool_input, from_number, request):
        """Execute a Claude tool call and return the result as a plain string."""
        import apps.standup.strings_he as s

        if tool_name == 'get_meetings':
            return self._query_meetings_msg(
                from_number, tool_input.get('date_description', 'today')
            )

        if tool_name == 'get_next_meeting':
            return self._query_next_meeting_msg(from_number)

        if tool_name == 'get_free_time':
            return self._query_free_time_msg(
                from_number, tool_input.get('date_description', 'today')
            )

        if tool_name == 'get_birthdays':
            period = tool_input.get('period_description', 'week')
            period = 'month' if 'month' in period.lower() else 'week'
            return self._query_birthdays_msg(from_number, period)

        if tool_name == 'create_event':
            return self._execute_create_event(tool_input, from_number)

        if tool_name == 'set_timezone':
            tz_name = tool_input.get('timezone_name', 'Asia/Jerusalem')
            from apps.calendar_bot.models import CalendarToken
            CalendarToken.objects.filter(phone_number=from_number).update(timezone=tz_name)
            logger.info('Timezone set to %s for phone=%s', tz_name, from_number)
            return f'אזור הזמן עודכן ל-{tz_name}'

        if tool_name == 'connect_calendar':
            webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', '')
            if webhook_base_url:
                auth_url = webhook_base_url.rstrip('/') + f'/calendar/auth/start/?phone={from_number}'
            else:
                auth_url = request.build_absolute_uri(
                    f'/calendar/auth/start/?phone={from_number}'
                )
            return auth_url

        if tool_name == 'disconnect_calendar':
            from apps.calendar_bot.models import CalendarToken
            deleted, _ = CalendarToken.objects.filter(phone_number=from_number).delete()
            logger.info(
                'Calendar disconnected for phone=%s (deleted %d tokens)', from_number, deleted
            )
            return f'היומן נותק בהצלחה. נמחקו {deleted} חיבורים.'

        return f'כלי לא מוכר: {tool_name}'

    def _execute_create_event(self, tool_input, from_number):
        """Parse tool_input and call create_event in calendar_service."""
        import apps.standup.strings_he as s
        from apps.calendar_bot.calendar_service import create_event, get_user_tz

        date_desc = tool_input.get('date_description', '')
        start_time = tool_input.get('start_time', '')
        end_time = tool_input.get('end_time', '')
        title = tool_input.get('title', '')
        description = tool_input.get('description')
        location = tool_input.get('location')

        user_tz = get_user_tz(from_number)
        today = datetime.datetime.now(tz=user_tz).date()

        if date_desc.lower() == 'today':
            target_date = today
        elif date_desc.lower() == 'tomorrow':
            target_date = today + datetime.timedelta(days=1)
        else:
            try:
                target_date = datetime.date.fromisoformat(date_desc)
            except (ValueError, TypeError):
                target_date = _parse_date_input(date_desc, user_tz)
                if target_date is None:
                    return 'לא הצלחתי להבין את התאריך. אנא ציין תאריך מחדש.'

        ok, error_code = create_event(
            from_number, target_date, start_time, end_time, title,
            description=description, location=location,
        )
        if ok:
            return s.SCHEDULE_CREATED.format(
                date=_format_date_he(target_date),
                start=start_time,
                end=end_time,
                title=title,
            )
        if error_code == 'token_revoked':
            return 'פג תוקף החיבור ליומן. שלח "חבר יומן" כדי להתחבר מחדש.'
        return s.SCHEDULE_ERROR

    # ----------------------------------------------------------------------- #
    # Calendar query helpers — return plain strings (no _xml wrapper)
    # ----------------------------------------------------------------------- #

    def _query_meetings_msg(self, from_number, period):
        """Return the meetings query result as a plain string."""
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken
        from apps.calendar_bot.calendar_service import get_user_tz, get_events_for_date
        from apps.calendar_bot.query_helpers import resolve_day, format_events_for_day, format_week_view

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return s.NO_CALENDAR_CONNECTED

        user_tz = get_user_tz(from_number)
        today = datetime.datetime.now(tz=user_tz).date()
        target, label = resolve_day(period, today)

        # Fallback: try ISO date parse if resolve_day didn't recognise the string
        if target is None:
            try:
                target = datetime.date.fromisoformat(period)
                label = target.strftime('%A, %b %-d')
            except (ValueError, TypeError):
                target = today
                label = today.strftime('%A, %b %-d')

        if target == 'week':
            week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
            week_end = week_start + datetime.timedelta(days=6)
            week_events = {}
            current = week_start
            while current <= week_end:
                try:
                    evs = get_events_for_date(from_number, current, exclude_birthdays=True)
                except Exception:
                    evs = []
                week_events[current] = evs
                current += datetime.timedelta(days=1)
            return format_week_view(week_events, week_start, week_end)
        else:
            try:
                events = get_events_for_date(from_number, target, exclude_birthdays=True)
            except Exception:
                logger.exception('Calendar API error: phone=%s', from_number)
                return s.CALENDAR_FETCH_ERROR
            return format_events_for_day(events, label)

    def _query_next_meeting_msg(self, from_number):
        """Return the next-meeting query result as a plain string."""
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken
        from apps.calendar_bot.calendar_service import get_user_tz, get_events_for_date

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return s.NO_CALENDAR_CONNECTED

        user_tz = get_user_tz(from_number)
        now_local = datetime.datetime.now(tz=user_tz)
        today = now_local.date()

        for days_offset in range(8):
            check_date = today + datetime.timedelta(days=days_offset)
            try:
                events = get_events_for_date(from_number, check_date, exclude_birthdays=True)
            except Exception:
                events = []
            for ev in events:
                if ev['start'] is None:
                    continue
                if ev['start'] > now_local:
                    time_until = ev['start'] - now_local
                    minutes_until = int(time_until.total_seconds() / 60)
                    if minutes_until < 60:
                        until_str = f'בעוד {minutes_until} דקות'
                    elif minutes_until < 120:
                        until_str = f'בעוד {minutes_until // 60} שעה {minutes_until % 60} דקות'
                    else:
                        until_str = f'בעוד {minutes_until // 60} שעות'
                    if days_offset == 0:
                        return s.NEXT_MEETING_PREFIX.format(
                            summary=ev['summary'], time=ev['start_str'], until=until_str)
                    elif days_offset == 1:
                        return s.NEXT_MEETING_TOMORROW.format(
                            time=ev['start_str'], summary=ev['summary'])
                    else:
                        day_label = ev['start'].strftime('%A, %b %-d')
                        return s.NEXT_MEETING_FUTURE.format(
                            time=ev['start_str'], summary=ev['summary'], day=day_label)

        return s.NO_MEETINGS_WEEK

    def _query_free_time_msg(self, from_number, period):
        """Return the free-time query result as a plain string."""
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken
        from apps.calendar_bot.calendar_service import get_user_tz, get_free_slots_for_date
        from apps.calendar_bot.query_helpers import resolve_day

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return s.NO_CALENDAR_CONNECTED

        user_tz = get_user_tz(from_number)
        today = datetime.datetime.now(tz=user_tz).date()

        if period == 'this week':
            week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
            lines = []
            for i in range(7):
                d = week_start + datetime.timedelta(days=i)
                slots = get_free_slots_for_date(from_number, d)
                day_name = d.strftime('%A')
                if slots is None:
                    lines.append(f'{day_name}: שגיאה')
                elif not slots:
                    lines.append(f'{day_name}: עמוס')
                else:
                    slot_strs = [f'{sl["start"]}–{sl["end"]}' for sl in slots]
                    lines.append(f'{day_name}: {", ".join(slot_strs)}')
            return s.FREE_SLOTS_HEADER + '\n' + '\n'.join(lines)

        target, label = resolve_day(period, today)

        # Fallback: try ISO date parse
        if target is None:
            try:
                target = datetime.date.fromisoformat(period)
            except (ValueError, TypeError):
                target = today

        slots = get_free_slots_for_date(from_number, target)

        if slots is None:
            return s.CALENDAR_FETCH_ERROR
        if not slots:
            return s.FREE_TODAY_PACKED

        lines = [s.FREE_SLOTS_HEADER]
        for sl in slots:
            h = sl['minutes'] // 60
            mn = sl['minutes'] % 60
            if h > 0 and mn > 0:
                dur = f'{h}ש {mn}ד'
            elif h > 0:
                dur = f'{h} שעות'
            else:
                dur = f'{sl["minutes"]} דקות'
            lines.append(f'• {sl["start"]}–{sl["end"]} ({dur})')
        return '\n'.join(lines)

    def _query_birthdays_msg(self, from_number, period):
        """Return the birthdays query result as a plain string."""
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken
        from apps.calendar_bot.calendar_service import get_birthdays_next_week, get_user_tz

        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        if token is None or not token.access_token:
            return s.NO_CALENDAR_CONNECTED

        user_tz = get_user_tz(from_number)

        try:
            birthdays = get_birthdays_next_week(from_number)
        except Exception:
            logger.exception('Error fetching birthdays for phone=%s', from_number)
            return s.BIRTHDAYS_FETCH_ERROR

        if period == 'month':
            now_local = datetime.datetime.now(tz=user_tz)
            this_month = now_local.month
            month_birthdays = []
            for b in birthdays:
                raw = b.get('raw_date', '')
                try:
                    bd = datetime.date.fromisoformat(raw[:10])
                    if bd.month == this_month:
                        month_birthdays.append(b)
                except (ValueError, TypeError):
                    pass
            if not month_birthdays:
                return s.NO_BIRTHDAYS_MONTH
            lines = [s.BIRTHDAYS_MONTH_HEADER]
            for b in month_birthdays:
                lines.append(f'• {b["summary"]} — {b["date"]}')
            return '\n'.join(lines)

        if not birthdays:
            return s.NO_BIRTHDAYS
        lines = [s.BIRTHDAYS_HEADER]
        for b in birthdays:
            lines.append(f'• {b["summary"]} — {b["date"]}')
        return '\n'.join(lines)

    # ----------------------------------------------------------------------- #
    # Calendar query helpers — HttpResponse variants (back-compat)
    # ----------------------------------------------------------------------- #

    def _query_meetings(self, from_number, period):
        return _xml(self._query_meetings_msg(from_number, period))

    def _query_next_meeting(self, from_number):
        return _xml(self._query_next_meeting_msg(from_number))

    def _query_free_time(self, from_number, period):
        return _xml(self._query_free_time_msg(from_number, period))

    def _query_birthdays(self, from_number, period):
        return _xml(self._query_birthdays_msg(from_number, period))

    # ----------------------------------------------------------------------- #
    # Settings actions (kept for back-compat / external callers)
    # ----------------------------------------------------------------------- #

    def _set_timezone(self, from_number, tz_name):
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken
        CalendarToken.objects.filter(phone_number=from_number).update(timezone=tz_name)
        logger.info('Timezone set to %s for phone=%s', tz_name, from_number)
        return _xml(s.TIMEZONE_SET.format(tz_name=tz_name))

    def _disconnect_calendar(self, from_number):
        from apps.calendar_bot.models import CalendarToken
        deleted, _ = CalendarToken.objects.filter(phone_number=from_number).delete()
        logger.info(
            'Calendar disconnected for phone=%s (deleted %d tokens)', from_number, deleted
        )
        return _xml('✅ היומן נותק.')

    def _handle_connect_calendar(self, request, from_number):
        import apps.standup.strings_he as s
        webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', '')
        if webhook_base_url:
            auth_url = webhook_base_url.rstrip('/') + f'/calendar/auth/start/?phone={from_number}'
        else:
            auth_url = request.build_absolute_uri(f'/calendar/auth/start/?phone={from_number}')
        return _xml(s.CONNECT_CALENDAR_MSG.format(auth_url=auth_url))

    # ----------------------------------------------------------------------- #
    # Onboarding: name collection
    # ----------------------------------------------------------------------- #

    def _handle_name_collection(self, request, from_number, name):
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken, OnboardingState

        name = name.strip()[:100]
        if not name:
            return _xml(s.ONBOARDING_NAME_REPROMPT)

        token, _ = CalendarToken.objects.get_or_create(
            phone_number=from_number,
            defaults={
                'account_email': '',
                'access_token': '',
                'refresh_token': '',
                'name': name,
            },
        )
        if not token.name:
            token.name = name
            token.save(update_fields=['name'])

        OnboardingState.objects.filter(phone_number=from_number).delete()
        logger.info('Name collected: phone=%s name=%r', from_number, name)

        webhook_base_url = getattr(settings, 'WEBHOOK_BASE_URL', '')
        if webhook_base_url:
            auth_url = webhook_base_url.rstrip('/') + f'/calendar/auth/start/?phone={from_number}'
        else:
            auth_url = request.build_absolute_uri(f'/calendar/auth/start/?phone={from_number}')

        return _xml(s.ONBOARDING_WELCOME.format(name=name, auth_url=auth_url))

    # ----------------------------------------------------------------------- #
    # Legacy: /summary
    # ----------------------------------------------------------------------- #

    def _handle_summary(self, from_number):
        current_week = datetime.datetime.now().isocalendar()[1]
        entries = StandupEntry.objects.filter(
            phone_number=from_number,
            week_number=current_week,
        ).order_by('created_at')

        resp = MessagingResponse()
        if not entries.exists():
            resp.message('אין רשומות שבוע זה.')
        else:
            lines = [f'סיכום שבוע {current_week}:\n']
            for entry in entries:
                date_str = entry.created_at.strftime('%Y-%m-%d')
                lines.append(f'{date_str}: {entry.message}')
            resp.message('\n'.join(lines))
        return HttpResponse(str(resp), content_type='application/xml')

    # ----------------------------------------------------------------------- #
    # Back-compat stubs (used by existing tests)
    # ----------------------------------------------------------------------- #

    def _try_day_query(self, from_number, body_lower, exclude_birthdays=False):
        """Kept for backward-compat with existing tests."""
        return self._query_meetings(from_number, body_lower)

    def _try_next_meeting(self, from_number):
        """Kept for backward-compat with existing tests."""
        return self._query_next_meeting(from_number)

    def _try_free_today(self, from_number):
        """Kept for backward-compat with existing tests."""
        return self._query_free_time(from_number, 'today')

    def _try_birthdays_next_week(self, from_number):
        """Kept for backward-compat with existing tests."""
        return self._query_birthdays(from_number, 'week')


# --------------------------------------------------------------------------- #
# TZA-130: Twilio delivery status callback view
# --------------------------------------------------------------------------- #

@method_decorator(csrf_exempt, name='dispatch')
class TwilioStatusCallbackView(APIView):
    """
    POST /standup/twilio-status/

    Receives Twilio message status callbacks and writes delivery events
    to the application log so they appear in Railway logs.
    """

    permission_classes = []

    def post(self, request, *args, **kwargs):
        message_sid = request.data.get('MessageSid', '')
        to = request.data.get('To', '')
        status = request.data.get('MessageStatus', '')
        error_code = request.data.get('ErrorCode', '')
        error_message = request.data.get('ErrorMessage', '')

        if status in ('sent', 'delivered'):
            logger.info('[Twilio] %s → %s: %s', message_sid, to, status)
        else:
            logger.error(
                '[Twilio] %s → %s: %s (error %s: %s)',
                message_sid, to, status, error_code, error_message,
            )

        return HttpResponse(status=204)


# --------------------------------------------------------------------------- #
# Legacy digest-time parser (used by tasks.py)
# --------------------------------------------------------------------------- #

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
