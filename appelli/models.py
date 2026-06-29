from django.conf import settings
from django.db import models


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
    corso_di_laurea = models.CharField(max_length=255)
    commissione = models.ForeignKey(
        Commissione,
        on_delete=models.PROTECT,
        related_name="appelli",
    )

    class Meta:
        verbose_name = "Appello di laurea"
        verbose_name_plural = "Appelli di laurea"
        ordering = ["-data"]
        # data + corso_di_laurea identificano logicamente l'appello
        constraints = [
            models.UniqueConstraint(
                fields=["data", "corso_di_laurea"],
                name="unique_appello_data_corso",
            )
        ]

    def __str__(self):
        return f"{self.corso_di_laurea} - {self.data:%d/%m/%Y}"


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
        blank=True,
        null=True,
        help_text="File della tesi di laurea.",
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
