from django.urls import path

from . import views


app_name = "photos"

urlpatterns = [
    path("", views.notes_home, name="todo"),
    path("documents/", views.document_library, name="documents"),
    path("profile/", views.profile, name="profile"),
    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),
    path("titles/", views.index, name="index"),
    path("library/", views.media_library, name="media_library"),
    path("tools/hentaidad/", views.hentaidad_tool, name="hentaidad_tool"),
    path("tools/hentaidad/download-single/", views.hentaidad_tool_download_single, name="hentaidad_tool_download_single"),
    path("tools/hentaidad/download/", views.hentaidad_tool_download, name="hentaidad_tool_download"),
    path("titles/<str:slug>/", views.title_detail, name="title_detail"),
    path("titles/<str:slug>/characters/", views.title_characters, name="title_characters"),
    path("titles/<str:slug>/edit/", views.title_edit, name="title_edit"),
    path("titles/<str:slug>/delete/", views.title_delete, name="title_delete"),
    path(
        "titles/<str:title_slug>/characters/<str:character_slug>/",
        views.legacy_character_detail,
        name="legacy_character_detail",
    ),
    path("characters/<int:character_id>-<str:character_slug>/", views.character_detail, name="character_detail"),
    path(
        "characters/<int:character_id>-<str:character_slug>/gallery/",
        views.character_gallery,
        name="character_gallery",
    ),
    path(
        "characters/<int:character_id>-<str:character_slug>/gallery/upload/",
        views.character_gallery_upload,
        name="character_gallery_upload",
    ),
    path(
        "titles/<str:title_slug>/characters/<str:character_slug>/delete/",
        views.character_delete,
        name="character_delete",
    ),
    path("api/config/", views.config, name="config"),
    path("api/tree/", views.tree, name="tree"),
    path("api/tree-children/", views.tree_children, name="tree_children"),
    path("api/folder/", views.folder, name="folder"),
    path("api/search/", views.search, name="search"),
    path("api/move/", views.move, name="move"),
    path("api/rename/", views.rename, name="rename"),
    path("api/delete/", views.delete, name="delete"),
    path("api/create-folder/", views.create_folder, name="create_folder"),
    path("api/upload/", views.upload, name="upload"),
    path("api/import-site/", views.import_site, name="import_site"),
    path("api/tags/", views.tags, name="tags"),
    path("api/cover/", views.cover, name="cover"),
    path("thumb/<str:size>/<path:relative_path>", views.thumbnail, name="thumbnail"),
    path("media/<path:relative_path>", views.media, name="media"),
]
