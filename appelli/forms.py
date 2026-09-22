"""Form dell'applicazione: caricamento della tesi e creazione di un appello.

Qui vive la validazione che il modello non puo' esprimere da solo: i controlli
sul contenuto dei file caricati e le regole valide solo per l'utente finale
(campi obbligatori nel form ma facoltativi nel database, perche' le righe gia'
esistenti e quelle create dall'import automatico non li hanno).
"""
from datetime import date

from django import forms
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.template.defaultfilters import filesizeformat

from thesis_submission.assign_user import GRUPPO_DOCENTE, GRUPPO_STUDENTE

from .models import (
    FORMATI_VIDEO,
    PUNTEGGIO_MAX,
    PUNTEGGIO_MIN,
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


def etichetta_persona(utente):
    """Nome e cognome, con il nome utente a fianco.

    Il nome utente compare sempre perche' due persone possono chiamarsi allo
    stesso modo, ed e' l'unico dato che le distingue con certezza.
    """
    completo = utente.get_full_name()
    if not completo:
        return utente.get_username()
    return f"{completo} ({utente.get_username()})"


def dati_utente(utente):
    """Utente ridotto ai campi che servono alle ricerche (JSON e template).

    E' la stessa forma restituita dall'endpoint di ricerca: cosi' il codice che
    disegna una persona scelta e' uno solo, sia che i dati arrivino da una
    ricerca sia che siano gia' presenti all'apertura della pagina.

    "etichetta" e' gia' pronta da stampare: senza, ogni template e ogni
    funzione JavaScript rifarebbe per conto proprio la stessa composizione di
    nome, cognome e nome utente.
    """
    return {
        "id": utente.pk,
        "nome": utente.first_name,
        "cognome": utente.last_name,
        "username": utente.get_username(),
        "email": utente.email,
        "etichetta": etichetta_persona(utente),
    }


class TutorField(forms.ModelChoiceField):
    """Il tutor si sceglie con la ricerca, non da un elenco a tendina.

    Stessa ragione di DocentiField (vedi sotto), con una sola differenza: qui
    il docente e' uno solo, quindi l'input nascosto e' singolo. La validazione
    resta quella di Django, che verifica l'id ricevuto contro il queryset:
    manomettendo il form non si puo' indicare come tutor qualcuno che docente
    non e'.
    """

    widget = forms.HiddenInput

    def label_from_instance(self, utente):
        return etichetta_persona(utente)


class TesiUploadForm(forms.ModelForm):
    """Form per titolo, file della tesi ed eventuale video.

    Scelte importanti:

    1. widget ``FileInput`` invece di ``ClearableFileInput`` sulla tesi:
       quest'ultimo genera la checkbox "Svuota" e, se ricevuta, azzera il
       campo. Con ``FileInput`` la richiesta di svuotamento non viene proprio
       letta, quindi la tesi si puo' solo sostituire, mai rimuovere.
    2. tesi e titolo vanno A COPPIA: o ci sono tutti e due, o nessuno (vedi
       clean). Cosi' si puo' salvare la sola scelta del tutor e completare il
       resto piu' avanti. Una volta salvati pero' non si cancellano: la tesi
       si puo' solo sostituire (punto 1), il titolo solo correggere.
    3. il video e' invece facoltativo E rimovibile: essendo un'aggiunta
       opzionale, impedirne la rimozione renderebbe permanente un errore.
    4. il tutor e' obbligatorio ma si sceglie UNA VOLTA SOLA: quando c'e' gia',
       il campo viene disabilitato (vedi __init__), quindi non e' modificabile
       nemmeno manomettendo la richiesta.
    """

    tutor = TutorField(
        queryset=User.objects.none(),          # popolato in __init__
        label="Tutor",
        help_text="Cerca il docente per nome, cognome, nome utente o email.",
        error_messages={
            "required": "Scegli il docente che ti farà da tutor.",
            "invalid_choice": "Il docente scelto non è valido.",
        },
    )

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
        fields = ["titolo", "tutor", "file_tesi", "file_video", "link_video"]
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
        # Facoltativi uno per uno: l'obbligo e' di coppia, e lo applica clean().
        self.fields["file_tesi"].required = False
        self.fields["titolo"].required = False
        # Letto prima della validazione, per la stessa ragione del tutor qui
        # sotto: dopo, l'istanza porterebbe il titolo appena inviato.
        self.titolo_iniziale = self.instance.titolo if self.instance.pk else ""
        self.fields["tutor"].queryset = (
            User.objects.filter(groups__name=GRUPPO_DOCENTE)
            .order_by("last_name", "first_name", "username")
            .distinct()
        )

        # Si legge QUI, prima della validazione: su un POST rifiutato il
        # ModelForm copia comunque i dati inviati dentro l'istanza, quindi piu'
        # avanti "instance.tutor" sarebbe il docente appena scelto e non quello
        # gia' salvato. Letto dopo, un primo invio andato male mostrerebbe la
        # scelta come definitiva pur non essendo mai stata salvata.
        self.tutor_bloccato = bool(self.instance.pk and self.instance.tutor_id)
        self.tutor_iniziale = self.instance.tutor if self.tutor_bloccato else None
        # disabled non e' un accorgimento grafico: Django ignora il valore
        # ricevuto e riusa quello iniziale, quindi il tutor gia' scelto non si
        # puo' cambiare nemmeno inviando un altro id a mano.
        if self.tutor_bloccato:
            self.fields["tutor"].disabled = True

        # Il radio parte gia' sulla modalita' in uso dall'iscrizione.
        if not self.is_bound:
            self.fields["modalita_video"].initial = self.modalita_iniziale()

    def tutor_selezionato(self):
        """Tutor attualmente scelto, come dati pronti per il template (o None).

        Serve a ridisegnare la persona scelta quando il form torna indietro con
        un errore: l'input nascosto contiene solo l'id, e senza questi dati la
        selezione sembrerebbe essersi svuotata.
        """
        if self.tutor_bloccato:
            return dati_utente(self.tutor_iniziale)
        if self.is_bound:
            valore = self.data.get(self.add_prefix("tutor"))
            # isdigit: un id non numerico farebbe fallire filter(pk=...) con un
            # ValueError invece di risolversi in "nessuna selezione".
            if valore and str(valore).isdigit():
                utente = self.fields["tutor"].queryset.filter(pk=valore).first()
                if utente:
                    return dati_utente(utente)
        return None

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
        """Titolo senza spazi ai bordi; se era gia' salvato, mai vuoto.

        Uno spazio non e' un titolo: normalizzando qui si evita che il
        controllo di coppia in clean() si aggiri con un carattere vuoto.
        Il riferimento e' titolo_iniziale, fissato in __init__.
        """
        titolo = (self.cleaned_data.get("titolo") or "").strip()
        if not titolo and self.titolo_iniziale:
            raise forms.ValidationError(
                "Il titolo della tesi non può essere svuotato."
            )
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
        """Titolo e tesi a coppia; modalita' del video.

        La coppia si giudica sull'iscrizione COME RISULTERA' dopo il
        salvataggio, non sul solo invio: senza un nuovo file Django restituisce
        quello gia' salvato, quindi correggere il titolo di una tesi gia'
        caricata non chiede di ricaricarla. Se uno dei due campi ha gia' un
        errore suo (file non PDF, titolo svuotato) non se ne aggiunge un
        secondo sulla coppia.

        Sul video, il vincolo "mai file e link insieme" e' garantito anche dal
        database (CheckConstraint), ma qui si traduce in un messaggio
        comprensibile invece che in un IntegrityError.
        """
        dati = super().clean()

        if "titolo" in dati and "file_tesi" in dati:
            ha_titolo = bool(dati["titolo"])
            ha_tesi = bool(dati["file_tesi"])
            if ha_tesi and not ha_titolo:
                self.add_error(
                    "titolo", "Hai caricato la tesi: indica anche il titolo."
                )
            elif ha_titolo and not ha_tesi:
                self.add_error(
                    "file_tesi",
                    "Hai indicato il titolo: carica anche il file della tesi.",
                )

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
        return etichetta_persona(utente)


class AppelloForm(forms.ModelForm):
    """Creazione di un appello da parte del presidente.

    Il presidente sceglie data, orario e i docenti che compongono la
    commissione; la Commissione vera e propria non si seleziona da un elenco ma
    viene ricavata da quei docenti (riusata se ne esiste gia' una con
    esattamente le stesse persone, creata altrimenti). Cosi' chi crea
    l'appello ragiona in termini di persone, che e' come funziona davvero, e
    non deve prima censire delle commissioni.

    NOTA: "corso_di_laurea" lo fornisce il file xlsx (vedi analizza_xlsx in
    views.py), che lo scrive nel campo insieme all'elenco degli studenti. Il
    campo resta pero' modificabile: l'elenco puo' riportare una dicitura
    diversa da quella con cui l'appello va pubblicato.
    """

    docenti = DocentiField(
        queryset=User.objects.none(),          # popolato in __init__
        label="Membri della commissione",
        help_text="Cerca i docenti per nome, cognome, nome utente o email.",
        error_messages={
            "required": "Seleziona almeno un membro della commissione.",
        },
    )

    # Obbligatori: un appello senza laureandi non ha ragione di esistere, e
    # crearlo vuoto significherebbe accorgersene solo piu' tardi, quando la
    # pagina del presidente mostra un appello che non serve a nessuno.
    studenti = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),          # popolato in __init__
        label="Studenti da iscrivere",
        widget=forms.MultipleHiddenInput,
        error_messages={
            "required": "Carica l'elenco dei laureandi: un appello senza "
                        "studenti da iscrivere non può essere creato.",
        },
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
        # Il calendario del browser non propone le date passate. Va calcolato
        # qui e non nella definizione del widget: li' verrebbe valutato una
        # volta sola all'avvio, e dal giorno dopo il limite sarebbe vecchio.
        self.fields["data"].widget.attrs["min"] = date.today().isoformat()

    def clean_data(self):
        """Nessun appello nel passato.

        L'attributo "min" del campo e' solo un suggerimento al browser: chi
        invia la richiesta a mano non lo incontra nemmeno, quindi la regola va
        ripetuta qui, dove non si puo' aggirare.
        """
        data = self.cleaned_data["data"]
        if data < date.today():
            raise forms.ValidationError(
                "La data dell'appello non può essere nel passato."
            )
        return data

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
        # Nei dati inviati ci sono solo id (stringhe), ma "initial" puo' essere
        # stato passato da codice con gli User stessi: si accettano entrambi.
        ids = [v.pk if hasattr(v, "pk") else v for v in valori]
        return [
            dati_utente(u)
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
            dati_utente(u)
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

    Il confronto avviene in Python e non in SQL: "esattamente questi docenti"
    e' un'uguaglianza fra insiemi, che con l'ORM richiederebbe di combinare un
    conteggio dei membri con un filtro per ciascun docente, molto meno
    leggibile. Il costo e' lineare nel numero di commissioni: trascurabile
    finche' restano poche, da spostare nel database se diventassero migliaia.
    """
    voluti = {d.pk for d in docenti}
    for commissione in Commissione.objects.prefetch_related("docenti"):
        if {d.pk for d in commissione.docenti.all()} == voluti:
            return commissione
    return None


class ValutazioneForm(forms.ModelForm):
    """Titolo, punti e giudizio, compilati dal TUTOR dei propri studenti.

    Punteggio e giudizio sono materiale interno ai docenti: non esiste nessun
    form dell'area studente che li contenga, quindi lo studente non puo'
    toccarli nemmeno inviando una richiesta costruita a mano.

    Sul titolo vale la stessa regola del form dello studente: si puo' sempre
    correggere, mai svuotare. Qui pero' e' ammesso lasciarlo vuoto se vuoto
    era gia', altrimenti il tutor non potrebbe registrare una valutazione
    per uno studente che il titolo non l'ha ancora messo.
    """

    # I punti sono tre valori, non un numero qualsiasi: si scelgono con tre
    # pulsanti affiancati invece che digitandoli. Il campo va dichiarato qui
    # perche' quello dedotto dal modello sarebbe un IntegerField, che non ha
    # le scelte da cui i pulsanti nascono.
    #
    # Facoltativo di per se': si puo' salvare il solo titolo senza valutare.
    # Diventa obbligatorio quando c'e' il giudizio, e viceversa: vedi clean().
    # empty_value=None fa si' che l'assenza arrivi al modello come NULL, cioe'
    # "non ancora valutato", e non come 0, che e' un punteggio valido.
    punteggio = forms.TypedChoiceField(
        choices=[(v, v) for v in range(PUNTEGGIO_MIN, PUNTEGGIO_MAX + 1)],
        coerce=int,
        empty_value=None,
        required=False,
        label="Punteggio",
        help_text="punti da aggiungere al voto",
        widget=forms.RadioSelect(
            # btn-check e' la casella di spunta "invisibile" di Bootstrap: si
            # vede solo l'etichetta che le sta accanto, resa come pulsante.
            # autocomplete="off" evita che il browser, tornando indietro,
            # ripristini una scelta diversa da quella mostrata dalla pagina.
            attrs={"class": "btn-check", "autocomplete": "off"}
        ),
    )

    class Meta:
        model = StudenteAppelloDiLaurea
        fields = ["titolo", "punteggio", "giudizio"]
        widgets = {
            "titolo": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Titolo della tesi"}
            ),
            "giudizio": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Note per la commissione...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Letto prima della validazione: dopo, _post_clean avrebbe gia' copiato
        # nell'istanza il titolo appena inviato.
        self.titolo_iniziale = self.instance.titolo if self.instance.pk else ""

    def clean(self):
        """Punteggio e giudizio: o tutti e due, o nessuno dei due.

        Il numero dice quanto vale la tesi, il giudizio dice perche': mezza
        valutazione lascerebbe la commissione con un voto senza motivo, o con
        un commento che non si sa dove collochi lo studente. Restano pero'
        entrambi facoltativi finche' sono vuoti tutti e due, perche' il
        tutor deve poter correggere il solo titolo di uno studente che non
        ha ancora valutato.
        """
        dati = super().clean()
        punteggio = dati.get("punteggio")
        giudizio = (dati.get("giudizio") or "").strip()

        if punteggio is not None and not giudizio:
            self.add_error(
                "giudizio",
                "Hai scelto un punteggio: scrivi anche il giudizio che lo motiva.",
            )
        elif punteggio is None and giudizio:
            self.add_error(
                "punteggio",
                "Hai scritto un giudizio: scegli anche il punteggio da proporre.",
            )
        return dati

    def clean_titolo(self):
        """Il titolo si puo' correggere ma non svuotare, se prima c'era.

        Il riferimento e' titolo_iniziale, fissato in __init__ (vedi li' il
        perche'), non il valore corrente dell'istanza.
        """
        titolo = (self.cleaned_data.get("titolo") or "").strip()
        if not titolo and self.titolo_iniziale:
            raise forms.ValidationError(
                "Il titolo non puo' essere vuoto."
            )
        return titolo
