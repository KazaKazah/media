import json
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, SuspiciousFileOperation
from django.db.models import Case, Count, IntegerField, Q, When
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import CharacterCreateForm, CharacterForm, TextDocumentUploadForm, TitleForm
from . import library
from .models import Character, TextDocument, Title, TodoItem, TodoProject


def json_error(error: Exception, status: int = 400):
    return JsonResponse({"error": str(error) or "Request failed"}, status=status)


def user_can_manage(user) -> bool:
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


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
    if kind in Title.Kind.values:
        titles = titles.filter(kind=kind)
    if query:
        titles = titles.filter(
            Q(name__icontains=query)
            | Q(original_name__icontains=query)
            | Q(description__icontains=query)
            | Q(gallery_folder__icontains=query)
            | Q(characters__name__icontains=query)
            | Q(characters__role__icontains=query)
        ).distinct()
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
        "title_kinds": Title.Kind.choices,
        "titles": titles.prefetch_related("characters"),
    })


@ensure_csrf_cookie
@admin_required
def media_library(request):
    return render(request, "photos/index.html")


@ensure_csrf_cookie
def title_detail(request, slug):
    title = get_object_or_404(Title, slug=slug)
    form = CharacterCreateForm()
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
    characters = title.characters.all()
    return render(request, "photos/title_detail.html", {
        "can_manage": user_can_manage(request.user),
        "title": title,
        "form": form,
        "female_characters": characters.filter(gender=Character.Gender.FEMALE),
        "male_characters": characters.filter(gender=Character.Gender.MALE),
        "other_characters": characters.filter(gender=Character.Gender.OTHER),
    })


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
def character_detail(request, title_slug, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        title__slug=title_slug,
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
