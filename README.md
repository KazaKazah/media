# NAS Photo Drop and Tag

Django + Bootstrap 5 приложение для Synology NAS: дерево папок, просмотр фото/видео, теги и перенос файлов по папкам.

## Быстрый запуск в Docker

Перед первым запуском лучше создать `.env` из примера и заменить секрет:

```sh
cp .env.example .env
```

```sh
docker compose up -d --build
```

Откройте:

```text
http://адрес-nas:8000
```

Путь к общей папке задается переменной `PHOTO_ROOT` в `.env`.
При старте контейнер сам создает папку данных и выполняет миграции Django.

## Переменные

- `MEDIA_ROOT` - путь к папке с фото. Локально по умолчанию `./media_library`, в контейнере `/media/photos`.
- `APP_DATA_DIR` - папка для данных приложения, по умолчанию `/app/data`.
- `SQLITE_PATH` - путь к SQLite базе, локально по умолчанию `./db.sqlite3`, в контейнере `/app/data/db.sqlite3`.
- `DJANGO_SECRET_KEY` - секрет Django, для NAS лучше заменить.
- `DJANGO_ALLOWED_HOSTS` - разрешенные хосты, для домашней сети можно оставить `*`.
- `MEDIA_PAGE_SIZE` - сколько файлов отдавать за одну подгрузку, по умолчанию `60`.
- `MEDIA_TREE_MAX_DEPTH` - максимальная глубина бокового дерева папок, по умолчанию `4`.
- `DJANGO_CSRF_TRUSTED_ORIGINS` - доверенные HTTPS origins, например `https://photos.example.com`.
- `DJANGO_SECURE_SSL_REDIRECT` - включите `1`, если приложение всегда открывается через HTTPS.
- `DJANGO_SECURE_HSTS_SECONDS` - HSTS TTL в секундах; оставьте `0`, если используете HTTP в локальной сети.
- `DJANGO_SESSION_COOKIE_SECURE` и `DJANGO_CSRF_COOKIE_SECURE` - включите `1` только при HTTPS.

## Возможности

- дерево папок общей библиотеки;
- просмотр фото и видео;
- поиск по имени и тегам;
- авторизация перед доступом к медиатеке, API и медиа-файлам;
- теги хранятся в `data/tags.json` с файловой блокировкой и атомарной записью;
- перенос файлов drag-and-drop на папку слева;
- перенос выбранного файла через панель справа;
- защита API от выхода за пределы `MEDIA_ROOT`.

## Пользователь для входа

После миграций создайте учетную запись:

```sh
python manage.py createsuperuser
```

Затем откройте приложение. Без входа Django перенаправит на:

```text
/accounts/login/
```

## Локальный запуск без Docker

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
python manage.py migrate
MEDIA_ROOT="/path/to/photos" APP_DATA_DIR="./data" python manage.py runserver 0.0.0.0:8000
```

Для быстрой локальной проверки без реальной библиотеки можно создать папку:

```sh
mkdir -p media_library/test
```

## Synology DS224+

1. Установите Container Manager.
2. Скопируйте проект, например в `/volume1/docker/dropandtag`.
3. В `docker-compose.yml` укажите вашу общую папку:

```yaml
volumes:
  - ./data:/app/data
  - /volume1/photo:/media/photos
```

4. Запустите `docker compose up -d --build` или создайте проект через интерфейс Container Manager.
