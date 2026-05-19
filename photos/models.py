from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Title(models.Model):
    class Kind(models.TextChoices):
        ANIME = "anime", "Аниме"
        MANGA = "manga", "Манга"
        OTHER = "other", "Другое"

    name = models.CharField("Название", max_length=220)
    slug = models.SlugField("URL", max_length=240, unique=True, blank=True)
    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.ANIME)
    original_name = models.CharField("Оригинальное название", max_length=220, blank=True)
    description = models.TextField("Описание", blank=True)
    poster_path = models.CharField("Путь к постеру в медиатеке", max_length=500, blank=True)
    gallery_folder = models.CharField("Папка галереи тайтла", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
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


class Character(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Женский"
        MALE = "male", "Мужской"
        OTHER = "other", "Другое"

    title = models.ForeignKey(Title, on_delete=models.CASCADE, related_name="characters")
    name = models.CharField("Имя", max_length=220)
    slug = models.SlugField("URL", max_length=240, blank=True)
    gender = models.CharField("Пол", max_length=20, choices=Gender.choices, default=Gender.FEMALE)
    role = models.CharField("Роль", max_length=120, blank=True)
    race = models.CharField("Раса", max_length=160, blank=True)
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
            kwargs={"title_slug": self.title.slug, "character_slug": self.slug},
        )
