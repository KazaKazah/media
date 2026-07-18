from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_sqlite(connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")


class PhotosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "photos"

    def ready(self):
        connection_created.connect(configure_sqlite, dispatch_uid="photos.configure_sqlite")
