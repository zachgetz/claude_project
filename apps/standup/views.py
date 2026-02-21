"""
TZA-110: Full menu-driven WhatsApp bot redesign.

State machine:
 - Root level: ANY input -> show main menu and set state='main_menu'.
 - main_menu state: digit 1-6 enters corresponding submenu.
 - Inside a numbered submenu: only valid digits (including 0) accepted.
   Any other input -> INVALID_OPTION + re-show current menu.
 - Inside Schedule flow (action='schedule'): free text on text steps,
   structured validation on date/time steps. 0 or 'batel' at any step -> cancel.

All bot response text is 100% Hebrew. Only exception: user-provided content
(e.g. event title typed in English).

TZA-121: After returning a result from a meetings/free-time/birthdays submenu
selection, keep pending_action set to the current submenu state and re-display
the submenu options. Only clear submenu state when user sends 0 or \u05d1\u05d8\u05dc.
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
# MENU_TRIGGERS kept for any code that imported it:
MENU_TRIGGERS = {'menu', 'options', 'calendar', '0'}

# --------------------------------------------------------------------------- #
# Timezone map for settings submenu (index 0 = option 1)
# --------------------------------------------------------------------------- #

TZ_MAP = [
    'Asia/Jerusalem',
    'Europe/London',
    'America/New_York',
    'Europe/Paris',
    'Asia/Dubai',
    'America/Los_Angeles',
]


# --------------------------------------------------------------------------- #
# Helper: send a TwiML XML response
# --------------------------------------------------------------------------- #

def _xml(text):
    resp = MessagingResponse()
    resp.message(text)
    return HttpResponse(str(resp), content_type='application/xml')


# --------------------------------------------------------------------------- #
# State helpers (UserMenuState)
# --------------------------------------------------------------------------- #

def _get_state(phone_number):
    """Return (pending_action, pending_step, pending_data) for a phone number."""
    from apps.calendar_bot.models import UserMenuState
    try:
        s = UserMenuState.objects.get(phone_number=phone_number)
        return s.pending_action, s.pending_step, s.pending_data or {}
    except UserMenuState.DoesNotExist:
        return None, None, {}


def _set_state(phone_number, action, step, data):
    from apps.calendar_bot.models import UserMenuState
    UserMenuState.objects.update_or_create(
        phone_number=phone_number,
        defaults={'pending_action': action, 'pending_step': step, 'pending_data': data},
    )


def _clear_state(phone_number):
    from apps.calendar_bot.models import UserMenuState
    UserMenuState.objects.filter(phone_number=phone_number).delete()


# --------------------------------------------------------------------------- #
# Date/time validation helpers for Schedule flow
# --------------------------------------------------------------------------- #

def _parse_date_input(text, user_tz):
    """
    Accept: Hebrew/English words for today/tomorrow, DD/MM, DD/MM/YYYY.
    Returns datetime.date or None.
    """
    text = text.strip()
    now_local = datetime.datetime.now(tz=user_tz)
    today = now_local.date()

    if text in ('\u05d4\u05d9\u05d5\u05dd', 'today'):
        return today
    if text in ('\u05de\u05d7\u05e8', 'tomorrow'):
        return today + datetime.timedelta(days=1)

    # DD/MM
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

    # DD/MM/YYYY
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
# Main webhook view
# --------------------------------------------------------------------------- #

class WhatsAppWebhookView(APIView):
    permission_classes = [TwilioSignaturePermission]

    def post(self, request, *args, **kwargs):
        from_number = request.data.get('From', '')
        body = request.data.get('Body', '') or ''
        body_stripped = body.strip()
        body_lower = body_stripped.lower()

        logger.info('Incoming webhook: phone=%s body=%.50r', from_number, body)

        # -- Legacy /summary command ---------------------------------------- #
        if body_lower == '/summary':
            return self._handle_summary(from_number)

        # -- Retrieve current state ----------------------------------------- #
        action, step, data = _get_state(from_number)

        # ------------------------------------------------------------------- #
        # STATE: schedule flow
        # ------------------------------------------------------------------- #
        if action == 'schedule':
            return self._handle_schedule_step(request, from_number, body_stripped, step, data)

        # ------------------------------------------------------------------- #
        # STATE: inside a numbered submenu
        # ------------------------------------------------------------------- #
        if action in ('meetings_menu', 'free_time_menu', 'birthdays_menu',
                      'settings_menu', 'timezone_menu', 'disconnect_confirm',
                      'digest_prompt'):
            return self._handle_menu_state(
                request, from_number, body_stripped, action, step, data
            )

        # ------------------------------------------------------------------- #
        # STATE: main_menu (user already saw the main menu; now picking)
        # ------------------------------------------------------------------- #
        if action == 'main_menu':
            return self._handle_main_menu_pick(request, from_number, body_stripped)

        # ------------------------------------------------------------------- #
        # ROOT LEVEL (no active state)
        # ------------------------------------------------------------------- #
        return self._handle_root(request, from_number, body_stripped)

    # ----------------------------------------------------------------------- #
    # Root handler: show main menu (or onboarding for new users)
    # ----------------------------------------------------------------------- #

    def _handle_root(self, request, from_number, body_stripped):
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken, OnboardingState

        # Empty body
        if not body_stripped:
            logger.warning('Empty body from phone=%s', from_number)
            return Response({'error': 'Body cannot be empty.'}, status=400)

        # Check if user is mid-onboarding (awaiting name)
        try:
            onboarding = OnboardingState.objects.get(phone_number=from_number)
            if onboarding.step == OnboardingState.STEP_AWAITING_NAME:
                return self._handle_name_collection(request, from_number, body_stripped)
        except OnboardingState.DoesNotExist:
            pass

        # Check calendar connection
        token = CalendarToken.objects.filter(
            phone_number=from_number
        ).order_by('created_at').first()
        has_calendar = bool(token and token.access_token)

        if not has_calendar:
            if not OnboardingState.objects.filter(phone_number=from_number).exists():
                logger.info('First contact - starting onboarding: phone=%s', from_number)
                OnboardingState.objects.get_or_create(phone_number=from_number)
                return _xml(s.ONBOARDING_GREETING)
            return _xml(s.ONBOARDING_NAME_REPROMPT)

        # Connected user at root -> show main menu, enter main_menu state
        _set_state(from_number, 'main_menu', 1, {})
        return _xml(s.MAIN_MENU_TEXT)

    # ----------------------------------------------------------------------- #
    # Main menu pick (state='main_menu')
    # ----------------------------------------------------------------------- #

    def _handle_main_menu_pick(self, request, from_number, body_stripped):
        import apps.standup.strings_he as s

        digit = body_stripped.strip()

        if digit == '1':
            _set_state(from_number, 'meetings_menu', 1, {})
            return _xml(s.MEETINGS_MENU_TEXT)

        if digit == '2':
            _set_state(from_number, 'free_time_menu', 1, {})
            return _xml(s.FREE_TIME_MENU_TEXT)

        if digit == '3':
            _set_state(from_number, 'schedule', 1, {})
            return _xml(s.SCHEDULE_STEP1)

        if digit == '4':
            _set_state(from_number, 'birthdays_menu', 1, {})
            return _xml(s.BIRTHDAYS_MENU_TEXT)

        if digit == '5':
            _set_state(from_number, 'settings_menu', 1, {})
            return _xml(s.SETTINGS_MENU_TEXT)

        if digit == '6':
            _set_state(from_number, 'main_menu', 1, {})
            return _xml(s.HELP_TEXT)

        if digit == '0':
            _set_state(from_number, 'main_menu', 1, {})
            return _xml(s.MAIN_MENU_TEXT)

        # Invalid -> error + re-show main menu
        _set_state(from_number, 'main_menu', 1, {})
        return _xml(s.INVALID_OPTION + '\n' + s.MAIN_MENU_TEXT)

    # ----------------------------------------------------------------------- #
    # Numbered submenu state handler
    # ----------------------------------------------------------------------- #

    def _handle_menu_state(self, request, from_number, body_stripped, action, step, data):
        import apps.standup.strings_he as s

        digit = body_stripped.strip()

        # ---- Meetings submenu -------------------------------------------- #
        if action == 'meetings_menu':
            if digit == '0':
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            if digit == '1':
                _set_state(from_number, 'meetings_menu', 1, {})
                msg = self._query_meetings_msg(from_number, 'today')
                return _xml(msg + '\n\n' + s.MEETINGS_MENU_TEXT)
            if digit == '2':
                _set_state(from_number, 'meetings_menu', 1, {})
                msg = self._query_meetings_msg(from_number, 'tomorrow')
                return _xml(msg + '\n\n' + s.MEETINGS_MENU_TEXT)
            if digit == '3':
                _set_state(from_number, 'meetings_menu', 1, {})
                msg = self._query_meetings_msg(from_number, 'this week')
                return _xml(msg + '\n\n' + s.MEETINGS_MENU_TEXT)
            if digit == '4':
                _set_state(from_number, 'meetings_menu', 1, {})
                msg = self._query_next_meeting_msg(from_number)
                return _xml(msg + '\n\n' + s.MEETINGS_MENU_TEXT)
            return _xml(s.INVALID_OPTION + '\n' + s.MEETINGS_MENU_TEXT)

        # ---- Free time submenu ------------------------------------------- #
        if action == 'free_time_menu':
            if digit == '0':
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            if digit in ('1', '2', '3'):
                _set_state(from_number, 'free_time_menu', 1, {})
                day_map = {'1': 'today', '2': 'tomorrow', '3': 'this week'}
                msg = self._query_free_time_msg(from_number, day_map[digit])
                return _xml(msg + '\n\n' + s.FREE_TIME_MENU_TEXT)
            return _xml(s.INVALID_OPTION + '\n' + s.FREE_TIME_MENU_TEXT)

        # ---- Birthdays submenu ------------------------------------------- #
        if action == 'birthdays_menu':
            if digit == '0':
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            if digit == '1':
                _set_state(from_number, 'birthdays_menu', 1, {})
                msg = self._query_birthdays_msg(from_number, 'week')
                return _xml(msg + '\n\n' + s.BIRTHDAYS_MENU_TEXT)
            if digit == '2':
                _set_state(from_number, 'birthdays_menu', 1, {})
                msg = self._query_birthdays_msg(from_number, 'month')
                return _xml(msg + '\n\n' + s.BIRTHDAYS_MENU_TEXT)
            return _xml(s.INVALID_OPTION + '\n' + s.BIRTHDAYS_MENU_TEXT)

        # ---- Settings submenu -------------------------------------------- #
        if action == 'settings_menu':
            if digit == '0':
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            if digit == '1':
                _set_state(from_number, 'timezone_menu', 1, {})
                return _xml(s.TIMEZONE_MENU_TEXT)
            if digit == '2':
                _set_state(from_number, 'digest_prompt', 1, {})
                return _xml(s.DIGEST_PROMPT)
            if digit == '3':
                _clear_state(from_number)
                return self._handle_connect_calendar(request, from_number)
            if digit == '4':
                _set_state(from_number, 'disconnect_confirm', 1, {})
                return _xml(s.DISCONNECT_CONFIRM_TEXT)
            return _xml(s.INVALID_OPTION + '\n' + s.SETTINGS_MENU_TEXT)

        # ---- Timezone submenu -------------------------------------------- #
        if action == 'timezone_menu':
            if digit == '0':
                _set_state(from_number, 'settings_menu', 1, {})
                return _xml(s.SETTINGS_MENU_TEXT)
            if digit in ('1', '2', '3', '4', '5', '6'):
                tz_name = TZ_MAP[int(digit) - 1]
                _clear_state(from_number)
                return self._set_timezone(from_number, tz_name)
            return _xml(s.INVALID_OPTION + '\n' + s.TIMEZONE_MENU_TEXT)

        # ---- Digest prompt (free-text step) ------------------------------ #
        if action == 'digest_prompt':
            if digit in ('0', '\u05d1\u05d8\u05dc'):
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            t = _parse_time_hhmm(body_stripped)
            if t is None:
                return _xml(s.DIGEST_INVALID + '\n' + s.DIGEST_PROMPT)
            h, m = t
            from apps.calendar_bot.models import CalendarToken
            CalendarToken.objects.filter(phone_number=from_number).update(
                digest_hour=h, digest_minute=m, digest_enabled=True
            )
            _clear_state(from_number)
            logger.info('Digest time set to %02d:%02d for phone=%s', h, m, from_number)
            return _xml(s.DIGEST_TIME_SET.format(hour=h, minute=m))

        # ---- Disconnect confirm ------------------------------------------ #
        if action == 'disconnect_confirm':
            if digit in ('0', '2', '\u05dc\u05d0'):
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.MAIN_MENU_TEXT)
            if digit == '1':
                _clear_state(from_number)
                return self._disconnect_calendar(from_number)
            return _xml(s.INVALID_OPTION + '\n' + s.DISCONNECT_CONFIRM_TEXT)

        # Fallback
        _set_state(from_number, 'main_menu', 1, {})
        return _xml(s.MAIN_MENU_TEXT)

    # ----------------------------------------------------------------------- #
    # Schedule flow (multi-step)
    # ----------------------------------------------------------------------- #

    def _handle_schedule_step(self, request, from_number, body_stripped, step, data):
        import apps.standup.strings_he as s
        from apps.calendar_bot.calendar_service import get_user_tz, create_event

        # Cancel anytime with 0 or 'batel' (Hebrew: cancel).
        # Use _set_state('main_menu') instead of _clear_state so the very next
        # message is routed via _handle_main_menu_pick and the bot stays responsive.
        if body_stripped in ('0', '\u05d1\u05d8\u05dc'):
            _set_state(from_number, 'main_menu', 1, {})
            return _xml(s.SCHEDULE_CANCELLED + '\n' + s.MAIN_MENU_TEXT)

        user_tz = get_user_tz(from_number)

        # Step 1: date
        if step == 1:
            d = _parse_date_input(body_stripped, user_tz)
            if d is None:
                return _xml(s.SCHEDULE_INVALID + '\n' + s.SCHEDULE_STEP1)
            data['date'] = d.isoformat()
            _set_state(from_number, 'schedule', 2, data)
            return _xml(s.SCHEDULE_STEP2)

        # Step 2: start time
        if step == 2:
            t = _parse_time_hhmm(body_stripped)
            if t is None:
                return _xml(s.SCHEDULE_INVALID + '\n' + s.SCHEDULE_STEP2)
            data['start'] = f'{t[0]:02d}:{t[1]:02d}'
            _set_state(from_number, 'schedule', 3, data)
            return _xml(s.SCHEDULE_STEP3)

        # Step 3: end time
        if step == 3:
            t = _parse_time_hhmm(body_stripped)
            if t is None:
                return _xml(s.SCHEDULE_INVALID + '\n' + s.SCHEDULE_STEP3)
            start_h, start_m = [int(x) for x in data['start'].split(':')]
            end_h, end_m = t[0], t[1]
            if (end_h * 60 + end_m) <= (start_h * 60 + start_m):
                return _xml(s.SCHEDULE_INVALID + '\n' + s.SCHEDULE_STEP3)
            data['end'] = f'{end_h:02d}:{end_m:02d}'
            _set_state(from_number, 'schedule', 4, data)
            return _xml(s.SCHEDULE_STEP4)

        # Step 4: title (non-empty)
        if step == 4:
            title = body_stripped.strip()
            if not title:
                return _xml(s.SCHEDULE_INVALID + '\n' + s.SCHEDULE_STEP4)
            data['title'] = title
            _set_state(from_number, 'schedule', 5, data)
            return _xml(s.SCHEDULE_STEP5)

        # Step 5: description (or 'daleg' to skip)
        if step == 5:
            if body_stripped == '\u05d3\u05dc\u05d2':
                data['description'] = None
            else:
                data['description'] = body_stripped
            _set_state(from_number, 'schedule', 6, data)
            return _xml(s.SCHEDULE_STEP6)

        # Step 6: location (or 'daleg' to skip)
        if step == 6:
            if body_stripped == '\u05d3\u05dc\u05d2':
                data['location'] = None
            else:
                data['location'] = body_stripped
            _set_state(from_number, 'schedule', 7, data)
            return _xml(self._build_schedule_summary(data))

        # Step 7: confirm (asher / batel)
        if step == 7:
            if body_stripped == '\u05d1\u05d8\u05dc':
                # Use _set_state so the bot remains responsive at main_menu level.
                _set_state(from_number, 'main_menu', 1, {})
                return _xml(s.SCHEDULE_CANCELLED + '\n' + s.MAIN_MENU_TEXT)
            if body_stripped == '\u05d0\u05e9\u05e8':
                # Use _set_state so the bot remains responsive at main_menu level.
                _set_state(from_number, 'main_menu', 1, {})
                target_date = datetime.date.fromisoformat(data['date'])
                ok, result = create_event(
                    from_number,
                    target_date,
                    data['start'],
                    data['end'],
                    data['title'],
                    description=data.get('description'),
                    location=data.get('location'),
                )
                if ok:
                    msg = s.SCHEDULE_CREATED.format(
                        date=_format_date_he(target_date),
                        start=data['start'],
                        end=data['end'],
                        title=data['title'],
                    )
                    return _xml(msg)
                else:
                    return _xml(s.SCHEDULE_ERROR + '\n' + s.MAIN_MENU_TEXT)
            # Any other input at confirmation step -> re-show summary
            return _xml(s.SCHEDULE_INVALID + '\n' + self._build_schedule_summary(data))

        # Unexpected step: reset to main_menu state so the bot stays responsive.
        _set_state(from_number, 'main_menu', 1, {})
        return _xml(s.MAIN_MENU_TEXT)

    def _build_schedule_summary(self, data):
        target_date = datetime.date.fromisoformat(data['date'])
        desc_display = data.get('description') or '\u2014'
        loc_display = data.get('location') or '\u2014'
        return (
            '\u05e7\u05d1\u05e2 \u05e4\u05d2\u05d9\u05e9\u05d4:\n'
            f'\U0001f4c5 \u05ea\u05d0\u05e8\u05d9\u05da: {_format_date_he(target_date)}\n'
            f'\U0001f550 \u05e9\u05e2\u05d4: {data["start"]}\u2013{data["end"]}\n'
            f'\U0001f4dd \u05db\u05d5\u05ea\u05e8\u05ea: {data["title"]}\n'
            f'\U0001f4ac \u05ea\u05d9\u05d0\u05d5\u05e8: {desc_display}\n'
            f'\U0001f4cd \u05de\u05d9\u05e7\u05d5\u05dd: {loc_display}\n\n'
            '\u05dc\u05d0\u05d9\u05e9\u05d5\u05e8 \u05e9\u05dc\u05d7: \u05d0\u05e9\u05e8\n'
            '\u05dc\u05d1\u05d9\u05d8\u05d5\u05dc \u05e9\u05dc\u05d7: \u05d1\u05d8\u05dc'
        )

    # ----------------------------------------------------------------------- #
    # Calendar query helpers — message-string variants (TZA-121)
    # These return a plain string (not wrapped in _xml) so callers can append
    # submenu text before wrapping in _xml.
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

        if target == 'week':
            # Israeli calendar: week starts on Sunday
            # (today.weekday() + 1) % 7 gives days since last Sunday
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
                        until_str = (
                            f'\u05d1\u05e2\u05d5\u05d3 {minutes_until} \u05d3\u05e7\u05d5\u05ea'
                        )
                    elif minutes_until < 120:
                        until_str = (
                            f'\u05d1\u05e2\u05d5\u05d3 {minutes_until // 60} '
                            f'\u05e9\u05e2\u05d4 {minutes_until % 60} \u05d3\u05e7\u05d5\u05ea'
                        )
                    else:
                        until_str = (
                            f'\u05d1\u05e2\u05d5\u05d3 {minutes_until // 60} \u05e9\u05e2\u05d5\u05ea'
                        )
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
            # Israeli calendar: week starts on Sunday
            week_start = today - datetime.timedelta(days=(today.weekday() + 1) % 7)
            lines = []
            for i in range(7):
                d = week_start + datetime.timedelta(days=i)
                slots = get_free_slots_for_date(from_number, d)
                day_name = d.strftime('%A')
                if slots is None:
                    lines.append(f'{day_name}: \u05e9\u05d2\u05d9\u05d0\u05d4')
                elif not slots:
                    lines.append(f'{day_name}: \u05e2\u05de\u05d5\u05e1')
                else:
                    slot_strs = [f'{sl["start"]}\u2013{sl["end"]}' for sl in slots]
                    lines.append(f'{day_name}: {", ".join(slot_strs)}')
            return s.FREE_SLOTS_HEADER + '\n' + '\n'.join(lines)

        target, label = resolve_day(period, today)
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
                dur = f'{h}\u05e9 {mn}\u05d3'
            elif h > 0:
                dur = f'{h} \u05e9\u05e2\u05d5\u05ea'
            else:
                dur = f'{sl["minutes"]} \u05d3\u05e7\u05d5\u05ea'
            lines.append(f'\u2022 {sl["start"]}\u2013{sl["end"]} ({dur})')
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
                lines.append(f'\u2022 {b["summary"]} \u2014 {b["date"]}')
            return '\n'.join(lines)

        if not birthdays:
            return s.NO_BIRTHDAYS
        lines = [s.BIRTHDAYS_HEADER]
        for b in birthdays:
            lines.append(f'\u2022 {b["summary"]} \u2014 {b["date"]}')
        return '\n'.join(lines)

    # ----------------------------------------------------------------------- #
    # Calendar query helpers — HttpResponse variants (back-compat)
    # These delegate to the _msg variants above and wrap in _xml().
    # Existing tests that mock _query_meetings etc. continue to work.
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
    # Settings actions
    # ----------------------------------------------------------------------- #

    def _set_timezone(self, from_number, tz_name):
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken

        CalendarToken.objects.filter(phone_number=from_number).update(timezone=tz_name)
        logger.info('Timezone set to %s for phone=%s', tz_name, from_number)
        return _xml(s.TIMEZONE_SET.format(tz_name=tz_name))

    def _disconnect_calendar(self, from_number):
        import apps.standup.strings_he as s
        from apps.calendar_bot.models import CalendarToken

        deleted, _ = CalendarToken.objects.filter(phone_number=from_number).delete()
        logger.info('Calendar disconnected for phone=%s (deleted %d tokens)', from_number, deleted)
        msg = (
            '\u2705 \u05d4\u05d9\u05d5\u05de\u05df \u05e0\u05d5\u05ea\u05e7.\n\n'
            + s.MAIN_MENU_TEXT
        )
        return _xml(msg)

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
            resp.message('\u05d0\u05d9\u05df \u05e8\u05e9\u05d5\u05de\u05d5\u05ea \u05e9\u05d1\u05d5\u05e2 \u05d6\u05d4.')
        else:
            lines = [f'\u05e1\u05d9\u05db\u05d5\u05dd \u05e9\u05d1\u05d5\u05e2 {current_week}:\n']
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

    - No authentication required (status callbacks are server-to-server;
      they don't carry a Twilio request signature that matches the webhook URL).
    - Returns HTTP 204 No Content for all valid POST requests.
    """

    permission_classes = []

    def post(self, request, *args, **kwargs):
        message_sid = request.data.get('MessageSid', '')
        to = request.data.get('To', '')
        status = request.data.get('MessageStatus', '')
        error_code = request.data.get('ErrorCode', '')
        error_message = request.data.get('ErrorMessage', '')

        if status in ('sent', 'delivered'):
            logger.info(
                '[Twilio] %s \u2192 %s: %s',
                message_sid,
                to,
                status,
            )
        else:
            logger.error(
                '[Twilio] %s \u2192 %s: %s (error %s: %s)',
                message_sid,
                to,
                status,
                error_code,
                error_message,
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
