# Перенос на Synology DS224+

## 1. Подготовить NAS

1. Установите **Container Manager** в Package Center.
2. Создайте папку для приложения, например:

```text
/volume1/docker/dropandtag
```

3. Убедитесь, что папка с фото существует, например:

```text
/volume1/photo
```

## 2. Скопировать проект на NAS

Скопируйте содержимое проекта в:

```text
/volume1/docker/dropandtag
```

Можно через SMB-папку Windows, File Station, `scp` или `rsync`.

## 3. Настроить `.env`

На NAS в папке проекта создайте файл `.env` из примера:

```sh
cp .env.example .env
```

Откройте `.env` и проверьте:

```env
APP_PORT=8000
PHOTO_ROOT=/volume1/photo
DJANGO_ALLOWED_HOSTS=*
DJANGO_SECRET_KEY=change-this-secret-on-nas
DJANGO_DEBUG=0
TZ=Asia/Qyzylorda
```

Перед доступом из интернета замените `DJANGO_SECRET_KEY` на длинную случайную строку.

## 4. Запустить контейнер

В SSH на NAS:

```sh
cd /volume1/docker/dropandtag
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

В домашней сети:

```text
http://IP-NAS:8000
```

Например:

```text
http://192.168.1.50:8000
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

## 8. Для доступа не из дома

Безопаснее сначала использовать VPN/Tailscale. Если будете открывать наружу через DDNS/reverse proxy, используйте HTTPS и оставьте авторизацию включенной.
