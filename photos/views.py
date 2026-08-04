import json
import base64
import gzip
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.db.models import Case, Count, IntegerField, Q, When
from django.db.models.functions import Lower
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    CharacterCreateForm,
    CharacterFolderImportForm,
    CharacterForm,
    TextDocumentUploadForm,
    TitleForm,
    UserProfileForm,
)
from . import library
from .note_crypto import NoteDecryptionError, decrypt_note, encrypt_note
from .models import Character, TextDocument, Title, TodoItem, TodoProject, UserProfile


def json_error(error: Exception, status: int = 400):
    return JsonResponse({"error": str(error) or "Request failed"}, status=status)


def user_can_manage(user) -> bool:
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


@login_required
def profile(request):
    try:
        instance = request.user.profile
    except UserProfile.DoesNotExist:
        instance = None
    form = UserProfileForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        user_profile = form.save(commit=False)
        user_profile.user = request.user
        avatar = form.cleaned_data.get("avatar_upload")
        if avatar:
            try:
                user_profile.avatar_path = save_cover_upload(
                    avatar,
                    f"Profiles/{request.user.pk}",
                )
            except ValueError as error:
                form.add_error("avatar_upload", str(error))
        if not form.errors:
            user_profile.save()
            return redirect(f"{reverse('photos:profile')}?saved=1")
    return render(request, "photos/profile.html", {
        "form": form,
        "profile": instance,
    })


def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not user_can_manage(request.user):
            raise PermissionDenied("Доступ разрешён только администратору")
        return view_func(request, *args, **kwargs)

    return wrapper


def parse_due_at(value: str):
    if not value:
        return None
    parsed = parse_datetime(value)
    if not parsed:
        parsed = parse_datetime(f"{value}:00")
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def todo_counts(items):
    today = timezone.localdate()
    now = timezone.now()
    return {
        "inbox": items.filter(is_done=False).exclude(kind=TodoItem.Kind.NOTE).count(),
        "today": items.filter(is_done=False, due_at__date=today).exclude(kind=TodoItem.Kind.NOTE).count(),
        "overdue": items.filter(is_done=False, due_at__lt=now).exclude(kind=TodoItem.Kind.NOTE).count(),
        "upcoming": items.filter(is_done=False, due_at__date__gt=today).exclude(kind=TodoItem.Kind.NOTE).count(),
        "reminders": items.filter(is_done=False, kind=TodoItem.Kind.REMINDER).count(),
        "notes": items.filter(is_done=False, kind=TodoItem.Kind.NOTE).count(),
        "records": items.filter(is_done=False, kind=TodoItem.Kind.RECORD).count(),
        "done": items.filter(is_done=True).count(),
    }


def todo_redirect(request):
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("photos:todo")


def todo_item_values(request, projects):
    project_id = request.POST.get("project") or None
    kind = request.POST.get("kind", TodoItem.Kind.TASK)
    priority = request.POST.get("priority", TodoItem.Priority.MEDIUM)
    return {
        "project": projects.filter(pk=project_id).first() if project_id else None,
        "kind": kind if kind in TodoItem.Kind.values else TodoItem.Kind.TASK,
        "priority": priority if priority in TodoItem.Priority.values else TodoItem.Priority.MEDIUM,
        "title": request.POST.get("title", "").strip(),
        "body": request.POST.get("body", "").strip(),
        "tags": request.POST.get("tags", "").strip(),
        "due_at": parse_due_at(request.POST.get("due_at", "")),
        "is_pinned": bool(request.POST.get("is_pinned")),
    }


@ensure_csrf_cookie
@login_required
def todo_home(request):
    projects = TodoProject.objects.filter(owner=request.user).annotate(
        active_count=Count("items", filter=Q(items__is_done=False) & ~Q(items__kind=TodoItem.Kind.NOTE)),
        note_count=Count("items", filter=Q(items__is_done=False, items__kind=TodoItem.Kind.NOTE)),
    )
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_project":
            name = request.POST.get("name", "").strip()
            if name:
                TodoProject.objects.get_or_create(owner=request.user, name=name)
            return todo_redirect(request)
        if action == "create_item":
            values = todo_item_values(request, projects)
            if values["title"]:
                TodoItem.objects.create(owner=request.user, **values)
            return todo_redirect(request)
        if action == "update_item":
            item = get_object_or_404(TodoItem, pk=request.POST.get("item"), owner=request.user)
            values = todo_item_values(request, projects)
            if values["title"]:
                for field, value in values.items():
                    setattr(item, field, value)
                item.save()
            return todo_redirect(request)
        if action == "toggle_item":
            item = get_object_or_404(TodoItem, pk=request.POST.get("item"), owner=request.user)
            item.is_done = not item.is_done
            item.completed_at = timezone.now() if item.is_done else None
            item.save(update_fields=["is_done", "completed_at", "updated_at"])
            return todo_redirect(request)
        if action == "toggle_pin":
            item = get_object_or_404(TodoItem, pk=request.POST.get("item"), owner=request.user)
            item.is_pinned = not item.is_pinned
            item.save(update_fields=["is_pinned", "updated_at"])
            return todo_redirect(request)
        if action == "delete_item":
            get_object_or_404(TodoItem, pk=request.POST.get("item"), owner=request.user).delete()
            return todo_redirect(request)
        if action == "clear_completed":
            TodoItem.objects.filter(owner=request.user, is_done=True).delete()
            return todo_redirect(request)

    items = TodoItem.objects.filter(owner=request.user).select_related("project")
    all_items = items
    view = request.GET.get("view", "inbox")
    query = request.GET.get("q", "").strip()
    project_id = request.GET.get("project", "")
    uncategorized_notes = view == "notes" and request.GET.get("category") == "unassigned"
    priority = request.GET.get("priority", "")
    sort = request.GET.get("sort", "due")
    today = timezone.localdate()
    now = timezone.now()

    if view == "today":
        items = items.filter(is_done=False).exclude(kind=TodoItem.Kind.NOTE).filter(Q(due_at__date=today) | Q(due_at__isnull=True))
    elif view == "overdue":
        items = items.filter(is_done=False, due_at__lt=now).exclude(kind=TodoItem.Kind.NOTE)
    elif view == "upcoming":
        items = items.filter(is_done=False, due_at__date__gt=today).exclude(kind=TodoItem.Kind.NOTE)
    elif view == "reminders":
        items = items.filter(is_done=False, kind=TodoItem.Kind.REMINDER)
    elif view == "notes":
        items = items.filter(is_done=False, kind=TodoItem.Kind.NOTE)
    elif view == "records":
        items = items.filter(is_done=False, kind=TodoItem.Kind.RECORD)
    elif view == "done":
        items = items.filter(is_done=True)
    else:
        items = items.filter(is_done=False).exclude(kind=TodoItem.Kind.NOTE)

    if view == "notes" and uncategorized_notes:
        items = items.filter(project__isnull=True)
    elif project_id:
        items = items.filter(project_id=project_id)
    if priority in TodoItem.Priority.values:
        items = items.filter(priority=priority)
    else:
        priority = ""
    if query:
        items = items.filter(Q(title__icontains=query) | Q(body__icontains=query) | Q(tags__icontains=query))

    items = items.annotate(
        deadline_rank=Case(When(due_at__isnull=True, then=1), default=0, output_field=IntegerField()),
        priority_rank=Case(
            When(priority=TodoItem.Priority.URGENT, then=0),
            When(priority=TodoItem.Priority.HIGH, then=1),
            When(priority=TodoItem.Priority.MEDIUM, then=2),
            default=3,
            output_field=IntegerField(),
        ),
    )
    if sort == "priority":
        items = items.order_by("-is_pinned", "priority_rank", "deadline_rank", "due_at", "-created_at")
    elif sort == "created":
        items = items.order_by("-is_pinned", "-created_at")
    else:
        sort = "due"
        items = items.order_by("-is_pinned", "deadline_rank", "due_at", "priority_rank", "-created_at")

    note_categories = []
    selected_note = None
    note_items = []
    if view == "notes":
        if project_id or uncategorized_notes:
            note_items = list(items[:200])
            selected_note_id = request.GET.get("note", "")
            selected_note = next(
                (item for item in note_items if str(item.pk) == selected_note_id),
                None,
            )
        else:
            grouped_notes = {}
            unassigned_count = 0
            for item in items:
                if item.project_id:
                    grouped_notes[item.project_id] = grouped_notes.get(item.project_id, 0) + 1
                else:
                    unassigned_count += 1
            note_categories = [
                {"project": project, "count": grouped_notes.get(project.pk, 0)}
                for project in projects
            ]
            note_categories.append({"project": None, "count": unassigned_count})

    counts = todo_counts(all_items)
    total = counts["inbox"] + counts["done"]
    return render(request, "photos/todo.html", {
        "can_manage": user_can_manage(request.user),
        "counts": counts,
        "completion_percent": round(counts["done"] * 100 / total) if total else 0,
        "items": items[:200],
        "kind_choices": TodoItem.Kind.choices,
        "priority": priority,
        "priority_choices": TodoItem.Priority.choices,
        "projects": projects,
        "query": query,
        "note_categories": note_categories,
        "note_items": note_items,
        "selected_note": selected_note,
        "uncategorized_notes": uncategorized_notes,
        "selected_project": project_id,
        "selected_project_object": projects.filter(pk=project_id).first() if project_id else None,
        "sort": sort,
        "now": now,
        "today": today,
        "view": view,
    })


def note_library_url(project_id="", note_id=""):
    parameters = []
    if project_id:
        parameters.append(f"project={project_id}")
    if note_id:
        parameters.append(f"note={note_id}")
    suffix = f"?{'&'.join(parameters)}" if parameters else ""
    return f"{reverse('photos:todo')}{suffix}"


@ensure_csrf_cookie
@login_required
def notes_home(request):
    legacy_actions = {
        "create_item", "update_item", "toggle_item", "toggle_pin",
        "delete_item", "clear_completed",
    }
    if request.POST.get("action") in legacy_actions or request.GET.get("view"):
        return todo_home(request)
    projects = TodoProject.objects.filter(owner=request.user).annotate(
        note_count=Count("items", filter=Q(items__kind=TodoItem.Kind.NOTE)),
    )
    project_id = request.GET.get("project", "")
    selected_project = projects.filter(pk=project_id).first() if project_id else None
    query = request.GET.get("q", "").strip()
    notes = TodoItem.objects.filter(owner=request.user, kind=TodoItem.Kind.NOTE).select_related("project")
    if selected_project:
        notes = notes.filter(project=selected_project)
    elif request.GET.get("uncategorized"):
        notes = notes.filter(project__isnull=True)
    if query:
        notes = notes.filter(Q(title__icontains=query) | Q(tags__icontains=query) | Q(body__icontains=query))
    notes = notes.order_by("-is_pinned", "-updated_at")

    selected_note_id = request.GET.get("note", "")
    selected_note = notes.filter(pk=selected_note_id).first() if selected_note_id else notes.first()
    unlocked_body = None
    note_error = ""

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "create_project":
            name = request.POST.get("name", "").strip()
            if name:
                project, _ = TodoProject.objects.get_or_create(owner=request.user, name=name)
                return redirect(note_library_url(project.pk))
            return redirect("photos:todo")

        if action == "create_note":
            title = request.POST.get("title", "").strip()
            body = request.POST.get("body", "")
            password = request.POST.get("password", "")
            confirm = request.POST.get("password_confirm", "")
            requested_project = request.POST.get("project", "")
            project = projects.filter(pk=requested_project).first() if requested_project else None
            if not title:
                note_error = "Укажите название заметки."
            elif password and password != confirm:
                note_error = "Пароли не совпадают."
            else:
                note = TodoItem(owner=request.user, project=project, kind=TodoItem.Kind.NOTE, title=title)
                if password:
                    note.is_encrypted = True
                    note.encrypted_body = encrypt_note(body, password)
                    note.body = ""
                else:
                    note.body = body
                note.save()
                return redirect(note_library_url(project.pk if project else "", note.pk))

        if action in {"unlock_note", "update_note", "delete_note", "toggle_note_pin"}:
            note = get_object_or_404(TodoItem, pk=request.POST.get("item"), owner=request.user, kind=TodoItem.Kind.NOTE)
            selected_note = note
            selected_note_id = str(note.pk)
            if action == "delete_note":
                project = note.project_id
                note.delete()
                return redirect(note_library_url(project))
            if action == "toggle_note_pin":
                note.is_pinned = not note.is_pinned
                note.save(update_fields=["is_pinned", "updated_at"])
                return redirect(note_library_url(note.project_id, note.pk))
            password = request.POST.get("password", "")
            try:
                current_body = decrypt_note(note.encrypted_body, password) if note.is_encrypted else note.body
            except NoteDecryptionError as error:
                note_error = str(error)
            else:
                if action == "unlock_note":
                    unlocked_body = current_body
                else:
                    title = request.POST.get("title", "").strip()
                    body = request.POST.get("body", "")
                    requested_project = request.POST.get("project", "")
                    project = projects.filter(pk=requested_project).first() if requested_project else None
                    keep_encrypted = bool(request.POST.get("is_encrypted"))
                    new_password = request.POST.get("new_password", "")
                    if not title:
                        note_error = "Укажите название заметки."
                        unlocked_body = body
                    elif new_password and new_password != request.POST.get("new_password_confirm", ""):
                        note_error = "Новые пароли не совпадают."
                        unlocked_body = body
                    else:
                        encryption_password = new_password or password
                        note.title = title
                        note.project = project
                        note.tags = request.POST.get("tags", "").strip()
                        note.is_pinned = bool(request.POST.get("is_pinned"))
                        if keep_encrypted:
                            if not encryption_password:
                                note_error = "Укажите пароль для зашифрованной заметки."
                                unlocked_body = body
                            else:
                                note.is_encrypted = True
                                note.encrypted_body = encrypt_note(body, encryption_password)
                                note.body = ""
                        else:
                            note.is_encrypted = False
                            note.encrypted_body = ""
                            note.body = body
                        if not note_error:
                            note.save()
                            return redirect(note_library_url(note.project_id, note.pk))

    # Refresh the visible collection after non-redirecting POST actions.
    notes = list(notes[:300])
    if selected_note and selected_note.owner_id == request.user.pk:
        selected_note = next((note for note in notes if note.pk == selected_note.pk), selected_note)
    return render(request, "photos/notes.html", {
        "can_manage": user_can_manage(request.user),
        "note_error": note_error,
        "notes": notes,
        "projects": projects,
        "query": query,
        "selected_note": selected_note,
        "selected_project": selected_project,
        "unlocked_body": unlocked_body,
    })


@login_required
def document_library(request):
    documents = TextDocument.objects.filter(owner=request.user)
    query = request.GET.get("q", "").strip()
    if query:
        documents = documents.filter(
            Q(title__icontains=query)
            | Q(original_filename__icontains=query)
            | Q(content__icontains=query)
        )

    form = TextDocumentUploadForm()
    if request.method == "POST":
        form = TextDocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            return redirect(form.save(request.user))

    return render(request, "photos/documents.html", {
        "can_manage": user_can_manage(request.user),
        "documents": documents,
        "form": form,
        "query": query,
    })


@login_required
def document_detail(request, pk):
    document = get_object_or_404(TextDocument, pk=pk, owner=request.user)
    return render(request, "photos/document_detail.html", {
        "document": document,
    })


@require_POST
@login_required
def document_delete(request, pk):
    document = get_object_or_404(TextDocument, pk=pk, owner=request.user)
    document.delete()
    return redirect("photos:documents")


@ensure_csrf_cookie
def index(request):
    titles = Title.objects.all()
    kind = request.GET.get("kind", "")
    query = request.GET.get("q", "").strip()
    selected_formats = [value for value in request.GET.getlist("format") if value in Title.Format.values]
    selected_statuses = [value for value in request.GET.getlist("status") if value in Title.ReleaseStatus.values]
    selected_ratings = [value for value in request.GET.getlist("rating") if value in Title.AgeRating.values]
    selected_audiences = [value for value in request.GET.getlist("audience") if value in Title.Audience.values]
    selected_seasons = [value for value in request.GET.getlist("season") if value in Title.Season.values]
    selected_genres = [value for value in request.GET.getlist("genre") if value in dict(Title.GENRE_CHOICES)]
    selected_themes = [value for value in request.GET.getlist("theme") if value in dict(Title.THEME_CHOICES)]
    selected_years = []
    for value in request.GET.getlist("year"):
        try:
            selected_years.append(int(value))
        except ValueError:
            continue
    sort = request.GET.get("sort", "name")
    sort_fields = {
        "updated": "-updated_at",
        "name": "name",
        "year": "-year",
        "score": "-score",
        "characters": "-character_count",
    }
    if kind in Title.Kind.values:
        titles = titles.filter(kind=kind)
    else:
        # Adult-category titles stay out of the general catalog until the user
        # explicitly selects that category in the top-level type switcher.
        titles = titles.exclude(kind=Title.Kind.HENTAI)
    if query:
        titles = titles.filter(
            Q(name__icontains=query)
            | Q(original_name__icontains=query)
            | Q(description__icontains=query)
            | Q(genres__icontains=query)
            | Q(themes__icontains=query)
            | Q(gallery_folder__icontains=query)
            | Q(characters__name__icontains=query)
            | Q(characters__role__icontains=query)
        ).distinct()
    if selected_formats:
        titles = titles.filter(format__in=selected_formats)
    if selected_statuses:
        titles = titles.filter(release_status__in=selected_statuses)
    if selected_ratings:
        titles = titles.filter(age_rating__in=selected_ratings)
    if selected_audiences:
        titles = titles.filter(audience__in=selected_audiences)
    if selected_seasons:
        titles = titles.filter(season__in=selected_seasons)
    if selected_years:
        titles = titles.filter(year__in=selected_years)
    for genre in selected_genres:
        titles = titles.filter(genres__icontains=genre)
    for theme in selected_themes:
        titles = titles.filter(themes__icontains=theme)
    titles = titles.annotate(character_count=Count("characters", distinct=True))
    if sort == "name" or sort not in sort_fields:
        titles = titles.order_by(Lower("name"), "name")
    else:
        titles = titles.order_by(sort_fields[sort], Lower("name"), "name")
    form = TitleForm()
    if request.method == "POST":
        if not user_can_manage(request.user):
            raise PermissionDenied("Создавать тайтлы может только администратор")
        form = TitleForm(request.POST)
        if form.is_valid():
            title = form.save()
            return redirect(title)
    return render(request, "photos/catalog.html", {
        "can_manage": user_can_manage(request.user),
        "form": form,
        "kind": kind,
        "query": query,
        "sort": sort if sort in sort_fields else "name",
        "title_kinds": Title.Kind.choices,
        "format_choices": Title.Format.choices,
        "status_choices": Title.ReleaseStatus.choices,
        "rating_choices": Title.AgeRating.choices,
        "audience_choices": Title.Audience.choices,
        "season_choices": Title.Season.choices,
        "genre_choices": Title.GENRE_CHOICES,
        "theme_choices": Title.THEME_CHOICES,
        "year_choices": Title.objects.exclude(year=None).values_list("year", flat=True).distinct().order_by("-year"),
        "selected_formats": selected_formats,
        "selected_statuses": selected_statuses,
        "selected_ratings": selected_ratings,
        "selected_audiences": selected_audiences,
        "selected_seasons": selected_seasons,
        "selected_years": selected_years,
        "selected_genres": selected_genres,
        "selected_themes": selected_themes,
        "titles": titles.prefetch_related("characters"),
    })


@ensure_csrf_cookie
@admin_required
def media_library(request):
    return render(request, "photos/index.html")


@ensure_csrf_cookie
def title_detail(request, slug):
    title = get_object_or_404(Title, slug=slug)
    if request.method == "POST":
        if not user_can_manage(request.user):
            raise PermissionDenied("Изменять тайтлы может только администратор")
        if request.POST.get("action") == "upload_title_cover":
            title.poster_path = save_cover_upload(
                request.FILES.get("cover"),
                f"Covers/Titles/{title.slug}",
            )
            title.save(update_fields=["poster_path", "updated_at"])
            return redirect(title)
    characters = title.characters.annotate(
        importance_rank=Case(
            When(importance=Character.Importance.MAIN, then=0),
            When(importance=Character.Importance.SUPPORTING, then=1),
            default=2,
            output_field=IntegerField(),
        )
    ).order_by("importance_rank", "name")
    guide_character = characters.exclude(portrait_path="").first() or characters.first()
    return render(request, "photos/title_detail.html", {
        "can_manage": user_can_manage(request.user),
        "title": title,
        "character_preview": characters,
        "guide_character": guide_character,
    })


@login_required
def hentaidad_tool(request):
    return render(request, "photos/hentaidad_tool.html")


def build_single_file_downloader() -> bytes:
    project_root = Path(__file__).resolve().parent.parent
    script_dir = project_root / "scripts"
    sync_payload = base64.b64encode(gzip.compress(
        (script_dir / "hentaidad_sync.py").read_bytes(),
        compresslevel=9,
    )).decode("ascii")
    gui_source = (script_dir / "hentaidad_downloader_gui.py").read_text(encoding="utf-8")
    gui_source = gui_source.replace("#!/usr/bin/env python3\n", "", 1)
    gui_source = gui_source.replace("from __future__ import annotations\n", "", 1)
    gui_source = gui_source.replace(
        'script = Path(__file__).with_name("hentaidad_sync.py")',
        "script = embedded_sync_path()",
        1,
    )
    preamble = f'''#!/usr/bin/env python3
"""Hentaidad Downloader: single-file desktop application."""
import base64 as _base64
import gzip as _gzip
import hashlib as _hashlib
import tempfile as _tempfile
from pathlib import Path as _EmbeddedPath

_SYNC_PAYLOAD = "{sync_payload}"

def embedded_sync_path():
    payload = _gzip.decompress(_base64.b64decode(_SYNC_PAYLOAD))
    folder = _EmbeddedPath(_tempfile.gettempdir()) / "DropAndTag-HentaidadDownloader"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ("hentaidad_sync-" + _hashlib.sha256(payload).hexdigest()[:12] + ".py")
    if not target.exists() or target.read_bytes() != payload:
        target.write_bytes(payload)
    return target

'''
    return (preamble + gui_source).encode("utf-8")


@login_required
def hentaidad_tool_download_single(request):
    payload = BytesIO(build_single_file_downloader())
    response = FileResponse(payload, content_type="text/x-python")
    response["Content-Disposition"] = 'attachment; filename="HentaidadDownloader.pyw"'
    return response


@login_required
def hentaidad_tool_download(request):
    project_root = Path(__file__).resolve().parent.parent
    script_dir = project_root / "scripts"
    payload = BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.write(script_dir / "hentaidad_sync.py", "HentaidadDownloader/hentaidad_sync.py")
        archive.write(script_dir / "hentaidad_downloader_gui.py", "HentaidadDownloader/hentaidad_downloader_gui.py")
        archive.write(script_dir / "README_HENTAIDAD_SYNC.md", "HentaidadDownloader/README.md")
        archive.writestr(
            "HentaidadDownloader/start-windows.bat",
            "@echo off\r\ncd /d %~dp0\r\npython hentaidad_downloader_gui.py\r\npause\r\n",
        )
        archive.writestr(
            "HentaidadDownloader/start-linux.sh",
            "#!/usr/bin/env sh\ncd \"$(dirname \"$0\")\"\npython3 hentaidad_downloader_gui.py\n",
        )
    payload.seek(0)
    response = FileResponse(payload, content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="HentaidadDownloader.zip"'
    return response


@ensure_csrf_cookie
def title_characters(request, slug):
    title = get_object_or_404(Title, slug=slug)
    form = CharacterCreateForm()
    import_form = CharacterFolderImportForm()
    bulk_error = ""
    if request.method == "POST":
        if not user_can_manage(request.user):
            raise PermissionDenied("Добавлять персонажей может только администратор")
        action = request.POST.get("action", "")
        if action == "bulk_update_characters":
            selected_ids = list(dict.fromkeys(request.POST.getlist("characters")))
            if not selected_ids or any(not value.isdigit() for value in selected_ids):
                bulk_error = "Выберите хотя бы одного персонажа."
            elif len(selected_ids) > 500:
                bulk_error = "За один раз можно изменить не более 500 персонажей."
            else:
                updates = {}
                gender = request.POST.get("bulk_gender", "")
                importance = request.POST.get("bulk_importance", "")
                if gender in Character.Gender.values:
                    updates["gender"] = gender
                if importance in Character.Importance.values:
                    updates["importance"] = importance
                if request.POST.get("apply_role"):
                    updates["role"] = request.POST.get("bulk_role", "").strip()[:120]
                if request.POST.get("apply_race"):
                    updates["race"] = request.POST.get("bulk_race", "").strip()[:160]
                if request.POST.get("apply_faction"):
                    updates["faction"] = request.POST.get("bulk_faction", "").strip()[:160]
                if not updates:
                    bulk_error = "Выберите хотя бы одно поле для изменения."
                else:
                    characters_to_update = title.characters.filter(pk__in=selected_ids)
                    updated = characters_to_update.update(**updates, updated_at=timezone.now())
                    target = reverse("photos:title_characters", kwargs={"slug": title.slug})
                    return redirect(f"{target}?bulk_updated={updated}")
        elif action == "import_character_folders":
            import_form = CharacterFolderImportForm(request.POST)
            if import_form.is_valid():
                try:
                    if request.FILES.getlist("folder_files"):
                        imported, skipped = import_uploaded_character_folders(
                            title,
                            import_form.cleaned_data,
                            request.FILES.getlist("folder_files"),
                            request.POST.getlist("relative_paths"),
                        )
                    elif import_form.cleaned_data.get("source_folder"):
                        imported, skipped = import_character_folders(title, import_form.cleaned_data)
                    else:
                        raise FileNotFoundError("Перетащите папку или выберите её кнопкой ниже.")
                except (FileNotFoundError, NotADirectoryError, SuspiciousFileOperation, OSError) as error:
                    import_form.add_error("source_folder", str(error))
                else:
                    target = reverse("photos:title_characters", kwargs={"slug": title.slug})
                    return redirect(f"{target}?imported={imported}&skipped={skipped}")
        else:
            form = CharacterCreateForm(request.POST, request.FILES)
        if form.is_valid():
            character = form.save(commit=False)
            character.title = title
            character.save()
            if form.cleaned_data.get("portrait_upload"):
                character.portrait_path = save_cover_upload(
                    form.cleaned_data["portrait_upload"],
                    f"Covers/Characters/{title.slug}/{character.slug}",
                )
            if form.cleaned_data.get("create_gallery"):
                character.gallery_folder = ensure_media_folder(
                    character.gallery_folder or default_character_gallery(character)
                )
            if character.portrait_path or character.gallery_folder:
                character.save(update_fields=["portrait_path", "gallery_folder", "updated_at"])
            return redirect(character)

    characters = title.characters.annotate(
        importance_rank=Case(
            When(importance=Character.Importance.MAIN, then=0),
            When(importance=Character.Importance.SUPPORTING, then=1),
            default=2,
            output_field=IntegerField(),
        )
    ).order_by("importance_rank", "name")
    factions = sorted(
        {value.strip() for value in characters.values_list("faction", flat=True) if value.strip()},
        key=str.casefold,
    ) if title.kind == Title.Kind.GAME else []
    return render(request, "photos/title_characters.html", {
        "can_manage": user_can_manage(request.user),
        "bulk_error": bulk_error,
        "title": title,
        "form": form,
        "import_form": import_form,
        "characters": characters,
        "main_characters": characters.filter(importance=Character.Importance.MAIN),
        "supporting_characters": characters.filter(importance=Character.Importance.SUPPORTING),
        "episodic_characters": characters.filter(importance=Character.Importance.EPISODIC),
        "female_characters": characters.filter(gender=Character.Gender.FEMALE),
        "male_characters": characters.filter(gender=Character.Gender.MALE),
        "other_gender_characters": characters.filter(gender=Character.Gender.OTHER),
        "gender_choices": Character.Gender.choices,
        "importance_choices": Character.Importance.choices,
        "factions": factions,
    })


def normalize_media_folder_reference(value: str) -> str:
    """Accept a library path, absolute path inside MEDIA_ROOT, or a library URL."""
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme or parsed.query:
        query_path = parse_qs(parsed.query).get("path", [None])[0]
        if query_path is None:
            raise SuspiciousFileOperation("В ссылке медиатеки не найден параметр path.")
        value = unquote(query_path)

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(library.media_root().resolve()).as_posix()
        except ValueError as error:
            raise SuspiciousFileOperation("Можно выбирать папки только внутри медиатеки.") from error
    return value


def first_image_relative(folder: Path) -> str:
    for root, directory_names, file_names in os.walk(folder):
        directory_names[:] = sorted(
            (name for name in directory_names if not name.startswith(".")),
            key=str.casefold,
        )
        for filename in sorted(file_names, key=str.casefold):
            candidate = Path(root) / filename
            if not filename.startswith(".") and library.is_image_file(candidate):
                return candidate.resolve().relative_to(library.media_root().resolve()).as_posix()
    return ""


def import_character_folders(title: Title, cleaned_data: dict) -> tuple[int, int]:
    relative = normalize_media_folder_reference(cleaned_data["source_folder"])
    _, parent = library.resolve_media_path(relative)
    if not parent.exists():
        raise FileNotFoundError("Папка не найдена в медиатеке.")
    if not parent.is_dir():
        raise NotADirectoryError("Указанный путь не является папкой.")

    folders = sorted(
        (
            item for item in parent.iterdir()
            if item.is_dir() and not item.is_symlink() and not item.name.startswith(".")
        ),
        key=lambda item: item.name.casefold(),
    )
    if not folders:
        raise FileNotFoundError("В выбранной папке нет подпапок с персонажами.")

    imported = skipped = 0
    media_root = library.media_root().resolve()
    for folder in folders:
        name = folder.name.strip()
        if not name or len(name) > Character._meta.get_field("name").max_length:
            skipped += 1
            continue
        if title.characters.filter(name__iexact=name).exists():
            skipped += 1
            continue
        Character.objects.create(
            title=title,
            name=name,
            gender=cleaned_data["gender"],
            importance=cleaned_data["importance"],
            faction=cleaned_data.get("faction", ""),
            gallery_folder=folder.resolve().relative_to(media_root).as_posix(),
            portrait_path=(first_image_relative(folder) if cleaned_data.get("use_first_photo") else ""),
        )
        imported += 1
    return imported, skipped


def import_uploaded_character_folders(
    title: Title,
    cleaned_data: dict,
    uploaded_files: list,
    relative_paths: list[str],
) -> tuple[int, int]:
    if len(uploaded_files) != len(relative_paths):
        raise OSError("Браузер не передал структуру папок. Выберите общую папку ещё раз.")

    entries = []
    for uploaded, raw_path in zip(uploaded_files, relative_paths):
        clean_path = library.normalize_relative(raw_path)
        parts = Path(clean_path).parts
        if len(parts) < 2 or not library.is_image_file(Path(uploaded.name)):
            continue
        entries.append((uploaded, parts))
    if not entries:
        raise FileNotFoundError("В выбранных подпапках не найдено поддерживаемых изображений.")

    # Folder selection supplies Root/Character/photo.jpg. A drag assembled by the
    # browser follows the same convention. Remove the shared Root component.
    first_parts = {parts[0] for _, parts in entries}
    has_shared_root = len(first_parts) == 1 and all(len(parts) >= 3 for _, parts in entries)
    groups: dict[str, list[tuple]] = {}
    for uploaded, parts in entries:
        useful = parts[1:] if has_shared_root else parts
        if len(useful) < 2:
            continue
        groups.setdefault(useful[0], []).append((uploaded, useful[1:]))
    if not groups:
        raise FileNotFoundError("В общей папке должны находиться подпапки с именами персонажей.")

    imported = skipped = 0
    batch_name = next(iter(first_parts)) if has_shared_root else "Загруженные персонажи"
    base = f"Catalog/{title.slug}/Импорт/{batch_name}"
    for name, files in sorted(groups.items(), key=lambda item: item[0].casefold()):
        name = name.strip()
        if not name or len(name) > Character._meta.get_field("name").max_length:
            skipped += 1
            continue
        if title.characters.filter(name__iexact=name).exists():
            skipped += 1
            continue

        gallery = ensure_media_folder(f"{base}/{name}")
        portrait = ""
        for uploaded, remainder in files:
            target = gallery
            if len(remainder) > 1:
                nested = "/".join(remainder[:-1])
                target = ensure_media_folder(f"{gallery}/{nested}")
            result = library.save_uploaded_files(target, [uploaded])
            if not portrait and result.get("saved"):
                portrait = result["saved"][0]
        Character.objects.create(
            title=title,
            name=name,
            gender=cleaned_data["gender"],
            importance=cleaned_data["importance"],
            faction=cleaned_data.get("faction", ""),
            gallery_folder=gallery,
            portrait_path=portrait if cleaned_data.get("use_first_photo") else "",
        )
        imported += 1
    return imported, skipped


@admin_required
def title_edit(request, slug):
    title = get_object_or_404(Title, slug=slug)
    form = TitleForm(request.POST or None, instance=title)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(title)
    return render(request, "photos/title_form.html", {"form": form, "title": title})


@require_POST
@admin_required
def title_delete(request, slug):
    title = get_object_or_404(Title, slug=slug)
    title.delete()
    return redirect("photos:index")


def default_character_gallery(character: Character) -> str:
    return f"Catalog/{character.title.slug}/{character.gender}/{character.slug}"


def ensure_media_folder(relative_path: str) -> str:
    clean, absolute = library.resolve_media_path(relative_path)
    absolute.mkdir(parents=True, exist_ok=True)
    return clean


def save_cover_upload(uploaded_file, target_folder: str) -> str:
    if not uploaded_file:
        raise ValueError("Выберите изображение обложки")
    if Path(uploaded_file.name).suffix.lower() not in library.IMAGE_EXTENSIONS:
        raise ValueError("Обложка должна быть изображением")
    ensure_media_folder(target_folder)
    result = library.save_uploaded_files(target_folder, [uploaded_file])
    if not result["saved"]:
        raise ValueError("Не удалось сохранить обложку")
    return result["saved"][0]


@ensure_csrf_cookie
def character_detail(request, character_id, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        pk=character_id,
        slug=character_slug,
    )
    form = CharacterForm(request.POST or None, instance=character)
    if request.method == "POST":
        if not user_can_manage(request.user):
            raise PermissionDenied("Изменять персонажей может только администратор")
        if request.POST.get("action") == "upload_portrait":
            character.portrait_path = save_cover_upload(
                request.FILES.get("cover"),
                f"Covers/Characters/{character.title.slug}/{character.slug}",
            )
            character.save(update_fields=["portrait_path", "updated_at"])
            return redirect(character)
        if request.POST.get("action") == "create_gallery":
            character.gallery_folder = ensure_media_folder(
                character.gallery_folder or default_character_gallery(character)
            )
            character.save(update_fields=["gallery_folder", "updated_at"])
            return redirect(character)
        if form.is_valid():
            form.save()
            return redirect(character)
    return render(request, "photos/character_detail.html", {
        "can_manage": user_can_manage(request.user),
        "character": character,
        "form": form,
    })


def legacy_character_detail(request, title_slug, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        title__slug=title_slug,
        slug=character_slug,
    )
    return redirect(character, permanent=True)


def character_gallery_location(character: Character, requested_folder: str = ""):
    if not character.gallery_folder:
        raise Http404("Галерея персонажа ещё не создана")
    base_rel, base_path = library.resolve_media_path(character.gallery_folder)
    if not base_path.is_dir():
        raise Http404("Папка галереи не найдена")
    subfolder = library.normalize_relative(requested_folder)
    current_rel = f"{base_rel}/{subfolder}" if subfolder else base_rel
    current_rel, current_path = library.resolve_media_path(current_rel)
    try:
        current_path.relative_to(base_path)
    except ValueError as error:
        raise SuspiciousFileOperation("Папка находится за пределами галереи персонажа") from error
    if not current_path.is_dir():
        raise Http404("Папка галереи не найдена")
    return base_rel, base_path, subfolder, current_rel


def character_gallery_entry(character: Character, relative_path: str):
    base_rel, base_path, _, _ = character_gallery_location(character)
    try:
        clean = library.normalize_relative(relative_path)
    except SuspiciousFileOperation as error:
        raise SuspiciousFileOperation("Элемент находится за пределами галереи персонажа") from error
    full_rel = f"{base_rel}/{clean}" if clean else base_rel
    full_rel, full_path = library.resolve_media_path(full_rel)
    try:
        full_path.relative_to(base_path)
    except ValueError as error:
        raise SuspiciousFileOperation("Элемент находится за пределами галереи персонажа") from error
    if full_path == base_path:
        raise SuspiciousFileOperation("Корневую папку галереи изменять нельзя")
    return full_rel, full_path


def character_gallery_folder_options(character: Character):
    _, base_path, _, _ = character_gallery_location(character)
    options = [{"path": "", "label": "Все фото (корень галереи)"}]
    for root, directory_names, _ in os.walk(base_path):
        directory_names[:] = sorted(
            (name for name in directory_names if not name.startswith(".") and name != "#recycle"),
            key=str.casefold,
        )
        for name in directory_names:
            folder = Path(root) / name
            relative = folder.relative_to(base_path).as_posix()
            options.append({"path": relative, "label": relative.replace("/", " › ")})
    return options


@ensure_csrf_cookie
def character_gallery(request, character_id, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        pk=character_id,
        slug=character_slug,
    )
    operation_error = ""
    base_rel, _, subfolder, current_rel = character_gallery_location(
        character,
        request.GET.get("folder", ""),
    )
    if request.method == "POST":
        if not user_can_manage(request.user):
            raise PermissionDenied("Управлять галереей может только администратор")
        action = request.POST.get("action", "")
        try:
            if action == "gallery_create_folder":
                library.create_folder(current_rel, request.POST.get("name", ""))
            elif action == "gallery_rename":
                source_rel, _ = character_gallery_entry(character, request.POST.get("source", ""))
                library.rename_entry(source_rel, request.POST.get("name", ""), request.POST.get("type", "file"))
            elif action == "gallery_move":
                source_rel, _ = character_gallery_entry(character, request.POST.get("source", ""))
                _, _, _, target_rel = character_gallery_location(character, request.POST.get("target", ""))
                library.move_entry(source_rel, target_rel, request.POST.get("type", "file"))
            elif action == "gallery_bulk_move":
                sources = list(dict.fromkeys(request.POST.getlist("sources")))
                if not sources:
                    raise ValueError("Выберите хотя бы одну фотографию.")
                if len(sources) > 500:
                    raise ValueError("За один раз можно переместить не более 500 файлов.")
                _, _, _, target_rel = character_gallery_location(character, request.POST.get("target", ""))
                validated_sources = []
                for source in sources:
                    source_rel, source_path = character_gallery_entry(character, source)
                    if not source_path.is_file() or not library.is_media_file(source_path):
                        raise ValueError("Выбранный элемент не является фотографией или видео.")
                    validated_sources.append(source_rel)
                for source_rel in validated_sources:
                    library.move_entry(source_rel, target_rel, "file")
            else:
                raise ValueError("Неизвестная операция с галереей")
        except (ValueError, OSError, SuspiciousFileOperation) as error:
            operation_error = str(error)
        else:
            target = reverse("photos:character_gallery", kwargs={
                "character_id": character.pk,
                "character_slug": character.slug,
            })
            changed = len(request.POST.getlist("sources")) if action == "gallery_bulk_move" else 1
            suffix = f"?folder={quote(subfolder)}&changed={changed}" if subfolder else f"?changed={changed}"
            return redirect(f"{target}{suffix}")
    listing = library.list_folder(current_rel, 0, 200)
    files = list(listing["files"])
    while listing["hasMore"]:
        listing = library.list_folder(current_rel, listing["nextOffset"], 200)
        files.extend(listing["files"])
    for file in files:
        file["relative"] = file["path"][len(base_rel):].lstrip("/")

    folders = []
    for folder in library.list_folder(current_rel, 0, 1)["folders"]:
        relative = folder["path"][len(base_rel):].lstrip("/")
        preview = folder.get("cover", "")
        if not preview:
            child_listing = library.list_folder(folder["path"], 0, 1)
            first_file = child_listing["files"][0] if child_listing["files"] else None
            preview = first_file["path"] if first_file and first_file["type"] == "image" else ""
        if preview:
            try:
                _, preview_path = library.resolve_media_path(preview)
                if not library.is_image_file(preview_path):
                    preview = ""
            except SuspiciousFileOperation:
                preview = ""
        folders.append({**folder, "relative": relative, "preview": preview})

    breadcrumbs = []
    parts = [part for part in subfolder.split("/") if part]
    for index, part in enumerate(parts):
        breadcrumbs.append({"name": part, "path": "/".join(parts[:index + 1])})

    return render(request, "photos/character_gallery.html", {
        "breadcrumbs": breadcrumbs,
        "can_manage": user_can_manage(request.user),
        "character": character,
        "current_folder": subfolder,
        "files": files,
        "folders": folders,
        "folder_options": character_gallery_folder_options(character),
        "image_count": sum(file["type"] == "image" for file in files),
        "operation_error": operation_error,
        "video_count": sum(file["type"] == "video" for file in files),
    })


@ensure_csrf_cookie
@admin_required
def character_gallery_upload(request, character_id, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        pk=character_id,
        slug=character_slug,
    )
    if not character.gallery_folder:
        character.gallery_folder = ensure_media_folder(default_character_gallery(character))
        character.save(update_fields=["gallery_folder", "updated_at"])

    base_rel, _, subfolder, current_rel = character_gallery_location(
        character,
        request.GET.get("folder", "") if request.method == "GET" else request.POST.get("folder", ""),
    )
    error = ""
    if request.method == "POST":
        action = request.POST.get("action", "upload")
        new_folder_name = request.POST.get("new_folder", "").strip()
        if action == "create_folder":
            if not new_folder_name:
                error = "Введите название новой папки."
            else:
                try:
                    created = library.create_folder(current_rel, new_folder_name)
                    created_subfolder = created["path"][len(base_rel):].lstrip("/")
                    return redirect(
                        f"{reverse('photos:character_gallery_upload', args=[character.pk, character.slug])}"
                        f"?folder={quote(created_subfolder)}&created=1"
                    )
                except (ValueError, OSError, SuspiciousFileOperation) as create_error:
                    error = str(create_error)

        uploaded_files = request.FILES.getlist("photos")
        selected_files = [
            upload
            for upload in uploaded_files
            if Path(upload.name).suffix.lower() in library.IMAGE_EXTENSIONS
        ]
        upload_target = current_rel
        if action == "upload" and new_folder_name:
            try:
                upload_target = library.create_folder(current_rel, new_folder_name)["path"]
            except (ValueError, OSError, SuspiciousFileOperation) as create_error:
                error = str(create_error)
        if action != "upload":
            pass
        elif error:
            pass
        elif not uploaded_files:
            error = "Выберите хотя бы одно изображение."
        elif not selected_files:
            error = "В выбранной папке нет поддерживаемых изображений."
        else:
            result = library.save_uploaded_files(upload_target, selected_files)
            if result["saved"]:
                return redirect(f"{character.get_absolute_url()}?uploaded={len(result['saved'])}")
            error = "Не удалось сохранить выбранные изображения."

    return render(request, "photos/character_gallery_upload.html", {
        "character": character,
        "current_folder": subfolder,
        "error": error,
    })


@require_POST
@admin_required
def character_delete(request, title_slug, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        title__slug=title_slug,
        slug=character_slug,
    )
    title = character.title
    character.delete()
    return redirect(title)


@require_GET
@admin_required
def config(request):
    return JsonResponse({"mediaRoot": str(library.media_root())})


@require_GET
@admin_required
def tree(request):
    try:
        return JsonResponse({"root": str(library.media_root()), "folders": library.list_folder_children("")})
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_GET
@admin_required
def tree_children(request):
    try:
        return JsonResponse({
            "path": library.normalize_relative(request.GET.get("path", "")),
            "folders": library.list_folder_children(request.GET.get("path", "")),
        })
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_GET
@admin_required
def folder(request):
    try:
        return JsonResponse(library.list_folder(
            request.GET.get("path", ""),
            request.GET.get("offset", 0),
            request.GET.get("limit"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_GET
@admin_required
def search(request):
    try:
        return JsonResponse(library.search_media(request.GET.get("q", "")))
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_POST
@admin_required
def move(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.move_entry(
            payload.get("source", ""),
            payload.get("targetFolder", ""),
            payload.get("type", "file"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def rename(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.rename_entry(
            payload.get("path", ""),
            payload.get("name", ""),
            payload.get("type", "file"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def delete(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.delete_entry(
            payload.get("path", ""),
            payload.get("type", "file"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def create_folder(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.create_folder(payload.get("parent", ""), payload.get("name", "")))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def upload(request):
    try:
        return JsonResponse(library.save_uploaded_files(
            request.POST.get("targetFolder", ""),
            request.FILES.getlist("files"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_POST
@admin_required
def import_site(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.import_images_from_site(
            payload.get("targetFolder", ""),
            payload.get("url", ""),
            payload.get("limit", library.IMPORT_MAX_IMAGES),
        ))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def tags(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.set_file_tags(payload.get("path", ""), payload.get("tags", [])))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@admin_required
def cover(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.set_folder_cover(payload.get("folder", ""), payload.get("cover", "")))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_GET
def media(request, relative_path):
    try:
        clean, absolute = library.resolve_media_path(relative_path)
    except SuspiciousFileOperation as error:
        return json_error(error, status=400)
    is_restricted_poster = Title.objects.filter(is_adult=True, poster_path=clean).exists()
    if is_restricted_poster and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not clean.startswith("Covers/") and not user_can_manage(request.user):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        raise PermissionDenied("Доступ к медиа разрешён только администратору")
    if not absolute.is_file() or not library.is_media_file(absolute):
        return JsonResponse({"error": "Media not found"}, status=404)
    response = FileResponse(open(absolute, "rb"), content_type=library.guess_content_type(absolute))
    response["Content-Disposition"] = f'inline; filename="{absolute.name}"'
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_GET
def thumbnail(request, size, relative_path):
    try:
        clean, absolute = library.resolve_media_path(relative_path)
    except SuspiciousFileOperation as error:
        return json_error(error, status=400)
    is_restricted_poster = Title.objects.filter(is_adult=True, poster_path=clean).exists()
    if is_restricted_poster and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not clean.startswith("Covers/") and not user_can_manage(request.user):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        raise PermissionDenied("Доступ к медиа разрешён только администратору")
    if not absolute.is_file() or not library.is_image_file(absolute):
        return JsonResponse({"error": "Image not found"}, status=404)
    try:
        target, content_type = library.thumbnail_file(clean, size)
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)
    response = FileResponse(open(target, "rb"), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{target.name}"'
    response["Cache-Control"] = "private, max-age=86400"
    return response
