# Перенос на Synology DS224+ через Tailscale

## 1. Подготовить NAS

1. Установите **Container Manager** в Package Center.
2. Установите **Tailscale** на NAS и подключите NAS к вашему tailnet.
3. Создайте папку для приложения. Если старая версия уже была в этой папке и вы очистили ее содержимое, используйте эту же директорию. Рекомендуемый путь:

```text
/volume2/docker/dropandtag
```

4. Убедитесь, что папка с изображениями существует:

```text
/volume2/Личная папка для Асанали/картинки
```

## 2. Скопировать проект на NAS

Скопируйте содержимое текущего проекта в папку приложения на NAS:

```text
/volume2/docker/dropandtag
```

Можно через SMB-папку Windows, File Station, `scp` или `rsync`.

Важно: копируйте файлы проекта целиком, включая `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `manage.py`, папки `dropandtag`, `photos`, `templates`, `static`. Папку `venv` копировать не нужно.

## 3. Настроить `.env`

На NAS в папке проекта создайте файл `.env` из примера:

```sh
cp .env.example .env
```

Откройте `.env` и проверьте:

```env
APP_PORT=8000
PHOTO_ROOT="/volume2/Личная папка для Асанали/картинки"
DJANGO_ALLOWED_HOSTS=*
DJANGO_SECRET_KEY=change-this-secret-on-nas
DJANGO_DEBUG=0
TZ=Asia/Qyzylorda
```

`PHOTO_ROOT` - это путь на NAS. Внутри контейнера он будет подключен как `/media/photos`, и именно эту папку приложение покажет в дереве каталога.

Перед запуском замените `DJANGO_SECRET_KEY` на длинную случайную строку.

## 4. Запустить контейнер

В SSH на NAS:

```sh
cd /volume2/docker/dropandtag
docker compose up -d --build
```

Проверить логи:

```sh
docker compose logs -f
```

## 5. Создать пользователя для входа

```sh
docker compose exec dropandtag python manage.py createsuperuser
```

Введите логин, email можно пропустить, затем пароль.

## 6. Открыть приложение

Через домашнюю сеть:

```text
http://IP-NAS:8000
```

Например:

```text
http://192.168.1.50:8000
```

Через Tailscale:

```text
http://TAILSCALE-IP-NAS:8000
```

Или по MagicDNS-имени, если MagicDNS включен в Tailscale:

```text
http://ИМЯ-NAS:8000
```

Сначала откроется форма входа.

## 7. Если порт занят

Поменяйте в `.env`:

```env
APP_PORT=8010
```

Перезапустите:

```sh
docker compose up -d
```

Открывайте:

```text
http://IP-NAS:8010
```

## 8. Проверить, что дерево видит папку `картинки`

После входа откройте каталог. Если дерево пустое:

1. Проверьте, что в `.env` указан точный путь `PHOTO_ROOT`.
2. Проверьте права доступа Container Manager к папке `/volume2/Личная папка для Асанали/картинки`.
3. Перезапустите контейнер:

```sh
docker compose restart
```

## 9. Если будете открывать не только через Tailscale

Для Tailscale HTTP обычно достаточно `DJANGO_ALLOWED_HOSTS=*` и `DJANGO_CSRF_TRUSTED_ORIGINS=`. Если позже подключите HTTPS/reverse proxy с доменом, добавьте origin, например:

```env
DJANGO_CSRF_TRUSTED_ORIGINS=https://photos.example.com
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
```
