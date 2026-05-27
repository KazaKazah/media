from django.contrib import admin

from .models import Character, TextDocument, Title, TodoItem, TodoProject


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_adult", "updated_at")
    list_filter = ("kind", "is_adult")
    search_fields = ("name", "original_name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "gender", "role", "height", "weight", "updated_at")
    list_filter = ("gender", "title__kind")
    search_fields = ("name", "title__name", "race", "features", "abilities", "eye_color", "hair_color")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TodoProject)
class TodoProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "color", "created_at")
    list_filter = ("owner",)
    search_fields = ("name", "owner__username")


@admin.register(TodoItem)
class TodoItemAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "kind", "priority", "project", "due_at", "is_done", "completed_at", "is_pinned")
    list_filter = ("kind", "priority", "is_done", "is_pinned", "project")
    search_fields = ("title", "body", "tags", "owner__username")


@admin.register(TextDocument)
class TextDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "original_filename", "updated_at")
    list_filter = ("owner",)
    search_fields = ("title", "original_filename", "content", "owner__username")
