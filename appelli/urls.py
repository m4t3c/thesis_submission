"""Percorsi dell'applicazione, raggruppati per area.

I nomi delle rotte ("appelli:carica_tesi", ...) sono l'unico riferimento usato
in view e template: cambiando un percorso qui non si deve toccare nient'altro.
"""
from django.urls import path

from . import views

app_name = "appelli"

urlpatterns = [
    path("", views.home, name="home"),
    # Smistamento per ruolo dopo il login (percorso protetto da Shibboleth)
    path("dashboard/", views.dashboard, name="dashboard"),
    # Dump degli attributi Shibboleth: aperta a ogni utente autenticato,
    # cosi' si diagnostica l'identita' vera di chi segnala un problema
    path("shibboleth/test/", views.shibboleth_test, name="shibboleth_test"),
    # Area studente
    path("studente/", views.studente_dashboard, name="studente_dashboard"),
    path(
        "iscrizioni/<int:iscrizione_id>/carica-tesi/",
        views.carica_tesi,
        name="carica_tesi",
    ),
    # Area presidente
    path("presidente/", views.presidente_dashboard, name="presidente_dashboard"),
    path("appelli/nuovo/", views.crea_appello, name="crea_appello"),
    path("api/docenti/", views.cerca_docenti, name="cerca_docenti"),
    path("api/elenco-xlsx/", views.analizza_xlsx, name="analizza_xlsx"),
    # Area docente
    path("docente/", views.docente_dashboard, name="docente_dashboard"),
    # Ricerca fra i propri laureandi: risponde con le righe gia' impaginate
    path("api/laureandi/", views.cerca_laureandi, name="cerca_laureandi"),
    # Valutazione di un proprio laureando (solo il tutor)
    path(
        "laureandi/<int:iscrizione_id>/valutazione/",
        views.salva_valutazione,
        name="salva_valutazione",
    ),
    path("appelli/<int:appello_id>/", views.appello_detail, name="appello_detail"),
    # Download protetto
    path(
        "iscrizioni/<int:iscrizione_id>/scarica-tesi/",
        views.scarica_tesi,
        name="scarica_tesi",
    ),
    path(
        "iscrizioni/<int:iscrizione_id>/scarica-video/",
        views.scarica_video,
        name="scarica_video",
    ),
]
