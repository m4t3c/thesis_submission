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
    # Pagina di test Shibboleth (da rimuovere/proteggere in produzione)
    path("shibboleth/test/", views.shibboleth_test, name="shibboleth_test"),
    # Area studente
    path("studente/", views.studente_dashboard, name="studente_dashboard"),
    path("appelli/<int:appello_id>/iscriviti/", views.iscriviti, name="iscriviti"),
    path(
        "iscrizioni/<int:iscrizione_id>/carica-tesi/",
        views.carica_tesi,
        name="carica_tesi",
    ),
    # Area presidente
    path("presidente/", views.presidente_dashboard, name="presidente_dashboard"),
    path("appelli/nuovo/", views.crea_appello, name="crea_appello"),
    path("api/docenti/", views.cerca_docenti, name="cerca_docenti"),
    # Area docente
    path("docente/", views.docente_dashboard, name="docente_dashboard"),
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
