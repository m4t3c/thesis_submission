from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import F

from .storage import SovrascriviStorage


# Ordine con cui gli appelli vanno sempre elencati: dal piu' vecchio, e a
# parita' di giorno prima quelli con un orario gia' fissato.
# ATTENZIONE: non basta metterlo in Meta.ordering. Quando una query usa
# annotate() con un'aggregazione, Django RIMUOVE l'ORDER BY di default per non
# interferire con il GROUP BY, e le righe tornano in ordine arbitrario: in quei
# casi va passato esplicitamente con .order_by(*ORDINE_APPELLI).
ORDINE_APPELLI = ["data", F("ora").asc(nulls_last=True)]


class Commissione(models.Model):
    """Commissione di laurea: insieme di docenti che valutano un appello.

    Relazione "partecipa" del diagramma ER: un docente partecipa a 0..n
    commissioni, una commissione e' composta da 1..n docenti (many-to-many).
    """

    nome = models.CharField(max_length=255, blank=True)
    docenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="commissioni",
        limit_choices_to={"groups__name": "docente"},
        help_text="Docenti che fanno parte della commissione.",
    )

    class Meta:
        verbose_name = "Commissione"
        verbose_name_plural = "Commissioni"

    def __str__(self):
        """Il solo identificativo numerico.

        Una commissione non ha un nome che significhi qualcosa per chi legge:
        e' semplicemente l'insieme di docenti associato a un appello. Cio' che
        interessa davvero sono le persone, mostrate nel dettaglio dell'appello;
        altrove non compare alcun riferimento alla commissione.
        """
        return str(self.pk)


class AppelloDiLaurea(models.Model):
    """Appello di laurea.

    Come da specifica si usa l'id di default di Django come identificativo.
    Relazione "Ha" del diagramma ER: ogni appello ha esattamente una
    commissione (1,1), mentre una commissione puo' essere associata a piu'
    appelli (1,n). Si preferisce creare piu' appelli piuttosto che un singolo
    appello con piu' commissioni.
    """

    data = models.DateField()
    # Orario di inizio della seduta. E' un TimeField e non un DateTimeField
    # perche' con USE_TZ attivo un datetime verrebbe convertito in UTC e
    # riletto come ora locale: qui serve semplicemente "l'appello e' alle 9:00",
    # senza fusi di mezzo. Facoltativo: gli appelli gia' inseriti non ce
    # l'hanno e puo' non essere ancora stato deciso.
    ora = models.TimeField(
        null=True,
        blank=True,
        verbose_name="Orario",
        help_text="Orario di inizio della seduta (facoltativo).",
    )
    corso_di_laurea = models.CharField(max_length=255)
    commissione = models.ForeignKey(
        Commissione,
        on_delete=models.PROTECT,
        related_name="appelli",
    )

    class Meta:
        verbose_name = "Appello di laurea"
        verbose_name_plural = "Appelli di laurea"
        # Ordine CRESCENTE: in ogni elenco (studenti, docenti, admin) il
        # primo appello e' il piu' vecchio. Stando nel Meta la regola vale
        # ovunque, anche nelle liste generate dai template come
        # "commissione.appelli.all", che non passano da nessuna view.
        # A parita' di giorno, chi ha gia' un orario precede chi non ce l'ha:
        # senza nulls_last i NULL finirebbero per primi.
        ordering = ORDINE_APPELLI
        # Nello stesso giorno e per lo stesso corso possono esserci piu'
        # appelli, purche' affidati a commissioni diverse: cio' che identifica
        # logicamente l'appello e' quindi la tripletta data + corso +
        # commissione. L'orario NON entra nel vincolo: la stessa commissione
        # che esamina lo stesso corso nello stesso giorno e' un unico appello,
        # anche se le sedute si svolgono in due fasce orarie.
        constraints = [
            models.UniqueConstraint(
                fields=["data", "corso_di_laurea", "commissione"],
                name="unique_appello_data_corso_commissione",
            )
        ]

    @property
    def etichetta_pubblica(self):
        """Descrizione dell'appello SENZA la commissione.

        Va usata ovunque il testo possa essere letto da uno studente (tabelle,
        messaggi, popup di conferma): la composizione della commissione non
        deve essere visibile ai candidati. Tenerla in un unico punto evita che
        la commissione ricompaia per distrazione in una pagina nuova.
        """
        quando = f"{self.data:%d/%m/%Y}"
        if self.ora:
            quando += f" alle {self.ora:%H:%M}"
        return f"{self.corso_di_laurea} - {quando}"

    def __str__(self):
        # Rappresentazione COMPLETA, usata dall'area amministrativa: senza il
        # riferimento alla commissione due appelli dello stesso giorno e corso
        # sarebbero indistinguibili nei menu a tendina. Nelle pagine
        # dell'applicazione non si usa: per gli studenti c'e'
        # etichetta_pubblica, per i docenti l'elenco dei membri.
        return f"{self.etichetta_pubblica} (commissione {self.commissione})"


# Estensioni video accettate per il caricamento diretto.
FORMATI_VIDEO = ["mp4", "mov", "m4v", "webm", "mkv", "avi"]


def _cartella_iscrizione(instance):
    return f"tesi/appello_{instance.appello_id}/studente_{instance.studente_id}"


def percorso_file_tesi(instance, filename):
    """Organizza i file caricati per appello e studente."""
    return f"{_cartella_iscrizione(instance)}/{filename}"


def percorso_file_video(instance, filename):
    """Il video va in una sottocartella propria.

    Serve a non mescolarlo con la tesi: SovrascriviStorage cancella un file
    omonimo prima di scrivere, e tenerli separati mantiene vera l'assunzione
    "una cartella, un solo file" su cui quel comportamento si regge.
    """
    return f"{_cartella_iscrizione(instance)}/video/{filename}"


class StudenteAppelloDiLaurea(models.Model):
    """Tabella ad hoc per la relazione "iscrizione" (Studente - Appello).

    Si usa una tabella esplicita invece della semplice ManyToMany di Django
    per poter memorizzare dati aggiuntivi, ad esempio la data di iscrizione.

    Gli allegati (tesi e video) sono per ora campi di questa tabella: sono
    pochi e con regole diverse fra loro, quindi una tabella "Allegato"
    dedicata aggiungerebbe join e complessita' senza vantaggi. Resta la
    strada da prendere se in futuro gli allegati diventeranno molti o di tipo
    variabile, e non richiederebbe di toccare le altre entita'.
    """

    studente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="iscrizioni",
        limit_choices_to={"groups__name": "studente"},
    )
    appello = models.ForeignKey(
        AppelloDiLaurea,
        on_delete=models.CASCADE,
        related_name="iscrizioni",
    )
    data_iscrizione = models.DateTimeField(auto_now_add=True)
    file_tesi = models.FileField(
        upload_to=percorso_file_tesi,
        # Senza questo storage, ricaricare la tesi con lo stesso nome del file
        # gia' presente produce un nome alterato (es. "tesi_a8Fk2Pq.pdf").
        storage=SovrascriviStorage(),
        blank=True,
        null=True,
        # L'unico formato ammesso e' il PDF. Il validatore controlla
        # l'estensione ed e' applicato ovunque si usi un ModelForm, quindi
        # vale anche per i caricamenti fatti dall'area amministrativa.
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
        help_text="File della tesi di laurea, in formato PDF.",
    )
    # blank=True perche' le iscrizioni gia' esistenti non hanno un titolo e
    # perche' l'import automatico dall'Excel creera' righe senza. Nel form
    # dello studente e' invece obbligatorio: cosi' si puo' sempre cambiare ma
    # mai svuotare.
    titolo = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Titolo della tesi",
        help_text="Titolo della tesi di laurea.",
    )
    file_video = models.FileField(
        upload_to=percorso_file_video,
        storage=SovrascriviStorage(),
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=FORMATI_VIDEO)],
        verbose_name="File video",
        help_text="Video di presentazione (facoltativo).",
    )
    link_video = models.URLField(
        max_length=500,
        blank=True,
        verbose_name="Link al video",
        help_text="Indirizzo di un video gia' pubblicato online (facoltativo).",
    )

    class Meta:
        verbose_name = "Iscrizione"
        verbose_name_plural = "Iscrizioni"
        ordering = ["-data_iscrizione"]
        # Uno studente puo' iscriversi una sola volta allo stesso appello
        constraints = [
            models.UniqueConstraint(
                fields=["studente", "appello"],
                name="unique_iscrizione_studente_appello",
            ),
            # Il video si fornisce O caricando un file O indicando un link,
            # mai entrambi. Consentito che manchino tutti e due: e' facoltativo.
            models.CheckConstraint(
                condition=models.Q(file_video="") | models.Q(link_video=""),
                name="video_file_o_link_non_entrambi",
            ),
        ]

    @property
    def ha_video(self):
        return bool(self.file_video or self.link_video)

    def __str__(self):
        return f"{self.studente} -> {self.appello}"
