import json
import hashlib
import mimetypes
import os
import shutil
import socket
import sqlite3
import tempfile
import time
from html.parser import HTMLParser
from ipaddress import ip_address
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

import fcntl

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover - optional dependency during deploy upgrades
    Image = ImageOps = UnidentifiedImageError = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
IMPORT_USER_AGENT = "DropAndTag/1.0 media importer"
IMPORT_MAX_IMAGES = 60
IMPORT_MAX_GALLERIES = 30
IMPORT_MAX_BYTES = 25 * 1024 * 1024
IMPORT_HTML_MAX_BYTES = 4 * 1024 * 1024
INDEX_STALE_SECONDS = 60
THUMBNAIL_SIZES = {
    "thumb": (720, 900),
    "preview": (1800, 1800),
}


def media_root() -> Path:
    root = settings.MEDIA_LIBRARY_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir() -> Path:
    root = settings.APP_DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def tags_file() -> Path:
    target = data_dir() / "tags.json"
    if not target.exists():
        target.write_text("{}\n", encoding="utf-8")
    return target


def covers_file() -> Path:
    target = data_dir() / "covers.json"
    if not target.exists():
        target.write_text("{}\n", encoding="utf-8")
    return target


def imports_file() -> Path:
    target = data_dir() / "imports.json"
    if not target.exists():
        target.write_text("{}\n", encoding="utf-8")
    return target


def index_file() -> Path:
    return data_dir() / "media_index.sqlite3"


def thumbnail_dir() -> Path:
    target = data_dir() / "thumbs"
    target.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def locked_data_file(target: Path):
    lock_path = target.with_suffix(f"{target.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_json_file(target: Path) -> dict:
    with locked_data_file(target):
        content = target.read_text(encoding="utf-8") or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target.name} contains invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{target.name} must contain a JSON object")
    return data


def write_json_file(target: Path, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with locked_data_file(target):
        fd, temp_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path.exists():
                temp_path.unlink()


def update_json_file(target: Path, updater) -> dict:
    with locked_data_file(target):
        content = target.read_text(encoding="utf-8") or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target.name} contains invalid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{target.name} must contain a JSON object")

        result = updater(data)
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        return result


def normalize_relative(value: str | None = "") -> str:
    raw = str(value or "").replace("\\", "/").lstrip("/")
    normalized = os.path.normpath(raw).replace("\\", "/")
    if normalized in {".", ""}:
        return ""
    if normalized == ".." or normalized.startswith("../") or os.path.isabs(normalized):
        raise SuspiciousFileOperation("Path escapes media root")
    return normalized


def resolve_media_path(value: str | None = "") -> tuple[str, Path]:
    clean = normalize_relative(value)
    absolute = (media_root() / clean).resolve()
    try:
        absolute.relative_to(media_root())
    except ValueError as exc:
        raise SuspiciousFileOperation("Path escapes media root") from exc
    return clean, absolute


def read_tags() -> dict[str, list[str]]:
    return read_json_file(tags_file())


def write_tags(data: dict[str, list[str]]) -> None:
    write_json_file(tags_file(), data)


def read_covers() -> dict[str, str]:
    return read_json_file(covers_file())


def write_covers(data: dict[str, str]) -> None:
    write_json_file(covers_file(), data)


def update_tags(updater) -> dict:
    return update_json_file(tags_file(), updater)


def update_covers(updater) -> dict:
    return update_json_file(covers_file(), updater)


def update_imports(updater) -> dict:
    return update_json_file(imports_file(), updater)


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def media_kind(path: Path) -> str:
    return "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video"


def folder_child_count(path: Path) -> int:
    try:
        with os.scandir(path) as entries:
            return sum(
                1
                for entry in entries
                if not entry.name.startswith(".") and entry.is_dir(follow_symlinks=False)
            )
    except OSError:
        return 0


def list_tree(relative_path: str = "", depth: int = 0) -> list[dict]:
    clean, absolute = resolve_media_path(relative_path)
    folders = []
    with os.scandir(absolute) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if not is_dir:
                continue
            child_rel = f"{clean}/{entry.name}" if clean else entry.name
            children = []
            if depth + 1 < settings.MEDIA_TREE_MAX_DEPTH:
                children = list_tree(child_rel, depth + 1)
            folders.append({
                "name": entry.name,
                "path": child_rel,
                "children": children,
                "childCount": folder_child_count(child),
            })
    return sorted(folders, key=lambda item: item["name"].casefold())


def list_folder_children(relative_path: str = "") -> list[dict]:
    clean, absolute = resolve_media_path(relative_path)
    folders = []
    with os.scandir(absolute) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            child = absolute / entry.name
            child_rel = f"{clean}/{entry.name}" if clean else entry.name
            folders.append({
                "name": entry.name,
                "path": child_rel,
                "children": [],
                "childCount": folder_child_count(child),
                "childrenLoaded": False,
            })
    return sorted(folders, key=lambda item: item["name"].casefold())


def bounded_int(value, default: int, minimum: int = 0, maximum: int = 500) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def list_folder(relative_path: str = "", offset: int = 0, limit: int | None = None) -> dict:
    clean, absolute = resolve_media_path(relative_path)
    offset = bounded_int(offset, 0, minimum=0, maximum=1_000_000)
    limit = bounded_int(limit, settings.MEDIA_PAGE_SIZE, minimum=1, maximum=200)
    folder_tags = read_tags()
    folder_covers = read_covers()
    folders = []
    files = []

    with os.scandir(absolute) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            child = absolute / entry.name
            child_rel = f"{clean}/{entry.name}" if clean else entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                folders.append({
                    "name": entry.name,
                    "path": child_rel,
                    "type": "folder",
                    "cover": folder_covers.get(child_rel, ""),
                })
                continue
            if not is_file or not is_media_file(child):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            files.append({
                "name": entry.name,
                "path": child_rel,
                "type": media_kind(child),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "tags": folder_tags.get(child_rel, []),
            })

    folders.sort(key=lambda item: item["name"].casefold())
    files.sort(key=lambda item: item["modified"], reverse=True)
    cover_path = folder_covers.get(clean, "")
    if cover_path:
        files.sort(key=lambda item: item["path"] != cover_path)
    total_files = len(files)
    paged_files = files[offset:offset + limit]
    next_offset = offset + len(paged_files)
    return {
        "path": clean,
        "cover": cover_path,
        "folders": folders,
        "files": paged_files,
        "fileCount": total_files,
        "offset": offset,
        "nextOffset": next_offset,
        "hasMore": next_offset < total_files,
    }


def index_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(index_file())
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS media_entries (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            parent TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0,
            modified REAL NOT NULL DEFAULT 0,
            tags TEXT NOT NULL DEFAULT '',
            cover TEXT NOT NULL DEFAULT '',
            search_text TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS media_entries_type_idx ON media_entries(type)")
    connection.execute("CREATE INDEX IF NOT EXISTS media_entries_modified_idx ON media_entries(modified)")
    return connection


def mark_media_index_stale() -> None:
    target = index_file()
    if target.exists():
        os.utime(target, (0, 0))


def media_index_is_stale() -> bool:
    target = index_file()
    return not target.exists() or time.time() - target.stat().st_mtime > INDEX_STALE_SECONDS


def refresh_media_index(force: bool = False) -> None:
    if not force and not media_index_is_stale():
        return

    folder_tags = read_tags()
    folder_covers = read_covers()
    root = media_root()
    rows = []

    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        dirnames[:] = sorted(
            [dirname for dirname in dirnames if not dirname.startswith(".")],
            key=str.casefold,
        )
        current_rel = "" if current_path == root else current_path.relative_to(root).as_posix()

        for dirname in dirnames:
            child = current_path / dirname
            child_rel = child.relative_to(root).as_posix()
            parent = child.parent.relative_to(root).as_posix() if child.parent != root else ""
            cover = folder_covers.get(child_rel, "")
            search_text = " ".join([dirname, child_rel, cover]).casefold()
            rows.append((child_rel, dirname, "folder", parent, 0, 0, "", cover, search_text))

        for filename in filenames:
            if filename.startswith("."):
                continue
            child = current_path / filename
            if not is_media_file(child):
                continue
            child_rel = child.relative_to(root).as_posix()
            try:
                stat = child.stat()
            except OSError:
                continue
            tags = " ".join(folder_tags.get(child_rel, []))
            search_text = " ".join([filename, child_rel, tags]).casefold()
            rows.append((
                child_rel,
                filename,
                media_kind(child),
                current_rel,
                stat.st_size,
                stat.st_mtime,
                tags,
                "",
                search_text,
            ))

    with index_connection() as connection:
        connection.execute("DELETE FROM media_entries")
        connection.executemany(
            """
            INSERT INTO media_entries (
                path, name, type, parent, size, modified, tags, cover, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()


def indexed_file_entry(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "path": row["path"],
        "type": row["type"],
        "size": row["size"],
        "modified": row["modified"],
        "tags": [tag for tag in row["tags"].split(" ") if tag],
    }


def indexed_folder_entry(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "path": row["path"],
        "type": "folder",
        "cover": row["cover"],
        "tags": [],
    }


def matches_media_query(entry: dict, query: str) -> bool:
    haystack = [
        entry.get("name", ""),
        entry.get("path", ""),
        " ".join(entry.get("tags", [])),
    ]
    return query in " ".join(haystack).casefold()


def search_media(query: str, limit: int = 240) -> dict:
    clean_query = str(query or "").strip()
    if not clean_query:
        return list_folder("")

    query_folded = clean_query.casefold()
    limit = bounded_int(limit, 240, minimum=1, maximum=500)
    refresh_media_index()
    pattern = f"%{query_folded}%"
    with index_connection() as connection:
        connection.row_factory = sqlite3.Row
        folder_rows = connection.execute(
            """
            SELECT * FROM media_entries
            WHERE type = 'folder' AND search_text LIKE ?
            ORDER BY path COLLATE NOCASE
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
        file_rows = connection.execute(
            """
            SELECT * FROM media_entries
            WHERE type != 'folder' AND search_text LIKE ?
            ORDER BY modified DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()

    folders = [indexed_folder_entry(row) for row in folder_rows]
    files = [indexed_file_entry(row) for row in file_rows]
    return {
        "path": "",
        "query": clean_query,
        "folders": folders,
        "files": files,
        "fileCount": len(files),
        "folderCount": len(folders),
        "offset": 0,
        "nextOffset": len(files),
        "hasMore": False,
        "limited": len(folders) + len(files) >= limit * 2,
    }


def path_is_inside_folder(file_path: str, folder_path: str) -> bool:
    if not folder_path:
        return True
    return file_path == folder_path or file_path.startswith(f"{folder_path}/")


def unique_destination(folder: Path, filename: str) -> Path:
    destination = folder / filename
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    counter = 1
    while True:
        candidate = folder / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def sanitize_folder_name(name: str) -> str:
    clean = str(name or "").strip().strip(".")
    if not clean:
        raise ValueError("Folder name is required")
    if "/" in clean or "\\" in clean or clean in {".", ".."}:
        raise ValueError("Folder name cannot contain slashes")
    return clean[:120]


def sanitize_file_name(name: str, original_suffix: str = "") -> str:
    clean = Path(str(name or "").strip()).name.strip().strip(".")
    if not clean:
        raise ValueError("File name is required")
    if "/" in clean or "\\" in clean or clean in {".", ".."}:
        raise ValueError("File name cannot contain slashes")
    candidate = clean[:160]
    if not Path(candidate).suffix and original_suffix:
        candidate = f"{candidate}{original_suffix}"
    if Path(candidate).suffix.lower() not in MEDIA_EXTENSIONS:
        raise ValueError("File extension is not supported")
    return candidate


class ImageSourceParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.urls = []

    def add_url(self, value: str | None):
        if not value:
            return
        value = value.strip()
        if not value or value.startswith("data:"):
            return
        self.urls.append(urljoin(self.base_url, value))

    def add_srcset(self, value: str | None):
        if not value:
            return
        for candidate in value.split(","):
            self.add_url(candidate.strip().split(" ")[0])

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"img", "source"}:
            self.add_url(attrs.get("src"))
            self.add_url(attrs.get("data-src"))
            self.add_url(attrs.get("data-original"))
            self.add_srcset(attrs.get("srcset"))
            self.add_srcset(attrs.get("data-srcset"))
        if tag == "a":
            self.add_url(attrs.get("href"))
        if tag == "meta" and attrs.get("property") in {"og:image", "twitter:image"}:
            self.add_url(attrs.get("content"))


class LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href")
        if not href:
            return
        href = href.strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return
        self.links.append(urljoin(self.base_url, href))


def assert_public_http_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Введите полный http/https адрес")
    host = parsed.hostname
    if not host:
        raise ValueError("Не удалось определить домен")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Не удалось найти сайт") from exc
    for address in addresses:
        parsed_ip = ip_address(address)
        if parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local or parsed_ip.is_reserved:
            raise ValueError("Нельзя импортировать с локальных или внутренних адресов")
    return parsed.geturl()


def fetch_url(url: str, max_bytes: int) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": IMPORT_USER_AGENT})
    with urlopen(request, timeout=12) as response:
        content_type = response.headers.get_content_type()
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError("Файл слишком большой")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Файл слишком большой")
    return data, content_type


def image_suffix_from_url(url: str, content_type: str = "") -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed and guessed.lower() in IMAGE_EXTENSIONS:
        return guessed.lower()
    return ".jpg"


def image_filename_from_url(url: str, index: int, content_type: str = "") -> str:
    parsed_name = Path(unquote(urlparse(url).path)).name
    suffix = image_suffix_from_url(url, content_type)
    if not parsed_name or not Path(parsed_name).suffix:
        parsed_name = f"site-image-{index}{suffix}"
    return sanitize_file_name(parsed_name, suffix)


def import_folder_name(page_url: str) -> str:
    host = urlparse(page_url).hostname or "site"
    safe_host = "".join(char if char.isalnum() else "-" for char in host).strip("-") or "site"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return sanitize_folder_name(f"{safe_host}-{timestamp}")


def gallery_folder_name(gallery_url: str, index: int) -> str:
    parsed = urlparse(gallery_url)
    parts = [part for part in unquote(parsed.path).split("/") if part]
    raw_name = parts[-1] if parts else parsed.hostname or f"gallery-{index}"
    if Path(raw_name).suffix:
        raw_name = Path(raw_name).stem
    safe_name = "".join(char if char.isalnum() or char in {" ", "-", "_"} else "-" for char in raw_name)
    safe_name = safe_name.strip(" -_.") or f"gallery-{index}"
    return sanitize_folder_name(f"{index:02d}-{safe_name}")


def same_site_url(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    return candidate.scheme in {"http", "https"} and candidate.netloc == base.netloc


def extract_gallery_links(page_url: str, html: bytes) -> list[str]:
    parser = LinkParser(page_url)
    parser.feed(html.decode("utf-8", errors="ignore"))
    result = []
    seen = {page_url.rstrip("/")}
    for candidate in parser.links:
        parsed = urlparse(candidate)
        clean = parsed._replace(fragment="", query=parsed.query).geturl()
        if clean.rstrip("/") in seen:
            continue
        if not same_site_url(page_url, clean):
            continue
        suffix = Path(unquote(parsed.path)).suffix.lower()
        if suffix in IMAGE_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
            continue
        seen.add(clean.rstrip("/"))
        result.append(clean)
    return result


def extract_image_urls(page_url: str, html: bytes) -> list[str]:
    parser = ImageSourceParser(page_url)
    parser.feed(html.decode("utf-8", errors="ignore"))
    result = []
    seen = set()
    for candidate in parser.urls:
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.geturl() in seen:
            continue
        suffix = Path(unquote(parsed.path)).suffix.lower()
        if suffix and suffix not in IMAGE_EXTENSIONS:
            continue
        seen.add(parsed.geturl())
        result.append(parsed.geturl())
    return result


def save_imported_images(target_path: Path, image_urls: list[str], limit: int, skipped: list[dict]) -> list[str]:
    saved = []
    for index, image_url in enumerate(image_urls[:limit], start=1):
        try:
            assert_public_http_url(image_url)
            data, content_type = fetch_url(image_url, IMPORT_MAX_BYTES)
            if not content_type.startswith("image/"):
                skipped.append({"url": image_url, "reason": "not image"})
                continue
            filename = image_filename_from_url(image_url, index, content_type)
            destination = unique_destination(target_path, filename)
            destination.write_bytes(data)
            saved.append(destination.relative_to(media_root()).as_posix())
        except (OSError, ValueError) as exc:
            skipped.append({"url": image_url, "reason": str(exc)})
    return saved


def import_registry_key(source_url: str, parent_folder: str) -> str:
    parsed = urlparse(source_url)
    return f"{parsed.scheme}://{parsed.netloc}|{parent_folder}"


def import_images_from_site(target_folder: str, page_url: str, limit: int = IMPORT_MAX_IMAGES) -> dict:
    parent_rel, parent_path = resolve_media_path(target_folder)
    if not parent_path.is_dir():
        raise ValueError("Target is not a folder")
    safe_url = assert_public_http_url(page_url)
    downloads = parent_path / "Загрузки"
    downloads.mkdir(exist_ok=True)
    target_path = unique_destination(downloads, import_folder_name(safe_url))
    target_path.mkdir()
    target_rel = target_path.relative_to(media_root()).as_posix()
    limit = bounded_int(limit, IMPORT_MAX_IMAGES, minimum=1, maximum=IMPORT_MAX_IMAGES)
    page_data, page_type = fetch_url(safe_url, IMPORT_HTML_MAX_BYTES)
    if page_type.startswith("image/"):
        image_urls = [safe_url]
    else:
        image_urls = extract_image_urls(safe_url, page_data)
    gallery_links = [] if page_type.startswith("image/") else extract_gallery_links(safe_url, page_data)

    saved = []
    skipped = []
    galleries = []
    skipped_existing = 0
    imported_now = []
    registry_key = import_registry_key(safe_url, parent_rel)
    imported_data = read_json_file(imports_file())

    def already_imported(gallery_url: str) -> bool:
        return gallery_url in set(imported_data.get(registry_key, []))

    def remember_imports(data):
        current = set(data.get(registry_key, []))
        current.update(imported_now)
        data[registry_key] = sorted(current)
        return {"remembered": len(imported_now), "total": len(data[registry_key])}

    found_count = len(image_urls)
    if gallery_links:
        found_count = 0
        for gallery_index, gallery_url in enumerate(gallery_links[:IMPORT_MAX_GALLERIES], start=1):
            try:
                assert_public_http_url(gallery_url)
                if already_imported(gallery_url):
                    skipped_existing += 1
                    continue
                gallery_data, gallery_type = fetch_url(gallery_url, IMPORT_HTML_MAX_BYTES)
                if gallery_type.startswith("image/"):
                    gallery_images = [gallery_url]
                else:
                    gallery_images = extract_image_urls(gallery_url, gallery_data)
                if not gallery_images:
                    skipped.append({"url": gallery_url, "reason": "no images"})
                    continue
                found_count += len(gallery_images)
                gallery_path = unique_destination(target_path, gallery_folder_name(gallery_url, gallery_index))
                gallery_path.mkdir()
                gallery_saved = save_imported_images(gallery_path, gallery_images, limit, skipped)
                saved.extend(gallery_saved)
                galleries.append({
                    "url": gallery_url,
                    "folder": gallery_path.relative_to(media_root()).as_posix(),
                    "found": len(gallery_images),
                    "saved": gallery_saved,
                })
                if gallery_saved:
                    imported_now.append(gallery_url)
            except (OSError, ValueError) as exc:
                skipped.append({"url": gallery_url, "reason": str(exc)})
    else:
        if already_imported(safe_url):
            skipped_existing = 1
        else:
            saved = save_imported_images(target_path, image_urls, limit, skipped)
            if saved:
                imported_now.append(safe_url)

    if imported_now:
        update_imports(remember_imports)
    if saved:
        mark_media_index_stale()

    return {
        "folder": target_rel,
        "parentFolder": parent_rel,
        "source": safe_url,
        "found": found_count,
        "galleryCount": len(galleries),
        "galleryLinksFound": len(gallery_links),
        "skippedExisting": skipped_existing,
        "galleries": galleries,
        "saved": saved,
        "skipped": skipped,
        "limit": limit,
    }


def create_folder(parent: str, name: str) -> dict:
    parent_rel, parent_path = resolve_media_path(parent)
    if not parent_path.is_dir():
        raise ValueError("Parent is not a folder")
    folder_name = sanitize_folder_name(name)
    destination = parent_path / folder_name
    if destination.exists():
        raise ValueError("Folder already exists")
    destination.mkdir()
    mark_media_index_stale()
    return {
        "name": folder_name,
        "path": f"{parent_rel}/{folder_name}" if parent_rel else folder_name,
    }


def save_uploaded_files(target_folder: str, uploaded_files) -> dict:
    target_rel, target_path = resolve_media_path(target_folder)
    if not target_path.is_dir():
        raise ValueError("Target is not a folder")

    saved = []
    skipped = []
    for uploaded_file in uploaded_files:
        filename = Path(uploaded_file.name).name
        if not filename:
            skipped.append(uploaded_file.name)
            continue
        if Path(filename).suffix.lower() not in MEDIA_EXTENSIONS:
            skipped.append(filename)
            continue

        destination = unique_destination(target_path, filename)
        with destination.open("wb") as file:
            for chunk in uploaded_file.chunks():
                file.write(chunk)
        saved.append(destination.relative_to(media_root()).as_posix())

    if saved:
        mark_media_index_stale()
    return {"folder": target_rel, "saved": saved, "skipped": skipped}


def move_media_file(source: str, target_folder: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    target_rel, target_path = resolve_media_path(target_folder)
    if not source_path.is_file() or not is_media_file(source_path):
        raise ValueError("Source is not a supported media file")
    if not target_path.is_dir():
        raise ValueError("Target is not a folder")
    if source_path.parent == target_path:
        return {"from": source_rel, "to": source_rel}

    destination = unique_destination(target_path, source_path.name)
    shutil.move(str(source_path), str(destination))
    destination_rel = destination.relative_to(media_root()).as_posix()

    def move_tags(folder_tags):
        if source_rel in folder_tags:
            folder_tags[destination_rel] = folder_tags.pop(source_rel)

    update_tags(move_tags)

    def move_covers(folder_covers):
        for folder_path, cover_path in list(folder_covers.items()):
            if cover_path == source_rel:
                folder_covers[folder_path] = destination_rel

    update_covers(move_covers)
    mark_media_index_stale()

    return {"from": source_rel, "to": destination_rel}


def move_folder(source: str, target_folder: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    target_rel, target_path = resolve_media_path(target_folder)
    if not source_rel:
        raise ValueError("Root folder cannot be moved")
    if not source_path.is_dir():
        raise ValueError("Source is not a folder")
    if not target_path.is_dir():
        raise ValueError("Target is not a folder")
    if source_path.parent == target_path:
        return {"from": source_rel, "to": source_rel}
    try:
        target_path.relative_to(source_path)
        raise ValueError("Folder cannot be moved into itself")
    except ValueError as error:
        if str(error) == "Folder cannot be moved into itself":
            raise

    destination = unique_destination(target_path, source_path.name)
    shutil.move(str(source_path), str(destination))
    destination_rel = destination.relative_to(media_root()).as_posix()

    prefix = f"{source_rel}/"

    def move_tags(folder_tags):
        moved_tags = {}
        for file_path, tags in folder_tags.items():
            if file_path == source_rel or file_path.startswith(prefix):
                suffix = file_path[len(source_rel):].lstrip("/")
                moved_tags[f"{destination_rel}/{suffix}" if suffix else destination_rel] = tags
            else:
                moved_tags[file_path] = tags
        folder_tags.clear()
        folder_tags.update(moved_tags)

    update_tags(move_tags)

    def move_covers(folder_covers):
        moved_covers = {}
        for folder_path, cover_path in folder_covers.items():
            next_folder = folder_path
            next_cover = cover_path
            if folder_path == source_rel or folder_path.startswith(prefix):
                suffix = folder_path[len(source_rel):].lstrip("/")
                next_folder = f"{destination_rel}/{suffix}" if suffix else destination_rel
            if cover_path == source_rel or cover_path.startswith(prefix):
                suffix = cover_path[len(source_rel):].lstrip("/")
                next_cover = f"{destination_rel}/{suffix}" if suffix else destination_rel
            moved_covers[next_folder] = next_cover
        folder_covers.clear()
        folder_covers.update(moved_covers)

    update_covers(move_covers)
    mark_media_index_stale()

    return {"from": source_rel, "to": destination_rel}


def move_entry(source: str, target_folder: str, entry_type: str = "file") -> dict:
    if entry_type == "folder":
        return move_folder(source, target_folder)
    return move_media_file(source, target_folder)


def cleanup_deleted_metadata(deleted_rel: str, entry_type: str) -> None:
    prefix = f"{deleted_rel}/"

    def clean_tags(folder_tags):
        for file_path in list(folder_tags.keys()):
            if file_path == deleted_rel or (entry_type == "folder" and file_path.startswith(prefix)):
                folder_tags.pop(file_path, None)

    update_tags(clean_tags)

    def clean_covers(folder_covers):
        for folder_path, cover_path in list(folder_covers.items()):
            folder_deleted = entry_type == "folder" and (
                folder_path == deleted_rel or folder_path.startswith(prefix)
            )
            cover_deleted = cover_path == deleted_rel or (
                entry_type == "folder" and cover_path.startswith(prefix)
            )
            if folder_deleted or cover_deleted:
                folder_covers.pop(folder_path, None)

    update_covers(clean_covers)


def delete_media_file(source: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    if not source_path.is_file() or not is_media_file(source_path):
        raise ValueError("Source is not a supported media file")
    source_path.unlink()
    cleanup_deleted_metadata(source_rel, "file")
    mark_media_index_stale()
    return {"deleted": source_rel, "type": "file"}


def delete_folder(source: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    if not source_rel:
        raise ValueError("Root folder cannot be deleted")
    if not source_path.is_dir():
        raise ValueError("Source is not a folder")
    shutil.rmtree(source_path)
    cleanup_deleted_metadata(source_rel, "folder")
    mark_media_index_stale()
    return {"deleted": source_rel, "type": "folder"}


def delete_entry(source: str, entry_type: str = "file") -> dict:
    if entry_type == "folder":
        return delete_folder(source)
    return delete_media_file(source)


def replace_metadata_path(old_rel: str, new_rel: str, entry_type: str) -> None:
    prefix = f"{old_rel}/"

    def move_tags(folder_tags):
        moved_tags = {}
        for file_path, tags in folder_tags.items():
            if file_path == old_rel or (entry_type == "folder" and file_path.startswith(prefix)):
                suffix = file_path[len(old_rel):].lstrip("/")
                moved_tags[f"{new_rel}/{suffix}" if suffix else new_rel] = tags
            else:
                moved_tags[file_path] = tags
        folder_tags.clear()
        folder_tags.update(moved_tags)

    update_tags(move_tags)

    def move_covers(folder_covers):
        moved_covers = {}
        for folder_path, cover_path in folder_covers.items():
            next_folder = folder_path
            next_cover = cover_path
            if entry_type == "folder" and (folder_path == old_rel or folder_path.startswith(prefix)):
                suffix = folder_path[len(old_rel):].lstrip("/")
                next_folder = f"{new_rel}/{suffix}" if suffix else new_rel
            if cover_path == old_rel or (entry_type == "folder" and cover_path.startswith(prefix)):
                suffix = cover_path[len(old_rel):].lstrip("/")
                next_cover = f"{new_rel}/{suffix}" if suffix else new_rel
            moved_covers[next_folder] = next_cover
        folder_covers.clear()
        folder_covers.update(moved_covers)

    update_covers(move_covers)


def rename_media_file(source: str, new_name: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    if not source_path.is_file() or not is_media_file(source_path):
        raise ValueError("Source is not a supported media file")
    filename = sanitize_file_name(new_name, source_path.suffix)
    destination = source_path.with_name(filename)
    if destination == source_path:
        return {"from": source_rel, "to": source_rel, "name": source_path.name, "type": "file"}
    if destination.exists():
        raise ValueError("A file or folder with this name already exists")
    source_path.rename(destination)
    destination_rel = destination.relative_to(media_root()).as_posix()
    replace_metadata_path(source_rel, destination_rel, "file")
    mark_media_index_stale()
    return {"from": source_rel, "to": destination_rel, "name": destination.name, "type": "file"}


def rename_folder(source: str, new_name: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    if not source_rel:
        raise ValueError("Root folder cannot be renamed")
    if not source_path.is_dir():
        raise ValueError("Source is not a folder")
    folder_name = sanitize_folder_name(new_name)
    destination = source_path.with_name(folder_name)
    if destination == source_path:
        return {"from": source_rel, "to": source_rel, "name": source_path.name, "type": "folder"}
    if destination.exists():
        raise ValueError("A file or folder with this name already exists")
    source_path.rename(destination)
    destination_rel = destination.relative_to(media_root()).as_posix()
    replace_metadata_path(source_rel, destination_rel, "folder")
    mark_media_index_stale()
    return {"from": source_rel, "to": destination_rel, "name": destination.name, "type": "folder"}


def rename_entry(source: str, new_name: str, entry_type: str = "file") -> dict:
    if entry_type == "folder":
        return rename_folder(source, new_name)
    return rename_media_file(source, new_name)


def set_file_tags(file_path: str, next_tags: list[str]) -> dict:
    clean, absolute = resolve_media_path(file_path)
    if not absolute.is_file() or not is_media_file(absolute):
        raise ValueError("Path is not a supported media file")
    normalized = []
    for tag in next_tags:
        value = str(tag).strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    normalized = normalized[:20]

    def save_tags(folder_tags):
        if normalized:
            folder_tags[clean] = normalized
        else:
            folder_tags.pop(clean, None)

    update_tags(save_tags)
    mark_media_index_stale()
    return {"path": clean, "tags": normalized}


def set_folder_cover(folder_path: str, cover_path: str) -> dict:
    folder_rel, folder = resolve_media_path(folder_path)
    cover_rel, cover = resolve_media_path(cover_path)
    if not folder.is_dir():
        raise ValueError("Folder does not exist")
    if not cover.is_file() or not is_image_file(cover):
        raise ValueError("Cover must be an image file")
    if not path_is_inside_folder(cover_rel, folder_rel):
        raise ValueError("Cover image must be inside the selected folder")

    def save_cover(folder_covers):
        folder_covers[folder_rel] = cover_rel

    update_covers(save_cover)
    mark_media_index_stale()
    return {"folder": folder_rel, "cover": cover_rel}


def thumbnail_file(relative_path: str, size: str) -> tuple[Path, str]:
    clean, absolute = resolve_media_path(relative_path)
    if size not in THUMBNAIL_SIZES:
        raise ValueError("Unknown thumbnail size")
    if not absolute.is_file() or not is_image_file(absolute):
        raise ValueError("Thumbnail source must be an image")
    if Image is None:
        return absolute, guess_content_type(absolute)

    stat = absolute.stat()
    cache_key = hashlib.sha256(f"{size}|{clean}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()
    destination = thumbnail_dir() / f"{cache_key}.jpg"
    if destination.exists():
        return destination, "image/jpeg"

    try:
        with Image.open(absolute) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail(THUMBNAIL_SIZES[size], Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "#ffffff")
                if image.mode in {"RGBA", "LA"}:
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image)
                image = background
            elif image.mode == "L":
                image = image.convert("RGB")
            image.save(destination, "JPEG", quality=84, optimize=True, progressive=True)
    except (OSError, UnidentifiedImageError):
        return absolute, guess_content_type(absolute)

    return destination, "image/jpeg"


def guess_content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
