from pathlib import Path

from django import forms

from .document_readers import DocumentReadError, SUPPORTED_EXTENSIONS, extract_document_text
from .models import Character, TextDocument, Title, UserProfile


class CommaSeparatedMultipleChoiceField(forms.MultipleChoiceField):
    def prepare_value(self, value):
        if isinstance(value, str):
            return [item for item in value.split(",") if item]
        return super().prepare_value(value)

    def clean(self, value):
        selected = super().clean(value)
        return ",".join(selected)


class TitleForm(forms.ModelForm):
    genres = CommaSeparatedMultipleChoiceField(
        label="Жанры",
        choices=Title.GENRE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    themes = CommaSeparatedMultipleChoiceField(
        label="Темы",
        choices=Title.THEME_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault("class", "title-check-list")
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_score(self):
        score = self.cleaned_data.get("score")
        if score is not None and not 0 <= score <= 10:
            raise forms.ValidationError("Оценка должна быть от 0 до 10.")
        return score

    def clean_year(self):
        year = self.cleaned_data.get("year")
        if year is not None and not 1900 <= year <= 2200:
            raise forms.ValidationError("Укажите год от 1900 до 2200.")
        return year

    class Meta:
        model = Title
        fields = [
            "name", "original_name", "kind", "format", "release_status",
            "year", "season", "episodes", "score", "age_rating", "audience",
            "genres", "themes", "is_adult", "description", "poster_path", "gallery_folder",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "year": forms.NumberInput(attrs={"min": 1900, "max": 2200}),
            "score": forms.NumberInput(attrs={"min": 0, "max": 10, "step": .1}),
            "episodes": forms.NumberInput(attrs={"min": 0}),
        }


class CharacterForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    class Meta:
        model = Character
        fields = [
            "name",
            "original_name",
            "gender",
            "importance",
            "role",
            "race",
            "faction",
            "height",
            "weight",
            "eye_color",
            "hair_color",
            "bust",
            "waist",
            "hips",
            "body",
            "features",
            "abilities",
            "notes",
            "portrait_path",
            "gallery_folder",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
            "features": forms.Textarea(attrs={"rows": 4}),
            "abilities": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


class CharacterCreateForm(CharacterForm):
    portrait_upload = forms.ImageField(
        label="Портрет",
        required=False,
        help_text="JPG, PNG или WEBP. Файл можно добавить позже.",
        widget=forms.FileInput(attrs={"accept": "image/*", "class": "form-control"}),
    )
    create_gallery = forms.BooleanField(
        label="Сразу создать папку галереи",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    class Meta(CharacterForm.Meta):
        fields = CharacterForm.Meta.fields
        widgets = {
            **CharacterForm.Meta.widgets,
            "name": forms.TextInput(attrs={
                "placeholder": "Например, Мока Акашия",
                "autocomplete": "off",
                "autofocus": True,
            }),
            "original_name": forms.TextInput(attrs={"placeholder": "Например, 赤夜 萌香 / Moka Akashiya"}),
            "role": forms.TextInput(attrs={"placeholder": "Главная героиня, антагонист…"}),
            "race": forms.TextInput(attrs={"placeholder": "Человек, вампир, демон…"}),
            "faction": forms.TextInput(attrs={"placeholder": "Например, Альянс, Империя, Нейтральные"}),
            "height": forms.TextInput(attrs={"placeholder": "Например, 168 см"}),
            "weight": forms.TextInput(attrs={"placeholder": "Например, 52 кг"}),
            "eye_color": forms.TextInput(attrs={"placeholder": "Например, зелёные"}),
            "hair_color": forms.TextInput(attrs={"placeholder": "Например, серебристые"}),
            "bust": forms.TextInput(attrs={"placeholder": "Например, 92 см"}),
            "waist": forms.TextInput(attrs={"placeholder": "Например, 58 см"}),
            "hips": forms.TextInput(attrs={"placeholder": "Например, 88 см"}),
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Телосложение и внешность"}),
            "features": forms.Textarea(attrs={"rows": 3, "placeholder": "Характер, привычки, отличительные черты"}),
            "abilities": forms.Textarea(attrs={"rows": 3, "placeholder": "Навыки и способности"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Любая дополнительная информация"}),
            "portrait_path": forms.TextInput(attrs={"placeholder": "Covers/Characters/…"}),
            "gallery_folder": forms.TextInput(attrs={"placeholder": "Оставьте пустым для автоматического пути"}),
        }


class CharacterFolderImportForm(forms.Form):
    source_folder = forms.CharField(
        label="Или путь уже существующей папки в медиатеке",
        max_length=1000,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Catalog/Название/Персонажи или ссылка из медиатеки",
            "autocomplete": "off",
        }),
        help_text="Необязательно: используйте, если фотографии уже находятся на сервере.",
    )
    gender = forms.ChoiceField(
        label="Пол для новых персонажей",
        choices=Character.Gender.choices,
        initial=Character.Gender.FEMALE,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    importance = forms.ChoiceField(
        label="Роль для новых персонажей",
        choices=Character.Importance.choices,
        initial=Character.Importance.SUPPORTING,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    faction = forms.CharField(
        label="Фракция для новых персонажей",
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Например, Альянс",
        }),
        help_text="Применится ко всем персонажам из выбранных папок.",
    )
    use_first_photo = forms.BooleanField(
        label="Использовать первое фото как портрет",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )


class TextDocumentUploadForm(forms.Form):
    MAX_SIZE = 20 * 1024 * 1024

    title = forms.CharField(label="Название", max_length=220, required=False)
    document = forms.FileField(
        label="Документ",
        widget=forms.FileInput(attrs={"accept": ",".join(sorted(SUPPORTED_EXTENSIONS))}),
    )

    def clean_document(self):
        document = self.cleaned_data["document"]
        extension = Path(document.name).suffix.lower()
        if extension == ".doc":
            raise forms.ValidationError("Старый формат .doc не поддерживается: сохраните файл как .docx.")
        if extension not in SUPPORTED_EXTENSIONS:
            formats = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise forms.ValidationError(f"Поддерживаемые форматы: {formats}.")
        if document.size > self.MAX_SIZE:
            raise forms.ValidationError("Размер документа не должен превышать 20 МБ.")

        payload = document.read()
        document.seek(0)
        try:
            self.text_content = extract_document_text(document.name, payload)
        except DocumentReadError as error:
            raise forms.ValidationError(str(error)) from error
        return document

    def save(self, owner):
        document = self.cleaned_data["document"]
        title = self.cleaned_data["title"].strip() or Path(document.name).stem
        return TextDocument.objects.create(
            owner=owner,
            title=title,
            original_filename=Path(document.name).name,
            content=self.text_content,
        )


class UserProfileForm(forms.ModelForm):
    avatar_upload = forms.ImageField(
        label="Новый аватар",
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*", "class": "form-control"}),
    )

    class Meta:
        model = UserProfile
        fields = ["display_name", "bio", "location", "website", "birth_date"]
        widgets = {
            "display_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Как к вам обращаться"}),
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 5, "placeholder": "Несколько слов о себе"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Например, Астана"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://…"}),
            "birth_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }
