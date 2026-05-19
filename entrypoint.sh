#!/bin/sh
set -e

mkdir -p "$MEDIA_ROOT" "$APP_DATA_DIR"
python manage.py migrate --noinput

exec "$@"
