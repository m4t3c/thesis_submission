"""Viste dell'applicazione, divise per area (studente, docente, presidente).

I permessi si controllano SEMPRE qui, all'inizio di ogni view: i template si
limitano a nascondere quello che l'utente non puo' fare, ma nascondere un
pulsante non impedisce di inviare la richiesta a mano.
"""
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from django.template.defaultfilters import filesizeformat

from .forms import MAX_BYTE_VIDEO, AppelloForm, TesiUploadForm
from .models import (
    FORMATI_VIDEO,
    ORDINE_APPELLI,
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

    iscrizioni = request.user.iscrizioni.select_related("appello").order_by(
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
def iscriviti(request, appello_id):
    """Iscrive lo studente a un appello.

    L'iscrizione non e' annullabile dallo studente (non esiste alcun percorso
    di disiscrizione): un ripensamento va gestito dalla segreteria, come
    indicato nel messaggio di conferma.
    """
    # Il vincolo "solo gli studenti si iscrivono" e' applicato qui, lato view.
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono iscriversi a un appello.")
    if request.method != "POST":
        return redirect("appelli:studente_dashboard")

    appello = get_object_or_404(AppelloDiLaurea, pk=appello_id)
    iscrizione, created = StudenteAppelloDiLaurea.objects.get_or_create(
        studente=request.user, appello=appello
    )
    if created:
        messages.success(
            request,
            f"Iscrizione a «{appello.etichetta_pubblica}» effettuata. "
            "Per annullarla rivolgiti alla segreteria.",
        )
    else:
        messages.info(request, f"Sei gia' iscritto a «{appello.etichetta_pubblica}».")
    return redirect("appelli:studente_dashboard")


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

    if request.method == "POST":
        form = TesiUploadForm(request.POST, request.FILES, instance=iscrizione)
        if form.is_valid():
            form.save()
            if form.changed_data:
                messages.success(request, "Dati della tesi salvati correttamente.")
            else:
                messages.info(request, "Nessuna modifica da salvare.")
            return redirect("appelli:studente_dashboard")
    else:
        form = TesiUploadForm(instance=iscrizione)

    nome_file = os.path.basename(iscrizione.file_tesi.name) if iscrizione.file_tesi else ""
    nome_video = os.path.basename(iscrizione.file_video.name) if iscrizione.file_video else ""
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

def _contesto_appelli(utente, puo_creare, titolo):
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
    return {
        "miei_appelli": miei,
        "altri_appelli": altri,
        "puo_creare_appelli": puo_creare,
        "titolo_pagina": titolo,
    }


@login_required
def docente_dashboard(request):
    """Elenco degli appelli visto dal docente, senza il pulsante di creazione."""
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti possono accedere a questa pagina.")

    return render(
        request,
        "appelli/docente_dashboard.html",
        _contesto_appelli(request.user, puo_creare=False, titolo="Area Docente"),
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

    iscrizioni = appello.iscrizioni.select_related("studente")
    return render(
        request,
        "appelli/appello_detail.html",
        {
            "appello": appello,
            "iscrizioni": iscrizioni,
            # Un presidente e' anche docente: senza questo, "Torna indietro" lo
            # riporterebbe sempre nell'area docente, cioe' non da dove veniva.
            "url_ritorno": (
                "appelli:presidente_dashboard"
                if is_presidente(request.user)
                else "appelli:docente_dashboard"
            ),
        },
    )


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
        _contesto_appelli(request.user, puo_creare=True, titolo="Area Presidente"),
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

    Risponde in JSON alla tendina di composizione della commissione.
    """
    if not is_presidente(request.user):
        raise PermissionDenied("Solo il presidente può cercare i docenti.")
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

    risultati = [
        {
            "id": u.pk,
            "nome": u.first_name,
            "cognome": u.last_name,
            "username": u.get_username(),
            "email": u.email,
        }
        for u in docenti[:MAX_RISULTATI_RICERCA]
    ]
    return JsonResponse({"risultati": risultati})


# --- Download protetto del file della tesi ---------------------------------

def _iscrizione_scaricabile(request, iscrizione_id):
    """Iscrizione richiesta, se l'utente ha diritto di vederne gli allegati.

    Il permesso e' lo stesso per tesi e video: lo studente proprietario o un
    docente della commissione di quell'appello. Tenerlo in un'unica funzione
    evita che i due percorsi di download divergano.
    """
    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea.objects.select_related("appello"), pk=iscrizione_id
    )

    e_proprietario = iscrizione.studente_id == request.user.pk
    e_commissario = is_docente(request.user) and docente_in_commissione(
        request.user, iscrizione.appello
    )
    if not (e_proprietario or e_commissario):
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
