"""
NLP AI helper: sends WhatsApp user messages to Claude with tool definitions.

Replaces the rigid digit-based state machine with open Hebrew natural language.
Claude understands intent and calls the appropriate tool; this module handles
the two-step conversation (initial request → tool result → final reply).
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """אתה עוזר אישי של בוט ווטסאפ לניהול יומן.

תאריך היום: {today}

כללים חשובים:
- ענה תמיד בעברית בלבד, בצורה קצרה וידידותית
- אל תשתמש ב-markdown (כוכביות, #, -, רשימות עם *) — ווטסאפ לא מציג אותם
- אל תשתמש בטקסט אנגלי בתוך משפטים עבריים
- שעות ותאריכים — כתוב אותם בסוף משפט כדי לא לשבור את כיוון הטקסט
- אם חסרים פרטים לתזמון אירוע (כגון שעה או כותרת), שאל את המשתמש בעדינות
- לכלים שמציגים פגישות או זמן פנוי: השתמש ב-'today', 'tomorrow', 'this week', או שם יום באנגלית (monday, tuesday, wednesday, thursday, friday, saturday, sunday)
- לכלי יצירת אירוע: המר תאריך לפורמט ISO YYYY-MM-DD תוך שימוש בשנת {year} אלא אם צוינה שנה אחרת. המר שעה לפורמט HH:MM (24 שעות)
- כשהמשתמש בוחר יומן מרשימה (לפי מספר או שם), העבר את כתובת האימייל המלאה בשדה calendar_email בקריאה הבאה ל-create_event
"""


def _get_system_prompt() -> str:
    import datetime
    today = datetime.date.today()
    return _SYSTEM_PROMPT_TEMPLATE.format(today=today.isoformat(), year=today.year)

TOOLS = [
    {
        "name": "get_meetings",
        "description": "מחזיר רשימת פגישות מהיומן עבור תאריך או תקופה מסוימת",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_description": {
                    "type": "string",
                    "description": (
                        "תאריך או תקופה. השתמש ב: 'today', 'tomorrow', 'this week', "
                        "או שם יום באנגלית כגון 'monday', 'tuesday', 'wednesday'"
                    ),
                }
            },
            "required": ["date_description"],
        },
    },
    {
        "name": "get_next_meeting",
        "description": "מחזיר את הפגישה הקרובה ביותר מעכשיו",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_free_time",
        "description": "מחזיר את הזמנים הפנויים ביומן עבור תאריך או תקופה מסוימת",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_description": {
                    "type": "string",
                    "description": (
                        "תאריך או תקופה. השתמש ב: 'today', 'tomorrow', 'this week', "
                        "או שם יום באנגלית"
                    ),
                }
            },
            "required": ["date_description"],
        },
    },
    {
        "name": "get_birthdays",
        "description": "מחזיר ימי הולדת מהיומן לשבוע הקרוב או לחודש הנוכחי",
        "input_schema": {
            "type": "object",
            "properties": {
                "period_description": {
                    "type": "string",
                    "description": "תקופה: 'week' לשבוע הקרוב, 'month' לחודש הנוכחי",
                }
            },
            "required": ["period_description"],
        },
    },
    {
        "name": "create_event",
        "description": (
            "יוצר אירוע חדש ביומן Google. "
            "דרוש: תאריך ISO (YYYY-MM-DD), שעת התחלה (HH:MM), שעת סיום (HH:MM), כותרת. "
            "אם המשתמש ציין לאיזה יומן (לפי כינוי כמו personal/work או אימייל), כלול calendar_label או calendar_email. "
            "אם לא ציין, אל תכלול אותם — המערכת תשאל אותו."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date_description": {
                    "type": "string",
                    "description": "תאריך האירוע בפורמט YYYY-MM-DD",
                },
                "start_time": {
                    "type": "string",
                    "description": "שעת התחלה בפורמט HH:MM (24 שעות)",
                },
                "end_time": {
                    "type": "string",
                    "description": "שעת סיום בפורמט HH:MM (24 שעות)",
                },
                "title": {
                    "type": "string",
                    "description": "כותרת האירוע",
                },
                "description": {
                    "type": "string",
                    "description": "תיאור האירוע (אופציונלי)",
                },
                "location": {
                    "type": "string",
                    "description": "מיקום האירוע (אופציונלי)",
                },
                "calendar_email": {
                    "type": "string",
                    "description": "כתובת האימייל של היומן שבו ליצור את האירוע (אופציונלי)",
                },
                "calendar_label": {
                    "type": "string",
                    "description": (
                        "כינוי היומן שבו ליצור את האירוע, לדוגמה: personal, work, אישי, עבודה (אופציונלי). "
                        "השתמש בזה כשהמשתמש מציין את שם היומן במילים."
                    ),
                },
            },
            "required": ["date_description", "start_time", "end_time", "title"],
        },
    },
    {
        "name": "set_timezone",
        "description": "מגדיר את אזור הזמן של המשתמש",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone_name": {
                    "type": "string",
                    "description": (
                        "שם אזור הזמן בפורמט IANA, "
                        "לדוגמה: Asia/Jerusalem, Europe/London, America/New_York, Europe/Paris"
                    ),
                }
            },
            "required": ["timezone_name"],
        },
    },
    {
        "name": "connect_calendar",
        "description": "מחזיר קישור לחיבור יומן Google חדש",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "disconnect_calendar",
        "description": "מנתק את יומן Google המחובר ומוחק את הטוקן",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def ask_claude_with_tools(user_message: str, history: list) -> dict:
    """
    Send user_message to Claude with tool definitions.

    Returns one of:
      {'type': 'text', 'content': str}
      {'type': 'tool_use', 'name': str, 'input': dict, 'id': str}
    """
    import anthropic
    import os

    api_key = settings.ANTHROPIC_API_KEY or os.environ.get('ANTHROPIC_API_KEY', '')
    logger.warning('ANTHROPIC_API_KEY present=%s len=%d', bool(api_key), len(api_key))
    messages = history + [{"role": "user", "content": user_message}]
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=_get_system_prompt(),
        tools=TOOLS,
        messages=messages,
    )
    for block in response.content:
        if block.type == "tool_use":
            return {
                "type": "tool_use",
                "name": block.name,
                "input": block.input,
                "id": block.id,
            }
    text = next((b.text for b in response.content if hasattr(b, "text")), "")
    return {"type": "text", "content": text}


def ask_claude_with_result(
    user_message: str, tool_call: dict, tool_result_str: str, history: list
) -> str:
    """
    Feed the tool result back to Claude and return the final Hebrew reply string.
    """
    import anthropic
    import os

    api_key = settings.ANTHROPIC_API_KEY or os.environ.get('ANTHROPIC_API_KEY', '')
    messages = history + [
        {"role": "user", "content": user_message},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_call["id"],
                    "name": tool_call["name"],
                    "input": tool_call["input"],
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call["id"],
                    "content": tool_result_str,
                }
            ],
        },
    ]
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system=_get_system_prompt(),
        messages=messages,
    )
    return next(
        (b.text for b in response.content if hasattr(b, "text")),
        "מצטער, אירעה שגיאה בעיבוד התשובה.",
    )
