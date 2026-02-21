from django.contrib import admin
from .models import CalendarToken


@admin.register(CalendarToken)
class CalendarTokenAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'token_expiry', 'created_at', 'updated_at')
    search_fields = ('phone_number',)
