from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Character, TextDocument, Title, TodoItem, TodoProject


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

    def test_gallery_upload_returns_to_character_profile(self):
        character = Character.objects.create(
            title=self.title,
            name="Акено",
            gallery_folder="Catalog/character-studio/female/akeno",
        )
        gallery = Path(self.temp_media.name) / character.gallery_folder
        gallery.mkdir(parents=True)
        photo = SimpleUploadedFile("new-photo.jpg", b"image", content_type="image/jpeg")

        response = self.client.post(
            f"{character.get_absolute_url()}gallery/upload/",
            {"photos": photo},
        )

        self.assertRedirects(
            response,
            f"{character.get_absolute_url()}?uploaded=1",
        )
        self.assertTrue((gallery / "new-photo.jpg").exists())


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
