from django.urls import path

from . import views


app_name = "photos"

urlpatterns = [
    path("", views.index, name="index"),
    path("library/", views.media_library, name="media_library"),
    path("titles/<str:slug>/", views.title_detail, name="title_detail"),
    path("titles/<str:slug>/edit/", views.title_edit, name="title_edit"),
    path(
        "titles/<str:title_slug>/characters/<str:character_slug>/",
        views.character_detail,
        name="character_detail",
    ),
    path("api/config/", views.config, name="config"),
    path("api/tree/", views.tree, name="tree"),
    path("api/folder/", views.folder, name="folder"),
    path("api/move/", views.move, name="move"),
    path("api/rename/", views.rename, name="rename"),
    path("api/delete/", views.delete, name="delete"),
    path("api/create-folder/", views.create_folder, name="create_folder"),
    path("api/upload/", views.upload, name="upload"),
    path("api/tags/", views.tags, name="tags"),
    path("api/cover/", views.cover, name="cover"),
    path("media/<path:relative_path>", views.media, name="media"),
]
