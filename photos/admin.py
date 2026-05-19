from django.contrib import admin

from .models import Character, Title


@admin.register(Title)
class TitleAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "updated_at")
    list_filter = ("kind",)
    search_fields = ("name", "original_name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ("name", "title", "gender", "role", "updated_at")
    list_filter = ("gender", "title__kind")
    search_fields = ("name", "title__name", "race", "features", "abilities")
    prepopulated_fields = {"slug": ("name",)}
