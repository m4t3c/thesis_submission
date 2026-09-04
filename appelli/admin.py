"""Configurazione dell'area amministrativa di Django.

E' lo strumento della segreteria, non dell'utente finale: da qui si correggono
i casi che l'applicazione non prevede (annullare un'iscrizione, assegnare a
mano il gruppo "presidente", sistemare un appello sbagliato). Per questo qui
si mostrano anche i dati che le pagine pubbliche nascondono, a partire dalla
commissione.
"""
from django.contrib import admin

from .models import AppelloDiLaurea, Commissione, StudenteAppelloDiLaurea


class IscrizioneInline(admin.TabularInline):
    """Iscrizioni mostrate dentro la pagina del relativo appello.

    ``extra = 0`` perche' la pagina serve quasi sempre a consultare o
    correggere le iscrizioni esistenti: le righe vuote in coda sarebbero solo
    rumore.
    """

    model = StudenteAppelloDiLaurea
    extra = 0
    # Data di iscrizione: la assegna il database (auto_now_add), quindi e'
    # visibile ma non modificabile.
    readonly_fields = ("data_iscrizione",)
    # Con qualche migliaio di studenti una tendina completa sarebbe
    # inutilizzabile: si cerca per nome.
    autocomplete_fields = ("studente",)


@admin.register(Commissione)
class CommissioneAdmin(admin.ModelAdmin):
    """Commissioni, elencate per membri e non per identificativo."""

    list_display = ("__str__", "elenco_docenti")
    filter_horizontal = ("docenti",)
    # Richiesto da autocomplete_fields di AppelloDiLaureaAdmin: senza,
    # l'admin non saprebbe su quale campo cercare.
    search_fields = ("nome",)

    @admin.display(description="Docenti")
    def elenco_docenti(self, obj):
        """Membri della commissione in una sola riga.

        Il solo id non direbbe nulla a chi consulta l'elenco: cio' che
        identifica una commissione sono le persone che la compongono.
        """
        return ", ".join(d.get_username() for d in obj.docenti.all())


@admin.register(AppelloDiLaurea)
class AppelloDiLaureaAdmin(admin.ModelAdmin):
    """Appelli di laurea, con le iscrizioni modificabili sulla stessa pagina."""

    list_display = ("corso_di_laurea", "data", "ora", "commissione")
    list_filter = ("corso_di_laurea", "data")
    date_hierarchy = "data"
    search_fields = ("corso_di_laurea",)
    inlines = [IscrizioneInline]


@admin.register(StudenteAppelloDiLaurea)
class StudenteAppelloDiLaureaAdmin(admin.ModelAdmin):
    """Iscrizioni, con lo stato degli allegati a colpo d'occhio."""

    list_display = ("studente", "appello", "titolo", "data_iscrizione", "ha_tesi", "ha_video")
    list_filter = ("appello__corso_di_laurea",)
    # __str__ dell'appello include la commissione: senza questo si farebbe una
    # query in piu' per ogni riga dell'elenco.
    list_select_related = ("studente", "appello", "appello__commissione")
    readonly_fields = ("data_iscrizione",)
    autocomplete_fields = ("studente", "appello")
    search_fields = ("studente__username", "studente__email", "titolo")

    # Le due colonne seguenti mostrano se l'allegato c'e', non quale sia: nel
    # lavoro di segreteria la domanda ricorrente e' "chi non ha ancora
    # consegnato", e la spunta si legge molto piu' in fretta di un percorso.

    @admin.display(boolean=True, description="Tesi caricata")
    def ha_tesi(self, obj):
        return bool(obj.file_tesi)

    @admin.display(boolean=True, description="Video")
    def ha_video(self, obj):
        return obj.ha_video
