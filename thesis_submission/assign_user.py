from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import PersistentRemoteUserMiddleware
from django.contrib.auth.models import Group

# --- Nomi delle chiavi in request.META (come da dump /shibboleth/test) -------
# In produzione (tesi.ing.unimore.it) il SP e' su un altro host e passa gli
# attributi come header HTTP "X-Shib-*" attraverso il reverse proxy fino a
# Gunicorn; WSGI li espone in request.META in MAIUSCOLO con prefisso "HTTP_",
# quindi diventano "HTTP_X_SHIB_*" (verificato su /shibboleth/test).
ATTR_USERNAME = "HTTP_X_SHIB_UID"
ATTR_GIVENNAME = "HTTP_X_SHIB_GIVENNAME"
ATTR_SURNAME = "HTTP_X_SHIB_SN"
ATTR_MAIL = "HTTP_X_SHIB_MAIL"
ATTR_OU = "HTTP_X_SHIB_OU"

# --- Ruolo -------------------------------------------------------------------
# Se il campo 'ou' contiene il valore "studenti" l'utente e' uno studente,
# in tutti gli altri casi e' un docente (decisione presa con il prof).
# Esempio reale (studente): ou = "people;studenti;Ingegneria Informatica (MO)"
VALORE_OU_STUDENTE = "studenti"
GRUPPO_STUDENTE = "studente"
GRUPPO_DOCENTE = "docente"


class AssignUserMiddleware(PersistentRemoteUserMiddleware):
    """Prende l'identità dall'attributo Shibboleth 'uid' invece di REMOTE_USER."""
    header = ATTR_USERNAME


class AssignUserBackend(RemoteUserBackend):
    """Crea/aggiorna lo User Django a ogni login, a partire dagli attributi Shibboleth."""

    def configure_user(self, request, user, created=True):
        meta = request.META

        # Dati anagrafici
        user.first_name = meta.get(ATTR_GIVENNAME, "") or user.first_name
        user.last_name = meta.get(ATTR_SURNAME, "") or user.last_name
        user.email = meta.get(ATTR_MAIL, "") or user.email
        user.save()

        # Ruolo: se 'ou' contiene "studenti" -> studente, altrimenti docente.
        # (es. studente: ou = "people;studenti;Ingegneria Informatica (MO)")
        ou_parts = [p.strip().lower() for p in meta.get(ATTR_OU, "").split(";")]
        if VALORE_OU_STUDENTE in ou_parts:
            group_name = GRUPPO_STUDENTE
        else:
            group_name = GRUPPO_DOCENTE

        # Assegna l'utente al Group corretto e lo toglie dall'altro ruolo noto,
        # così se il ruolo cambia tra un accesso e l'altro resta coerente.
        ruoli_noti = {GRUPPO_STUDENTE, GRUPPO_DOCENTE}
        user.groups.remove(*Group.objects.filter(name__in=ruoli_noti))
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)

        return user

