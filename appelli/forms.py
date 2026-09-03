from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat

from .models import FORMATI_VIDEO, StudenteAppelloDiLaurea

# Primi byte di ogni file PDF valido ("%PDF-"): serve a scartare i file
# rinominati in .pdf che PDF non sono.
FIRMA_PDF = b"%PDF-"

# Dimensione massima del video caricato. Un video non compresso riempie in
# fretta il volume delle tesi, quindi conviene un tetto esplicito: senza, il
# limite di fatto e' lo spazio libero sul disco del server.
MAX_BYTE_VIDEO = 500 * 1024 * 1024  # 500 MB

# Valori del gruppo di radio che sceglie come fornire il video.
VIDEO_NESSUNO = "nessuno"
VIDEO_FILE = "file"
VIDEO_LINK = "link"


class TesiUploadForm(forms.ModelForm):
    """Form per titolo, file della tesi ed eventuale video.

    Scelte importanti:

    1. widget ``FileInput`` invece di ``ClearableFileInput`` sulla tesi:
       quest'ultimo genera la checkbox "Svuota" e, se ricevuta, azzera il
       campo. Con ``FileInput`` la richiesta di svuotamento non viene proprio
       letta, quindi la tesi si puo' solo sostituire, mai rimuovere.
    2. tesi e titolo obbligatori nel form, benche' facoltativi nel modello
       (una iscrizione puo' esistere senza, e l'import automatico ne creera').
       Cosi' un invio a vuoto non puo' essere usato per cancellarli.
    3. il video e' invece facoltativo E rimovibile: essendo un'aggiunta
       opzionale, impedirne la rimozione renderebbe permanente un errore.
    """

    modalita_video = forms.ChoiceField(
        required=False,
        label="Video di presentazione (facoltativo)",
        choices=[
            (VIDEO_NESSUNO, "Nessun video"),
            (VIDEO_FILE, "Carica un file video"),
            (VIDEO_LINK, "Inserisci il link a un video"),
        ],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = StudenteAppelloDiLaurea
        fields = ["titolo", "file_tesi", "file_video", "link_video"]
        widgets = {
            "titolo": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Titolo della tesi",
                    "maxlength": 500,
                }
            ),
            "file_tesi": forms.FileInput(
                attrs={
                    "class": "form-control upload-input",
                    # Filtra la finestra di scelta file del browser (comodita',
                    # non un controllo: la verifica vera e' in clean_file_tesi).
                    "accept": "application/pdf,.pdf",
                }
            ),
            "file_video": forms.FileInput(
                attrs={
                    "class": "form-control upload-input",
                    "accept": "video/*," + ",".join(f".{e}" for e in FORMATI_VIDEO),
                    # Il limite viaggia con il campo, cosi' il controllo lato
                    # browser (che avvisa PRIMA di iniziare il caricamento) usa
                    # sempre lo stesso valore di clean_file_video e non una
                    # copia da tenere allineata a mano.
                    "data-max-byte": MAX_BYTE_VIDEO,
                }
            ),
            "link_video": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file_tesi"].required = True
        self.fields["titolo"].required = True
        # Il radio parte gia' sulla modalita' in uso dall'iscrizione.
        if not self.is_bound:
            self.fields["modalita_video"].initial = self.modalita_iniziale()

    def modalita_iniziale(self):
        if self.instance.pk and self.instance.file_video:
            return VIDEO_FILE
        if self.instance.pk and self.instance.link_video:
            return VIDEO_LINK
        return VIDEO_NESSUNO

    # --- Tesi -------------------------------------------------------------

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
            raise forms.ValidationError("Il file deve essere in formato PDF.")

        inizio = file.read(len(FIRMA_PDF))
        file.seek(0)  # il file va riletto da capo al momento del salvataggio
        if inizio != FIRMA_PDF:
            raise forms.ValidationError(
                "Il file non sembra un PDF valido: controlla di aver scelto "
                "il file giusto."
            )

        return file

    def clean_titolo(self):
        # Uno spazio non e' un titolo: normalizzando qui si evita che il
        # controllo di obbligatorieta' si aggiri con un carattere vuoto.
        titolo = (self.cleaned_data.get("titolo") or "").strip()
        if not titolo:
            raise forms.ValidationError("Il titolo della tesi è obbligatorio.")
        return titolo

    # --- Video ------------------------------------------------------------

    def clean_file_video(self):
        file = self.cleaned_data.get("file_video")
        if not isinstance(file, UploadedFile):
            return file

        if file.size > MAX_BYTE_VIDEO:
            raise forms.ValidationError(
                f"Il video supera la dimensione massima consentita "
                f"({filesizeformat(MAX_BYTE_VIDEO)}). Il file scelto ne occupa "
                f"{filesizeformat(file.size)}."
            )
        return file

    def clean(self):
        """Applica la modalita' scelta: video, link, o nessuno dei due.

        Il vincolo "mai entrambi" e' garantito anche dal database
        (CheckConstraint), ma qui si traduce in un messaggio comprensibile
        invece che in un IntegrityError.
        """
        dati = super().clean()
        modalita = dati.get("modalita_video") or self.modalita_iniziale()

        if modalita == VIDEO_FILE:
            # Il link va azzerato: le due modalita' si escludono.
            dati["link_video"] = ""
            if not dati.get("file_video"):
                self.add_error(
                    "file_video",
                    "Scegli il file video da caricare, oppure seleziona "
                    "un'altra opzione.",
                )
        elif modalita == VIDEO_LINK:
            dati["file_video"] = ""
            if not dati.get("link_video"):
                self.add_error(
                    "link_video",
                    "Inserisci il link al video, oppure seleziona un'altra "
                    "opzione.",
                )
        else:  # VIDEO_NESSUNO: si rimuove quel che c'era
            dati["file_video"] = ""
            dati["link_video"] = ""

        return dati
