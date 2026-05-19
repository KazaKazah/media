import json

from django.core.exceptions import SuspiciousFileOperation
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .forms import CharacterForm, TitleForm
from . import library
from .models import Character, Title


def json_error(error: Exception, status: int = 400):
    return JsonResponse({"error": str(error) or "Request failed"}, status=status)


@ensure_csrf_cookie
@login_required
def index(request):
    titles = Title.objects.all()
    kind = request.GET.get("kind", "")
    query = request.GET.get("q", "").strip()
    if kind in Title.Kind.values:
        titles = titles.filter(kind=kind)
    if query:
        titles = titles.filter(name__icontains=query)
    form = TitleForm()
    if request.method == "POST":
        form = TitleForm(request.POST)
        if form.is_valid():
            title = form.save()
            return redirect(title)
    return render(request, "photos/catalog.html", {
        "form": form,
        "kind": kind,
        "query": query,
        "title_kinds": Title.Kind.choices,
        "titles": titles.prefetch_related("characters"),
    })


@ensure_csrf_cookie
@login_required
def media_library(request):
    return render(request, "photos/index.html")


@login_required
def title_detail(request, slug):
    title = get_object_or_404(Title, slug=slug)
    form = CharacterForm()
    if request.method == "POST":
        form = CharacterForm(request.POST)
        if form.is_valid():
            character = form.save(commit=False)
            character.title = title
            character.save()
            return redirect(character)
    characters = title.characters.all()
    return render(request, "photos/title_detail.html", {
        "title": title,
        "form": form,
        "female_characters": characters.filter(gender=Character.Gender.FEMALE),
        "male_characters": characters.filter(gender=Character.Gender.MALE),
        "other_characters": characters.filter(gender=Character.Gender.OTHER),
    })


@login_required
def title_edit(request, slug):
    title = get_object_or_404(Title, slug=slug)
    form = TitleForm(request.POST or None, instance=title)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(title)
    return render(request, "photos/title_form.html", {"form": form, "title": title})


def default_character_gallery(character: Character) -> str:
    return f"Catalog/{character.title.slug}/{character.gender}/{character.slug}"


def ensure_media_folder(relative_path: str) -> str:
    clean, absolute = library.resolve_media_path(relative_path)
    absolute.mkdir(parents=True, exist_ok=True)
    return clean


@login_required
def character_detail(request, title_slug, character_slug):
    character = get_object_or_404(
        Character.objects.select_related("title"),
        title__slug=title_slug,
        slug=character_slug,
    )
    form = CharacterForm(request.POST or None, instance=character)
    if request.method == "POST":
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
        "character": character,
        "form": form,
    })


@require_GET
@login_required
def config(request):
    return JsonResponse({"mediaRoot": str(library.media_root())})


@require_GET
@login_required
def tree(request):
    try:
        return JsonResponse({"root": str(library.media_root()), "folders": library.list_tree("")})
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_GET
@login_required
def folder(request):
    try:
        return JsonResponse(library.list_folder(
            request.GET.get("path", ""),
            request.GET.get("offset", 0),
            request.GET.get("limit"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_POST
@login_required
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
@login_required
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
@login_required
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
@login_required
def create_folder(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.create_folder(payload.get("parent", ""), payload.get("name", "")))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@login_required
def upload(request):
    try:
        return JsonResponse(library.save_uploaded_files(
            request.POST.get("targetFolder", ""),
            request.FILES.getlist("files"),
        ))
    except (ValueError, OSError, SuspiciousFileOperation) as error:
        return json_error(error)


@require_POST
@login_required
def tags(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.set_file_tags(payload.get("path", ""), payload.get("tags", [])))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_POST
@login_required
def cover(request):
    try:
        payload = json.loads(request.body or "{}")
        return JsonResponse(library.set_folder_cover(payload.get("folder", ""), payload.get("cover", "")))
    except (ValueError, OSError, SuspiciousFileOperation, json.JSONDecodeError) as error:
        return json_error(error)


@require_GET
@login_required
def media(request, relative_path):
    try:
        clean, absolute = library.resolve_media_path(relative_path)
    except SuspiciousFileOperation as error:
        return json_error(error, status=400)
    if not absolute.is_file() or not library.is_media_file(absolute):
        return JsonResponse({"error": "Media not found"}, status=404)
    response = FileResponse(open(absolute, "rb"), content_type=library.guess_content_type(absolute))
    response["Content-Disposition"] = f'inline; filename="{absolute.name}"'
    response["Cache-Control"] = "private, max-age=3600"
    return response
