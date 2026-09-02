from django.contrib import admin

from .models import AppelloDiLaurea, Commissione, StudenteAppelloDiLaurea


class IscrizioneInline(admin.TabularInline):
    model = StudenteAppelloDiLaurea
    extra = 0
    readonly_fields = ("data_iscrizione",)
    autocomplete_fields = ("studente",)


@admin.register(Commissione)
class CommissioneAdmin(admin.ModelAdmin):
    list_display = ("__str__", "elenco_docenti")
    filter_horizontal = ("docenti",)
    search_fields = ("nome",)

    @admin.display(description="Docenti")
    def elenco_docenti(self, obj):
        return ", ".join(d.get_username() for d in obj.docenti.all())


@admin.register(AppelloDiLaurea)
class AppelloDiLaureaAdmin(admin.ModelAdmin):
    list_display = ("corso_di_laurea", "data", "ora", "commissione")
    list_filter = ("corso_di_laurea", "data")
    date_hierarchy = "data"
    search_fields = ("corso_di_laurea",)
    inlines = [IscrizioneInline]


@admin.register(StudenteAppelloDiLaurea)
class StudenteAppelloDiLaureaAdmin(admin.ModelAdmin):
    list_display = ("studente", "appello", "titolo", "data_iscrizione", "ha_tesi", "ha_video")
    list_filter = ("appello__corso_di_laurea",)
    # __str__ dell'appello include la commissione: senza questo si farebbe una
    # query in piu' per ogni riga dell'elenco.
    list_select_related = ("studente", "appello", "appello__commissione")
    readonly_fields = ("data_iscrizione",)
    autocomplete_fields = ("studente", "appello")
    search_fields = ("studente__username", "studente__email", "titolo")

    @admin.display(boolean=True, description="Tesi caricata")
    def ha_tesi(self, obj):
        return bool(obj.file_tesi)

    @admin.display(boolean=True, description="Video")
    def ha_video(self, obj):
        return obj.ha_video
