from django.contrib.auth.backends import RemoteUserBackend
from django.contrib.auth.middleware import PersistentRemoteUserMiddleware
from django.contrib.auth.models import Group

# --- Nomi delle chiavi in request.META (come da dump /shibboleth/test) -------
# NB: con Apache+mod_shib gli attributi arrivano come variabili d'ambiente,
# quindi SENZA prefisso "HTTP_". Se sul deploy finale (tesi.ing.unimore.it)
# arrivassero invece come header, diventerebbero es. "HTTP_UID": vai su
# /shibboleth/test e verifica i nomi reali.
# Se usiamo Traefik e Gunicorn bisogna inserire HTTP_ davanti ad ogni campo
ATTR_USERNAME = "uid"        
ATTR_GIVENNAME = "givenName" 
ATTR_SURNAME = "sn"          
ATTR_MAIL = "mail"           
ATTR_OU = "ou"               

# --- Mappatura ruolo: 2° valore di 'ou' (plurale)  ->  nome del Group Django -
#    TODO
OU_TO_GROUP = {
    "studenti": "studente",
    "docenti": "docente",
    "": "altro",
}


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

        # Ruolo: secondo valore del campo 'ou'  (es. "people;studenti;...")
        ou_parts = [p.strip().lower() for p in meta.get(ATTR_OU, "").split(";")]
        ruolo = ou_parts[1] if len(ou_parts) > 1 else ""
        group_name = OU_TO_GROUP.get(ruolo)

        # Assegna l'utente al Group corretto e lo toglie dagli altri ruoli noti,
        # così se il ruolo cambia tra un accesso e l'altro resta coerente.
        ruoli_noti = set(OU_TO_GROUP.values())
        user.groups.remove(*Group.objects.filter(name__in=ruoli_noti))
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)

        return user

