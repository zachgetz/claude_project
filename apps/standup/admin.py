from django.contrib import admin
from .models import StandupEntry

@admin.register(StandupEntry)
class StandupEntryAdmin(admin.ModelAdmin):
    list_display = ['phone_number', 'week_number', 'created_at']
    list_filter = ['phone_number', 'week_number']
    search_fields = ['phone_number', 'message']
    ordering = ['-created_at']
