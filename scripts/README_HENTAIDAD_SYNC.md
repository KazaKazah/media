# Отдельная синхронизация Hentaidad

Скрипт `hentaidad_sync.py` сохраняет каждый доступный альбом в отдельную
папку и не зависит от Django или контейнера проекта.

Используйте его только для материалов, которые вам разрешено архивировать.
Скрипт не обходит авторизацию, платный доступ или защиту сайта.

## Первый безопасный тест

```bash
cd ~/media
python3 scripts/hentaidad_sync.py \
  --output /mnt/synology/photos/picture/hentaidad \
  --state-file /home/asan/media/data/hentaidad-sync.sqlite3 \
  --max-pages 1 \
  --max-albums 2 \
  --max-images-per-album 3 \
  --dry-run \
  --confirm-adult-and-rights
```

`--dry-run` читает страницы и показывает будущие загрузки, но изображения не
сохраняет.

## Ограниченная настоящая загрузка

```bash
python3 scripts/hentaidad_sync.py \
  --output /mnt/synology/photos/picture/hentaidad \
  --state-file /home/asan/media/data/hentaidad-sync.sqlite3 \
  --max-pages 1 \
  --max-albums 2 \
  --max-images-per-album 3 \
  --confirm-adult-and-rights
```

## Полная синхронизация доступной части

После проверки:

```bash
python3 scripts/hentaidad_sync.py \
  --output /mnt/synology/photos/picture/hentaidad \
  --state-file /home/asan/media/data/hentaidad-sync.sqlite3 \
  --delay 2 \
  --confirm-adult-and-rights
```

Не рекомендуется уменьшать задержку: сайт может ограничить слишком частые
запросы.

## Что предотвращает повторное скачивание

В целевой папке создаются:

- SQLite-файл из `--state-file` — реестр альбомов, изображений, ошибок и запусков;
- `last-sync.json` — дата и итог последнего запуска;
- `.album-sync.json` внутри альбома — URL и дата последней проверки.

URL каждого изображения является уникальным ключом. При повторном запуске
известный файл пропускается, если его локальная копия существует. Неудачные и
оборванные загрузки повторяются.

Скрипт каждый раз повторно проверяет известные альбомы, поэтому новые фото,
добавленные в старый альбом, будут скачаны.

Для Synology, подключённого через CIFS, храните `--state-file` на локальном
диске VDS, как в примерах. Так блокировки SQLite не зависят от сетевой файловой
системы. Сами изображения и JSON-метки остаются на Synology.

## Авторизованный доступ

Если доступная вам часть сайта требует входа, экспортируйте cookies браузера в
формате Netscape `cookies.txt` и передайте файл:

```bash
python3 scripts/hentaidad_sync.py \
  --output /mnt/synology/photos/picture/hentaidad \
  --state-file /home/asan/media/data/hentaidad-sync.sqlite3 \
  --cookies /root/.hentaidad-cookies.txt \
  --confirm-adult-and-rights
```

Защитите его:

```bash
sudo chmod 600 /root/.hentaidad-cookies.txt
```

Cookies нельзя добавлять в Git или отправлять другим людям.

Если сайт не принимает соединения с IP-адреса VDS, можно указать принадлежащий
вам HTTP(S)-прокси:

```bash
python3 scripts/hentaidad_sync.py \
  --output /mnt/synology/photos/picture/hentaidad \
  --state-file /home/asan/media/data/hentaidad-sync.sqlite3 \
  --proxy http://user:password@proxy.example:3128 \
  --confirm-adult-and-rights
```

Не используйте случайные публичные прокси: они могут перехватывать cookies.

## Автоматический запуск

Пример ежедневного cron в 03:20:

```cron
20 3 * * * cd /home/asan/media && /usr/bin/python3 scripts/hentaidad_sync.py --output /mnt/synology/photos/picture/hentaidad --state-file /home/asan/media/data/hentaidad-sync.sqlite3 --delay 2 --confirm-adult-and-rights >> /home/asan/media/data/hentaidad-sync.log 2>&1
```

Сначала выполните несколько ручных ограниченных запусков и проверьте структуру
папок.

## Коды завершения

- `0` — успешно;
- `1` — критическая ошибка;
- `2` — завершено, но отдельные изображения или альбомы дали ошибки;
- `130` — остановлено пользователем; следующий запуск продолжит работу.
