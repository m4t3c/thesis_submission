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


def is_relatore(utente, iscrizione):
    """True se l'utente e' il relatore (tutor) di quella iscrizione."""
    return iscrizione.tutor_id == utente.pk


def puo_valutare(utente, iscrizione):
    """Chi puo' correggere titolo, punteggio e giudizio: il solo relatore.

    Non basta essere docente e non basta essere in commissione: la valutazione
    e' una proposta personale di chi ha seguito la tesi, e solo lui la scrive.
    """
    return is_docente(utente) and is_relatore(utente, iscrizione)


# --- Pagina di test Shibboleth --------------------------------------------

def shibboleth_test(request):
    """Stampa tutti gli attributi che il server passa a Django (request.META).

    Serve a verificare i nomi reali degli attributi Shibboleth (uid, ou, sn,
    givenName, ...) sul dominio di produzione, prima di configurare
    shibboleth.py. ATTENZIONE: espone dati sensibili (cookie di sessione,
    header) -> da RIMUOVERE o proteggere una volta finiti i test.
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
    """Pagina dello studente: le sue iscrizioni e gli appelli a cui puo' iscriversi.

    I due elenchi sono complementari: un appello a cui lo studente e' gia'
    iscritto non deve ricomparire fra quelli disponibili, altrimenti il
    pulsante "Iscriviti" prometterebbe un'azione che non ha piu' effetto.
    """
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono accedere a questa pagina.")

    iscrizioni = request.user.iscrizioni.select_related("appello", "tutor").order_by(
        "appello__data", F("appello__ora").asc(nulls_last=True)
    )
    appelli_iscritti = iscrizioni.values_list("appello_id", flat=True)
    # L'ordine (dal piu' vecchio) arriva dal Meta di AppelloDiLaurea.
    appelli_disponibili = AppelloDiLaurea.objects.exclude(
        pk__in=list(appelli_iscritti)
    )

    return render(
        request,
        "appelli/studente_dashboard.html",
        {
            "iscrizioni": iscrizioni,
            "appelli_disponibili": appelli_disponibili,
        },
    )


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
        },
    )


# --- Area docente ----------------------------------------------------------

def _contesto_appelli(request, puo_creare, titolo, filtri=None):
    utente = request.user
    """Contesto della pagina appelli, condiviso da docenti e presidente.

    Le due pagine mostrano le stesse due tabelle ("i miei appelli" e gli
    altri): al presidente si aggiunge soltanto il pulsante di creazione. Un
    unico contesto evita che le due viste divergano col tempo.
    """
    def elenco(queryset):
        # order_by esplicito: con annotate() il Meta.ordering non viene
        # applicato (vedi ORDINE_APPELLI in models.py).
        return (
            queryset.select_related("commissione")
            .annotate(numero_iscritti=Count("iscrizioni"))
            .distinct()
            .order_by(*ORDINE_APPELLI)
        )

    miei = elenco(AppelloDiLaurea.objects.filter(commissione__docenti=utente))
    altri = elenco(AppelloDiLaurea.objects.exclude(commissione__docenti=utente))

    contesto = {
        "miei_appelli": miei,
        "altri_appelli": altri,
        "puo_creare_appelli": puo_creare,
        "titolo_pagina": titolo,
    }
    contesto.update(_tutorati_del_docente(request, utente, filtri))
    return contesto


# Filtri della sezione tutorati. Sono anche gli unici parametri che vengono
# riportati nell'URL dopo un salvataggio: tutto il resto viene scartato.
PARAMETRI_TUTORATI = ("q",)


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


def _tutorati_correnti(utente):
    """Iscrizioni di cui l'utente e' relatore, con il modulo gia' agganciato.

    Solo appelli non ancora passati: una tesi discussa non si valuta piu', e
    tenere in pagina anni di archivio renderebbe la sezione inservibile proprio
    per cio' a cui serve, cioe' vedere su chi si deve ancora intervenire.

    Costa UNA query, qualunque sia il numero di tutorati: studente e appello
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
    # sono tanti quanti i tutorati, e con gli id predefiniti ("id_titolo",
    # "id_punteggio_0", ...) ogni <label> punterebbe al campo del PRIMO modulo.
    for iscrizione in righe:
        iscrizione.form = ValutazioneForm(
            instance=iscrizione, auto_id=f"id_%s_{iscrizione.pk}"
        )
    return righe


def _tutorati_del_docente(request, utente, filtri=None):
    """Sezione tutorati pronta per il template: gruppi ed eventuali risultati.

    Non ha relazione con gli appelli delle proprie commissioni: si puo' essere
    relatore di uno studente senza sedere nella commissione che lo esamina,
    quindi l'elenco si costruisce a parte.

    I gruppi si calcolano SEMPRE, anche durante una ricerca: cosi' annullarla
    e' immediato, perche' l'elenco completo e' gia' nella pagina e non va
    richiesto di nuovo al server.
    """
    if filtri is None:
        termine = (request.GET.get("q") or "").strip()
    else:
        # Filtri espliciti: arrivano dal campo "ritorno" di una POST, dove la
        # querystring non c'e'. Si tiene solo cio' che e' un filtro noto, come
        # fa _url_ritorno_tutorati: il valore viene dal browser.
        voci = dict((c, v) for c, v in filtri if c in PARAMETRI_TUTORATI)
        termine = (voci.get("q") or "").strip()
    correnti = _tutorati_correnti(utente)

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

    return {
        "tutorati_trovati": trovati,
        "tutorati_gruppi": gruppi,
        "tutorati_totali": len(correnti),
        "ricerca_tutorati": termine,
        "punteggio_massimo": PUNTEGGIO_MAX,
    }


@login_required
def docente_dashboard(request):
    """Elenco degli appelli visto dal docente, senza il pulsante di creazione."""
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

    return render(
        request,
        "appelli/appello_detail.html",
        {
            "appello": appello,
            "iscrizioni": iscrizioni,
            "iscritti_miei": miei,
            "iscritti_altri": altri,
            # Un presidente e' anche docente: senza questo, "Torna indietro" lo
            # riporterebbe sempre nell'area docente, cioe' non da dove veniva.
            "url_ritorno": (
                "appelli:presidente_dashboard"
                if is_presidente(request.user)
                else "appelli:docente_dashboard"
            ),
        },
    )


def _url_ritorno_tutorati(request, iscrizione):
    """Dove tornare dopo un salvataggio: stessa pagina, stessi filtri, stessa riga.

    Del "ritorno" ricevuto si tengono SOLO i filtri della sezione e si
    ricostruisce il percorso con reverse(): cosi' un valore manomesso non puo'
    trasformare il salvataggio in un rimando verso un sito esterno.
    """
    nome = (
        "appelli:presidente_dashboard"
        if is_presidente(request.user)
        else "appelli:docente_dashboard"
    )
    coppie = [
        (chiave, valore)
        for chiave, valore in parse_qsl(request.POST.get("ritorno", ""))
        if chiave in PARAMETRI_TUTORATI
    ]
    url = reverse(nome)
    if coppie:
        url += "?" + urlencode(coppie)
    # L'ancora riporta alla riga appena salvata invece che in cima all'elenco.
    return f"{url}#tutorato-{iscrizione.pk}"


@login_required
def salva_valutazione(request, iscrizione_id):
    """Titolo, punti e giudizio di un proprio tutorato, salvati dal relatore."""
    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea.objects.select_related("studente", "appello"),
        pk=iscrizione_id,
    )
    # Il controllo sta qui e non nel template: nascondere il pulsante non
    # impedisce a un altro docente di inviare la richiesta a mano.
    if not puo_valutare(request.user, iscrizione):
        raise PermissionDenied("Solo il relatore può valutare questo studente.")
    if request.method != "POST":
        return redirect(_url_ritorno_tutorati(request, iscrizione))

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
        return redirect(_url_ritorno_tutorati(request, iscrizione))

    # Errore: si RIDISEGNA la pagina con dentro questo modulo, invece di
    # rimandare alla dashboard. Con il rimando il pannello si sarebbe richiuso
    # e quanto scritto sarebbe andato perso: chi aveva compilato solo il
    # giudizio avrebbe dovuto riscriverlo daccapo.
    return _pagina_con_valutazione_da_correggere(request, iscrizione, form)


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
    for gruppo in contesto["tutorati_gruppi"]:
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
def cerca_tutorati(request):
    """Cerca fra i propri tutorati e risponde con le righe gia' impaginate.

    Risponde HTML e non JSON perche' ogni riga porta con se' il modulo di
    valutazione, con il token CSRF e i valori gia' salvati: ricostruirlo in
    JavaScript vorrebbe dire riscrivere il template una seconda volta, e tenere
    allineate a mano due copie della stessa cosa.

    La ricerca vera e' la stessa della pagina (_tutorati_del_docente): qui si
    riusa, non si riscrive, cosi' con e senza JavaScript i risultati coincidono.
    """
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti hanno dei tutorati.")
    if not _richiesta_interna(request):
        raise PermissionDenied("Questo endpoint è riservato all'applicazione.")

    termine = (request.GET.get("q") or "").strip()
    correnti = _tutorati_correnti(request.user)
    if termine:
        parole = termine.lower().split()
        trovati = [t for t in correnti if _corrisponde(t, parole)]
    else:
        trovati = []

    html = render_to_string(
        "appelli/_risultati_tutorati.html",
        {
            "tutorati_trovati": trovati,
            "tutorati_totali": len(correnti),
            "ricerca_tutorati": termine,
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
    docente della commissione di quell'appello, oppure il relatore. Il relatore
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
    e_relatore = is_docente(request.user) and is_relatore(request.user, iscrizione)
    if not (e_proprietario or e_commissario or e_relatore):
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
