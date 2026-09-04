"""Dati aggiunti al contesto di OGNI template (vedi TEMPLATES in settings.py)."""
from django.conf import settings
from django.shortcuts import resolve_url


def login_url(request):
    """URL del pulsante "Accedi", gia' risolto in un percorso utilizzabile.

    LOGIN_URL cambia a seconda dell'ambiente: in produzione e' l'indirizzo
    completo dell'handler Shibboleth, in locale il nome della rotta del form di
    Django. ``resolve_url`` appiana la differenza, cosi' i template scrivono
    sempre e solo ``href="{{ login_url }}"``.
    """
    return {"login_url": resolve_url(settings.LOGIN_URL)}
