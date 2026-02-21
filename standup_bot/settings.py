# This file is intentionally disabled.
# Use standup_bot/settings/dev.py (local) or standup_bot/settings/prod.py (production)
# Set DJANGO_SETTINGS_MODULE accordingly.
raise ImportError(
    "Do not import standup_bot.settings directly. "
    "Set DJANGO_SETTINGS_MODULE=standup_bot.settings.prod (or .dev for local)."
)
