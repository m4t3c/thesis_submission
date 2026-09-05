"""Form dell'applicazione: caricamento della tesi e creazione di un appello.

Qui vive la validazione che il modello non puo' esprimere da solo: i controlli
sul contenuto dei file caricati e le regole valide solo per l'utente finale
(campi obbligatori nel form ma facoltativi nel database, perche' le righe gia'
esistenti e quelle create dall'import automatico non li hanno).
"""
from django import forms
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat

from thesis_submission.assign_user import GRUPPO_DOCENTE, GRUPPO_STUDENTE

from .models import (
    FORMATI_VIDEO,
    AppelloDiLaurea,
    Commissione,
    StudenteAppelloDiLaurea,
)

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
        """Modalita' video corrispondente a com'e' l'iscrizione adesso.

        Serve due volte: per preselezionare il radio all'apertura della pagina
        e, in ``clean()``, come valore di riserva quando la scelta non arriva
        (richiesta manomessa o campo assente).
        """
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
        """Fa rispettare il limite di dimensione del video.

        E' il controllo che conta davvero: quello lato browser avvisa prima di
        iniziare il caricamento, ma si aggira disattivando il JavaScript.
        """
        file = self.cleaned_data.get("file_video")
        # Come per la tesi: senza una nuova scelta Django restituisce il file
        # gia' presente, che non va rivalidato.
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


class DocentiField(forms.ModelMultipleChoiceField):
    """Docenti scelti tramite ricerca, non da un elenco a tendina.

    Il widget e' MultipleHiddenInput: la pagina NON stampa un <option> per
    ogni docente. Con qualche migliaio di utenti quell'elenco renderebbe la
    pagina pesantissima e la scelta impraticabile; la selezione avviene invece
    interrogando l'endpoint di ricerca (appelli:cerca_docenti), che restituisce
    al massimo dieci risultati per volta.

    La validazione resta quella normale di Django: gli id ricevuti vengono
    verificati contro il queryset, quindi non si puo' far passare un utente
    che non e' un docente manomettendo il form.
    """

    widget = forms.MultipleHiddenInput

    def label_from_instance(self, utente):
        """Etichetta di un docente: nome e cognome, con il nome utente a fianco.

        Il nome utente compare sempre perche' due docenti possono chiamarsi
        allo stesso modo, ed e' l'unico dato che li distingue con certezza.
        """
        completo = utente.get_full_name()
        if not completo:
            return utente.get_username()
        return f"{completo} ({utente.get_username()})"


class AppelloForm(forms.ModelForm):
    """Creazione di un appello da parte del presidente.

    Il presidente sceglie data, orario e i docenti che compongono la
    commissione; la Commissione vera e propria non si seleziona da un elenco ma
    viene ricavata da quei docenti (riusata se ne esiste gia' una con
    esattamente le stesse persone, creata altrimenti). Cosi' chi crea
    l'appello ragiona in termini di persone, che e' come funziona davvero, e
    non deve prima censire delle commissioni.

    NOTA: "corso_di_laurea" e' per ora inserito a mano. Quando arrivera'
    l'importazione da xlsx sara' quel file a fornirlo, e il campo potra'
    sparire da questo form senza toccare il resto.
    """

    docenti = DocentiField(
        queryset=User.objects.none(),          # popolato in __init__
        label="Membri della commissione",
        help_text="Cerca i docenti per nome, cognome, nome utente o email.",
        error_messages={
            "required": "Seleziona almeno un membro della commissione.",
        },
    )

    studenti = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),          # popolato in __init__
        required=False,
        label="Studenti da iscrivere",
        widget=forms.MultipleHiddenInput,
    )

    class Meta:
        model = AppelloDiLaurea
        fields = ["corso_di_laurea", "data", "ora"]
        widgets = {
            "corso_di_laurea": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Es. Ingegneria Informatica"}
            ),
            "data": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}, format="%Y-%m-%d"
            ),
            "ora": forms.TimeInput(
                attrs={"class": "form-control", "type": "time"}, format="%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["docenti"].queryset = (
            User.objects.filter(groups__name=GRUPPO_DOCENTE)
            .order_by("last_name", "first_name", "username")
            .distinct()
        )
        self.fields["studenti"].queryset = User.objects.filter(
            groups__name=GRUPPO_STUDENTE
        ).distinct()
        # L'orario e' facoltativo nel modello, ma un appello creato qui ha
        # senso che ce l'abbia: si chiede sempre.
        self.fields["ora"].required = True

    def docenti_selezionati(self):
        """Docenti attualmente scelti, come dati pronti per il template.

        Serve a ridisegnare le persone gia' selezionate quando il form torna
        indietro con un errore: gli input nascosti contengono solo gli id, e
        senza questi dati l'utente vedrebbe la selezione svuotarsi.
        """
        if not self.is_bound:
            valori = self.initial.get("docenti") or []
        else:
            valori = self.data.getlist(self.add_prefix("docenti"))
        if not valori:
            return []
        ids = [v.pk if hasattr(v, "pk") else v for v in valori]
        return [
            {
                "id": u.pk,
                "nome": u.first_name,
                "cognome": u.last_name,
                "username": u.get_username(),
                "email": u.email,
            }
            for u in self.fields["docenti"].queryset.filter(pk__in=ids)
        ]

    def studenti_selezionati(self):
        """Studenti attualmente in elenco, come dati pronti per il template."""
        if not self.is_bound:
            valori = self.initial.get("studenti") or []
        else:
            valori = self.data.getlist(self.add_prefix("studenti"))
        if not valori:
            return []
        ids = [v.pk if hasattr(v, "pk") else v for v in valori]
        return [
            {
                "id": u.pk,
                "nome": u.first_name,
                "cognome": u.last_name,
                "username": u.get_username(),
                "email": u.email,
            }
            for u in self.fields["studenti"].queryset.filter(pk__in=ids)
        ]

    def clean(self):
        """Verifica che l'appello non esista gia'.

        La commissione va identificata qui e non solo in save() perche'
        partecipa al vincolo di unicita' (data + corso + commissione): senza
        questo controllo il duplicato emergerebbe come IntegrityError al
        salvataggio, cioe' come errore 500 invece che come messaggio.
        """
        dati = super().clean()
        docenti = dati.get("docenti")
        if not docenti:
            return dati

        # Solo una LETTURA: se la commissione non esiste ancora viene creata in
        # save(), altrimenti una validazione fallita lascerebbe in giro
        # commissioni mai usate da nessun appello.
        self.commissione = commissione_esistente_con(docenti)

        if self.commissione and dati.get("data") and dati.get("corso_di_laurea"):
            duplicato = (
                AppelloDiLaurea.objects.filter(
                    data=dati["data"],
                    corso_di_laurea=dati["corso_di_laurea"],
                    commissione=self.commissione,
                )
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if duplicato:
                raise forms.ValidationError(
                    "Esiste già un appello per questo corso, in questa data e "
                    "con questa stessa commissione."
                )
        return dati

    def save(self, commit=True):
        """Crea la commissione se serve, poi salva l'appello.

        Il form non e' utilizzabile con commit=False: l'appello ha bisogno di
        una commissione gia' salvata per poterla referenziare.
        """
        if not commit:
            raise ValueError(
                "AppelloForm richiede commit=True: la commissione va salvata "
                "prima dell'appello che la referenzia."
            )

        docenti = self.cleaned_data["docenti"]
        commissione = getattr(self, "commissione", None)
        if commissione is None:
            # Nessun nome: la commissione si identifica con il proprio id.
            commissione = Commissione.objects.create()
            commissione.docenti.set(docenti)

        self.instance.commissione = commissione
        appello = super().save(commit=True)

        # Iscrizioni prese dall'elenco xlsx. get_or_create e non create: se il
        # form viene reinviato (doppio click, ricarica) non deve fallire sul
        # vincolo di unicita' studente+appello.
        for studente in self.cleaned_data.get("studenti") or []:
            StudenteAppelloDiLaurea.objects.get_or_create(
                studente=studente, appello=appello
            )
        return appello


def commissione_esistente_con(docenti):
    """Commissione composta esattamente da questi docenti, se gia' esiste.

    Riusarla evita di riempire il database di commissioni identiche ogni volta
    che il presidente ripete gli stessi nomi. Restituisce None se non c'e'.
    """
    voluti = {d.pk for d in docenti}
    for commissione in Commissione.objects.prefetch_related("docenti"):
        if {d.pk for d in commissione.docenti.all()} == voluti:
            return commissione
    return None

