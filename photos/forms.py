from pathlib import Path

from django import forms

from .document_readers import DocumentReadError, SUPPORTED_EXTENSIONS, extract_document_text
from .models import Character, TextDocument, Title


class TitleForm(forms.ModelForm):
    class Meta:
        model = Title
        fields = ["name", "kind", "is_adult", "original_name", "description", "poster_path", "gallery_folder"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
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
            "gender",
            "role",
            "race",
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
            "role": forms.TextInput(attrs={"placeholder": "Главная героиня, антагонист…"}),
            "race": forms.TextInput(attrs={"placeholder": "Человек, вампир, демон…"}),
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
