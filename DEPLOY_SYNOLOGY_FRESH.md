# Чистая установка контейнера на Synology DS224+

Эта инструкция создает новый контейнер с нуля. Старый контейнер можно оставить остановленным до проверки нового запуска.

## 1. Папки на NAS

Папка проекта:

```text
/volume2/docker/dropandtag
```

Папка с картинками, которую приложение должно показывать как дерево:

```text
/volume2/Личная папка для Асанали/картинки
```

## 2. Удалить старый контейнер из Container Manager

В Container Manager:

1. Остановите старый контейнер `dropandtag`.
2. Удалите старый контейнер.
3. Если есть старый проект `dropandtag`, удалите проект тоже.
4. Образы можно удалить позже, когда новая версия точно заработает.

Не удаляйте папку:

```text
/volume2/Личная папка для Асанали/картинки
```

## 3. Скопировать проект

Скопируйте текущий проект в:

```text
/volume2/docker/dropandtag
```

Не нужно копировать:

```text
venv
__pycache__
*.pyc
```

## 4. Создать `.env`

В папке проекта на NAS:

```sh
cd /volume2/docker/dropandtag
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

Замените `DJANGO_SECRET_KEY` на длинную случайную строку.

## 5. Запустить новый контейнер через SSH

```sh
cd /volume2/docker/dropandtag
docker compose -f docker-compose.synology.yml up -d --build
```

Если появляется ошибка:

```text
permission denied while trying to connect to the Docker daemon socket
```

значит текущий SSH-пользователь не имеет доступа к Docker. На Synology чаще всего нужно запускать команды через `sudo`:

```sh
sudo docker compose -f docker-compose.synology.yml config
sudo docker compose -f docker-compose.synology.yml up -d --build
sudo docker compose -f docker-compose.synology.yml ps
```

Если `sudo` просит пароль, введите пароль пользователя Synology. Если `sudo` не разрешен, зайдите в DSM под администратором и проверьте, что пользователь находится в группе `administrators`.

Проверить статус:

```sh
docker compose -f docker-compose.synology.yml ps
```

Посмотреть логи:

```sh
docker compose -f docker-compose.synology.yml logs -f
```

## 6. Создать пользователя

```sh
docker compose -f docker-compose.synology.yml exec web python manage.py createsuperuser
```

## 7. Открыть через Tailscale

В Tailscale найдите IP NAS, обычно он выглядит как `100.x.y.z`.

Откройте:

```text
http://100.x.y.z:8000
```

Если включен MagicDNS:

```text
http://имя-nas:8000
```

## 8. Проверить дерево папок

После входа приложение должно показывать содержимое:

```text
/volume2/Личная папка для Асанали/картинки
```

Внутри контейнера эта папка подключена как:

```text
/media/photos
```

Если дерево пустое, проверьте:

1. Точный путь `PHOTO_ROOT` в `.env`.
2. Права доступа Container Manager к папке `картинки`.
3. Что в папке есть файлы или подпапки с изображениями.

После исправления перезапустите:

```sh
docker compose -f docker-compose.synology.yml restart
```
