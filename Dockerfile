FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=0 \
    MEDIA_ROOT=/media/photos \
    APP_DATA_DIR=/app/data \
    SQLITE_PATH=/app/data/db.sqlite3

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /media/photos /app/data \
    && DJANGO_SECRET_KEY=build-time-collectstatic-key python manage.py collectstatic --noinput \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "dropandtag.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
