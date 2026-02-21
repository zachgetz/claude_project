from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse


def health_check(request):
    return HttpResponse("OK", status=200)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),
    path('bot/', include('apps.bot.urls')),
    path('standup/', include('apps.standup.urls')),
    path('calendar/', include('apps.calendar_bot.urls')),
]
