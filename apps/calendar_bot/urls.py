from django.urls import path
from . import views

urlpatterns = [
    path('auth/start/', views.calendar_auth_start, name='calendar_auth_start'),
    path('auth/callback/', views.calendar_auth_callback, name='calendar_auth_callback'),
]
