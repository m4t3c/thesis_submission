"""Email di avviso mandate quando nasce un appello.

Un solo posto in cui stanno "chi va avvisato", "con che testo" e "con che
link": le view chiamano avvisa_nuovo_appello() e non sanno altro. Tenerlo
separato dalle view serve anche a poterlo riusare quando gli avvisi
partiranno da altrove (una modifica alla commissione, un comando di
manutenzione, un import automatico).
"""
import logging

from django.core.mail import EmailMessage, get_connection
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

OGGETTO_STUDENTE = "Iscrizione a un appello di laurea"
OGGETTO_DOCENTE = "Nomina nella commissione di un appello di laurea"


def _nome(utente):
    """Nome e cognome, o lo username se l'anagrafica e' vuota."""
    return utente.get_full_name() or utente.get_username()


def _url(request, nome_rotta, *argomenti):
    """Indirizzo COMPLETO (schema + host) della pagina.

    Nell'email un percorso relativo non serve a niente: ci vuole
    https://tesi.ing.unimore.it/... . build_absolute_uri lo ricava dalla
    richiesta in corso; dietro Traefik lo schema arriva da
    X-Forwarded-Proto, che settings.py dichiara in SECURE_PROXY_SSL_HEADER,
    e l'host e' comunque filtrato da ALLOWED_HOSTS.
    """
    return request.build_absolute_uri(reverse(nome_rotta, args=argomenti))


def _messaggi_studenti(request, appello):
    """Un'email per ogni studente iscritto, con il link alla propria tesi."""
    messaggi, senza_email = [], []
    for iscrizione in appello.iscrizioni.select_related("studente"):
        studente = iscrizione.studente
        if not studente.email:
            senza_email.append(_nome(studente))
            continue
        corpo = render_to_string(
            "appelli/email/studente_iscritto.txt",
            {
                "nome": _nome(studente),
                # etichetta_pubblica e NON str(appello): nel testo destinato
                # agli studenti la commissione non deve comparire.
                "appello": appello.etichetta_pubblica,
                "url": _url(request, "appelli:carica_tesi", iscrizione.pk),
            },
        )
        messaggi.append(EmailMessage(OGGETTO_STUDENTE, corpo, to=[studente.email]))
    return messaggi, senza_email


def _messaggi_docenti(request, appello):
    """Un'email per ogni membro della commissione, con il link al dettaglio."""
    messaggi, senza_email = [], []
    url = _url(request, "appelli:appello_detail", appello.pk)
    membri = list(appello.commissione.docenti.all())
    for docente in membri:
        if not docente.email:
            senza_email.append(_nome(docente))
            continue
        corpo = render_to_string(
            "appelli/email/docente_commissione.txt",
            {
                "nome": _nome(docente),
                "appello": appello.etichetta_pubblica,
                # Gli altri membri: al docente la commissione si puo' mostrare.
                "colleghi": [_nome(d) for d in membri if d.pk != docente.pk],
                "url": url,
            },
        )
        messaggi.append(EmailMessage(OGGETTO_DOCENTE, corpo, to=[docente.email]))
    return messaggi, senza_email


def avvisa_nuovo_appello(request, appello):
    """Avvisa studenti iscritti e membri della commissione.

    Torna la terna (quante inviate, chi non ha un indirizzo, errore o None).
    L'errore viene restituito invece che sollevato: l'appello a quel punto
    esiste gia' nel database, e far fallire la richiesta lascerebbe il
    presidente convinto di non averlo creato. Sta a chi chiama decidere che
    cosa dirgli.
    """
    messaggi_studenti, senza_studenti = _messaggi_studenti(request, appello)
    messaggi_docenti, senza_docenti = _messaggi_docenti(request, appello)
    messaggi = messaggi_studenti + messaggi_docenti
    senza_email = senza_studenti + senza_docenti

    if not messaggi:
        return 0, senza_email, None

    try:
        # Una sola connessione al server di posta per tutti i messaggi:
        # aprirne una per ognuno moltiplicherebbe i tempi di attesa, che qui
        # l'utente aspetta davvero (l'invio avviene dentro la sua richiesta).
        connessione = get_connection(fail_silently=False)
        inviate = connessione.send_messages(messaggi) or 0
    except Exception as errore:  # noqa: BLE001 - rete e SMTP alzano di tutto
        logger.exception("Invio degli avvisi per l'appello %s non riuscito", appello.pk)
        return 0, senza_email, errore

    return inviate, senza_email, None
