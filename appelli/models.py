from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from .storage import SovrascriviStorage


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
        return self.nome or f"Commissione #{self.pk}"


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
        ordering = ["-data", "-ora"]
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
        # Rappresentazione COMPLETA, per admin e area docente: la commissione
        # fa parte dell'identita' dell'appello e senza di essa due appelli
        # dello stesso giorno e corso sarebbero indistinguibili nei menu a
        # tendina. Non usare nulla di tutto cio' verso gli studenti: per loro
        # c'e' etichetta_pubblica.
        return f"{self.etichetta_pubblica} ({self.commissione})"


def percorso_file_tesi(instance, filename):
    """Organizza i file caricati per appello e studente."""
    return f"tesi/appello_{instance.appello_id}/studente_{instance.studente_id}/{filename}"


class StudenteAppelloDiLaurea(models.Model):
    """Tabella ad hoc per la relazione "iscrizione" (Studente - Appello).

    Si usa una tabella esplicita invece della semplice ManyToMany di Django
    per poter memorizzare dati aggiuntivi, ad esempio la data di iscrizione.

    Il file della tesi e' per ora contenuto qui. In futuro, per scalabilita'
    (es. aggiunta di un video), il file potra' essere spostato in una tabella
    dedicata "Allegato" collegata a questa iscrizione, senza modificare le
    altre entita'.
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

    class Meta:
        verbose_name = "Iscrizione"
        verbose_name_plural = "Iscrizioni"
        ordering = ["-data_iscrizione"]
        # Uno studente puo' iscriversi una sola volta allo stesso appello
        constraints = [
            models.UniqueConstraint(
                fields=["studente", "appello"],
                name="unique_iscrizione_studente_appello",
            )
        ]

    def __str__(self):
        return f"{self.studente} -> {self.appello}"
