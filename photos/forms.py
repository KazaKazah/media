from django import forms

from .models import Character, Title


class TitleForm(forms.ModelForm):
    class Meta:
        model = Title
        fields = ["name", "kind", "original_name", "description", "poster_path", "gallery_folder"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class CharacterForm(forms.ModelForm):
    class Meta:
        model = Character
        fields = [
            "name",
            "gender",
            "role",
            "race",
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
