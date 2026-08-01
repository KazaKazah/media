#!/usr/bin/env python3
"""Incrementally synchronize explicitly authorized Hentaidad galleries.

The crawler only follows gallery cards and pagination links discovered on
Hentaidad pages. Every source image URL is recorded in SQLite before/after a
download, so interrupted runs are safe to repeat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


DEFAULT_START_URL = "https://hentaidad.com/"
USER_AGENT = "DropAndTag-HentaidadSync/1.0 (+authorized personal archive)"
IMAGE_EXTENSIONS = {".avif", ".bmp", ".gif", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".webp"}
IGNORED_IMAGE_WORDS = {
    "avatar", "favicon", "icon", "logo", "placeholder", "sprite", "user",
}
RESERVED_PATHS = {
    "", "about", "contact", "cookie-policy", "discussion", "dmca", "genres",
    "images", "login", "privacy", "privacy-policy", "terms", "videos",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized_url(value: str, base: str = "") -> str:
    parsed = urlparse(urljoin(base, value.strip()))
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", "", query, ""))


def safe_name(value: str, fallback: str, limit: int = 120) -> str:
    value = re.sub(r"\s+", " ", unquote(value or "")).strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value)
    value = value.strip(" .-_")
    return (value or fallback)[:limit].rstrip(" .")


def path_slug(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[-1] if parts else "gallery"


@dataclass(frozen=True)
class Link:
    url: str
    text: str
    rel: str
    css_class: str


class ArchivePageParser(HTMLParser):
    IMAGE_ATTRS = ("data-full", "data-original", "data-src", "data-lazy-src", "data-image", "src")

    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title = ""
        self.links: list[Link] = []
        self.images: list[str] = []
        self._anchor: dict | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key.lower(): value or "" for key, value in attrs_list}
        if tag == "base" and attrs.get("href"):
            self.page_url = urljoin(self.page_url, attrs["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and attrs.get("href"):
            self._anchor = {
                "url": normalized_url(attrs["href"], self.page_url),
                "text": [],
                "rel": attrs.get("rel", ""),
                "class": attrs.get("class", ""),
            }
        elif tag in {"img", "source"}:
            self._collect_image(attrs)
            if self._anchor:
                label = attrs.get("alt") or attrs.get("title")
                if label:
                    self._anchor["text"].append(label)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()
        elif tag == "a" and self._anchor:
            self.links.append(Link(
                self._anchor["url"],
                " ".join(self._anchor["text"]).strip(),
                self._anchor["rel"],
                self._anchor["class"],
            ))
            self._anchor = None

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title:
            self._title_parts.append(text)
        if self._anchor:
            self._anchor["text"].append(text)

    def _collect_image(self, attrs: dict[str, str]) -> None:
        candidates: list[str] = []
        for name in self.IMAGE_ATTRS:
            if attrs.get(name):
                candidates.append(attrs[name])
        for name in ("srcset", "data-srcset"):
            if attrs.get(name):
                entries = [item.strip().split()[0] for item in attrs[name].split(",") if item.strip()]
                if entries:
                    candidates.append(entries[-1])
        for candidate in candidates:
            if candidate.startswith(("data:", "blob:")):
                continue
            try:
                self.images.append(normalized_url(candidate, self.page_url))
            except ValueError:
                continue


class Registry:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                start_url TEXT NOT NULL,
                status TEXT NOT NULL,
                albums_seen INTEGER NOT NULL DEFAULT 0,
                images_saved INTEGER NOT NULL DEFAULT 0,
                images_skipped INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS albums (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                folder TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_success_at TEXT
            );
            CREATE TABLE IF NOT EXISTS images (
                url TEXT PRIMARY KEY,
                album_url TEXT NOT NULL,
                local_path TEXT,
                sha256 TEXT,
                size INTEGER,
                status TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                downloaded_at TEXT,
                last_error TEXT,
                FOREIGN KEY(album_url) REFERENCES albums(url)
            );
            """
        )
        self.connection.commit()

    def start_run(self, start_url: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(started_at, start_url, status) VALUES (?, ?, 'running')",
            (utc_now(), start_url),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, stats: dict[str, int]) -> None:
        self.connection.execute(
            """
            UPDATE runs SET finished_at=?, status=?, albums_seen=?, images_saved=?,
                images_skipped=?, errors=? WHERE id=?
            """,
            (
                utc_now(), status, stats["albums"], stats["saved"],
                stats["skipped"], stats["errors"], run_id,
            ),
        )
        self.connection.commit()

    def remember_album(self, url: str, title: str, folder: str) -> None:
        self.connection.execute(
            """
            INSERT INTO albums(url, title, folder, first_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET title=excluded.title, folder=excluded.folder
            """,
            (url, title, folder, utc_now()),
        )
        self.connection.commit()

    def image_done(self, url: str) -> bool:
        row = self.connection.execute(
            "SELECT local_path FROM images WHERE url=? AND status='downloaded'",
            (url,),
        ).fetchone()
        return bool(row and row[0] and Path(row[0]).is_file())

    def image_pending(self, url: str, album_url: str) -> None:
        self.connection.execute(
            """
            INSERT INTO images(url, album_url, status, first_seen_at)
            VALUES (?, ?, 'pending', ?)
            ON CONFLICT(url) DO NOTHING
            """,
            (url, album_url, utc_now()),
        )
        self.connection.commit()

    def image_saved(self, url: str, path: Path, digest: str, size: int) -> None:
        self.connection.execute(
            """
            UPDATE images SET local_path=?, sha256=?, size=?, status='downloaded',
                downloaded_at=?, last_error=NULL WHERE url=?
            """,
            (str(path.resolve()), digest, size, utc_now(), url),
        )
        self.connection.commit()

    def image_failed(self, url: str, error: str) -> None:
        self.connection.execute(
            "UPDATE images SET status='failed', last_error=? WHERE url=?",
            (error[:500], url),
        )
        self.connection.commit()

    def album_checked(self, url: str, success: bool) -> None:
        self.connection.execute(
            """
            UPDATE albums SET last_checked_at=?,
                last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END
            WHERE url=?
            """,
            (utc_now(), int(success), utc_now(), url),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class SyncClient:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        handlers = []
        if args.proxy:
            handlers.append(ProxyHandler({"http": args.proxy, "https": args.proxy}))
        if args.cookies:
            jar = MozillaCookieJar(str(args.cookies))
            if args.cookies.exists():
                jar.load(ignore_discard=True, ignore_expires=True)
            handlers.append(HTTPCookieProcessor(jar))
        self.opener = build_opener(*handlers)
        self.last_request_at = 0.0

    def request(self, url: str, max_bytes: int, accept: str) -> tuple[bytes, str]:
        delay = self.args.delay - (time.monotonic() - self.last_request_at)
        if delay > 0:
            time.sleep(delay)
        request = Request(url, headers={
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.8",
            "Referer": self.args.start_url,
            "User-Agent": self.args.user_agent,
        })
        last_error: Exception | None = None
        for attempt in range(1, self.args.retries + 1):
            try:
                self.last_request_at = time.monotonic()
                with self.opener.open(request, timeout=self.args.timeout) as response:
                    content_type = response.headers.get_content_type()
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise ValueError(f"response exceeds {max_bytes} bytes")
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise ValueError(f"response exceeds {max_bytes} bytes")
                    return data, content_type
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
                last_error = error
                if attempt < self.args.retries:
                    time.sleep(min(2 ** attempt, 15))
        raise RuntimeError(str(last_error or "request failed"))

    def html(self, url: str) -> ArchivePageParser:
        data, content_type = self.request(url, self.args.max_html_bytes, "text/html,application/xhtml+xml")
        if "html" not in content_type:
            raise RuntimeError(f"expected HTML, received {content_type}")
        parser = ArchivePageParser(url)
        parser.feed(data.decode("utf-8", errors="replace"))
        return parser

    def image(self, url: str) -> tuple[bytes, str]:
        data, content_type = self.request(url, self.args.max_image_bytes, "image/avif,image/webp,image/*")
        if not content_type.startswith("image/"):
            raise RuntimeError(f"expected image, received {content_type}")
        return data, content_type


def same_host(url: str, root_url: str) -> bool:
    return urlparse(url).hostname == urlparse(root_url).hostname


def is_next_link(link: Link) -> bool:
    words = f"{link.text} {link.rel} {link.css_class}".lower()
    return bool(re.search(r"\b(next|more|older|след)", words)) or "page=" in link.url


def is_gallery_link(link: Link, root_url: str) -> bool:
    if not same_host(link.url, root_url):
        return False
    marker = f"{link.text} {link.css_class}".lower()
    return "gallery" in marker and not is_next_link(link)


def relevant_image(url: str, root_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered = f"{parsed.netloc}{parsed.path}".lower()
    if any(word in lowered for word in IGNORED_IMAGE_WORDS):
        return False
    suffix = Path(unquote(parsed.path)).suffix.lower()
    return not suffix or suffix in IMAGE_EXTENSIONS


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def image_extension(url: str, content_type: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(content_type) or ".jpg"
    return ".jpg" if guessed == ".jpe" else guessed


def write_marker(output: Path, run_id: int, start_url: str, stats: dict[str, int], status: str) -> None:
    marker = {
        "run_id": run_id,
        "site": urlparse(start_url).netloc,
        "finished_at": utc_now(),
        "status": status,
        **stats,
    }
    (output / "last-sync.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def discover_albums(client: SyncClient, args: argparse.Namespace) -> list[tuple[str, str]]:
    queue = [normalized_url(args.start_url)]
    visited: set[str] = set()
    albums: dict[str, str] = {}
    while queue and len(visited) < args.max_pages:
        page_url = queue.pop(0)
        if page_url in visited:
            continue
        print(f"[LIST] {page_url}")
        parser = client.html(page_url)
        visited.add(page_url)
        for link in parser.links:
            if is_gallery_link(link, args.start_url):
                albums.setdefault(link.url, link.text or path_slug(link.url))
                if 0 < args.max_albums <= len(albums):
                    return list(albums.items())
            elif is_next_link(link) and same_host(link.url, args.start_url) and link.url not in visited:
                queue.append(link.url)
    return list(albums.items())


def album_images(client: SyncClient, album_url: str, args: argparse.Namespace) -> tuple[str, list[str]]:
    queue = [album_url]
    visited: set[str] = set()
    images: list[str] = []
    title = path_slug(album_url)
    while queue and len(visited) < args.max_album_pages:
        page_url = queue.pop(0)
        if page_url in visited:
            continue
        parser = client.html(page_url)
        visited.add(page_url)
        title = parser.title or title
        images.extend(url for url in parser.images if relevant_image(url, args.start_url))
        for link in parser.links:
            if is_next_link(link) and same_host(link.url, album_url) and link.url not in visited:
                queue.append(link.url)
    return title, unique(images)


def synchronize(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    registry = Registry((args.state_file or (output / ".hentaidad-sync.sqlite3")).resolve())
    client = SyncClient(args)
    stats = {"albums": 0, "saved": 0, "skipped": 0, "errors": 0}
    run_id = registry.start_run(args.start_url)
    status = "failed"
    try:
        albums = discover_albums(client, args)
        print(f"[INFO] discovered albums: {len(albums)}")
        for album_index, (album_url, card_title) in enumerate(albums, start=1):
            stats["albums"] += 1
            folder_name = safe_name(card_title, f"{album_index:05d}-{path_slug(album_url)}")
            album_folder = output / folder_name
            registry.remember_album(album_url, card_title, str(album_folder.resolve()))
            print(f"[ALBUM {album_index}/{len(albums)}] {card_title} -> {folder_name}")
            try:
                page_title, image_urls = album_images(client, album_url, args)
                if page_title and page_title != card_title:
                    refined = safe_name(page_title, folder_name)
                    candidate = output / refined
                    if not album_folder.exists() and candidate != album_folder:
                        album_folder = candidate
                        folder_name = refined
                        registry.remember_album(album_url, page_title, str(album_folder.resolve()))
                if args.max_images_per_album > 0:
                    image_urls = image_urls[:args.max_images_per_album]
                if not args.dry_run:
                    album_folder.mkdir(parents=True, exist_ok=True)
                for image_index, image_url in enumerate(image_urls, start=1):
                    registry.image_pending(image_url, album_url)
                    if registry.image_done(image_url):
                        stats["skipped"] += 1
                        continue
                    if args.dry_run:
                        print(f"  [WOULD DOWNLOAD] {image_url}")
                        continue
                    try:
                        data, content_type = client.image(image_url)
                        digest = hashlib.sha256(data).hexdigest()
                        extension = image_extension(image_url, content_type)
                        source_name = safe_name(Path(unquote(urlparse(image_url).path)).stem, f"image-{image_index:05d}")
                        destination = album_folder / f"{image_index:05d}-{source_name}{extension}"
                        if destination.exists():
                            destination = album_folder / f"{image_index:05d}-{source_name}-{digest[:10]}{extension}"
                        destination.write_bytes(data)
                        registry.image_saved(image_url, destination, digest, len(data))
                        stats["saved"] += 1
                        print(f"  [SAVED] {destination.name}")
                    except Exception as error:  # keep the remaining synchronization alive
                        registry.image_failed(image_url, str(error))
                        stats["errors"] += 1
                        print(f"  [ERROR] {image_url}: {error}", file=sys.stderr)
                if not args.dry_run:
                    (album_folder / ".album-sync.json").write_text(
                        json.dumps({
                            "album_url": album_url,
                            "title": page_title,
                            "last_checked_at": utc_now(),
                            "images_discovered": len(image_urls),
                        }, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                registry.album_checked(album_url, True)
            except Exception as error:
                registry.album_checked(album_url, False)
                stats["errors"] += 1
                print(f"[ALBUM ERROR] {album_url}: {error}", file=sys.stderr)
        status = "dry-run" if args.dry_run else ("completed-with-errors" if stats["errors"] else "completed")
        return 0 if not stats["errors"] else 2
    except KeyboardInterrupt:
        status = "interrupted"
        print("\n[INFO] interrupted; the next run will continue safely", file=sys.stderr)
        return 130
    except Exception as error:
        stats["errors"] += 1
        print(f"[FATAL] {error}", file=sys.stderr)
        return 1
    finally:
        registry.finish_run(run_id, status, stats)
        write_marker(output, run_id, args.start_url, stats, status)
        registry.close()
        print(f"[DONE] status={status} albums={stats['albums']} saved={stats['saved']} skipped={stats['skipped']} errors={stats['errors']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incrementally download authorized Hentaidad galleries into separate folders.",
    )
    parser.add_argument("--start-url", default=DEFAULT_START_URL, help="Gallery listing URL")
    parser.add_argument("--output", type=Path, required=True, help="Destination directory")
    parser.add_argument("--state-file", type=Path, help="SQLite registry path; keep it on a local disk when output is SMB/CIFS")
    parser.add_argument("--cookies", type=Path, help="Optional Netscape cookies.txt exported from your browser")
    parser.add_argument("--proxy", help="Optional HTTP(S) proxy URL if the site blocks the VDS address")
    parser.add_argument("--delay", type=float, default=1.5, help="Minimum seconds between requests")
    parser.add_argument("--timeout", type=float, default=30, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retries per request")
    parser.add_argument("--max-pages", type=int, default=10_000, help="Maximum listing pages")
    parser.add_argument("--max-album-pages", type=int, default=500, help="Maximum pages inside one album")
    parser.add_argument("--max-albums", type=int, default=0, help="Stop after N albums; 0 means unlimited")
    parser.add_argument("--max-images-per-album", type=int, default=0, help="Limit images per album; 0 means unlimited")
    parser.add_argument("--max-html-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--max-image-bytes", type=int, default=80 * 1024 * 1024)
    parser.add_argument("--user-agent", default=USER_AGENT)
    parser.add_argument("--dry-run", action="store_true", help="Discover without downloading images")
    parser.add_argument(
        "--confirm-adult-and-rights",
        action="store_true",
        help="Confirm that you are an adult and are authorized to archive the selected content",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.confirm_adult_and_rights:
        parser.error("add --confirm-adult-and-rights to confirm age and authorization")
    if normalized_url(args.start_url).split("://", 1)[-1].split("/", 1)[0] != "hentaidad.com":
        parser.error("--start-url must use hentaidad.com")
    if args.delay < 0 or args.retries < 1:
        parser.error("--delay must be >= 0 and --retries must be >= 1")
    return synchronize(args)


if __name__ == "__main__":
    raise SystemExit(main())
