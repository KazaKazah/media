from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Character, TextDocument, Title, TodoItem, TodoProject, UserProfile
from .note_crypto import NoteDecryptionError, decrypt_note, encrypt_note


class OptionalUserProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "profile-user",
            email="profile@example.com",
            password="test",
        )
        self.client.force_login(self.user)

    def test_missing_profile_does_not_break_catalog_or_create_a_record(self):
        response = self.client.get("/titles/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-user")
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_user_can_create_optional_profile(self):
        response = self.client.post("/profile/", {
            "display_name": "Асанали",
            "bio": "Владелец медиатеки",
            "location": "Астана",
            "website": "",
            "birth_date": "",
        })

        self.assertRedirects(response, "/profile/?saved=1", fetch_redirect_response=False)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.display_name, "Асанали")
        self.assertEqual(profile.location, "Астана")


class AdultTitleAccessTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        self.media_override = override_settings(MEDIA_LIBRARY_ROOT=Path(self.temp_media.name))
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

        poster = Path(self.temp_media.name) / "Covers" / "Titles" / "adult" / "poster.jpg"
        poster.parent.mkdir(parents=True)
        poster.write_bytes(b"poster")
        self.title = Title.objects.create(
            name="Adult title",
            kind=Title.Kind.HENTAI,
            poster_path="Covers/Titles/adult/poster.jpg",
        )

    def test_hentai_title_is_always_adult(self):
        self.assertTrue(self.title.is_adult)

    def test_guest_gets_mask_and_cannot_fetch_adult_poster(self):
        catalog = self.client.get("/titles/")
        detail = self.client.get(self.title.get_absolute_url())
        media = self.client.get("/media/Covers/Titles/adult/poster.jpg")

        self.assertContains(catalog, "18+")
        self.assertNotContains(catalog, "/media/Covers/Titles/adult/poster.jpg")
        self.assertNotContains(detail, "/media/Covers/Titles/adult/poster.jpg")
        self.assertRedirects(
            media,
            "/accounts/login/?next=/media/Covers/Titles/adult/poster.jpg",
            fetch_redirect_response=False,
        )

    def test_authenticated_user_can_see_adult_poster_in_detail(self):
        user = get_user_model().objects.create_user("viewer", password="test")
        client = Client()
        client.force_login(user)

        detail = client.get(self.title.get_absolute_url())
        media = client.get("/media/Covers/Titles/adult/poster.jpg")

        self.assertContains(detail, "/media/Covers/Titles/adult/poster.jpg")
        self.assertEqual(media.status_code, 200)


class CharacterCreateExperienceTests(TestCase):
    def setUp(self):
        self.temp_media = TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        self.media_override = override_settings(MEDIA_LIBRARY_ROOT=Path(self.temp_media.name))
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.admin = get_user_model().objects.create_superuser("catalog-admin", password="test")
        self.client.force_login(self.admin)
        self.title = Title.objects.create(name="Character studio")

    def test_create_form_renders_grouped_experience(self):
        response = self.client.get(f"{self.title.get_absolute_url()}characters/")

        self.assertContains(response, 'id="directoryCharacterForm"')
        self.assertContains(response, "Внешность и подробное описание")
        self.assertContains(response, "Роль в сюжете")
        self.assertContains(response, "Сразу создать папку галереи")
        self.assertContains(response, 'name="portrait_upload"')

    def test_character_can_be_created_with_portrait_and_gallery(self):
        portrait = SimpleUploadedFile(
            "hero.gif",
            (
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
                b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
                b"\x00\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )

        response = self.client.post(
            f"{self.title.get_absolute_url()}characters/",
            {
                "name": "Мока",
                "gender": Character.Gender.FEMALE,
                "importance": Character.Importance.MAIN,
                "role": "Главная героиня",
                "race": "Вампир",
                "portrait_upload": portrait,
                "create_gallery": "on",
            },
        )

        character = Character.objects.get(title=self.title)
        self.assertRedirects(response, character.get_absolute_url())
        self.assertTrue(character.portrait_path)
        self.assertTrue(character.gallery_folder)
        self.assertTrue((Path(self.temp_media.name) / character.portrait_path).exists())
        self.assertTrue((Path(self.temp_media.name) / character.gallery_folder).is_dir())

    def test_characters_can_be_imported_from_named_folders(self):
        source = Path(self.temp_media.name) / "Imports" / "Characters"
        (source / "Эрис Борей Грейрат" / "Арты").mkdir(parents=True)
        (source / "Рокси Мигурдия").mkdir()
        (source / "Эрис Борей Грейрат" / "Арты" / "eris.webp").write_bytes(b"image")
        (source / "Рокси Мигурдия" / "roxy.jpg").write_bytes(b"image")

        url = f"{self.title.get_absolute_url()}characters/"
        response = self.client.post(url, {
            "action": "import_character_folders",
            "source_folder": "/library/?path=Imports%2FCharacters",
            "gender": Character.Gender.FEMALE,
            "importance": Character.Importance.MAIN,
            "use_first_photo": "on",
        })

        self.assertRedirects(
            response,
            f"{url}?imported=2&skipped=0",
            fetch_redirect_response=False,
        )
        eris = Character.objects.get(title=self.title, name="Эрис Борей Грейрат")
        self.assertEqual(eris.gallery_folder, "Imports/Characters/Эрис Борей Грейрат")
        self.assertEqual(eris.portrait_path, "Imports/Characters/Эрис Борей Грейрат/Арты/eris.webp")
        self.assertEqual(eris.importance, Character.Importance.MAIN)

        second = self.client.post(url, {
            "action": "import_character_folders",
            "source_folder": "Imports/Characters",
            "gender": Character.Gender.FEMALE,
            "importance": Character.Importance.SUPPORTING,
            "use_first_photo": "on",
        })
        self.assertEqual(Character.objects.filter(title=self.title).count(), 2)
        self.assertEqual(second.url, f"{url}?imported=0&skipped=2")

    def test_dragged_character_folders_are_uploaded_with_their_structure(self):
        url = f"{self.title.get_absolute_url()}characters/"
        response = self.client.post(url, {
            "action": "import_character_folders",
            "gender": Character.Gender.FEMALE,
            "importance": Character.Importance.SUPPORTING,
            "use_first_photo": "on",
            "folder_files": [
                SimpleUploadedFile("eris.jpg", b"eris", content_type="image/jpeg"),
                SimpleUploadedFile("art.webp", b"art", content_type="image/webp"),
                SimpleUploadedFile("roxy.png", b"roxy", content_type="image/png"),
            ],
            "relative_paths": [
                "My Characters/Эрис/eris.jpg",
                "My Characters/Эрис/Arts/art.webp",
                "My Characters/Рокси/roxy.png",
            ],
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Character.objects.filter(title=self.title).count(), 2)
        eris = Character.objects.get(title=self.title, name="Эрис")
        self.assertTrue(eris.gallery_folder.endswith("/My Characters/Эрис"))
        self.assertTrue(eris.portrait_path.endswith("/My Characters/Эрис/eris.jpg"))
        self.assertTrue((Path(self.temp_media.name) / eris.portrait_path).is_file())
        self.assertTrue(
            (Path(self.temp_media.name) / eris.gallery_folder / "Arts" / "art.webp").is_file()
        )

    def test_single_character_folder_with_one_image_can_be_uploaded(self):
        url = f"{self.title.get_absolute_url()}characters/"
        response = self.client.post(url, {
            "action": "import_character_folders",
            "gender": Character.Gender.FEMALE,
            "importance": Character.Importance.SUPPORTING,
            "use_first_photo": "on",
            "folder_files": [
                SimpleUploadedFile("augusta.jpg", b"image", content_type="image/jpeg"),
            ],
            "relative_paths": [
                "Августа Фредерика Адель-Адлер/augusta.jpg",
            ],
        })

        self.assertEqual(response.status_code, 302)
        character = Character.objects.get(
            title=self.title,
            name="Августа Фредерика Адель-Адлер",
        )
        self.assertTrue(character.portrait_path.endswith("/augusta.jpg"))
        self.assertTrue((Path(self.temp_media.name) / character.portrait_path).is_file())

    def test_folder_import_script_uses_real_form_url(self):
        response = self.client.get(f"{self.title.get_absolute_url()}characters/")

        self.assertContains(response, 'folderImportForm.getAttribute("action")')
        self.assertNotContains(response, "fetch(folderImportForm.action")

    def test_characters_can_be_selected_and_bulk_edited(self):
        first = Character.objects.create(title=self.title, name="First", gender=Character.Gender.MALE)
        second = Character.objects.create(title=self.title, name="Second", gender=Character.Gender.MALE)
        untouched = Character.objects.create(title=self.title, name="Untouched", gender=Character.Gender.MALE)

        response = self.client.post(f"{self.title.get_absolute_url()}characters/", {
            "action": "bulk_update_characters",
            "characters": [str(first.pk), str(second.pk)],
            "bulk_gender": Character.Gender.FEMALE,
            "bulk_importance": Character.Importance.MAIN,
            "apply_role": "on",
            "bulk_role": "Героиня",
            "apply_race": "on",
            "bulk_race": "Человек",
        })

        self.assertEqual(response.status_code, 302)
        first.refresh_from_db()
        second.refresh_from_db()
        untouched.refresh_from_db()
        self.assertEqual(first.gender, Character.Gender.FEMALE)
        self.assertEqual(second.importance, Character.Importance.MAIN)
        self.assertEqual(first.role, "Героиня")
        self.assertEqual(second.race, "Человек")
        self.assertEqual(untouched.gender, Character.Gender.MALE)
        self.assertIn("bulk_updated=2", response.url)

    def test_bulk_edit_is_scoped_to_current_title_and_gender_tabs_render(self):
        female = Character.objects.create(title=self.title, name="Female", gender=Character.Gender.FEMALE)
        male = Character.objects.create(title=self.title, name="Male", gender=Character.Gender.MALE)
        another_title = Title.objects.create(name="Another title")
        foreign = Character.objects.create(title=another_title, name="Foreign", gender=Character.Gender.MALE)

        response = self.client.post(f"{self.title.get_absolute_url()}characters/", {
            "action": "bulk_update_characters",
            "characters": [str(female.pk), str(foreign.pk)],
            "bulk_gender": Character.Gender.OTHER,
        })
        page = self.client.get(f"{self.title.get_absolute_url()}characters/")

        female.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(female.gender, Character.Gender.OTHER)
        self.assertEqual(foreign.gender, Character.Gender.MALE)
        self.assertContains(page, 'data-gender-filter="female"')
        self.assertContains(page, 'data-gender-filter="male"')
        self.assertContains(page, 'data-gender="male"')

    def test_folder_import_rejects_paths_outside_media_library(self):
        response = self.client.post(
            f"{self.title.get_absolute_url()}characters/",
            {
                "action": "import_character_folders",
                "source_folder": "/tmp",
                "gender": Character.Gender.FEMALE,
                "importance": Character.Importance.SUPPORTING,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Можно выбирать папки только внутри медиатеки")
        self.assertFalse(Character.objects.filter(title=self.title).exists())

    def test_title_links_to_directory_and_legacy_character_url_redirects(self):
        character = Character.objects.create(title=self.title, name="Эрис")

        title_page = self.client.get(self.title.get_absolute_url())
        directory = self.client.get(f"{self.title.get_absolute_url()}characters/")
        legacy = self.client.get(
            f"{self.title.get_absolute_url()}characters/{character.slug}/"
        )

        self.assertContains(title_page, "Все персонажи")
        self.assertContains(directory, character.name)
        self.assertTrue(character.get_absolute_url().startswith(f"/characters/{character.pk}-"))
        self.assertRedirects(
            legacy,
            character.get_absolute_url(),
            status_code=301,
            fetch_redirect_response=False,
        )

    def test_character_gallery_lists_images_and_subfolders(self):
        character = Character.objects.create(
            title=self.title,
            name="Эрис",
            gallery_folder="Catalog/character-studio/female/eris",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        (gallery / "Арты").mkdir(parents=True)
        (gallery / "portrait.jpg").write_bytes(b"image")
        (gallery / "Арты" / "art.jpg").write_bytes(b"image")

        response = self.client.get(
            f"{character.get_absolute_url()}gallery/"
        )

        self.assertContains(response, "Галерея Эрис")
        self.assertContains(response, "portrait.jpg")
        self.assertContains(response, "Арты")
        self.assertContains(response, "Добавить фото")

        nested = self.client.get(
            f"{character.get_absolute_url()}gallery/",
            {"folder": "Арты"},
        )

        self.assertEqual(nested.status_code, 200)
        self.assertContains(nested, "art.jpg")
        self.assertContains(nested, "Арты")

    def test_character_gallery_can_create_rename_and_move_entries(self):
        character = Character.objects.create(
            title=self.title,
            name="Галерея",
            gallery_folder="Catalog/character-studio/female/gallery-manager",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        gallery.mkdir(parents=True)
        (gallery / "photo.jpg").write_bytes(b"image")
        url = f"{character.get_absolute_url()}gallery/"

        created = self.client.post(url, {"action": "gallery_create_folder", "name": "Арты"})
        self.assertEqual(created.status_code, 302)
        self.assertTrue((gallery / "Арты").is_dir())

        renamed = self.client.post(url, {
            "action": "gallery_rename",
            "source": "Арты",
            "type": "folder",
            "name": "Официальные арты",
        })
        self.assertEqual(renamed.status_code, 302)
        self.assertTrue((gallery / "Официальные арты").is_dir())

        moved = self.client.post(url, {
            "action": "gallery_move",
            "source": "photo.jpg",
            "type": "file",
            "target": "Официальные арты",
        })
        self.assertEqual(moved.status_code, 302)
        self.assertTrue((gallery / "Официальные арты" / "photo.jpg").is_file())

    def test_character_gallery_can_bulk_move_selected_photos(self):
        character = Character.objects.create(
            title=self.title,
            name="Bulk Gallery",
            gallery_folder="Catalog/character-studio/female/bulk-gallery",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        (gallery / "Избранное").mkdir(parents=True)
        for filename in ("one.jpg", "two.png", "leave.webp"):
            (gallery / filename).write_bytes(b"image")

        response = self.client.post(f"{character.get_absolute_url()}gallery/", {
            "action": "gallery_bulk_move",
            "sources": ["one.jpg", "two.png"],
            "target": "Избранное",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue((gallery / "Избранное" / "one.jpg").is_file())
        self.assertTrue((gallery / "Избранное" / "two.png").is_file())
        self.assertTrue((gallery / "leave.webp").is_file())
        self.assertIn("changed=2", response.url)

    def test_bulk_move_validates_every_source_before_moving_any_file(self):
        character = Character.objects.create(
            title=self.title,
            name="Safe Bulk Gallery",
            gallery_folder="Catalog/character-studio/female/safe-bulk-gallery",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        (gallery / "Target").mkdir(parents=True)
        (gallery / "safe.jpg").write_bytes(b"image")

        response = self.client.post(f"{character.get_absolute_url()}gallery/", {
            "action": "gallery_bulk_move",
            "sources": ["safe.jpg", "../../outside.jpg"],
            "target": "Target",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue((gallery / "safe.jpg").is_file())
        self.assertFalse((gallery / "Target" / "safe.jpg").exists())

    def test_character_gallery_cannot_manage_another_gallery(self):
        character = Character.objects.create(
            title=self.title,
            name="Safe Gallery",
            gallery_folder="Catalog/character-studio/female/safe-gallery",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        gallery.mkdir(parents=True)
        outside = Path(self.temp_media.name) / "outside.jpg"
        outside.write_bytes(b"image")

        response = self.client.post(f"{character.get_absolute_url()}gallery/", {
            "action": "gallery_rename",
            "source": "../../../../outside.jpg",
            "type": "file",
            "name": "stolen.jpg",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "за пределами галереи")
        self.assertTrue(outside.exists())

    def test_gallery_is_public_but_management_controls_are_admin_only(self):
        character = Character.objects.create(
            title=self.title,
            name="Public Gallery",
            gallery_folder="Catalog/character-studio/female/public-gallery",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        gallery.mkdir(parents=True)
        (gallery / "public.jpg").write_bytes(b"image")
        self.client.logout()

        response = self.client.get(f"{character.get_absolute_url()}gallery/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "public.jpg")
        self.assertNotContains(response, "Новая папка")
        self.assertNotContains(response, 'class="character-gallery-manage file-manage"')

    def test_gallery_upload_returns_to_character_profile(self):
        character = Character.objects.create(
            title=self.title,
            name="Акено",
            gallery_folder="Catalog/character-studio/female/akeno",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        gallery.mkdir(parents=True)
        photo = SimpleUploadedFile("new-photo.jpg", b"image", content_type="image/jpeg")
        ignored = SimpleUploadedFile("album-notes.txt", b"notes", content_type="text/plain")

        response = self.client.post(
            f"{character.get_absolute_url()}gallery/upload/",
            {"photos": [photo, ignored]},
        )

        self.assertRedirects(
            response,
            f"{character.get_absolute_url()}?uploaded=1",
        )
        self.assertTrue((gallery / "new-photo.jpg").exists())
        self.assertFalse((gallery / "album-notes.txt").exists())


class TitleCatalogMetadataTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("metadata-admin", password="test")
        self.client.force_login(self.admin)
        self.magic = Title.objects.create(
            name="Magic Academy",
            format=Title.Format.TV,
            release_status=Title.ReleaseStatus.ONGOING,
            year=2026,
            season=Title.Season.SUMMER,
            age_rating=Title.AgeRating.PG13,
            audience=Title.Audience.SHOUNEN,
            genres="fantasy,action",
            themes="school,magic",
            score="8.7",
        )
        self.romance = Title.objects.create(
            name="Quiet Romance",
            format=Title.Format.MOVIE,
            year=2024,
            genres="romance,drama",
        )

    def test_catalog_filters_optional_metadata(self):
        response = self.client.get("/titles/", {
            "format": Title.Format.TV,
            "year": "2026",
            "genre": "fantasy",
            "theme": "magic",
        })

        self.assertContains(response, self.magic.name)
        self.assertNotContains(response, self.romance.name)
        self.assertContains(response, "Сортировка")
        self.assertContains(response, "Жанры")

    def test_catalog_is_alphabetical_by_default_ignoring_case(self):
        Title.objects.create(name="alpha Story")
        Title.objects.create(name="Beta Story")

        response = self.client.get("/titles/")
        names = [title.name for title in response.context["titles"]]

        self.assertEqual(names, sorted(names, key=lambda name: (name.lower(), name)))
        self.assertEqual(response.context["sort"], "name")

    def test_create_form_saves_optional_genres_and_themes(self):
        response = self.client.post("/titles/", {
            "name": "New Metadata Title",
            "kind": Title.Kind.ANIME,
            "format": Title.Format.OVA,
            "year": "2025",
            "score": "7.5",
            "genres": ["action", "fantasy"],
            "themes": ["magic", "school"],
        })

        created = Title.objects.get(name="New Metadata Title")
        self.assertRedirects(response, created.get_absolute_url())
        self.assertEqual(created.genres, "action,fantasy")
        self.assertEqual(created.themes, "magic,school")

    def test_title_page_immediately_lists_all_related_characters(self):
        for index in range(10):
            Character.objects.create(title=self.magic, name=f"Character {index}")

        response = self.client.get(self.magic.get_absolute_url())

        for index in range(10):
            self.assertContains(response, f"Character {index}")

    def test_downloader_package_requires_login_and_contains_gui(self):
        anonymous = Client().get("/tools/hentaidad/download/")
        self.assertEqual(anonymous.status_code, 302)

        response = self.client.get("/tools/hentaidad/download/")
        payload = b"".join(response.streaming_content)
        with ZipFile(BytesIO(payload)) as archive:
            names = set(archive.namelist())

        self.assertIn("HentaidadDownloader/hentaidad_sync.py", names)
        self.assertIn("HentaidadDownloader/hentaidad_downloader_gui.py", names)
        self.assertIn("HentaidadDownloader/start-windows.bat", names)

        single = self.client.get("/tools/hentaidad/download-single/")
        single_payload = b"".join(single.streaming_content)
        compile(single_payload, "HentaidadDownloader.pyw", "exec")
        self.assertIn("HentaidadDownloader.pyw", single["Content-Disposition"])
        self.assertIn(b"embedded_sync_path", single_payload)


class TodoListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("planner", password="test")
        self.stranger = get_user_model().objects.create_user("other", password="test")
        self.client.force_login(self.user)
        self.project = TodoProject.objects.create(owner=self.user, name="Запуск")

    def test_item_can_be_created_with_project_and_priority(self):
        response = self.client.post(
            "/",
            {
                "action": "create_item",
                "title": "Подготовить релиз",
                "priority": TodoItem.Priority.URGENT,
                "kind": TodoItem.Kind.REMINDER,
                "project": self.project.pk,
                "tags": "важное, релиз",
            },
        )

        item = TodoItem.objects.get(owner=self.user)
        self.assertRedirects(response, "/")
        self.assertEqual(item.priority, TodoItem.Priority.URGENT)
        self.assertEqual(item.project, self.project)
        self.assertContains(self.client.get("/?view=inbox"), "Подготовить релиз")

    def test_deadline_views_show_only_relevant_active_items(self):
        past = TodoItem.objects.create(
            owner=self.user,
            title="Опоздавшая задача",
            due_at=timezone.now() - timedelta(hours=1),
        )
        future = TodoItem.objects.create(
            owner=self.user,
            title="Будущая задача",
            due_at=timezone.now() + timedelta(days=2),
        )

        overdue = self.client.get("/?view=overdue")
        upcoming = self.client.get("/?view=upcoming")

        self.assertContains(overdue, past.title)
        self.assertNotContains(overdue, future.title)
        self.assertContains(upcoming, future.title)
        self.assertNotContains(upcoming, past.title)

    def test_item_can_be_updated_pinned_and_completed(self):
        item = TodoItem.objects.create(owner=self.user, title="Черновик")

        self.client.post(
            "/",
            {
                "action": "update_item",
                "item": item.pk,
                "title": "Готовый план",
                "priority": TodoItem.Priority.HIGH,
                "kind": TodoItem.Kind.TASK,
                "project": self.project.pk,
            },
        )
        self.client.post("/", {"action": "toggle_pin", "item": item.pk})
        self.client.post("/", {"action": "toggle_item", "item": item.pk})
        item.refresh_from_db()

        self.assertEqual(item.title, "Готовый план")
        self.assertEqual(item.priority, TodoItem.Priority.HIGH)
        self.assertTrue(item.is_pinned)
        self.assertTrue(item.is_done)
        self.assertIsNotNone(item.completed_at)

    def test_bulk_delete_and_actions_do_not_touch_another_users_items(self):
        mine = TodoItem.objects.create(owner=self.user, title="Моё", is_done=True)
        theirs = TodoItem.objects.create(owner=self.stranger, title="Чужое", is_done=True)

        self.client.post("/", {"action": "clear_completed"})
        foreign_toggle = self.client.post("/", {"action": "toggle_item", "item": theirs.pk})

        self.assertFalse(TodoItem.objects.filter(pk=mine.pk).exists())
        self.assertTrue(TodoItem.objects.filter(pk=theirs.pk).exists())
        self.assertEqual(foreign_toggle.status_code, 404)

    def test_post_redirect_does_not_allow_external_next_url(self):
        item = TodoItem.objects.create(owner=self.user, title="Безопасный переход")

        response = self.client.post(
            "/",
            {"action": "toggle_pin", "item": item.pk, "next": "https://example.com/steal"},
        )

        self.assertRedirects(response, "/")

    def test_notes_are_browsed_by_category_and_opened_for_details(self):
        second_project = TodoProject.objects.create(owner=self.user, name="Личное")
        note = TodoItem.objects.create(
            owner=self.user,
            project=self.project,
            kind=TodoItem.Kind.NOTE,
            title="План запуска",
            body="Скрытые подробности запуска",
        )
        TodoItem.objects.create(
            owner=self.user,
            project=second_project,
            kind=TodoItem.Kind.NOTE,
            title="Личная заметка",
        )

        categories = self.client.get("/?view=notes")
        category = self.client.get(f"/?view=notes&project={self.project.pk}")
        detail = self.client.get(f"/?view=notes&project={self.project.pk}&note={note.pk}")
        inbox = self.client.get("/?view=inbox")

        self.assertContains(categories, "Запуск")
        self.assertContains(categories, "Без категории")
        self.assertNotContains(categories, note.title)
        self.assertContains(category, note.title)
        self.assertNotContains(category, note.body)
        self.assertNotContains(category, "Личная заметка")
        self.assertContains(detail, note.body)
        self.assertNotContains(inbox, note.title)

    def test_new_notes_page_creates_plain_title_and_text_note(self):
        response = self.client.post("/", {
            "action": "create_note",
            "title": "Название",
            "body": "Текст заметки",
            "project": self.project.pk,
        })

        note = TodoItem.objects.get(owner=self.user, title="Название")
        self.assertEqual(note.body, "Текст заметки")
        self.assertFalse(note.is_encrypted)
        self.assertEqual(response.status_code, 302)

    def test_encrypted_note_never_stores_plaintext_and_requires_password(self):
        response = self.client.post("/", {
            "action": "create_note",
            "title": "Секрет",
            "body": "Очень секретный текст",
            "password": "strong-password",
            "password_confirm": "strong-password",
        })

        note = TodoItem.objects.get(owner=self.user, title="Секрет")
        self.assertTrue(note.is_encrypted)
        self.assertEqual(note.body, "")
        self.assertNotIn("Очень секретный текст", note.encrypted_body)
        locked = self.client.get(f"/?note={note.pk}")
        self.assertNotContains(locked, "Очень секретный текст")
        wrong = self.client.post("/", {"action": "unlock_note", "item": note.pk, "password": "wrong"})
        self.assertContains(wrong, "Неверный пароль")
        unlocked = self.client.post("/", {
            "action": "unlock_note",
            "item": note.pk,
            "password": "strong-password",
        })
        self.assertContains(unlocked, "Очень секретный текст")

    def test_note_encryption_detects_wrong_password_and_tampering(self):
        payload = encrypt_note("Защищённый текст", "password")

        self.assertEqual(decrypt_note(payload, "password"), "Защищённый текст")
        with self.assertRaises(NoteDecryptionError):
            decrypt_note(payload, "wrong")
        replacement = "A" if payload[-2] != "A" else "B"
        with self.assertRaises(NoteDecryptionError):
            decrypt_note(payload[:-2] + replacement + payload[-1], "password")


class TextDocumentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reader", password="test")
        self.client.force_login(self.user)

    def test_text_document_upload_is_rendered_as_readable_page(self):
        upload = SimpleUploadedFile(
            "story.txt",
            "Первая строка.\n\nВторая глава.".encode("utf-8"),
            content_type="text/plain",
        )

        response = self.client.post("/documents/", {"title": "Рассказ", "document": upload})

        document = TextDocument.objects.get(owner=self.user)
        self.assertRedirects(response, document.get_absolute_url())
        detail = self.client.get(document.get_absolute_url())
        self.assertContains(detail, "Рассказ")
        self.assertContains(detail, "Первая строка.")
        self.assertContains(detail, "Вторая глава.")

    def test_cp1251_document_is_converted_to_text(self):
        upload = SimpleUploadedFile(
            "russian.txt",
            "Привет из документа".encode("cp1251"),
            content_type="text/plain",
        )

        self.client.post("/documents/", {"document": upload})

        self.assertEqual(TextDocument.objects.get().content, "Привет из документа")

    def test_fb2_document_is_converted_to_text(self):
        upload = SimpleUploadedFile(
            "book.fb2",
            (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
                "<body><section><title><p>Глава первая</p></title><p>Текст книги.</p></section></body>"
                "</FictionBook>"
            ).encode("utf-8"),
        )

        self.client.post("/documents/", {"document": upload})

        self.assertIn("Текст книги.", TextDocument.objects.get().content)

    def test_office_and_ebook_archives_are_converted_to_text(self):
        samples = [
            (
                "chapter.docx",
                self.archive_file(
                    "word/document.xml",
                    (
                        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        "<w:body><w:p><w:r><w:t>Текст DOCX</w:t></w:r></w:p></w:body></w:document>"
                    ).encode("utf-8"),
                ),
                "Текст DOCX",
            ),
            (
                "chapter.odt",
                self.archive_file(
                    "content.xml",
                    (
                        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
                        "<office:body><office:text><text:p>Текст ODT</text:p></office:text></office:body>"
                        "</office:document-content>"
                    ).encode("utf-8"),
                ),
                "Текст ODT",
            ),
            (
                "chapter.epub",
                self.archive_file(
                    "OEBPS/chapter.xhtml",
                    b"<html><body><h1>EPUB</h1><p>Text from EPUB</p></body></html>",
                ),
                "Text from EPUB",
            ),
        ]

        for filename, payload, expected in samples:
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/documents/",
                    {"document": SimpleUploadedFile(filename, payload)},
                )
                self.assertEqual(response.status_code, 302)
                self.assertIn(expected, TextDocument.objects.latest("pk").content)

    def test_pdf_with_text_layer_is_converted_to_text(self):
        upload = SimpleUploadedFile("page.pdf", self.pdf_with_text("Readable PDF text"))

        self.client.post("/documents/", {"document": upload})

        self.assertIn("Readable PDF text", TextDocument.objects.get().content)

    def test_legacy_word_document_has_conversion_hint(self):
        response = self.client.post(
            "/documents/",
            {"document": SimpleUploadedFile("old.doc", b"legacy word bytes")},
        )

        self.assertContains(response, "сохраните файл как .docx")
        self.assertFalse(TextDocument.objects.exists())

    def test_documents_require_login_and_are_private(self):
        document = TextDocument.objects.create(
            owner=self.user,
            title="Личное",
            original_filename="private.txt",
            content="Содержимое",
        )
        stranger = get_user_model().objects.create_user("stranger", password="test")
        other_client = Client()
        other_client.force_login(stranger)

        self.assertEqual(Client().get("/documents/").status_code, 302)
        self.assertEqual(other_client.get(document.get_absolute_url()).status_code, 404)

    @staticmethod
    def archive_file(name, content):
        stream = BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr(name, content)
        return stream.getvalue()

    @staticmethod
    def pdf_with_text(text):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for number, item in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{number} 0 obj\n".encode("ascii") + item + b"\nendobj\n")
        xref = len(pdf)
        pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
        )
        return bytes(pdf)
