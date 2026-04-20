web: python manage.py migrate --noinput && python -m gunicorn smartclub.wsgi:application --bind 0.0.0.0:$PORT --log-file - --access-logfile -
