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

# --- Ruolo -------------------------------------------------------------------
# Il ruolo si ricava dall'affiliation eduPerson, non piu' dal campo 'ou'.
#
# Il NOME dell'header non e' sempre lo stesso: per gli studenti arriva come
# "affiliation" secco, per i docenti con un prefisso davanti (a seconda
# dell'attributo rilasciato dal SP: unscoped-affiliation, eduPersonAffiliation,
# eduPersonScopedAffiliation...). Invece di indovinare un nome preciso si
# raccolgono TUTTI gli header il cui nome contiene "AFFILIATION" e se ne
# uniscono i valori: cosi' la regola vale in entrambi i casi e continua a
# funzionare se domani il SP cambia l'etichetta dell'attributo.
FRAMMENTO_AFFILIATION = "AFFILIATION"

# I valori sono "scoped" (es. "student@unimore.it"). La parte dopo la @ non e'
# un indirizzo di posta: e' il dominio dell'organizzazione che GARANTISCE quel
# ruolo. Va quindi verificata e non semplicemente tagliata, altrimenti in una
# federazione (IDEM, eduGAIN) uno "student@altroateneo.it" verrebbe accettato
# come studente UNIMORE.
SCOPE_ATTESO = "unimore.it"

# Regola sui valori: uno scope SBAGLIATO fa scartare il valore, uno scope
# ASSENTE no. Il motivo e' che i due casi dicono cose diverse:
#   - "student@unibo.it" afferma esplicitamente di venire da un altro ente:
#     e' il caso da bloccare (SP federato IDEM/eduGAIN);
#   - "student" secco e' semplicemente la forma non-scoped dello stesso
#     attributo (header "unscoped-affiliation"), che alcuni SP rilasciano al
#     posto o accanto a quella scoped. Scartarlo bloccherebbe utenti legittimi
#     senza proteggere da nulla.
# Cosi' la regola vale in entrambi i formati, senza dover sapere in anticipo
# quale dei due il SP rilascia ai docenti.
# NB: contro un header FALSIFICATO questo controllo non difende comunque (chi
# puo' scrivere l'header scrive anche "@unimore.it"): li' la difesa e' il
# reverse proxy che ripulisce gli X-Shib-* in arrivo dall'esterno.
SEPARATORI = ";,"

# L'insieme dei ruoli deve corrispondere ESATTAMENTE a una di queste due
# combinazioni. Qualsiasi altra cosa (personale tecnico-amministrativo,
# affiliation assente, valori inattesi) non riceve alcun gruppo e viene
# fermata dalla view 'dashboard' con la pagina di accesso negato.
RUOLI_STUDENTE = frozenset({"member", "student"})
RUOLI_DOCENTE = frozenset({"member", "employee", "faculty"})

GRUPPO_STUDENTE = "studente"
GRUPPO_DOCENTE = "docente"
GRUPPI_NOTI = (GRUPPO_STUDENTE, GRUPPO_DOCENTE)


def ruoli_affiliation(meta):
    """Insieme dei ruoli (senza scope) letti dagli header *affiliation*.

    Esempio: "member@unimore.it;student@unimore.it" -> {"member", "student"}.
    I valori con uno scope diverso da SCOPE_ATTESO vengono ignorati; quelli
    privi di scope sono accettati.
    """
    ruoli = set()
    for chiave, valore in meta.items():
        if FRAMMENTO_AFFILIATION not in chiave.upper():
            continue
        # request.META contiene anche oggetti non testuali (wsgi.input, ...).
        if not isinstance(valore, str):
            continue
        for separatore in SEPARATORI[1:]:
            valore = valore.replace(separatore, SEPARATORI[0])
        for pezzo in valore.split(SEPARATORI[0]):
            pezzo = pezzo.strip().lower()
            if not pezzo:
                continue
            # "student@unimore.it" -> ruolo "student", scope "unimore.it".
            # Senza "@" partition() restituisce separatore vuoto: e' la forma
            # non-scoped e viene accettata (vedi nota su SCOPE_ATTESO).
            ruolo, separatore, scope = pezzo.partition("@")
            if separatore and scope != SCOPE_ATTESO:
                continue
            ruoli.add(ruolo)
    return ruoli


def gruppo_per_affiliation(meta):
    """Nome del gruppo Django da assegnare, oppure None se non riconosciuto."""
    ruoli = ruoli_affiliation(meta)
    if ruoli == RUOLI_STUDENTE:
        return GRUPPO_STUDENTE
    if ruoli == RUOLI_DOCENTE:
        return GRUPPO_DOCENTE
    return None


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

        # Ruolo dall'affiliation. L'utente viene sempre tolto prima da entrambi
        # i gruppi noti: se il ruolo cambia (o smette di essere riconosciuto)
        # tra un accesso e l'altro, non restano permessi vecchi appiccicati.
        nome_gruppo = gruppo_per_affiliation(meta)
        user.groups.remove(*Group.objects.filter(name__in=GRUPPI_NOTI))
        if nome_gruppo:
            group, _ = Group.objects.get_or_create(name=nome_gruppo)
            user.groups.add(group)

        return user
