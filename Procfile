release: python manage.py migrate --noinput
web: gunicorn standup_bot.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --log-file -
worker: celery -A standup_bot worker --loglevel=info --concurrency=2
beat: celery -A standup_bot beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
