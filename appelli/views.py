"""Viste dell'applicazione, divise per area (studente, docente, presidente).

I permessi si controllano SEMPRE qui, all'inizio di ogni view: i template si
limitano a nascondere quello che l'utente non puo' fare, ma nascondere un
pulsante non impedisce di inviare la richiesta a mano.
"""
import os
from itertools import groupby
from urllib.parse import parse_qsl, urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from django.template.defaultfilters import filesizeformat

from .forms import (
    MAX_BYTE_VIDEO,
    AppelloForm,
    TesiUploadForm,
    ValutazioneForm,
    dati_utente,
)
from .notifiche import avvisa_nomina_tutor, avvisa_nuovo_appello
from .xlsx import MAX_BYTE_XLSX, ErroreXlsx, leggi_elenco
from .models import (
    FORMATI_VIDEO,
    ORDINE_APPELLI,
    PUNTEGGIO_MAX,
    AppelloDiLaurea,
    StudenteAppelloDiLaurea,
)


# --- Helper per i ruoli (basati sui gruppi di Django) ---------------------

def is_studente(user):
    """True se l'utente appartiene al gruppo "studente"."""
    return user.groups.filter(name="studente").exists()


def is_docente(user):
    """True se l'utente appartiene al gruppo "docente"."""
    return user.groups.filter(name="docente").exists()


def is_presidente(user):
    """Il presidente e' un docente con in piu' il gruppo "presidente".

    Il gruppo non arriva da Shibboleth (l'affiliation di un presidente e'
    identica a quella di un docente): lo assegna a mano un amministratore.
    """
    return user.groups.filter(name="presidente").exists()


def docente_in_commissione(user, appello):
    """True se il docente fa parte della commissione dell'appello."""
    return appello.commissione.docenti.filter(pk=user.pk).exists()


def is_tutor(utente, iscrizione):
    """True se l'utente e' il tutor di quella iscrizione."""
    return iscrizione.tutor_id == utente.pk


def puo_valutare(utente, iscrizione):
    """Chi puo' correggere titolo, punteggio e giudizio: il solo tutor.

    Non basta essere docente e non basta essere in commissione: la valutazione
    e' una proposta personale di chi ha seguito la tesi, e solo lui la scrive.
    """
    return is_docente(utente) and is_tutor(utente, iscrizione)


# --- Pagina di test Shibboleth --------------------------------------------

@login_required
def shibboleth_test(request):
    """Stampa tutti gli attributi che il server passa a Django (request.META).

    Serve a verificare i nomi reali degli attributi Shibboleth (uid, ou, sn,
    givenName, ...) sul dominio di produzione, prima di configurare
    shibboleth.py. E' aperta a QUALUNQUE utente autenticato, cosi' si possono
    controllare gli attributi di un'identita' vera (studente o docente) e non
    solo quelli di un amministratore: ognuno vede il dump della propria
    richiesta, quindi i propri attributi e i propri cookie.
    """
    righe = [
        f"{chiave}: {valore!r}, type: {type(valore)}"
        for chiave, valore in sorted(request.META.items())
    ]
    return HttpResponse("\n".join(righe), content_type="text/plain; charset=utf-8")


# --- Home con smistamento per ruolo ---------------------------------------

def home(request):
    """Pagina iniziale PUBBLICA (percorso '/').

    In produzione questo percorso non passa da Shibboleth (vedi le due router
    rule in docker-compose.prod.yml), quindi qui l'utente risulta sempre
    anonimo e vede la landing. In locale, un utente gia' autenticato viene
    comunque smistato alla sua dashboard.
    """
    if request.user.is_authenticated:
        return redirect("appelli:dashboard")
    return render(request, "appelli/landing.html")


@login_required
def dashboard(request):
    """Smistamento per ruolo dopo il login (percorso '/dashboard/', protetto).

    E' il bersaglio del login Shibboleth: essendo dietro autenticazione, quando
    lo si raggiunge l'utente e' gia' riconosciuto e lo si manda alla pagina
    giusta in base al gruppo.
    """
    if is_studente(request.user):
        return redirect("appelli:studente_dashboard")
    # Prima del docente: un presidente appartiene a entrambi i gruppi, e la
    # sua pagina e' quella piu' completa.
    if is_presidente(request.user):
        return redirect("appelli:presidente_dashboard")
    if is_docente(request.user):
        return redirect("appelli:docente_dashboard")
    # Nessun gruppo noto: l'affiliation Shibboleth non corrisponde ne' al
    # profilo studente ne' a quello docente. 403 e non 200 perche' e' a tutti
    # gli effetti un rifiuto (e non va indicizzato ne' messo in cache).
    return render(request, "appelli/accesso_negato.html", status=403)


# --- Area studente ---------------------------------------------------------

@login_required
def studente_dashboard(request):
    """Pagina dello studente: le sue iscrizioni e gli altri appelli in programma.

    All'iscrizione provvede il presidente caricando l'elenco (vedi
    analizza_xlsx): il secondo elenco non e' quindi un invito a iscriversi ma
    un calendario, e i due sono complementari. Un appello a cui lo studente e'
    gia' iscritto non deve ricomparire fra gli "altri", dove sembrerebbe una
    scadenza ancora da affrontare invece che la propria.

    Gli appelli gia' passati restano fuori da entrambi, e qui senza spunta che
    li riporti: la pagina serve a completare una consegna, e una scadenza
    trascorsa non si completa piu'. Allo studente riguarda al piu' la propria
    laurea, che ha gia' discusso; l'interruttore sta nell'area docente, dove
    invece capita davvero di dover rivedere un appello concluso.
    """
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono accedere a questa pagina.")

    oggi = timezone.localdate()

    iscrizioni = request.user.iscrizioni.select_related("appello", "tutor").order_by(
        "appello__data", F("appello__ora").asc(nulls_last=True)
    )
    # Gli id da escludere si prendono da TUTTE le iscrizioni, comprese quelle
    # passate: un appello a cui si e' gia' iscritti non deve ricomparire fra i
    # disponibili, dove sarebbe un appello altrui come tutti gli altri.
    appelli_iscritti = list(iscrizioni.values_list("appello_id", flat=True))

    return render(
        request,
        "appelli/studente_dashboard.html",
        {
            "iscrizioni": iscrizioni.filter(appello__data__gte=oggi),
            # L'ordine (dal piu' vecchio) arriva dal Meta di AppelloDiLaurea.
            "appelli_disponibili": AppelloDiLaurea.objects.exclude(
                pk__in=appelli_iscritti
            ).filter(data__gte=oggi),
        },
    )


def _stato_consegna(iscrizione):
    """Le tre cose che servono per la consegna, e quali risultano fatte.

    Torna le voci pronte per il template piu' il conteggio, cosi' la pagina
    non deve contarle da sola (i template Django non sanno sommare) e la
    percentuale della barra non viene calcolata a mano in due posti.

    "manca" e' il testo mostrato accanto alla voce non completata: dirlo qui
    tiene le tre frasi vicine, dove si vede subito che sono coerenti fra loro.
    """
    voci = [
        {"nome": "Titolo", "fatto": bool(iscrizione.titolo), "manca": "non ancora indicato"},
        {"nome": "Tutor", "fatto": bool(iscrizione.tutor_id), "manca": "non ancora scelto"},
        {"nome": "Tesi", "fatto": bool(iscrizione.file_tesi), "manca": "non ancora caricata"},
    ]
    fatte = sum(1 for v in voci if v["fatto"])
    return {
        "voci": voci,
        "fatte": fatte,
        "totale": len(voci),
        # A consegna finita la pagina cambia messaggio: vedi il template.
        "completa": fatte == len(voci),
        # Con zero voci fatte la barra resterebbe invisibile: un filo di
        # riempimento la fa leggere come "barra vuota" e non come "assente".
        "percentuale": round(fatte * 100 / len(voci)) if fatte else 3,
    }


@login_required
def carica_tesi(request, iscrizione_id):
    """Titolo, file della tesi ed eventuale video di una propria iscrizione.

    Il filtro su ``studente=request.user`` non e' un dettaglio: senza, l'id
    nell'URL basterebbe ad aprire (e sovrascrivere) la tesi di chiunque altro.
    """
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono caricare la tesi.")

    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea, pk=iscrizione_id, studente=request.user
    )

    # Nomi dei file GIA' SALVATI sul database, letti prima di legare il form:
    # su un POST non valido il ModelForm copia comunque i dati inviati dentro
    # l'istanza, quindi dopo la validazione "iscrizione.file_tesi" sarebbe il
    # file appena scelto. Leggendoli dopo, la pagina di errore mostrerebbe come
    # "gia' caricata" una tesi che invece non e' stata salvata.
    nome_file = os.path.basename(iscrizione.file_tesi.name) if iscrizione.file_tesi else ""
    nome_video = os.path.basename(iscrizione.file_video.name) if iscrizione.file_video else ""

    # Riepilogo "stato consegna" mostrato in pagina. Va letto qui, insieme ai
    # nomi dei file e per la stessa ragione: e' il riassunto di cio' che RISULTA
    # SALVATO, e su un POST rifiutato l'istanza porta gia' i dati inviati.
    # Calcolato dopo, darebbe per fatto quello che non e' stato salvato.
    #
    # Il video non entra nel conteggio: e' facoltativo, e vederlo fra le voci
    # mancanti farebbe credere allo studente che gli serva per laurearsi.
    stato_consegna = _stato_consegna(iscrizione)

    if request.method == "POST":
        form = TesiUploadForm(request.POST, request.FILES, instance=iscrizione)
        if form.is_valid():
            form.save()
            # Il tutor si sceglie UNA VOLTA SOLA (il form lo disabilita
            # appena c'e'), quindi "tutor" compare in changed_data solo al
            # momento della scelta: l'avviso parte una volta e non a ogni
            # salvataggio successivo di titolo, tesi o video.
            if "tutor" in form.changed_data and iscrizione.tutor_id:
                avvisa_nomina_tutor(request, iscrizione)
            if form.changed_data:
                messages.success(request, "Dati della tesi salvati correttamente.")
            else:
                messages.info(request, "Nessuna modifica da salvare.")
            return redirect("appelli:studente_dashboard")
    else:
        form = TesiUploadForm(instance=iscrizione)

    return render(
        request,
        "appelli/carica_tesi.html",
        {
            "form": form,
            "iscrizione": iscrizione,
            "nome_file": nome_file,
            "nome_video": nome_video,
            "formati_video": ", ".join(FORMATI_VIDEO),
            "max_video": filesizeformat(MAX_BYTE_VIDEO),
            "stato_consegna": stato_consegna,
        },
    )


# --- Area docente ----------------------------------------------------------

def _contesto_appelli(request, puo_creare, titolo, filtri=None):
    """Contesto della pagina appelli, condiviso da docenti e presidente.

    Le due pagine mostrano le stesse cose: la sezione dei propri laureandi e
    le due tabelle degli appelli ("i miei" e gli altri). Al presidente si
    aggiunge soltanto il pulsante di creazione. Un unico contesto evita che le
    due viste divergano col tempo.

    Args:
        request: richiesta corrente; da qui si leggono utente e querystring.
        puo_creare: se mostrare il pulsante di creazione di un appello.
        titolo: intestazione della pagina.
        filtri: coppie (chiave, valore) da usare al posto della querystring.
            Serve quando la pagina si ridisegna dopo una POST, in cui i
            filtri viaggiano nel campo "ritorno" e non nell'URL.
    """
    utente = request.user
    valori = _filtri_pagina(request, filtri)

    def elenco(queryset, passati):
        if not passati:
            queryset = queryset.filter(data__gte=timezone.localdate())
        # order_by esplicito: con annotate() il Meta.ordering non viene
        # applicato (vedi ORDINE_APPELLI in models.py).
        return (
            queryset.select_related("commissione")
            .annotate(numero_iscritti=Count("iscrizioni"))
            .distinct()
            .order_by(*ORDINE_APPELLI)
        )

    miei = elenco(
        AppelloDiLaurea.objects.filter(commissione__docenti=utente),
        valori[PASSATI_MIEI],
    )
    altri = elenco(
        AppelloDiLaurea.objects.exclude(commissione__docenti=utente),
        valori[PASSATI_ALTRI],
    )

    contesto = {
        "miei_appelli": miei,
        "altri_appelli": altri,
        "puo_creare_appelli": puo_creare,
        "titolo_pagina": titolo,
        "spunta_miei": _spunta(valori, PASSATI_MIEI),
        "spunta_altri": _spunta(valori, PASSATI_ALTRI),
        # Il form della ricerca e' l'altro comando della pagina, e ha lo
        # stesso bisogno: riportare cio' che non gestisce lui.
        "filtri_ricerca": _campi_nascosti(valori, "q"),
    }
    contesto.update(_laureandi_del_docente(request, utente, filtri))
    return contesto


def _filtri_pagina(request, filtri=None):
    """Valori dei filtri della pagina, letti dalla querystring o dal "ritorno".

    Dopo una POST la querystring non c'e': i filtri viaggiano nel campo
    "ritorno" del modulo e arrivano qui gia' spacchettati in coppie. In
    entrambi i casi si tiene solo cio' che e' un filtro noto, perche' il valore
    viene comunque dal browser.
    """
    if filtri is None:
        voci = request.GET
    else:
        voci = dict((c, v) for c, v in filtri if c in PARAMETRI_LAUREANDI)
    return {
        "q": (voci.get("q") or "").strip(),
        # Solo "1" accende un interruttore: un valore storto vale come spento,
        # che e' il comportamento predefinito e piu' innocuo.
        PASSATI_MIEI: voci.get(PASSATI_MIEI) == "1",
        PASSATI_ALTRI: voci.get(PASSATI_ALTRI) == "1",
    }


def _campi_nascosti(valori, escluso):
    """I filtri attivi della pagina meno uno, come coppie nome/valore.

    Ogni comando della pagina e' un form GET a se', e un form GET manda solo
    cio' che contiene: senza riportare gli altri filtri, accendere un
    interruttore spegnerebbe il gemello e azzererebbe la ricerca in corso.
    Si esclude il proprio, che il form gia' contiene per conto suo.
    """
    return [
        {"nome": chiave, "valore": "1" if valore is True else valore}
        for chiave, valore in valori.items()
        if chiave != escluso and valore
    ]


def _spunta(valori, nome):
    """Un interruttore "appelli passati" pronto per il template."""
    return {
        "nome": nome,
        "attiva": valori[nome],
        "nascosti": _campi_nascosti(valori, nome),
    }


# Le due tabelle degli appelli hanno un interruttore ciascuna, e quindi un
# parametro ciascuna: si guarda lo storico di una senza allungare l'altra.
PASSATI_MIEI = "passati_miei"
PASSATI_ALTRI = "passati_altri"

# Filtri della pagina degli appelli: la ricerca fra i laureandi e i due
# interruttori. Sono anche gli unici parametri che vengono riportati nell'URL
# dopo un salvataggio: tutto il resto viene scartato.
PARAMETRI_LAUREANDI = ("q", PASSATI_MIEI, PASSATI_ALTRI)


def _corrisponde(iscrizione, parole):
    """True se OGNI parola cercata compare in nome, cognome, matricola o titolo.

    Stessa regola della ricerca dei docenti: cosi' "ros mar" trova "Mario
    Rossi" senza pretendere l'ordine esatto.
    """
    campi = " ".join(
        (
            iscrizione.studente.first_name,
            iscrizione.studente.last_name,
            iscrizione.studente.get_username(),
            iscrizione.titolo,
        )
    ).lower()
    return all(parola in campi for parola in parole)


def _chiave_alfabetica(iscrizione):
    """Ordine per cognome, poi nome, poi username: lo stesso delle query.

    Serve dove l'elenco si riordina in Python invece che nel database. Il
    confronto e' in minuscolo perche' altrimenti "de Rossi" finirebbe dopo
    "Zeta", e lo username chiude la chiave per dare un ordine stabile anche a
    chi ha l'anagrafica vuota.
    """
    studente = iscrizione.studente
    return (
        studente.last_name.lower(),
        studente.first_name.lower(),
        studente.get_username().lower(),
    )


def _laureandi_correnti(utente):
    """Iscrizioni di cui l'utente e' tutor, con il modulo gia' agganciato.

    Solo appelli non ancora passati: una tesi discussa non si valuta piu', e
    tenere in pagina anni di archivio renderebbe la sezione inservibile proprio
    per cio' a cui serve, cioe' vedere su chi si deve ancora intervenire.

    Costa UNA query, qualunque sia il numero di laureandi: studente e appello
    arrivano gia' dentro, quindi il template non ne fa una per riga.
    """
    righe = list(
        StudenteAppelloDiLaurea.objects.filter(
            tutor=utente, appello__data__gte=timezone.localdate()
        )
        .select_related("studente", "appello")
        .order_by(
            "appello__data",
            F("appello__ora").asc(nulls_last=True),
            # appello_id nell'ordinamento non e' un vezzo: due appelli con la
            # stessa data e ora si alternerebbero nell'elenco e groupby, che
            # raggruppa solo righe ADIACENTI, li spezzerebbe in piu' gruppi.
            "appello_id",
            "studente__last_name",
            "studente__first_name",
            "studente__username",
        )
    )
    # Il modulo di modifica e' precompilato con i dati gia' salvati. auto_id
    # porta l'id dell'iscrizione dentro gli id dei campi: nella pagina i moduli
    # sono tanti quanti i laureandi, e con gli id predefiniti ("id_titolo",
    # "id_punteggio_0", ...) ogni <label> punterebbe al campo del PRIMO modulo.
    for iscrizione in righe:
        iscrizione.form = ValutazioneForm(
            instance=iscrizione, auto_id=f"id_%s_{iscrizione.pk}"
        )
    return righe


def _laureandi_del_docente(request, utente, filtri=None):
    """Sezione laureandi pronta per il template: gruppi ed eventuali risultati.

    Non ha relazione con gli appelli delle proprie commissioni: si puo' essere
    tutor di uno studente senza sedere nella commissione che lo esamina,
    quindi l'elenco si costruisce a parte.

    I gruppi si calcolano SEMPRE, anche durante una ricerca: cosi' annullarla
    e' immediato, perche' l'elenco completo e' gia' nella pagina e non va
    richiesto di nuovo al server.
    """
    # La sezione laureandi guarda solo il termine di ricerca: la spunta sugli
    # appelli passati non la riguarda, perche' una tesi gia' discussa non si
    # valuta piu' e resta fuori comunque (vedi _laureandi_correnti).
    termine = _filtri_pagina(request, filtri)["q"]
    correnti = _laureandi_correnti(utente)

    commissioni_mie = set(
        AppelloDiLaurea.objects.filter(commissione__docenti=utente).values_list(
            "id", flat=True
        )
    )

    gruppi = []
    for appello, righe in groupby(correnti, key=lambda t: t.appello):
        righe = list(righe)
        gruppi.append(
            {
                "appello": appello,
                "iscrizioni": righe,
                "totale": len(righe),
                # Zero e' un punteggio valido: "da valutare" e' chi ha il campo
                # ancora vuoto, non chi ha preso zero.
                "da_valutare": sum(1 for r in righe if not r.valutata),
                "in_commissione": appello.id in commissioni_mie,
            }
        )

    # Durante una ricerca il raggruppamento sparisce: chi cerca una persona non
    # sa a quale appello sia iscritta, quindi i risultati sono un elenco piatto.
    trovati = None
    if termine:
        parole = termine.lower().split()
        trovati = [t for t in correnti if _corrisponde(t, parole)]
        # Senza i gruppi resterebbe l'ordine per appello, che qui non si vede
        # piu': in un elenco piatto di persone l'ordine leggibile e' il cognome.
        trovati.sort(key=_chiave_alfabetica)

    return {
        "laureandi_trovati": trovati,
        "laureandi_gruppi": gruppi,
        "laureandi_totali": len(correnti),
        "ricerca_laureandi": termine,
        "punteggio_massimo": PUNTEGGIO_MAX,
    }


@login_required
def docente_dashboard(request):
    """Area del docente: i propri laureandi e gli appelli, senza creazione.

    Le due tabelle degli appelli e la sezione dei laureandi arrivano tutte da
    _contesto_appelli; rispetto al presidente manca il solo pulsante che crea
    un appello.
    """
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti possono accedere a questa pagina.")

    return render(
        request,
        "appelli/docente_dashboard.html",
        _contesto_appelli(request, puo_creare=False, titolo="Area Docente"),
    )


@login_required
def appello_detail(request, appello_id):
    """Dettaglio di un appello: commissione e studenti iscritti.

    Riservata ai docenti che compongono QUELLA commissione: e' la pagina da
    cui si scaricano le tesi, quindi il solo ruolo di docente non basta.
    """
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti possono accedere a questa pagina.")

    appello = get_object_or_404(
        AppelloDiLaurea.objects.select_related("commissione").prefetch_related(
            "commissione__docenti"
        ),
        pk=appello_id,
    )
    if not docente_in_commissione(request.user, appello):
        raise PermissionDenied("Non fai parte della commissione di questo appello.")

    return render(
        request, "appelli/appello_detail.html", _contesto_dettaglio(request, appello)
    )


def _contesto_dettaglio(request, appello):
    """Contesto del dettaglio di un appello, con i moduli di valutazione.

    Separato dalla view perche' serve anche a salva_valutazione: un
    salvataggio rifiutato dal dettaglio ridisegna questa pagina, non la
    dashboard. I permessi li controlla chi la chiama.
    """
    # Ordinate per cognome: l'ordine predefinito del modello e' quello di
    # iscrizione, che in un elenco da leggere non dice niente a nessuno.
    iscrizioni = list(
        appello.iscrizioni.select_related("studente", "tutor").order_by(
            "studente__last_name", "studente__first_name", "studente__username"
        )
    )
    # I propri laureandi vengono prima e restano distinti: chi apre questa
    # pagina cerca quasi sempre loro, e in un appello numeroso scorrere tutto
    # l'elenco per ritrovarli e' il lavoro che la pagina deve risparmiare.
    miei = [i for i in iscrizioni if i.tutor_id == request.user.pk]
    altri = [i for i in iscrizioni if i.tutor_id != request.user.pk]

    # Solo i propri laureandi hanno il modulo: la valutazione e' del tutor
    # (vedi puo_valutare). auto_id come in _laureandi_correnti, e per la stessa
    # ragione: un modulo per riga, e le <label> devono puntare al proprio.
    for iscrizione in miei:
        iscrizione.form = ValutazioneForm(
            instance=iscrizione, auto_id=f"id_%s_{iscrizione.pk}"
        )

    return {
        "appello": appello,
        "iscrizioni": iscrizioni,
        "iscritti_miei": miei,
        "iscritti_altri": altri,
        "punteggio_massimo": PUNTEGGIO_MAX,
        # Un presidente e' anche docente: senza questo, "Torna indietro" lo
        # riporterebbe sempre nell'area docente, cioe' non da dove veniva.
        "url_ritorno": (
            "appelli:presidente_dashboard"
            if is_presidente(request.user)
            else "appelli:docente_dashboard"
        ),
    }


def _ritorno_al_dettaglio(request, iscrizione):
    """True se il modulo e' stato inviato dal dettaglio dell'appello dello studente.

    Il campo "ritorno" del dettaglio porta l'URL della pagina. Lo si confronta
    con quello ricostruito da reverse(), e l'unico accettato e' quello
    dell'appello a cui lo studente e' iscritto: un valore diverso o manomesso
    fa ricadere sulla dashboard, e il valore ricevuto non finisce mai in un
    rimando.

    Serve anche essere in commissione, come per aprire la pagina: senza, un
    tutor esterno potrebbe farsi ridisegnare (sugli errori) un elenco di
    iscritti che appello_detail gli negherebbe.
    """
    atteso = reverse("appelli:appello_detail", args=[iscrizione.appello_id])
    return request.POST.get("ritorno", "") == atteso and docente_in_commissione(
        request.user, iscrizione.appello
    )


def _url_ritorno_laureandi(request, iscrizione):
    """Dove tornare dopo un salvataggio: stessa pagina, stessi filtri, stessa riga.

    Due pagine hanno il modulo: il dettaglio dell'appello (riconosciuto da
    _ritorno_al_dettaglio) e la dashboard. Per quest'ultima del "ritorno"
    ricevuto si tengono SOLO i filtri della sezione. In entrambi i casi il
    percorso si ricostruisce con reverse(): cosi' un valore manomesso non puo'
    trasformare il salvataggio in un rimando verso un sito esterno.
    """
    # L'ancora riporta alla riga appena salvata invece che in cima all'elenco.
    ancora = f"#laureando-{iscrizione.pk}"
    if _ritorno_al_dettaglio(request, iscrizione):
        return (
            reverse("appelli:appello_detail", args=[iscrizione.appello_id]) + ancora
        )

    nome = (
        "appelli:presidente_dashboard"
        if is_presidente(request.user)
        else "appelli:docente_dashboard"
    )
    coppie = [
        (chiave, valore)
        for chiave, valore in parse_qsl(request.POST.get("ritorno", ""))
        if chiave in PARAMETRI_LAUREANDI
    ]
    url = reverse(nome)
    if coppie:
        url += "?" + urlencode(coppie)
    return url + ancora


@login_required
def salva_valutazione(request, iscrizione_id):
    """Titolo, punti e giudizio di un proprio laureando, salvati dal tutor."""
    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea.objects.select_related("studente", "appello"),
        pk=iscrizione_id,
    )
    # Il controllo sta qui e non nel template: nascondere il pulsante non
    # impedisce a un altro docente di inviare la richiesta a mano.
    if not puo_valutare(request.user, iscrizione):
        raise PermissionDenied("Solo il tutor può valutare questo studente.")
    if request.method != "POST":
        return redirect(_url_ritorno_laureandi(request, iscrizione))

    # auto_id come quello dei moduli della pagina: se il modulo torna a video
    # con gli errori, gli id dei campi devono restare quelli, o le <label>
    # punterebbero altrove.
    form = ValutazioneForm(
        request.POST, instance=iscrizione, auto_id=f"id_%s_{iscrizione.pk}"
    )
    if form.is_valid():
        form.save()
        nome = iscrizione.studente.get_full_name() or iscrizione.studente.get_username()
        if form.changed_data:
            messages.success(request, f"Valutazione di {nome} salvata.")
        else:
            messages.info(request, "Nessuna modifica da salvare.")
        return redirect(_url_ritorno_laureandi(request, iscrizione))

    # Errore: si RIDISEGNA la pagina con dentro questo modulo, invece di
    # rimandare alla dashboard. Con il rimando il pannello si sarebbe richiuso
    # e quanto scritto sarebbe andato perso: chi aveva compilato solo il
    # giudizio avrebbe dovuto riscriverlo daccapo.
    if _ritorno_al_dettaglio(request, iscrizione):
        return _dettaglio_con_valutazione_da_correggere(request, iscrizione, form)
    return _pagina_con_valutazione_da_correggere(request, iscrizione, form)


def _dettaglio_con_valutazione_da_correggere(request, iscrizione, form):
    """Dettaglio dell'appello con un modulo di valutazione aperto sugli errori."""
    contesto = _contesto_dettaglio(request, iscrizione.appello)
    for riga in contesto["iscritti_miei"]:
        if riga.pk == iscrizione.pk:
            riga.form = form
    contesto["valutazione_aperta"] = iscrizione.pk
    return render(request, "appelli/appello_detail.html", contesto)


def _pagina_con_valutazione_da_correggere(request, iscrizione, form):
    """Dashboard del docente con un modulo di valutazione aperto sugli errori."""
    contesto = _contesto_appelli(
        request,
        puo_creare=is_presidente(request.user),
        titolo="Area Presidente" if is_presidente(request.user) else "Area Docente",
        filtri=parse_qsl(request.POST.get("ritorno", "")),
    )
    # Le righe dei gruppi e quelle dei risultati di ricerca sono gli STESSI
    # oggetti: basta sostituire il modulo qui perche' valga in entrambi gli
    # elenchi.
    for gruppo in contesto["laureandi_gruppi"]:
        for riga in gruppo["iscrizioni"]:
            if riga.pk == iscrizione.pk:
                riga.form = form
                # Anche il gruppo va aperto: di suo resta chiuso (tranne il
                # primo), e il modulo riaperto dentro un gruppo chiuso non si
                # vedrebbe. L'utente avrebbe davanti una pagina in apparenza
                # identica a prima, senza spiegazioni.
                gruppo["contiene_errore"] = True
    contesto["valutazione_aperta"] = iscrizione.pk
    return render(request, "appelli/docente_dashboard.html", contesto)


# --- Area presidente -------------------------------------------------------

@login_required
def presidente_dashboard(request):
    """La stessa pagina del docente, piu' il pulsante per creare un appello.

    Il presidente E' un docente: mostrargli una pagina diversa lo priverebbe
    della vista sui propri appelli senza alcun vantaggio.
    """
    if not is_presidente(request.user):
        raise PermissionDenied("Solo il presidente può accedere a questa pagina.")

    return render(
        request,
        "appelli/docente_dashboard.html",
        _contesto_appelli(request, puo_creare=True, titolo="Area Presidente"),
    )


@login_required
def crea_appello(request):
    """Creazione di un appello (data, orario, corso e membri della commissione).

    La commissione non si sceglie da un elenco: la ricava AppelloForm dai
    docenti selezionati, riusandone una gia' esistente se composta dalle
    stesse persone.
    """
    if not is_presidente(request.user):
        raise PermissionDenied("Solo il presidente può creare un appello.")

    if request.method == "POST":
        form = AppelloForm(request.POST)
        if form.is_valid():
            appello = form.save()
            messages.success(
                request, f"Appello «{appello.etichetta_pubblica}» creato."
            )
            # Gli avvisi partono dopo il salvataggio e la consegna al
            # server di posta avviene in sottofondo, quindi qui non si sa
            # ancora se andra' a buon fine (un guasto finisce nei log). Si sa
            # invece subito chi non ha un indirizzo in anagrafica, e quello va
            # detto: altrimenti il presidente darebbe per scontato che tutti
            # abbiano ricevuto la comunicazione.
            senza_email = avvisa_nuovo_appello(request, appello)
            if senza_email:
                messages.warning(
                    request,
                    "Nessun indirizzo email per: "
                    + ", ".join(senza_email)
                    + ". Queste persone non hanno ricevuto l'avviso.",
                )
            return redirect("appelli:presidente_dashboard")
    else:
        form = AppelloForm()

    return render(request, "appelli/crea_appello.html", {"form": form})


# --- Ricerca dei docenti (per comporre la commissione) ---------------------

# Quanti risultati al massimo tornano da una ricerca. Serve a tenere leggera
# sia la query sia la tendina: con qualche migliaio di utenti un elenco
# completo sarebbe inutilizzabile per chi cerca e costoso per il server.
MAX_RISULTATI_RICERCA = 10


def _richiesta_interna(request):
    """True se la richiesta arriva dalle pagine di questa applicazione.

    ATTENZIONE a cosa protegge e cosa no: questi controlli impediscono di
    aprire l'endpoint incollando l'URL nel browser e di interrogarlo da un
    altro sito, ma sono header, quindi falsificabili da chiunque sappia usare
    curl. La difesa VERA e' il controllo di autenticazione e ruolo nella view:
    senza una sessione valida da presidente non si ottiene nulla comunque.
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return False

    # Origin non viene sempre inviato sulle GET same-origin: si verifica solo
    # se c'e', altrimenti si rifiuterebbero richieste legittime.
    origine = request.headers.get("Origin") or request.headers.get("Referer")
    if origine:
        atteso = f"{request.scheme}://{request.get_host()}"
        if not origine.startswith(atteso):
            return False
    return True


@login_required
def cerca_docenti(request):
    """Cerca docenti per nome, cognome, nome utente o email.

    Risponde in JSON a due tendine diverse: quella con cui il presidente compone
    la commissione e quella con cui lo studente sceglie il proprio tutor. In
    entrambi i casi la domanda e' la stessa ("quali docenti corrispondono a
    questo testo"), quindi l'endpoint e' uno solo.
    """
    if not (is_presidente(request.user) or is_studente(request.user)):
        raise PermissionDenied("Non hai i permessi per cercare i docenti.")
    if not _richiesta_interna(request):
        raise PermissionDenied("Questo endpoint è riservato all'applicazione.")

    termine = (request.GET.get("q") or "").strip()
    if len(termine) < 2:
        # Con una lettera sola i risultati sarebbero troppi per essere utili.
        return JsonResponse({"risultati": []})

    # Ogni parola digitata deve comparire in almeno uno dei campi: cosi'
    # "ada cig" trova "Ada Cigala" senza richiedere l'ordine esatto.
    docenti = User.objects.filter(groups__name="docente")
    for parola in termine.split():
        docenti = docenti.filter(
            Q(first_name__icontains=parola)
            | Q(last_name__icontains=parola)
            | Q(username__icontains=parola)
            | Q(email__icontains=parola)
        )

    docenti = docenti.distinct().order_by("last_name", "first_name", "username")

    risultati = [dati_utente(u) for u in docenti[:MAX_RISULTATI_RICERCA]]
    return JsonResponse({"risultati": risultati})


@login_required
def cerca_laureandi(request):
    """Cerca fra i propri laureandi e risponde con le righe gia' impaginate.

    Risponde HTML e non JSON perche' ogni riga porta con se' il modulo di
    valutazione, con il token CSRF e i valori gia' salvati: ricostruirlo in
    JavaScript vorrebbe dire riscrivere il template una seconda volta, e tenere
    allineate a mano due copie della stessa cosa.

    Il criterio di ricerca e' lo stesso della pagina: si riusano
    _laureandi_correnti e _corrisponde, gli stessi pezzi su cui si regge
    _laureandi_del_docente, cosi' con e senza JavaScript i risultati
    coincidono. Non si chiama direttamente _laureandi_del_docente perche'
    calcolerebbe anche i gruppi per appello, che questa risposta non usa.
    """
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti hanno dei laureandi.")
    if not _richiesta_interna(request):
        raise PermissionDenied("Questo endpoint è riservato all'applicazione.")

    termine = (request.GET.get("q") or "").strip()
    correnti = _laureandi_correnti(request.user)
    if termine:
        parole = termine.lower().split()
        trovati = [t for t in correnti if _corrisponde(t, parole)]
        # Stesso ordine dei risultati calcolati dalla pagina (vedi
        # _laureandi_del_docente): con e senza JavaScript si deve vedere
        # la stessa cosa, ordine compreso.
        trovati.sort(key=_chiave_alfabetica)
    else:
        trovati = []

    html = render_to_string(
        "appelli/_risultati_laureandi.html",
        {
            "laureandi_trovati": trovati,
            "laureandi_totali": len(correnti),
            "ricerca_laureandi": termine,
            "punteggio_massimo": PUNTEGGIO_MAX,
        },
        request=request,
    )
    return JsonResponse({"html": html, "numero": len(trovati)})


@login_required
def analizza_xlsx(request):
    """Legge l'elenco laureandi caricato e risponde con corso e studenti.

    Non salva niente: serve solo a compilare il form di creazione. L'appello
    e le iscrizioni nascono quando il presidente conferma.
    """
    if not is_presidente(request.user):
        raise PermissionDenied("Solo il presidente può caricare l'elenco.")
    if not _richiesta_interna(request):
        raise PermissionDenied("Questo endpoint è riservato all'applicazione.")
    if request.method != "POST":
        return JsonResponse({"errore": "Metodo non consentito."}, status=405)

    file_caricato = request.FILES.get("file")
    if not file_caricato:
        return JsonResponse({"errore": "Nessun file ricevuto."}, status=400)
    if not file_caricato.name.lower().endswith(".xlsx"):
        return JsonResponse(
            {"errore": "Il file deve essere in formato .xlsx."}, status=400
        )
    if file_caricato.size > MAX_BYTE_XLSX:
        return JsonResponse(
            {"errore": "Il file è troppo grande per essere un elenco laureandi."},
            status=400,
        )

    try:
        corso, email = leggi_elenco(file_caricato)
    except ErroreXlsx as exc:
        return JsonResponse({"errore": str(exc)}, status=400)

    # Gli studenti si riconoscono dall'email: chi non e' gia' nel database non
    # puo' essere iscritto, e va segnalato al presidente invece di sparire.
    # leggi_elenco restituisce gli indirizzi in minuscolo, mentre in anagrafica
    # possono comparire con delle maiuscole: il filtro
    # email__in le trova grazie alla collation di MySQL, che non distingue
    # maiuscole e minuscole, ma il dizionario va indicizzato in minuscolo
    # altrimenti il confronto qui sotto le scarterebbe.
    utenti = {
        u.email.lower(): u
        for u in User.objects.filter(groups__name="studente", email__in=email)
    }

    trovati, mancanti = [], []
    for indirizzo in email:
        utente = utenti.get(indirizzo)
        if utente:
            trovati.append(dati_utente(utente))
        else:
            mancanti.append(indirizzo)

    return JsonResponse(
        {
            "corso": corso,
            "studenti": trovati,
            "mancanti": mancanti,
            "totale_nel_file": len(email),
        }
    )


# --- Download protetto del file della tesi ---------------------------------

def _iscrizione_scaricabile(request, iscrizione_id):
    """Iscrizione richiesta, se l'utente ha diritto di vederne gli allegati.

    Il permesso e' lo stesso per tesi e video: lo studente proprietario, un
    docente della commissione di quell'appello, oppure il tutor. Il tutor
    va incluso esplicitamente perche' NON e' detto che sieda in commissione:
    senza, i link agli allegati dei propri studenti gli darebbero un 403.
    Tenerlo in un'unica funzione evita che i due percorsi di download divergano.
    """
    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea.objects.select_related("appello"), pk=iscrizione_id
    )

    e_proprietario = iscrizione.studente_id == request.user.pk
    e_commissario = is_docente(request.user) and docente_in_commissione(
        request.user, iscrizione.appello
    )
    e_tutor = is_docente(request.user) and is_tutor(request.user, iscrizione)
    if not (e_proprietario or e_commissario or e_tutor):
        raise PermissionDenied("Non hai i permessi per scaricare questo file.")

    return iscrizione


@login_required
def scarica_tesi(request, iscrizione_id):
    """Serve il file della tesi solo a chi ne ha diritto."""
    iscrizione = _iscrizione_scaricabile(request, iscrizione_id)

    if not iscrizione.file_tesi:
        raise Http404("Nessun file caricato per questa iscrizione.")

    return FileResponse(iscrizione.file_tesi.open("rb"), as_attachment=True)


@login_required
def scarica_video(request, iscrizione_id):
    """Serve il video di presentazione, con gli stessi permessi della tesi."""
    iscrizione = _iscrizione_scaricabile(request, iscrizione_id)

    if not iscrizione.file_video:
        raise Http404("Nessun video caricato per questa iscrizione.")

    return FileResponse(iscrizione.file_video.open("rb"), as_attachment=True)
