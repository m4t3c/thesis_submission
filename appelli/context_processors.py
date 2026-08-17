from django.conf import settings
from django.shortcuts import resolve_url


def login_url(request):
    """Rende disponibile ai template l'URL di login (Shibboleth in produzione,
    form di Django in locale), gia' risolto in un percorso utilizzabile in un
    href."""
    return {"login_url": resolve_url(settings.LOGIN_URL)}
