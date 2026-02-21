#!/bin/bash
set -e

if [ "$SERVICE_TYPE" = "worker" ]; then
    echo "Starting Celery worker..."
    exec celery -A standup_bot worker --loglevel=info --concurrency=2
elif [ "$SERVICE_TYPE" = "beat" ]; then
    echo "Starting Celery beat..."
    exec celery -A standup_bot beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
else
    echo "Starting web server..."
    python manage.py migrate --noinput
    exec gunicorn standup_bot.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --log-file -
fi
