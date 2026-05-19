import json
import mimetypes
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import fcntl

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


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


def is_media_file(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def media_kind(path: Path) -> str:
    return "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video"


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
    total_files = len(files)
    paged_files = files[offset:offset + limit]
    next_offset = offset + len(paged_files)
    return {
        "path": clean,
        "folders": folders,
        "files": paged_files,
        "fileCount": total_files,
        "offset": offset,
        "nextOffset": next_offset,
        "hasMore": next_offset < total_files,
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


def create_folder(parent: str, name: str) -> dict:
    parent_rel, parent_path = resolve_media_path(parent)
    if not parent_path.is_dir():
        raise ValueError("Parent is not a folder")
    folder_name = sanitize_folder_name(name)
    destination = parent_path / folder_name
    if destination.exists():
        raise ValueError("Folder already exists")
    destination.mkdir()
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
    return {"deleted": source_rel, "type": "file"}


def delete_folder(source: str) -> dict:
    source_rel, source_path = resolve_media_path(source)
    if not source_rel:
        raise ValueError("Root folder cannot be deleted")
    if not source_path.is_dir():
        raise ValueError("Source is not a folder")
    shutil.rmtree(source_path)
    cleanup_deleted_metadata(source_rel, "folder")
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
    return {"folder": folder_rel, "cover": cover_rel}


def guess_content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
