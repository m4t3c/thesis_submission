from django import forms

from .models import StudenteAppelloDiLaurea


class TesiUploadForm(forms.ModelForm):
    """Form per il caricamento (o l'aggiornamento) del file della tesi."""

    class Meta:
        model = StudenteAppelloDiLaurea
        fields = ["file_tesi"]
        widgets = {
            "file_tesi": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
