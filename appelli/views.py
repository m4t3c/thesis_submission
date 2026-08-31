import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import TesiUploadForm
from .models import AppelloDiLaurea, StudenteAppelloDiLaurea


# --- Helper per i ruoli (basati sui gruppi di Django) ---------------------

def is_studente(user):
    return user.groups.filter(name="studente").exists()


def is_docente(user):
    return user.groups.filter(name="docente").exists()


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
    if is_docente(request.user):
        return redirect("appelli:docente_dashboard")
    # Nessun gruppo noto: l'affiliation Shibboleth non corrisponde ne' al
    # profilo studente ne' a quello docente. 403 e non 200 perche' e' a tutti
    # gli effetti un rifiuto (e non va indicizzato ne' messo in cache).
    return render(request, "appelli/accesso_negato.html", status=403)


# --- Area studente ---------------------------------------------------------

@login_required
def studente_dashboard(request):
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono accedere a questa pagina.")

    iscrizioni = request.user.iscrizioni.select_related("appello")
    appelli_iscritti = iscrizioni.values_list("appello_id", flat=True)
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
            request, f"Iscrizione a «{appello.etichetta_pubblica}» effettuata."
        )
    else:
        messages.info(request, f"Sei gia' iscritto a «{appello.etichetta_pubblica}».")
    return redirect("appelli:studente_dashboard")


@login_required
def disiscriviti(request, iscrizione_id):
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono disiscriversi.")
    if request.method != "POST":
        return redirect("appelli:studente_dashboard")

    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea.objects.select_related("appello"),
        pk=iscrizione_id,
        studente=request.user,
    )
    appello = iscrizione.appello
    # Il file della tesi eventualmente caricato viene rimosso dal disco in
    # automatico da django-cleanup (signal post_delete).
    iscrizione.delete()
    messages.success(
        request, f"Disiscrizione da «{appello.etichetta_pubblica}» effettuata."
    )
    return redirect("appelli:studente_dashboard")


@login_required
def carica_tesi(request, iscrizione_id):
    if not is_studente(request.user):
        raise PermissionDenied("Solo gli studenti possono caricare la tesi.")

    iscrizione = get_object_or_404(
        StudenteAppelloDiLaurea, pk=iscrizione_id, studente=request.user
    )

    if request.method == "POST":
        form = TesiUploadForm(request.POST, request.FILES, instance=iscrizione)
        if form.is_valid():
            form.save()
            # Il form accetta l'invio senza un nuovo file solo quando una tesi
            # e' gia' presente (in quel caso resta quella): distinguiamo i due
            # casi per non dire "caricato" quando non e' cambiato nulla.
            if "file_tesi" in form.changed_data:
                messages.success(request, "File della tesi caricato correttamente.")
            else:
                messages.info(request, "Nessun nuovo file scelto: la tesi resta invariata.")
            return redirect("appelli:studente_dashboard")
    else:
        form = TesiUploadForm(instance=iscrizione)

    nome_file = os.path.basename(iscrizione.file_tesi.name) if iscrizione.file_tesi else ""
    return render(
        request,
        "appelli/carica_tesi.html",
        {"form": form, "iscrizione": iscrizione, "nome_file": nome_file},
    )


# --- Area docente ----------------------------------------------------------

@login_required
def docente_dashboard(request):
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti possono accedere a questa pagina.")

    commissioni = request.user.commissioni.prefetch_related("appelli")
    return render(
        request,
        "appelli/docente_dashboard.html",
        {"commissioni": commissioni},
    )


@login_required
def appello_detail(request, appello_id):
    if not is_docente(request.user):
        raise PermissionDenied("Solo i docenti possono accedere a questa pagina.")

    appello = get_object_or_404(
        AppelloDiLaurea.objects.select_related("commissione"), pk=appello_id
    )
    if not docente_in_commissione(request.user, appello):
        raise PermissionDenied("Non fai parte della commissione di questo appello.")

    iscrizioni = appello.iscrizioni.select_related("studente")
    return render(
        request,
        "appelli/appello_detail.html",
        {"appello": appello, "iscrizioni": iscrizioni},
    )


# --- Download protetto del file della tesi ---------------------------------

@login_required
def scarica_tesi(request, iscrizione_id):
    """Serve il file della tesi solo allo studente proprietario o ai docenti
    della commissione dell'appello relativo."""
    iscrizione = get_object_or_404(StudenteAppelloDiLaurea, pk=iscrizione_id)

    e_proprietario = iscrizione.studente_id == request.user.pk
    e_commissario = is_docente(request.user) and docente_in_commissione(
        request.user, iscrizione.appello
    )
    if not (e_proprietario or e_commissario):
        raise PermissionDenied("Non hai i permessi per scaricare questo file.")

    if not iscrizione.file_tesi:
        raise Http404("Nessun file caricato per questa iscrizione.")

    return FileResponse(iscrizione.file_tesi.open("rb"), as_attachment=True)
