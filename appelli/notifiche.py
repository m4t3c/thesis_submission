"""Email di avviso mandate dall'applicazione.

Un solo posto in cui stanno "chi va avvisato", "con che testo" e "con che
link": le view chiamano avvisa_nuovo_appello() o avvisa_nomina_tutor() e non
sanno altro. Tenerlo separato dalle view serve anche a poterlo riusare quando
gli avvisi partiranno da altrove (una modifica alla commissione, un comando di
manutenzione, un import automatico).
"""
import logging
import threading

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)

OGGETTO_STUDENTE = "Iscrizione a un appello di laurea"
OGGETTO_DOCENTE = "Nomina nella commissione di un appello di laurea"
OGGETTO_TUTOR = "Nomina come tutor per una tesi di laurea"


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


def _spedisci(messaggi, appello_pk):
    """Consegna i messaggi gia' pronti al server di posta.

    Non tocca il database: riceve messaggi completi, cosi' puo' girare in un
    thread a parte senza aprirsi una connessione al database tutta sua (che
    poi andrebbe chiusa a mano, e che a lungo andare le esaurirebbe).

    Un errore qui si puo' solo scrivere nel log: quando questa funzione gira
    in sottofondo la risposta al presidente e' gia' partita da un pezzo.
    """
    try:
        # Una sola connessione per tutti i messaggi: aprirne una per ognuno
        # moltiplicherebbe l'handshake TLS, che da solo costa mezzo secondo.
        connessione = get_connection(fail_silently=False)
        inviate = connessione.send_messages(messaggi) or 0
        logger.info("Avvisi per l'appello %s: %s inviati", appello_pk, inviate)
    except Exception:  # noqa: BLE001 - rete e SMTP alzano di tutto
        logger.exception("Invio degli avvisi per l'appello %s non riuscito", appello_pk)


def _consegna(messaggi, appello_pk):
    """Manda i messaggi, in sottofondo o dentro la richiesta.

    Le due modalita' erano scritte dentro avvisa_nuovo_appello(); ora che gli
    avvisi partono da piu' punti stanno qui, o la regola "in esercizio non si
    aspetta la posta" andrebbe ricopiata (e tenuta allineata) ogni volta.

    Con l'elenco vuoto non fa niente: chi chiama non deve ricordarsi di
    controllarlo.
    """
    if not messaggi:
        return
    if settings.AVVISI_IN_BACKGROUND:
        # daemon=True: un riavvio non deve restare appeso ad aspettare
        # che la posta finisca.
        threading.Thread(
            target=_spedisci,
            args=(messaggi, appello_pk),
            name="avvisi-appello-%s" % appello_pk,
            daemon=True,
        ).start()
    else:
        # In test (e volendo in sviluppo) l'invio resta dentro la
        # richiesta: altrimenti non ci sarebbe modo di controllare la
        # posta subito dopo aver creato l'appello.
        _spedisci(messaggi, appello_pk)


def avvisa_nuovo_appello(request, appello):
    """Avvisa studenti iscritti e membri della commissione.

    I messaggi si preparano subito (serve il database, e serve la richiesta
    per costruire i link), ma la consegna al server di posta avviene in un
    thread separato: e' l'unica parte lenta, e tenerla dentro la richiesta
    significherebbe far aspettare il presidente mezzo secondo di handshake
    piu' una frazione per ogni destinatario. Con un appello numeroso sarebbe
    una pagina ferma per decine di secondi.

    Il prezzo di questa scelta, dichiarato: se il container viene fermato nei
    secondi subito successivi alla creazione, quelle email non partono e
    nessuno le ritenta. Per avere consegna garantita servirebbe una coda
    (Celery e simili), cioe' altri due servizi da mantenere.

    Torna l'elenco di chi non ha un indirizzo in anagrafica: quello si sa
    subito, senza aspettare l'invio, ed e' l'unica cosa che il presidente puo'
    davvero correggere.
    """
    messaggi_studenti, senza_studenti = _messaggi_studenti(request, appello)
    messaggi_docenti, senza_docenti = _messaggi_docenti(request, appello)
    messaggi = messaggi_studenti + messaggi_docenti
    senza_email = senza_studenti + senza_docenti

    _consegna(messaggi, appello.pk)

    return senza_email


def _url_per_il_tutor(request, iscrizione):
    """Pagina da cui il tutor vede quello studente per quell'appello.

    Non e' sempre la stessa, e la ragione e' una regola del dominio: il tutor
    NON deve per forza sedere nella commissione che esamina il suo studente
    (vedi il campo "tutor" in models.py), mentre appello_detail e' riservata
    ai membri di quella commissione. Mandare a tutti il link al dettaglio
    dell'appello vorrebbe dire mandare al caso piu' frequente un indirizzo che
    risponde "Non fai parte della commissione di questo appello".

    Quindi: a chi e' in commissione si da' la pagina dell'appello, che e' la
    piu' completa; a tutti gli altri l'area docente aperta sulla riga dello
    studente appena affidatogli (stessa ancora usata dopo una valutazione,
    vedi _url_ritorno_laureandi in views.py). In entrambi i casi il link porta
    all'appello di cui parla l'email, e in entrambi i casi funziona.
    """
    appello = iscrizione.appello
    if appello.commissione.docenti.filter(pk=iscrizione.tutor_id).exists():
        return _url(request, "appelli:appello_detail", appello.pk)
    return (
        _url(request, "appelli:docente_dashboard") + f"#laureando-{iscrizione.pk}"
    )


def avvisa_nomina_tutor(request, iscrizione):
    """Avvisa il docente che uno studente lo ha scelto come tutor.

    Un solo destinatario, quindi niente elenco di chi non ha indirizzo: se il
    docente non ce l'ha non c'e' nulla che lo studente possa farci, e mostrarlo
    nella sua pagina sarebbe solo un messaggio d'errore incomprensibile. Resta
    nel log, che e' dove chi amministra puo' accorgersene.

    La chiamata va fatta SOLO quando il tutor viene scelto davvero (vedi
    carica_tesi in views.py): il tutor non e' piu' modificabile dopo, ma lo
    stesso modulo si salva molte volte per titolo, tesi e video, e ogni
    salvataggio manderebbe un duplicato.

    Torna il nome del docente avvisato, o None se non aveva un indirizzo:
    serve ai test, alle view non serve niente.
    """
    docente = iscrizione.tutor
    studente = iscrizione.studente
    if not docente.email:
        logger.warning(
            "Nessun indirizzo email per il tutor %s (iscrizione %s)",
            _nome(docente),
            iscrizione.pk,
        )
        return None

    corpo = render_to_string(
        "appelli/email/docente_tutor.txt",
        {
            "nome": _nome(docente),
            "studente": _nome(studente),
            # L'indirizzo dello studente e' il motivo per cui questa email e'
            # utile: da li' il docente risponde, e la richiesta e' esplicita.
            "email_studente": studente.email,
            # etichetta_pubblica anche qui: la commissione non c'entra con il
            # tutoraggio, e il tutor potrebbe non farne parte.
            "appello": iscrizione.appello.etichetta_pubblica,
            "titolo": iscrizione.titolo,
            "url": _url_per_il_tutor(request, iscrizione),
        },
    )
    messaggio = EmailMessage(OGGETTO_TUTOR, corpo, to=[docente.email])
    _consegna([messaggio], iscrizione.appello_id)
    return _nome(docente)
