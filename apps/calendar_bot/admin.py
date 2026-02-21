from django.contrib import admin
from .models import CalendarToken, CalendarEventSnapshot, CalendarWatchChannel


@admin.register(CalendarToken)
class CalendarTokenAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'token_expiry', 'created_at', 'updated_at')
    search_fields = ('phone_number',)


@admin.register(CalendarEventSnapshot)
class CalendarEventSnapshotAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'event_id', 'title', 'start_time', 'status', 'updated_at')
    search_fields = ('phone_number', 'event_id', 'title')
    list_filter = ('status',)


@admin.register(CalendarWatchChannel)
class CalendarWatchChannelAdmin(admin.ModelAdmin):
    list_display = ('phone_number', 'channel_id', 'expiry', 'created_at')
    search_fields = ('phone_number',)
