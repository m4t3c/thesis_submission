from django import forms
from django.core.files.uploadedfile import UploadedFile

from .models import StudenteAppelloDiLaurea

# Primi byte di ogni file PDF valido ("%PDF-"): serve a scartare i file
# rinominati in .pdf che PDF non sono.
FIRMA_PDF = b"%PDF-"


class TesiUploadForm(forms.ModelForm):
    """Form per il caricamento (o la sostituzione) del file della tesi.

    Due scelte importanti:

    1. widget ``FileInput`` invece di ``ClearableFileInput``: quest'ultimo
       genera la checkbox "Svuota" e, se ricevuta, azzera il campo. Usando
       ``FileInput`` la richiesta di svuotamento non viene proprio letta,
       quindi il file caricato non e' piu' rimovibile: si puo' solo sostituire.
    2. campo obbligatorio: il campo del modello e' ``blank=True`` (una
       iscrizione puo' esistere senza tesi), ma in questo form un file va
       sempre scelto. Cosi' un invio a vuoto non puo' essere usato per
       cancellare il file, e se non c'e' ancora nessuna tesi l'utente riceve
       un errore chiaro invece di un salvataggio che non fa nulla.
    """

    class Meta:
        model = StudenteAppelloDiLaurea
        fields = ["file_tesi"]
        widgets = {
            "file_tesi": forms.FileInput(
                attrs={
                    "class": "form-control upload-input",
                    # Filtra la finestra di scelta file del browser (comodita',
                    # non un controllo: la verifica vera e' in clean_file_tesi).
                    "accept": "application/pdf,.pdf",
                }
            ),
        }
        labels = {"file_tesi": "File della tesi (PDF)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file_tesi"].required = True

    def clean_file_tesi(self):
        """Accetta solo PDF.

        L'estensione e' gia' controllata dal validatore sul modello; qui si
        aggiunge il controllo del tipo dichiarato dal browser e soprattutto
        quello dei primi byte del file, che e' l'unico non falsificabile
        rinominando il file.
        """
        file = self.cleaned_data["file_tesi"]

        # Se l'utente non ha scelto nulla, Django restituisce il file gia'
        # presente sull'iscrizione: non e' un caricamento, niente da validare.
        if not isinstance(file, UploadedFile):
            return file

        if file.content_type and file.content_type != "application/pdf":
            raise forms.ValidationError(
                "Il file deve essere in formato PDF."
            )

        inizio = file.read(len(FIRMA_PDF))
        file.seek(0)  # il file va riletto da capo al momento del salvataggio
        if inizio != FIRMA_PDF:
            raise forms.ValidationError(
                "Il file non sembra un PDF valido: controlla di aver scelto "
                "il file giusto."
            )

        return file
