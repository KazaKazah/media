from django.db import models
from django.conf import settings
from django.urls import reverse
from django.utils.text import slugify


class Title(models.Model):
    class Kind(models.TextChoices):
        ANIME = "anime", "Аниме"
        MANGA = "manga", "Манга"
        GAME = "game", "Игры"
        HENTAI = "hentai", "Хентай"
        MOVIE = "movie", "Кино"
        BOOK = "book", "Книги"
        OTHER = "other", "Другое"

    class Season(models.TextChoices):
        WINTER = "winter", "Зима"
        SPRING = "spring", "Весна"
        SUMMER = "summer", "Лето"
        AUTUMN = "autumn", "Осень"

    class ReleaseStatus(models.TextChoices):
        ANNOUNCED = "announced", "Анонсировано"
        ONGOING = "ongoing", "Выходит"
        COMPLETED = "completed", "Завершено"
        PAUSED = "paused", "Приостановлено"

    class Format(models.TextChoices):
        TV = "tv", "TV-сериал"
        MOVIE = "movie", "Фильм"
        OVA = "ova", "OVA"
        ONA = "ona", "ONA"
        SPECIAL = "special", "Спецвыпуск"
        SHORT = "short", "Короткометражное"
        MUSIC = "music", "Клип"
        OTHER = "other", "Другое"

    class AgeRating(models.TextChoices):
        G = "g", "G"
        PG = "pg", "PG"
        PG13 = "pg13", "PG-13"
        R17 = "r17", "R-17"
        RPLUS = "rplus", "R+"
        RX = "rx", "Rx"

    class Audience(models.TextChoices):
        SHOUNEN = "shounen", "Сёнен"
        SHOUJO = "shoujo", "Сёдзё"
        SEINEN = "seinen", "Сэйнэн"
        JOSEI = "josei", "Дзёсэй"
        KIDS = "kids", "Детское"

    GENRE_CHOICES = (
        ("action", "Экшен"), ("adventure", "Приключения"), ("comedy", "Комедия"),
        ("drama", "Драма"), ("fantasy", "Фэнтези"), ("romance", "Романтика"),
        ("sci-fi", "Фантастика"), ("slice-of-life", "Повседневность"),
        ("supernatural", "Сверхъестественное"), ("mystery", "Детектив"),
        ("horror", "Ужасы"), ("thriller", "Триллер"), ("sports", "Спорт"),
        ("ecchi", "Этти"), ("erotica", "Эротика"),
    )
    THEME_CHOICES = (
        ("school", "Школа"), ("isekai", "Исекай"), ("magic", "Магия"),
        ("vampires", "Вампиры"), ("demons", "Демоны"), ("military", "Военное"),
        ("historical", "Историческое"), ("space", "Космос"), ("music", "Музыка"),
        ("games", "Игры"), ("martial-arts", "Боевые искусства"),
        ("psychological", "Психологическое"), ("workplace", "Работа"),
        ("adult-cast", "Взрослые персонажи"),
    )

    name = models.CharField("Название", max_length=220)
    slug = models.SlugField("URL", max_length=240, unique=True, blank=True)
    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.ANIME)
    original_name = models.CharField("Оригинальное название", max_length=220, blank=True)
    description = models.TextField("Описание", blank=True)
    year = models.PositiveSmallIntegerField("Год выхода", null=True, blank=True)
    season = models.CharField("Сезон", max_length=12, choices=Season.choices, blank=True)
    release_status = models.CharField("Статус выхода", max_length=16, choices=ReleaseStatus.choices, blank=True)
    format = models.CharField("Формат", max_length=16, choices=Format.choices, blank=True)
    age_rating = models.CharField("Возрастной рейтинг", max_length=12, choices=AgeRating.choices, blank=True)
    audience = models.CharField("Аудитория", max_length=16, choices=Audience.choices, blank=True)
    genres = models.CharField("Жанры", max_length=500, blank=True)
    themes = models.CharField("Темы", max_length=500, blank=True)
    score = models.DecimalField("Оценка", max_digits=3, decimal_places=1, null=True, blank=True)
    episodes = models.PositiveSmallIntegerField("Количество эпизодов", null=True, blank=True)
    is_adult = models.BooleanField("18+", default=False)
    poster_path = models.CharField("Путь к постеру в медиатеке", max_length=500, blank=True)
    gallery_folder = models.CharField("Папка галереи тайтла", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.kind == self.Kind.HENTAI:
            self.is_adult = True
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or "title"
            slug = base
            counter = 1
            while Title.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("photos:title_detail", kwargs={"slug": self.slug})

    @property
    def genre_list(self):
        labels = dict(self.GENRE_CHOICES)
        return [labels.get(value, value) for value in self.genres.split(",") if value]

    @property
    def theme_list(self):
        labels = dict(self.THEME_CHOICES)
        return [labels.get(value, value) for value in self.themes.split(",") if value]


class Character(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Женский"
        MALE = "male", "Мужской"
        OTHER = "other", "Другое"

    class Importance(models.TextChoices):
        MAIN = "main", "Главный персонаж"
        SUPPORTING = "supporting", "Второстепенный персонаж"
        EPISODIC = "episodic", "Эпизодический персонаж"

    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="characters")
    name = models.CharField("Имя", max_length=220)
    original_name = models.CharField("Оригинальное имя", max_length=220, blank=True)
    slug = models.SlugField("URL", max_length=240, blank=True)
    gender = models.CharField("Пол", max_length=20, choices=Gender.choices, default=Gender.FEMALE)
    importance = models.CharField(
        "Роль в сюжете",
        max_length=20,
        choices=Importance.choices,
        default=Importance.SUPPORTING,
    )
    role = models.CharField("Роль", max_length=120, blank=True)
    race = models.CharField("Раса", max_length=160, blank=True)
    height = models.CharField("Рост", max_length=80, blank=True)
    weight = models.CharField("Вес", max_length=80, blank=True)
    eye_color = models.CharField("Цвет глаз", max_length=120, blank=True)
    hair_color = models.CharField("Цвет волос", max_length=120, blank=True)
    bust = models.CharField("Грудь", max_length=80, blank=True)
    waist = models.CharField("Талия", max_length=80, blank=True)
    hips = models.CharField("Бёдра", max_length=80, blank=True)
    body = models.TextField("Характеристики тела", blank=True)
    features = models.TextField("Особенности", blank=True)
    abilities = models.TextField("Способности", blank=True)
    notes = models.TextField("Дополнительная информация", blank=True)
    gallery_folder = models.CharField("Папка галереи персонажа", max_length=500, blank=True)
    portrait_path = models.CharField("Портрет в медиатеке", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["gender", "name"]
        unique_together = [("title", "slug")]

    def __str__(self):
        return f"{self.name} — {self.title.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True) or "character"
            slug = base
            counter = 1
            while Character.objects.filter(title=self.title, slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse(
            "photos:character_detail",
            kwargs={"character_id": self.pk, "character_slug": self.slug},
        )


class TodoProject(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_projects")
    name = models.CharField("Название", max_length=120)
    color = models.CharField("Цвет", max_length=24, default="#1f7a6d")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("owner", "name")]

    def __str__(self):
        return self.name


class TodoItem(models.Model):
    class Kind(models.TextChoices):
        TASK = "task", "Задача"
        REMINDER = "reminder", "Напоминание"
        NOTE = "note", "Заметка"
        RECORD = "record", "Запись"

    class Priority(models.TextChoices):
        LOW = "low", "Низкий"
        MEDIUM = "medium", "Средний"
        HIGH = "high", "Высокий"
        URGENT = "urgent", "Срочно"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_items")
    project = models.ForeignKey(TodoProject, on_delete=models.SET_NULL, null=True, blank=True, related_name="items")
    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.TASK)
    priority = models.CharField("Приоритет", max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    title = models.CharField("Заголовок", max_length=220)
    body = models.TextField("Текст", blank=True)
    tags = models.CharField("Метки", max_length=240, blank=True)
    due_at = models.DateTimeField("Дата и время", null=True, blank=True)
    is_done = models.BooleanField("Выполнено", default=False)
    is_pinned = models.BooleanField("Закреплено", default=False)
    completed_at = models.DateTimeField("Завершено", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["is_done", "-is_pinned", "due_at", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def tag_list(self):
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]


class TextDocument(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="text_documents")
    title = models.CharField("Название", max_length=220)
    original_filename = models.CharField("Имя файла", max_length=255)
    content = models.TextField("Текст")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("photos:document_detail", kwargs={"pk": self.pk})


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField("Отображаемое имя", max_length=120, blank=True)
    bio = models.TextField("О себе", blank=True)
    location = models.CharField("Город или страна", max_length=160, blank=True)
    website = models.URLField("Сайт", blank=True)
    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    avatar_path = models.CharField("Аватар в медиатеке", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.user.get_username()

    @property
    def public_name(self):
        return self.display_name or self.user.get_full_name() or self.user.get_username()
