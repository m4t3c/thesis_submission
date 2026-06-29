from django.urls import path

from . import views

app_name = "appelli"

urlpatterns = [
    path("", views.home, name="home"),
    # Area studente
    path("studente/", views.studente_dashboard, name="studente_dashboard"),
    path("appelli/<int:appello_id>/iscriviti/", views.iscriviti, name="iscriviti"),
    path(
        "iscrizioni/<int:iscrizione_id>/carica-tesi/",
        views.carica_tesi,
        name="carica_tesi",
    ),
    # Area docente
    path("docente/", views.docente_dashboard, name="docente_dashboard"),
    path("appelli/<int:appello_id>/", views.appello_detail, name="appello_detail"),
    # Download protetto
    path(
        "iscrizioni/<int:iscrizione_id>/scarica-tesi/",
        views.scarica_tesi,
        name="scarica_tesi",
    ),
]
