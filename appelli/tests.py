"""Test dell'applicazione, raggruppati per regola verificata.

Ogni classe copre una singola regola del dominio (chi accede a cosa, quali
file sono ammessi, che cosa identifica un appello) e ne verifica sia il caso
consentito sia quello vietato: e' il secondo a documentare davvero il vincolo.
I controlli passano dal client HTTP, non dai soli modelli, perche' gran parte
delle regole vive nelle view e nei form.

Uso:  python manage.py test appelli
"""
import datetime
import os
import re
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.mail.backends.base import BaseEmailBackend
from django.db import IntegrityError, connection, transaction
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .forms import MAX_BYTE_VIDEO
from .models import (
    PUNTEGGIO_MAX,
    AppelloDiLaurea,
    Commissione,
    StudenteAppelloDiLaurea,
)


# --- File caricati: una cartella usa e getta per l'intera esecuzione ---------
# Senza, i test scriverebbero nella MEDIA_ROOT vera (in Docker e' ./media del
# progetto, montata dal disco) e ci lascerebbero dei resti: i file sostituiti
# li cancella django-cleanup solo a transazione confermata, e TestCase non
# conferma mai. Il database di test riparte dagli stessi id a ogni esecuzione,
# quindi quei resti finiscono proprio nelle cartelle dei test successivi e ne
# falsano i controlli sul contenuto della cartella.
_MEDIA_DI_PROVA = None
_media_override = None


def setUpModule():
    global _MEDIA_DI_PROVA, _media_override
    _MEDIA_DI_PROVA = tempfile.mkdtemp(prefix="media-test-")
    # override_settings avvisa gli storage (setting_changed), che ricalcolano
    # la cartella: vale anche per SovrascriviStorage, creato senza location.
    _media_override = override_settings(MEDIA_ROOT=_MEDIA_DI_PROVA)
    _media_override.enable()


def tearDownModule():
    _media_override.disable()
    shutil.rmtree(_MEDIA_DI_PROVA, ignore_errors=True)


class BaseSetup(TestCase):
    """Scenario minimo comune: uno studente, un docente e un appello.

    I gruppi si leggono e non si creano: esistono gia' perche' li inserisce la
    migrazione 0002, che e' esattamente la garanzia che si vuole verificare.
    """

    def setUp(self):
        self.g_studente = Group.objects.get(name="studente")
        self.g_docente = Group.objects.get(name="docente")

        self.studente = User.objects.create_user("studente_test", password="pw")
        self.studente.groups.add(self.g_studente)

        self.docente = User.objects.create_user("docente_test", password="pw")
        self.docente.groups.add(self.g_docente)

        self.commissione = Commissione.objects.create(nome="Commissione A")
        self.commissione.docenti.add(self.docente)

        self.appello = AppelloDiLaurea.objects.create(
            data=datetime.date(2030, 1, 1),
            corso_di_laurea="Informatica",
            commissione=self.commissione,
        )


class RuoliTest(BaseSetup):
    """Smistamento per ruolo e confini fra le aree."""

    # I due casi seguenti seguono la catena (follow=True) invece di aspettarsi
    # un salto solo: da quando esiste la landing pubblica, "/" rimanda a
    # "/dashboard/", che a sua volta smista al ruolo. Cio' che conta e' dove si
    # arriva, non quanti passaggi servono.
    def test_studente_redirezione_home(self):
        self.client.force_login(self.studente)
        resp = self.client.get(reverse("appelli:home"), follow=True)
        self.assertEqual(
            resp.redirect_chain[-1][0], reverse("appelli:studente_dashboard")
        )

    def test_docente_redirezione_home(self):
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:home"), follow=True)
        self.assertEqual(
            resp.redirect_chain[-1][0], reverse("appelli:docente_dashboard")
        )

    def test_docente_non_accede_area_studente(self):
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:studente_dashboard"))
        self.assertEqual(resp.status_code, 403)


class IscrizioneManualeRimossaTest(BaseSetup):
    """Ci si iscrive solo tramite l'elenco caricato dal presidente."""

    def test_rotta_inesistente(self):
        with self.assertRaises(NoReverseMatch):
            reverse("appelli:iscriviti", args=[self.appello.id])

    def test_nessun_endpoint_di_iscrizione_risponde(self):
        self.client.force_login(self.studente)
        for percorso in (
            f"/appelli/{self.appello.id}/iscriviti/",
            f"/appelli/{self.appello.id}/iscriviti",
        ):
            with self.subTest(percorso=percorso):
                self.assertEqual(self.client.post(percorso).status_code, 404)
        self.assertFalse(StudenteAppelloDiLaurea.objects.exists())

    def test_dashboard_senza_azione_di_iscrizione(self):
        """L'elenco resta visibile, ma senza nessun modo di iscriversi.

        Si guarda il MECCANISMO dentro la tabella (un form da inviare, un
        pulsante da premere), non la parola "Iscriviti": quella puo'
        ricomparire in un testo qualunque - per esempio nel rimando a esse3 -
        senza che il pulsante sia tornato, e un test che la cerca fallirebbe
        per un motivo che non c'entra con cio' che deve difendere.
        """
        self.client.force_login(self.studente)
        testo = self.client.get(
            reverse("appelli:studente_dashboard")
        ).content.decode()

        # L'elenco degli appelli disponibili resta comunque visibile
        self.assertIn("Appelli disponibili", testo)

        inizio = testo.index("Appelli disponibili")
        fine = testo.find("</table>", inizio)
        self.assertNotEqual(fine, -1, "la tabella degli appelli disponibili non c'e'")
        tabella = testo[inizio:fine]
        self.assertNotIn("<form", tabella)
        self.assertNotIn("<button", tabella)


class DisiscrizioneRimossaTest(BaseSetup):
    """Lo studente non puo' piu' disiscriversi, in nessun modo."""

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.client.force_login(self.studente)

    def test_rotta_inesistente(self):
        """Non basta togliere il pulsante: l'endpoint non deve esistere."""
        with self.assertRaises(NoReverseMatch):
            reverse("appelli:disiscriviti", args=[self.iscrizione.id])

    def test_nessun_endpoint_di_disiscrizione_risponde(self):
        for percorso in (
            f"/iscrizioni/{self.iscrizione.id}/disiscriviti/",
            f"/iscrizioni/{self.iscrizione.id}/disiscriviti",
        ):
            with self.subTest(percorso=percorso):
                resp = self.client.post(percorso)
                self.assertEqual(resp.status_code, 404)
        self.assertTrue(
            StudenteAppelloDiLaurea.objects.filter(pk=self.iscrizione.pk).exists()
        )

    def test_dashboard_senza_pulsante(self):
        testo = self.client.get(reverse("appelli:studente_dashboard")).content.decode()
        self.assertNotIn("Disiscriviti", testo)
        # Resta la sola azione disponibile: aprire la pagina della tesi.
        self.assertIn(
            reverse("appelli:carica_tesi", args=[self.iscrizione.id]), testo
        )


class DownloadTesiTest(BaseSetup):
    """La tesi la scarica solo chi ne ha diritto.

    E' il controllo piu' delicato dell'applicazione: l'URL di download contiene
    l'id dell'iscrizione, quindi senza una verifica dei permessi basterebbe
    cambiare un numero per leggere la tesi di un altro studente.
    """

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente,
            appello=self.appello,
            file_tesi=SimpleUploadedFile("tesi.pdf", b"contenuto pdf"),
        )

    def test_docente_commissione_scarica(self):
        self.client.force_login(self.docente)
        resp = self.client.get(
            reverse("appelli:scarica_tesi", args=[self.iscrizione.id])
        )
        self.assertEqual(resp.status_code, 200)

    def test_docente_estraneo_non_scarica(self):
        altro = User.objects.create_user("docente_estraneo", password="pw")
        altro.groups.add(self.g_docente)
        self.client.force_login(altro)
        resp = self.client.get(
            reverse("appelli:scarica_tesi", args=[self.iscrizione.id])
        )
        self.assertEqual(resp.status_code, 403)

    def tearDown(self):
        # I file caricati finiscono in MEDIA_ROOT, che i test non ripuliscono
        # da soli: senza questa cancellazione resterebbero sul disco.
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)


class CaricamentoTesiTest(BaseSetup):
    """Regole sul file della tesi: solo PDF e nessuna rimozione."""

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.url = reverse("appelli:carica_tesi", args=[self.iscrizione.id])
        self.client.force_login(self.studente)

    def tearDown(self):
        self.iscrizione.refresh_from_db()
        for campo in (self.iscrizione.file_tesi, self.iscrizione.file_video):
            if campo:
                campo.delete(save=False)

    TITOLO = "Un titolo di tesi"

    def _pdf(self, nome="tesi.pdf"):
        return SimpleUploadedFile(nome, b"%PDF-1.7 contenuto", content_type="application/pdf")

    def _dati(self, **extra):
        """POST con titolo e tutor: la tesi, che va in coppia col titolo, la
        aggiunge il singolo test."""
        dati = {
            "titolo": self.TITOLO,
            "tutor": self.docente.pk,
            "modalita_video": "nessuno",
        }
        dati.update(extra)
        return dati

    def test_pdf_accettato(self):
        resp = self.client.post(self.url, self._dati(file_tesi=self._pdf()))
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertTrue(self.iscrizione.file_tesi)

    def test_estensione_non_pdf_rifiutata(self):
        file = SimpleUploadedFile("tesi.docx", b"contenuto", content_type="application/msword")
        resp = self.client.post(self.url, self._dati(file_tesi=file))
        self.assertEqual(resp.status_code, 200)  # resta sul form con l'errore
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_tesi)

    def test_finto_pdf_rifiutato(self):
        # Estensione e content-type giusti, ma il contenuto non e' un PDF.
        file = SimpleUploadedFile("tesi.pdf", b"PK\x03\x04 zip", content_type="application/pdf")
        resp = self.client.post(self.url, self._dati(file_tesi=file))
        self.assertEqual(resp.status_code, 200)
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_tesi)

    def test_file_non_rimovibile(self):
        self.client.post(self.url, self._dati(file_tesi=self._pdf()))
        self.iscrizione.refresh_from_db()
        nome_iniziale = self.iscrizione.file_tesi.name

        # Tentativo di svuotamento: checkbox "clear" di Django e invio senza
        # file. Entrambi i POST sono per il resto validi, cosi' il test misura
        # davvero il meccanismo di rimozione e non un errore di validazione.
        self.client.post(self.url, self._dati(**{"file_tesi-clear": "on"}))
        self.client.post(self.url, self._dati())

        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.file_tesi.name, nome_iniziale)

    def test_sostituzione_consentita(self):
        self.client.post(self.url, self._dati(file_tesi=self._pdf("prima.pdf")))
        self.iscrizione.refresh_from_db()
        primo = self.iscrizione.file_tesi.name

        self.client.post(self.url, self._dati(file_tesi=self._pdf("seconda.pdf")))
        self.iscrizione.refresh_from_db()
        self.assertNotEqual(self.iscrizione.file_tesi.name, primo)
        self.assertIn("seconda", self.iscrizione.file_tesi.name)

    def test_titolo_senza_tesi_da_errore(self):
        resp = self.client.post(self.url, self._dati())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "carica anche il file della tesi")

    def test_stesso_nome_non_viene_rinominato(self):
        """Ricaricare un file con lo stesso nome non aggiunge suffissi casuali."""
        self.client.post(self.url, self._dati(file_tesi=self._pdf("tesi.pdf")))
        self.iscrizione.refresh_from_db()
        primo = self.iscrizione.file_tesi.name
        self.assertTrue(primo.endswith("/tesi.pdf"), primo)

        nuovo = SimpleUploadedFile(
            "tesi.pdf", b"%PDF-1.7 versione aggiornata", content_type="application/pdf"
        )
        self.client.post(self.url, self._dati(file_tesi=nuovo))
        self.iscrizione.refresh_from_db()

        # Stesso percorso di prima e contenuto aggiornato: e' stato sovrascritto.
        self.assertEqual(self.iscrizione.file_tesi.name, primo)
        with self.iscrizione.file_tesi.open("rb") as f:
            self.assertEqual(f.read(), b"%PDF-1.7 versione aggiornata")

        # Nella cartella dell'iscrizione resta un solo file.
        cartella = os.path.dirname(self.iscrizione.file_tesi.path)
        self.assertEqual(os.listdir(cartella), ["tesi.pdf"])


class StatoConsegnaTest(BaseSetup):
    """Il riepilogo "stato consegna" della pagina della tesi.

    Riassume le TRE cose da consegnare (titolo, tutor, tesi) e va letto come
    "cosa risulta consegnato", non come "cosa ho scritto nel modulo": e' la
    differenza che questi test tengono ferma.
    """

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.url = reverse("appelli:carica_tesi", args=[self.iscrizione.id])
        self.client.force_login(self.studente)

    def tearDown(self):
        self.iscrizione.refresh_from_db()
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)

    def _stato(self):
        stato = self.client.get(self.url).context["stato_consegna"]
        return stato, {v["nome"]: v["fatto"] for v in stato["voci"]}

    def test_iscrizione_appena_creata_non_ha_niente_di_fatto(self):
        stato, fatte = self._stato()
        self.assertEqual(stato["fatte"], 0)
        self.assertEqual(stato["totale"], 3)
        self.assertEqual(fatte, {"Titolo": False, "Tutor": False, "Tesi": False})

    def test_conta_solo_le_voci_salvate(self):
        self.iscrizione.titolo = "Un titolo"
        self.iscrizione.tutor = self.docente
        self.iscrizione.save()

        stato, fatte = self._stato()
        self.assertEqual(stato["fatte"], 2)
        self.assertEqual(fatte, {"Titolo": True, "Tutor": True, "Tesi": False})

    def test_tutto_consegnato(self):
        self.iscrizione.titolo = "Un titolo"
        self.iscrizione.tutor = self.docente
        self.iscrizione.file_tesi.save(
            "tesi.pdf", SimpleUploadedFile("tesi.pdf", b"%PDF-1.7 x"), save=True
        )

        stato, fatte = self._stato()
        self.assertEqual(stato["fatte"], 3)
        self.assertEqual(stato["percentuale"], 100)
        self.assertTrue(all(fatte.values()))

    def test_il_video_non_entra_nel_conteggio(self):
        """E' facoltativo: fra le voci mancanti sembrerebbe necessario."""
        stato, _ = self._stato()
        self.assertEqual([v["nome"] for v in stato["voci"]], ["Titolo", "Tutor", "Tesi"])

    def test_un_invio_rifiutato_non_risulta_consegnato(self):
        """La parte delicata: niente e' stato salvato, niente deve dirsi fatto.

        Su un POST non valido il ModelForm copia comunque i dati ricevuti
        dentro l'istanza. Se il riepilogo venisse calcolato dopo la
        validazione mostrerebbe titolo e tutor come acquisiti, mentre il
        database e' rimasto vuoto.
        """
        # Titolo senza tesi, che vanno a coppia: l'invio viene rifiutato.
        resp = self.client.post(self.url, {
            "titolo": "Un titolo mai salvato",
            "tutor": self.docente.pk,
            "modalita_video": "nessuno",
        })
        self.assertEqual(resp.status_code, 200)       # resta sulla pagina
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.titolo)      # davvero non salvato

        stato = resp.context["stato_consegna"]
        self.assertEqual(stato["fatte"], 0)
        self.assertTrue(all(not v["fatto"] for v in stato["voci"]))

class UnicitaAppelloTest(BaseSetup):
    """Data + corso + commissione identificano un appello."""

    def _altro_appello(self, commissione, ora=None):
        return AppelloDiLaurea.objects.create(
            data=self.appello.data,
            ora=ora,
            corso_di_laurea=self.appello.corso_di_laurea,
            commissione=commissione,
        )

    def test_stessa_data_e_corso_con_commissioni_diverse(self):
        """Il caso che prima era vietato: ora deve funzionare."""
        altra = Commissione.objects.create(nome="Commissione B")
        altra.docenti.add(self.docente)
        secondo = self._altro_appello(altra)
        # Filtrato per data e corso: nel database di test c'e' anche l'appello
        # creato dalla migrazione dei dati demo (0003).
        omonimi = AppelloDiLaurea.objects.filter(
            data=self.appello.data, corso_di_laurea=self.appello.corso_di_laurea
        )
        self.assertEqual(omonimi.count(), 2)
        self.assertNotEqual(secondo.commissione, self.appello.commissione)

    def test_tripletta_duplicata_rifiutata(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._altro_appello(self.commissione)

    def test_orario_non_rende_unico(self):
        """Stessa commissione, stesso giorno, orari diversi: resta un duplicato."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._altro_appello(self.commissione, ora=datetime.time(15, 0))

    def test_orario_facoltativo_e_str(self):
        senza = self.appello
        self.assertIsNone(senza.ora)
        self.assertNotIn("ore", str(senza))

        altra = Commissione.objects.create(nome="Commissione B")
        con = self._altro_appello(altra, ora=datetime.time(9, 30))
        # Lo __str__ distingue i due appelli, altrimenti indistinguibili.
        self.assertIn("09:30", str(con))
        self.assertIn(f"commissione {altra.pk}", str(con))
        # Il nome non deve comparire: la commissione e' solo il suo id.
        self.assertNotIn("Commissione B", str(con))
        self.assertNotEqual(str(con), str(senza))

    def test_studente_sceglie_tra_appelli_omonimi_senza_vedere_commissione(self):
        altra = Commissione.objects.create(nome="Commissione B")
        secondo = self._altro_appello(altra, ora=datetime.time(9, 30))

        self.client.force_login(self.studente)
        resp = self.client.get(reverse("appelli:studente_dashboard"))
        testo = resp.content.decode()
        # L'orario distingue i due appelli...
        self.assertIn("09:30", testo)
        # ...ma la commissione non deve mai comparire allo studente.
        self.assertNotIn("Commissione A", testo)
        self.assertNotIn("Commissione B", testo)

        # L'orario resta l'unico elemento che li distingue.
        self.assertIn(secondo.ora.strftime("%H:%M"), testo)

    def test_pagine_dello_studente_senza_commissione(self):
        """Le pagine dello studente non nominano mai la commissione."""
        StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.client.force_login(self.studente)
        resp = self.client.get(reverse("appelli:studente_dashboard"))
        self.assertNotIn("Commissione A", resp.content.decode())

    def test_etichetta_pubblica_e_str(self):
        altra = Commissione.objects.create(nome="Commissione B")
        appello = self._altro_appello(altra, ora=datetime.time(9, 30))
        # Pubblica: corso, data, ora. Mai la commissione.
        self.assertIn("09:30", appello.etichetta_pubblica)
        self.assertNotIn("Commissione", appello.etichetta_pubblica)
        # Completa (solo area amministrativa): include l'identificativo.
        self.assertIn(f"commissione {altra.pk}", str(appello))


# Il middleware Shibboleth in produzione e' inserito solo se SHIB_ENABLED=1.
# Qui lo si attiva esplicitamente per poter simulare gli header del SP.
MIDDLEWARE_SHIB = list(settings.MIDDLEWARE) + [
    "thesis_submission.assign_user.AssignUserMiddleware"
]


@override_settings(MIDDLEWARE=MIDDLEWARE_SHIB)
class AffiliationTest(TestCase):
    """Assegnazione del ruolo a partire dall'affiliation Shibboleth.

    Simula gli header che il SP passa attraverso il reverse proxy, cosi' i tre
    profili (studente, docente, estraneo) sono verificabili senza disporre di
    un account reale per ognuno.
    """

    STUDENTE = "member@unimore.it;student@unimore.it"
    DOCENTE = "member@unimore.it;employee@unimore.it;faculty@unimore.it"

    def _accedi(self, uid, affiliation=None, header="HTTP_X_SHIB_AFFILIATION", **extra):
        meta = {"HTTP_X_SHIB_UID": uid}
        if affiliation is not None:
            meta[header] = affiliation
        meta.update(extra)
        return self.client.get(reverse("appelli:dashboard"), **meta)

    def _gruppi(self, uid):
        return set(
            User.objects.get(username=uid).groups.values_list("name", flat=True)
        )

    def test_studente_riconosciuto(self):
        resp = self._accedi("s123456", self.STUDENTE)
        self.assertRedirects(
            resp,
            reverse("appelli:studente_dashboard"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self._gruppi("s123456"), {"studente"})

    def test_docente_riconosciuto(self):
        resp = self._accedi("mrossi", self.DOCENTE)
        self.assertRedirects(
            resp,
            reverse("appelli:docente_dashboard"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self._gruppi("mrossi"), {"docente"})

    def test_nome_header_con_prefisso(self):
        """Per i docenti l'header ha un prefisso davanti a "affiliation"."""
        resp = self._accedi(
            "mrossi", self.DOCENTE, header="HTTP_X_SHIB_UNSCOPED_AFFILIATION"
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._gruppi("mrossi"), {"docente"})

    def test_estraneo_riceve_pagina_di_rifiuto(self):
        """Es. personale tecnico-amministrativo: member + employee, senza faculty."""
        resp = self._accedi("ttecnico", "member@unimore.it;employee@unimore.it")
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "Accesso non consentito", status_code=403)
        self.assertEqual(self._gruppi("ttecnico"), set())

    def test_affiliation_assente_riceve_rifiuto(self):
        resp = self._accedi("ignoto")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("ignoto"), set())

    def test_affiliation_parziale_non_basta(self):
        """Il solo "student" senza "member" non e' una combinazione valida."""
        resp = self._accedi("s999", "student@unimore.it")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("s999"), set())

    def test_scope_di_altro_ateneo_rifiutato(self):
        """Uno studente di un altro ateneo federato non e' studente qui."""
        resp = self._accedi("s888", "member@unibo.it;student@unibo.it")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("s888"), set())

    def test_scope_misto_non_riconosciuto(self):
        """Solo i valori con scope unimore.it contano: qui resta {member}."""
        resp = self._accedi("s889", "member@unimore.it;student@unibo.it")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("s889"), set())

    def test_scope_simile_non_inganna(self):
        """Un dominio che "contiene" unimore.it non deve passare."""
        for finto in ("student@unimore.it.example.com", "student@notunimore.it"):
            with self.subTest(scope=finto):
                self.client.logout()
                resp = self._accedi("s890", f"member@unimore.it;{finto}")
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(self._gruppi("s890"), set())

    def test_valori_senza_scope_accettati(self):
        """Forma non-scoped dello stesso attributo: va riconosciuta."""
        self._accedi("s891", "member;student")
        self.assertEqual(self._gruppi("s891"), {"studente"})

    def test_docente_senza_scope_accettato(self):
        """Il caso che non abbiamo ancora potuto verificare sul SP reale."""
        self._accedi("mrossi", "member;employee;faculty")
        self.assertEqual(self._gruppi("mrossi"), {"docente"})

    def test_scope_sbagliato_scartato_anche_se_misto_a_valori_nudi(self):
        """Uno scope estraneo resta escluso pur in presenza di valori nudi."""
        resp = self._accedi("s892", "member;student@unibo.it")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("s892"), set())

    def test_dump_reale_studente(self):
        """Valori osservati davvero su /shibboleth/test (agosto 2026).

        Su tesi.ing.unimore.it il SP e' su un altro host e l'attributo arriva
        come header ("HTTP_X_SHIB_AFFILIATION"); su olj.unimore.it il SP e'
        locale e lo espone come variabile ("affiliation", minuscolo, senza
        prefisso). Entrambe le forme devono dare lo stesso risultato.
        """
        reale = "member@unimore.it;student@unimore.it"

        self._accedi("s001", reale, header="HTTP_X_SHIB_AFFILIATION")
        self.assertEqual(self._gruppi("s001"), {"studente"})

        self.client.logout()
        self._accedi("s002", reale, header="affiliation")
        self.assertEqual(self._gruppi("s002"), {"studente"})

    def test_maiuscole_e_spazi_tollerati(self):
        self._accedi("s777", " Member@unimore.it ; STUDENT@unimore.it ")
        self.assertEqual(self._gruppi("s777"), {"studente"})

    def test_cambio_di_ruolo_rimuove_il_gruppo_precedente(self):
        self._accedi("mrossi", self.STUDENTE)
        self.assertEqual(self._gruppi("mrossi"), {"studente"})

        self.client.logout()
        self._accedi("mrossi", self.DOCENTE)
        # Il vecchio gruppo non deve restare appiccicato.
        self.assertEqual(self._gruppi("mrossi"), {"docente"})

    def test_ruolo_revocato_toglie_l_accesso(self):
        self._accedi("mrossi", self.DOCENTE)
        self.assertEqual(self._gruppi("mrossi"), {"docente"})

        self.client.logout()
        resp = self._accedi("mrossi", "member@unimore.it")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._gruppi("mrossi"), set())

    def test_anagrafica_popolata(self):
        self._accedi(
            "s123456",
            self.STUDENTE,
            HTTP_X_SHIB_GIVENNAME="Mario",
            HTTP_X_SHIB_SN="Rossi",
            HTTP_X_SHIB_MAIL="mario.rossi@studenti.unimore.it",
        )
        u = User.objects.get(username="s123456")
        self.assertEqual(u.get_full_name(), "Mario Rossi")
        self.assertEqual(u.email, "mario.rossi@studenti.unimore.it")


class TitoloEVideoTest(BaseSetup):
    """Titolo non rimovibile; video facoltativo, file O link."""

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.url = reverse("appelli:carica_tesi", args=[self.iscrizione.id])
        self.client.force_login(self.studente)

    def tearDown(self):
        self.iscrizione.refresh_from_db()
        for campo in (self.iscrizione.file_tesi, self.iscrizione.file_video):
            if campo:
                campo.delete(save=False)

    def _pdf(self):
        return SimpleUploadedFile(
            "tesi.pdf", b"%PDF-1.7 contenuto", content_type="application/pdf"
        )

    def _video(self, nome="presentazione.mp4", byte=b"contenuto video"):
        return SimpleUploadedFile(nome, byte, content_type="video/mp4")

    def _dati(self, **extra):
        dati = {
            "titolo": "Titolo iniziale",
            "tutor": self.docente.pk,
            "modalita_video": "nessuno",
        }
        dati.update(extra)
        return dati

    # --- Titolo ---------------------------------------------------------

    def test_titolo_salvato(self):
        self.client.post(self.url, self._dati(file_tesi=self._pdf()))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Titolo iniziale")

    def test_titolo_modificabile(self):
        self.client.post(self.url, self._dati(file_tesi=self._pdf()))
        self.client.post(self.url, self._dati(titolo="Titolo corretto"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Titolo corretto")

    def test_titolo_non_rimovibile(self):
        self.client.post(self.url, self._dati(file_tesi=self._pdf()))

        for tentativo in ("", "   "):
            with self.subTest(titolo=repr(tentativo)):
                resp = self.client.post(self.url, self._dati(titolo=tentativo))
                self.assertEqual(resp.status_code, 200)  # resta sul form
                self.iscrizione.refresh_from_db()
                self.assertEqual(self.iscrizione.titolo, "Titolo iniziale")

    # --- Video ----------------------------------------------------------

    def test_video_facoltativo(self):
        resp = self.client.post(self.url, self._dati(file_tesi=self._pdf()))
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.ha_video)

    def test_video_come_file(self):
        self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="file",
                       file_video=self._video()),
        )
        self.iscrizione.refresh_from_db()
        self.assertTrue(self.iscrizione.file_video)
        self.assertEqual(self.iscrizione.link_video, "")
        # Il video sta in una sottocartella sua, separata dalla tesi.
        self.assertIn("/video/", self.iscrizione.file_video.name)

    def test_video_come_link(self):
        self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="link",
                       link_video="https://example.com/v"),
        )
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.link_video, "https://example.com/v")
        self.assertFalse(self.iscrizione.file_video)

    def test_link_sostituisce_il_file(self):
        """Passare da file a link deve azzerare il file, non affiancarlo."""
        self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="file",
                       file_video=self._video()),
        )
        self.client.post(
            self.url,
            self._dati(modalita_video="link", link_video="https://example.com/v"),
        )
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_video)
        self.assertEqual(self.iscrizione.link_video, "https://example.com/v")

    def test_video_rimovibile(self):
        """Essendo facoltativo, il video si puo' togliere (a differenza della tesi)."""
        self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="link",
                       link_video="https://example.com/v"),
        )
        self.client.post(self.url, self._dati(modalita_video="nessuno"))
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.ha_video)

    def test_file_e_link_insieme_impossibili_nel_db(self):
        """Il CheckConstraint difende anche se si scavalca il form."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StudenteAppelloDiLaurea.objects.filter(pk=self.iscrizione.pk).update(
                    file_video="tesi/x/video/v.mp4",
                    link_video="https://example.com/v",
                )

    def test_formato_video_non_ammesso(self):
        resp = self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="file",
                       file_video=SimpleUploadedFile("v.exe", b"x")),
        )
        self.assertEqual(resp.status_code, 200)
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_video)

    def test_video_troppo_grande(self):
        grande = self._video(byte=b"x" * (MAX_BYTE_VIDEO + 1))
        resp = self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="file", file_video=grande),
        )
        self.assertEqual(resp.status_code, 200)
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_video)

    def test_modalita_file_senza_file_da_errore(self):
        resp = self.client.post(
            self.url, self._dati(file_tesi=self._pdf(), modalita_video="file")
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scegli il file video")

    # --- Download del video ---------------------------------------------

    def test_download_video_permessi(self):
        self.client.post(
            self.url,
            self._dati(file_tesi=self._pdf(), modalita_video="file",
                       file_video=self._video()),
        )
        url = reverse("appelli:scarica_video", args=[self.iscrizione.id])

        # Il proprietario scarica.
        self.assertEqual(self.client.get(url).status_code, 200)

        # Il docente della commissione scarica.
        self.client.force_login(self.docente)
        self.assertEqual(self.client.get(url).status_code, 200)

        # Un docente estraneo no.
        altro = User.objects.create_user("docente_estraneo2", password="pw")
        altro.groups.add(self.g_docente)
        self.client.force_login(altro)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_download_video_assente_da_404(self):
        url = reverse("appelli:scarica_video", args=[self.iscrizione.id])
        self.assertEqual(self.client.get(url).status_code, 404)


class TitoloETesiACoppiaTest(BaseSetup):
    """Titolo e file della tesi: o tutti e due, o nessuno.

    Nessuno dei due e' obbligatorio da solo, cosi' lo studente puo' salvare
    la sola scelta del tutor. La coppia si giudica su come l'iscrizione
    risultera' salvata, non sul singolo invio.
    """

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.url = reverse("appelli:carica_tesi", args=[self.iscrizione.id])
        self.client.force_login(self.studente)

    def tearDown(self):
        self.iscrizione.refresh_from_db()
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)

    def _pdf(self):
        return SimpleUploadedFile(
            "tesi.pdf", b"%PDF-1.7 contenuto", content_type="application/pdf"
        )

    def _post(self, **extra):
        dati = {"tutor": self.docente.pk, "modalita_video": "nessuno"}
        dati.update(extra)
        return self.client.post(self.url, dati)

    def test_si_salva_il_solo_tutor(self):
        resp = self._post()
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.tutor, self.docente)
        self.assertFalse(self.iscrizione.titolo)
        self.assertFalse(self.iscrizione.file_tesi)

    def test_titolo_di_soli_spazi_conta_come_assente(self):
        resp = self._post(titolo="   ")
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))

    def test_titolo_senza_tesi_rifiutato(self):
        resp = self._post(titolo="Un titolo")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "carica anche il file della tesi")
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.tutor_id)   # niente di salvato

    def test_tesi_senza_titolo_rifiutata(self):
        resp = self._post(file_tesi=self._pdf())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "indica anche il titolo")
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_tesi)

    def test_tutti_e_due_insieme_salvati(self):
        resp = self._post(titolo="Un titolo", file_tesi=self._pdf())
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Un titolo")
        self.assertTrue(self.iscrizione.file_tesi)

    def test_tutor_salvato_prima_poi_titolo_e_tesi(self):
        """Il tutor bloccato non impedisce di completare il resto dopo."""
        self._post()
        resp = self.client.post(self.url, {
            "titolo": "Un titolo", "file_tesi": self._pdf(),
            "modalita_video": "nessuno",
        })
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Un titolo")
        self.assertTrue(self.iscrizione.file_tesi)

    def test_tesi_gia_salvata_basta_per_correggere_il_titolo(self):
        self._post(titolo="Primo", file_tesi=self._pdf())
        resp = self._post(titolo="Secondo")
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Secondo")

    def test_titolo_gia_salvato_non_si_svuota_nemmeno_senza_tesi(self):
        """Un titolo senza tesi puo' esistere: lo mette il relatore dalla
        valutazione. Lo studente non deve poterlo cancellare con un invio a
        vuoto."""
        self.iscrizione.titolo = "Messo dal relatore"
        self.iscrizione.save()
        resp = self._post(titolo="")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "non può essere svuotato")
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Messo dal relatore")

    def test_la_pagina_spiega_la_regola_finche_manca_qualcosa(self):
        self.assertContains(self.client.get(self.url), "vanno inseriti insieme")


class PuliziaOrfaneTest(BaseSetup):
    """Il comando di pulizia non deve considerare orfano il video."""

    def test_video_referenziato_non_e_orfano(self):
        from io import StringIO

        from django.core.management import call_command

        iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente,
            appello=self.appello,
            file_tesi=SimpleUploadedFile("t.pdf", b"%PDF-1.7 x"),
            file_video=SimpleUploadedFile("v.mp4", b"video"),
        )
        try:
            out = StringIO()
            call_command("pulisci_tesi_orfane", stdout=out)
            testo = out.getvalue()
            self.assertNotIn(iscrizione.file_video.name, testo)
            self.assertNotIn(iscrizione.file_tesi.name, testo)
        finally:
            iscrizione.file_tesi.delete(save=False)
            iscrizione.file_video.delete(save=False)


class OrdinamentoAppelliTest(BaseSetup):
    """Ogni elenco di appelli parte dal piu' vecchio, per chiunque lo guardi."""

    def _appello(self, giorno, ora=None, corso="Informatica"):
        return AppelloDiLaurea.objects.create(
            data=datetime.date(2030, 1, giorno),
            ora=ora,
            corso_di_laurea=corso,
            commissione=self.commissione,
        )

    def test_ordine_crescente_per_data(self):
        tardi = self._appello(20)
        presto = self._appello(5)
        mezzo = self._appello(12)

        self.client.force_login(self.studente)
        elenco = list(
            self.client.get(reverse("appelli:studente_dashboard")).context[
                "appelli_disponibili"
            ]
        )
        # BaseSetup crea un appello al 01/01/2030 e la migrazione dei dati demo
        # un altro: si guardano solo i tre creati qui, nel loro ordine relativo.
        nostri = [a for a in elenco if a in (tardi, presto, mezzo)]
        self.assertEqual(nostri, [presto, mezzo, tardi])

    def test_a_parita_di_giorno_prima_chi_ha_orario(self):
        senza = self._appello(8)
        con = self._appello(8, ora=datetime.time(9, 0), corso="Matematica")

        self.client.force_login(self.studente)
        elenco = list(
            self.client.get(reverse("appelli:studente_dashboard")).context[
                "appelli_disponibili"
            ]
        )
        nostri = [a for a in elenco if a in (senza, con)]
        self.assertEqual(nostri, [con, senza])

    def test_ordine_di_default_del_modello(self):
        """La regola sta nel Meta, quindi vale anche senza order_by esplicito."""
        tardi = self._appello(20)
        presto = self._appello(5)
        nostri = [
            a
            for a in AppelloDiLaurea.objects.all()
            if a in (tardi, presto)
        ]
        self.assertEqual(nostri, [presto, tardi])

    def test_ordine_nella_dashboard_docente(self):
        tardi = self._appello(20)
        presto = self._appello(5)

        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:docente_dashboard"))
        # Entrambi usano la commissione di BaseSetup, di cui il docente fa
        # parte: compaiono quindi fra "i miei appelli".
        appelli = list(resp.context["miei_appelli"])
        nostri = [a for a in appelli if a in (tardi, presto)]
        self.assertEqual(nostri, [presto, tardi])

    def test_ordine_delle_mie_iscrizioni(self):
        """Anche "Le mie iscrizioni" e' una lista di appelli: stessa regola."""
        tardi = self._appello(20)
        presto = self._appello(5)
        for appello in (tardi, presto):
            StudenteAppelloDiLaurea.objects.create(
                studente=self.studente, appello=appello
            )

        self.client.force_login(self.studente)
        resp = self.client.get(reverse("appelli:studente_dashboard"))
        appelli = [i.appello for i in resp.context["iscrizioni"]]
        self.assertEqual(appelli, [presto, tardi])


class PresidenteTest(BaseSetup):
    """Ruolo presidente: accesso riservato e creazione degli appelli."""

    def setUp(self):
        super().setUp()
        self.g_presidente = Group.objects.get(name="presidente")
        # Un presidente e' un docente con in piu' il gruppo "presidente".
        self.presidente = User.objects.create_user("presidente_test", password="pw")
        self.presidente.groups.add(self.g_docente, self.g_presidente)

    # --- Accesso ---------------------------------------------------------

    def test_dashboard_smista_il_presidente(self):
        """Appartiene anche a "docente": deve prevalere la pagina presidente."""
        self.client.force_login(self.presidente)
        resp = self.client.get(reverse("appelli:dashboard"))
        self.assertRedirects(
            resp,
            reverse("appelli:presidente_dashboard"),
            fetch_redirect_response=False,
        )

    def test_docente_semplice_non_accede(self):
        self.client.force_login(self.docente)
        for nome in ("presidente_dashboard", "crea_appello"):
            with self.subTest(vista=nome):
                self.assertEqual(self.client.get(reverse("appelli:" + nome)).status_code, 403)

    def test_studente_non_accede(self):
        self.client.force_login(self.studente)
        self.assertEqual(
            self.client.get(reverse("appelli:presidente_dashboard")).status_code, 403
        )

    def test_docente_non_crea_appelli_via_post(self):
        """Non basta nascondere il pulsante: la POST deve essere respinta."""
        self.client.force_login(self.docente)
        prima = AppelloDiLaurea.objects.count()
        resp = self.client.post(reverse("appelli:crea_appello"), {
            "corso_di_laurea": "Abusivo",
            "data": "2031-06-01",
            "ora": "10:00",
            "docenti": [self.docente.pk],
        })
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(AppelloDiLaurea.objects.count(), prima)

    # --- Creazione -------------------------------------------------------

    def _crea(self, **extra):
        dati = {
            "corso_di_laurea": "Ingegneria Informatica",
            "data": "2031-06-01",
            "ora": "10:00",
            "docenti": [self.docente.pk, self.presidente.pk],
            # Obbligatori: senza, il form si rifiuta di creare l'appello.
            "studenti": [self.studente.pk],
        }
        dati.update(extra)
        return self.client.post(reverse("appelli:crea_appello"), dati)

    def test_creazione_appello(self):
        self.client.force_login(self.presidente)
        resp = self._crea()
        self.assertRedirects(
            resp,
            reverse("appelli:presidente_dashboard"),
            fetch_redirect_response=False,
        )
        appello = AppelloDiLaurea.objects.get(corso_di_laurea="Ingegneria Informatica")
        self.assertEqual(appello.data, datetime.date(2031, 6, 1))
        self.assertEqual(appello.ora, datetime.time(10, 0))
        self.assertEqual(
            set(appello.commissione.docenti.values_list("pk", flat=True)),
            {self.docente.pk, self.presidente.pk},
        )

    def test_commissione_riusata_se_stessi_docenti(self):
        """Ripetere le stesse persone non deve creare commissioni doppione."""
        self.client.force_login(self.presidente)
        self._crea()
        quante = Commissione.objects.count()

        self._crea(data="2031-07-15")   # stessa commissione, altra data
        self.assertEqual(Commissione.objects.count(), quante)
        self.assertEqual(
            AppelloDiLaurea.objects.filter(
                corso_di_laurea="Ingegneria Informatica"
            ).count(),
            2,
        )

    def test_commissione_nuova_se_docenti_diversi(self):
        self.client.force_login(self.presidente)
        self._crea()
        quante = Commissione.objects.count()

        # Serve un docente che non compaia in nessuna commissione esistente:
        # BaseSetup ne ha gia' creata una con il solo self.docente, che
        # verrebbe (correttamente) riusata.
        terzo = User.objects.create_user("docente_terzo", password="pw")
        terzo.groups.add(self.g_docente)

        self._crea(data="2031-07-15", docenti=[terzo.pk])
        self.assertEqual(Commissione.objects.count(), quante + 1)

    def test_duplicato_rifiutato_con_messaggio(self):
        """Stessa tripletta: errore leggibile, non un IntegrityError."""
        self.client.force_login(self.presidente)
        self._crea()
        resp = self._crea()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Esiste già un appello")

    def test_commissione_non_creata_se_il_form_e_invalido(self):
        """Una validazione fallita non deve lasciare commissioni orfane."""
        self.client.force_login(self.presidente)
        quante = Commissione.objects.count()
        resp = self._crea(data="")        # data mancante
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Commissione.objects.count(), quante)

    def test_dashboard_elenca_appelli_e_iscritti(self):
        self.client.force_login(self.presidente)
        self._crea()
        StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        resp = self.client.get(reverse("appelli:presidente_dashboard"))
        self.assertContains(resp, "Ingegneria Informatica")
        self.assertContains(resp, "Crea un nuovo appello")


@override_settings(MIDDLEWARE=MIDDLEWARE_SHIB)
class PresidenteRuoloPersistenteTest(TestCase):
    """Il gruppo "presidente" non deve essere revocato dal login Shibboleth.

    E' il rischio principale di questo ruolo: configure_user toglie l'utente da
    tutti i GRUPPI_NOTI a ogni accesso. Se "presidente" finisse in quella lista,
    l'assegnazione fatta a mano sparirebbe al primo login, in silenzio.
    """

    DOCENTE = "member@unimore.it;employee@unimore.it;faculty@unimore.it"

    def test_login_non_revoca_il_gruppo_presidente(self):
        utente = User.objects.create_user("presidente_shib")
        utente.groups.add(Group.objects.get(name="presidente"))

        resp = self.client.get(
            reverse("appelli:dashboard"),
            **{"HTTP_X_SHIB_UID": "presidente_shib",
               "HTTP_X_SHIB_AFFILIATION": self.DOCENTE},
        )

        gruppi = set(
            User.objects.get(username="presidente_shib")
            .groups.values_list("name", flat=True)
        )
        # Shibboleth assegna "docente"; "presidente" deve sopravvivere.
        self.assertEqual(gruppi, {"docente", "presidente"})
        self.assertRedirects(
            resp,
            reverse("appelli:presidente_dashboard"),
            fetch_redirect_response=False,
        )


class RicercaDocentiTest(BaseSetup):
    """Endpoint di ricerca dei docenti per comporre la commissione."""

    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        super().setUp()
        self.g_presidente = Group.objects.get(name="presidente")
        self.presidente = User.objects.create_user("pres", password="pw")
        self.presidente.groups.add(self.g_docente, self.g_presidente)
        self.url = reverse("appelli:cerca_docenti")

        self.ada = User.objects.create_user(
            "adcigala", first_name="Ada", last_name="Cigala",
            email="ada.cigala@unimore.it",
        )
        self.ada.groups.add(self.g_docente)

    def _cerca(self, q, **extra):
        parametri = dict(self.AJAX)
        parametri.update(extra)
        return self.client.get(self.url, {"q": q}, **parametri)

    # --- Accesso ---------------------------------------------------------

    def test_anonimo_non_accede(self):
        resp = self._cerca("ada")
        self.assertEqual(resp.status_code, 302)   # verso il login

    def test_studente_accede_per_scegliere_il_tutor(self):
        """Lo studente cerca fra i docenti: e' cosi' che sceglie il suo tutor."""
        self.client.force_login(self.studente)
        self.assertEqual(self._cerca("ada").status_code, 200)

    def test_docente_semplice_non_accede(self):
        self.client.force_login(self.docente)
        self.assertEqual(self._cerca("ada").status_code, 403)

    def test_senza_header_ajax_non_risponde(self):
        """Aprire l'URL nel browser non deve restituire l'elenco."""
        self.client.force_login(self.presidente)
        resp = self.client.get(self.url, {"q": "ada"})
        self.assertEqual(resp.status_code, 403)

    def test_origine_esterna_rifiutata(self):
        self.client.force_login(self.presidente)
        resp = self._cerca("ada", HTTP_ORIGIN="https://sito-esterno.example")
        self.assertEqual(resp.status_code, 403)

    # --- Ricerca ---------------------------------------------------------

    def test_ricerca_per_nome_cognome_username_email(self):
        self.client.force_login(self.presidente)
        for termine in ("Ada", "Cigala", "adcigala", "ada.cigala@unimore.it"):
            with self.subTest(termine=termine):
                dati = self._cerca(termine).json()
                self.assertIn(
                    self.ada.pk, [r["id"] for r in dati["risultati"]]
                )

    def test_piu_parole_in_ordine_libero(self):
        self.client.force_login(self.presidente)
        dati = self._cerca("cigala ada").json()
        self.assertEqual([r["id"] for r in dati["risultati"]], [self.ada.pk])

    def test_campi_restituiti(self):
        self.client.force_login(self.presidente)
        risultato = self._cerca("adcigala").json()["risultati"][0]
        self.assertEqual(
            set(risultato),
            {"id", "nome", "cognome", "username", "email", "etichetta"},
        )
        self.assertEqual(risultato["cognome"], "Cigala")
        self.assertEqual(risultato["email"], "ada.cigala@unimore.it")

    def test_solo_docenti(self):
        """Uno studente con un nome simile non deve comparire."""
        studente = User.objects.create_user(
            "adastudente", first_name="Ada", last_name="Rossi"
        )
        studente.groups.add(self.g_studente)

        self.client.force_login(self.presidente)
        ids = [r["id"] for r in self._cerca("Ada").json()["risultati"]]
        self.assertIn(self.ada.pk, ids)
        self.assertNotIn(studente.pk, ids)

    def test_massimo_dieci_risultati(self):
        for i in range(15):
            u = User.objects.create_user(f"zztest{i}", last_name="Zzcognome")
            u.groups.add(self.g_docente)

        self.client.force_login(self.presidente)
        self.assertEqual(len(self._cerca("Zzcognome").json()["risultati"]), 10)

    def test_termine_troppo_corto(self):
        """Con una lettera sola non si interroga il database."""
        self.client.force_login(self.presidente)
        self.assertEqual(self._cerca("a").json()["risultati"], [])

    def test_nessun_risultato(self):
        self.client.force_login(self.presidente)
        self.assertEqual(self._cerca("inesistente").json()["risultati"], [])


class CommissioneSenzaNomeTest(BaseSetup):
    """La commissione si identifica con l'id: il nome non si mostra mai."""

    def test_str_e_solo_il_numero(self):
        c = Commissione.objects.create(nome="Un nome qualsiasi")
        self.assertEqual(str(c), str(c.pk))

    def test_commissione_creata_dal_form_non_ha_nome(self):
        presidente = User.objects.create_user("pres2", password="pw")
        presidente.groups.add(self.g_docente, Group.objects.get(name="presidente"))
        nuovo = User.objects.create_user("doc_nuovo", password="pw")
        nuovo.groups.add(self.g_docente)

        self.client.force_login(presidente)
        self.client.post(reverse("appelli:crea_appello"), {
            "corso_di_laurea": "Matematica",
            "data": "2032-03-03",
            "ora": "09:00",
            "docenti": [nuovo.pk],
            "studenti": [self.studente.pk],
        })
        appello = AppelloDiLaurea.objects.get(corso_di_laurea="Matematica")
        self.assertEqual(appello.commissione.nome, "")

    def test_il_nome_non_compare_nelle_pagine(self):
        Commissione.objects.filter(pk=self.commissione.pk).update(
            nome="NOMESEGRETO"
        )
        self.client.force_login(self.docente)
        for url in (
            reverse("appelli:docente_dashboard"),
            reverse("appelli:appello_detail", args=[self.appello.id]),
        ):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), "NOMESEGRETO")

    def test_dashboard_non_nomina_la_commissione(self):
        """Nelle tabelle non deve restare traccia della commissione."""
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:docente_dashboard"))
        testo = resp.content.decode()
        self.assertNotIn("<th>Commissione</th>", testo)
        self.assertIn("Vedi dettagli", testo)
        self.assertNotIn("Vedi iscritti", testo)

    def test_dettaglio_mostra_i_membri_non_l_identificativo(self):
        """L'unico punto in cui la commissione compare: come elenco di persone."""
        self.docente.first_name = "Marco"
        self.docente.last_name = "Rossi"
        self.docente.email = "marco.rossi@unimore.it"
        self.docente.save()

        self.client.force_login(self.docente)
        resp = self.client.get(
            reverse("appelli:appello_detail", args=[self.appello.id])
        )
        self.assertContains(resp, "Marco Rossi")
        self.assertContains(resp, "marco.rossi@unimore.it")
        # niente identificativo della commissione in pagina
        self.assertNotContains(resp, f"Commissione #{self.commissione.pk}")


class DashboardUnificataTest(BaseSetup):
    """Docente e presidente vedono la stessa pagina, con o senza il pulsante."""

    def setUp(self):
        super().setUp()
        self.presidente = User.objects.create_user("pres3", password="pw")
        self.presidente.groups.add(
            self.g_docente, Group.objects.get(name="presidente")
        )

    def test_docente_vede_i_propri_appelli_e_gli_altri(self):
        altra = Commissione.objects.create()
        estraneo = AppelloDiLaurea.objects.create(
            data=datetime.date(2030, 5, 5),
            corso_di_laurea="Fisica",
            commissione=altra,
        )
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:docente_dashboard"))
        self.assertIn(self.appello, list(resp.context["miei_appelli"]))
        self.assertIn(estraneo, list(resp.context["altri_appelli"]))
        self.assertNotIn(estraneo, list(resp.context["miei_appelli"]))

    def test_docente_non_vede_il_pulsante_crea(self):
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:docente_dashboard"))
        self.assertFalse(resp.context["puo_creare_appelli"])
        self.assertNotContains(resp, "Crea un nuovo appello")

    def test_presidente_vede_la_stessa_pagina_piu_il_pulsante(self):
        self.client.force_login(self.presidente)
        resp = self.client.get(reverse("appelli:presidente_dashboard"))
        self.assertTemplateUsed(resp, "appelli/docente_dashboard.html")
        self.assertTrue(resp.context["puo_creare_appelli"])
        self.assertContains(resp, "Crea un nuovo appello")
        # e conserva le due tabelle del docente
        self.assertIn("miei_appelli", resp.context)
        self.assertIn("altri_appelli", resp.context)


class ErroreDocentiMancantiTest(BaseSetup):
    """Creare un appello senza membri deve dirlo chiaramente."""

    def test_messaggio_in_un_alert(self):
        presidente = User.objects.create_user("pres4", password="pw")
        presidente.groups.add(self.g_docente, Group.objects.get(name="presidente"))
        self.client.force_login(presidente)

        resp = self.client.post(reverse("appelli:crea_appello"), {
            "corso_di_laurea": "Informatica",
            "data": "2033-01-10",
            "ora": "09:00",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Seleziona almeno un membro della commissione")
        self.assertContains(resp, "alert alert-danger")


class RitornoDaDettaglioTest(BaseSetup):
    """"Torna indietro" deve riportare nell'area da cui si proviene."""

    def setUp(self):
        super().setUp()
        self.presidente = User.objects.create_user("pres5", password="pw")
        self.presidente.groups.add(
            self.g_docente, Group.objects.get(name="presidente")
        )
        self.commissione.docenti.add(self.presidente)
        self.url = reverse("appelli:appello_detail", args=[self.appello.id])

    def test_docente_torna_all_area_docente(self):
        self.client.force_login(self.docente)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["url_ritorno"], "appelli:docente_dashboard")
        self.assertContains(resp, reverse("appelli:docente_dashboard"))

    def test_presidente_torna_all_area_presidente(self):
        self.client.force_login(self.presidente)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["url_ritorno"], "appelli:presidente_dashboard")
        self.assertContains(resp, reverse("appelli:presidente_dashboard"))
        self.assertNotContains(resp, reverse("appelli:docente_dashboard"))


class ConfermaUscitaCreaAppelloTest(BaseSetup):
    """La pagina di creazione avvisa prima di uscire senza salvare."""

    def test_modale_e_pulsanti_presenti(self):
        presidente = User.objects.create_user("pres6", password="pw")
        presidente.groups.add(self.g_docente, Group.objects.get(name="presidente"))
        self.client.force_login(presidente)

        resp = self.client.get(reverse("appelli:crea_appello"))
        testo = resp.content.decode()
        self.assertIn('id="unsavedModal"', testo)
        for etichetta in ("Rimani", "Esci senza salvare", "Salva ed esci"):
            with self.subTest(pulsante=etichetta):
                self.assertIn(etichetta, testo)
        # I due modi di uscire (link in alto e pulsante Annulla) passano
        # entrambi dal controllo. Si contano i tag <a>, non le occorrenze
        # della stringa: una compare anche nel JavaScript.
        import re
        link = re.findall(r"<a\b[^>]*js-esci[^>]*>", testo)
        self.assertEqual(len(link), 2, link)


def _xlsx(intestazioni, righe):
    """Crea in memoria un xlsx con le colonne e i dati richiesti.

    I file veri contengono nomi ed email di studenti reali: qui si generano
    fogli sintetici, che restano nel repository senza dati personali.
    """
    from io import BytesIO

    from openpyxl import Workbook

    libro = Workbook()
    foglio = libro.active
    foglio.append(list(intestazioni))
    for r in righe:
        foglio.append(list(r))
    buffer = BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        "elenco.xlsx",
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# Le due varianti di intestazione realmente incontrate nei file di ateneo.
COLONNE_FORMATO_A = ["matricola", "CORSO", "cognome", "nome", "email", "ate"]
COLONNE_FORMATO_B = [
    "p06_cds_des", "p04_mat_matricola", "p01_anaper_cognome",
    "p01_anaper_nome", "p01_anaper_email", "p01_anaper_email_ate",
]


class LetturaXlsxTest(TestCase):
    """Il parser deve reggere entrambi i formati di estrazione."""

    def test_formato_con_colonne_brevi(self):
        from appelli.xlsx import leggi_elenco

        f = _xlsx(COLONNE_FORMATO_A, [
            ["1", "Ingegneria Informatica (MO)", "Rossi", "Mario",
             "mario@gmail.com", "111@studenti.unimore.it"],
        ])
        corso, email = leggi_elenco(f)
        self.assertEqual(corso, "Ingegneria Informatica (MO)")
        self.assertEqual(email, ["111@studenti.unimore.it"])

    def test_formato_con_colonne_prefissate(self):
        from appelli.xlsx import leggi_elenco

        f = _xlsx(COLONNE_FORMATO_B, [
            ["Artificial intelligence engineering", "1", "Rossi", "Mario",
             "mario@gmail.com", "111@studenti.unimore.it"],
        ])
        corso, email = leggi_elenco(f)
        self.assertEqual(corso, "Artificial intelligence engineering")
        self.assertEqual(email, ["111@studenti.unimore.it"])

    def test_prende_l_email_di_ateneo_non_quella_personale(self):
        """La colonna «email» esiste in entrambi i formati e non va usata."""
        from appelli.xlsx import leggi_elenco

        f = _xlsx(COLONNE_FORMATO_A, [
            ["1", "Informatica", "Rossi", "Mario",
             "personale@gmail.com", "111@studenti.unimore.it"],
        ])
        _corso, email = leggi_elenco(f)
        self.assertEqual(email, ["111@studenti.unimore.it"])

    def test_righe_vuote_ignorate(self):
        """I file reali hanno righe vuote in coda al foglio."""
        from appelli.xlsx import leggi_elenco

        f = _xlsx(COLONNE_FORMATO_A, [
            ["1", "Informatica", "Rossi", "Mario", "a@g.it", "111@studenti.unimore.it"],
            [None, None, None, None, None, None],
            [None, None, None, None, None, None],
        ])
        _corso, email = leggi_elenco(f)
        self.assertEqual(email, ["111@studenti.unimore.it"])

    def test_duplicati_rimossi(self):
        from appelli.xlsx import leggi_elenco

        f = _xlsx(COLONNE_FORMATO_A, [
            ["1", "Informatica", "Rossi", "Mario", "a@g.it", "111@studenti.unimore.it"],
            ["1", "Informatica", "Rossi", "Mario", "a@g.it", "111@studenti.unimore.it"],
        ])
        _corso, email = leggi_elenco(f)
        self.assertEqual(email, ["111@studenti.unimore.it"])

    def test_senza_colonna_email_errore_chiaro(self):
        from appelli.xlsx import ErroreXlsx, leggi_elenco

        f = _xlsx(["matricola", "CORSO", "cognome"], [["1", "Informatica", "Rossi"]])
        with self.assertRaises(ErroreXlsx) as ctx:
            leggi_elenco(f)
        self.assertIn("email di ateneo", str(ctx.exception))

    def test_senza_colonna_corso_errore_chiaro(self):
        from appelli.xlsx import ErroreXlsx, leggi_elenco

        f = _xlsx(["matricola", "cognome", "ate"],
                  [["1", "Rossi", "111@studenti.unimore.it"]])
        with self.assertRaises(ErroreXlsx) as ctx:
            leggi_elenco(f)
        self.assertIn("corso di laurea", str(ctx.exception))

    def test_file_non_xlsx_errore_chiaro(self):
        from appelli.xlsx import ErroreXlsx, leggi_elenco

        finto = SimpleUploadedFile("elenco.xlsx", b"non sono un foglio di calcolo")
        with self.assertRaises(ErroreXlsx):
            leggi_elenco(finto)


@override_settings(MIDDLEWARE=list(settings.MIDDLEWARE))
class CaricamentoElencoTest(BaseSetup):
    """Endpoint che legge l'elenco e prepara il form di creazione."""

    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        super().setUp()
        self.presidente = User.objects.create_user("pres_x", password="pw")
        self.presidente.groups.add(
            self.g_docente, Group.objects.get(name="presidente")
        )
        self.url = reverse("appelli:analizza_xlsx")

        self.iscritto = User.objects.create_user(
            "s111", email="111@studenti.unimore.it",
            first_name="Mario", last_name="Rossi",
        )
        self.iscritto.groups.add(self.g_studente)

    def _invia(self, file, utente=None):
        self.client.force_login(utente or self.presidente)
        return self.client.post(self.url, {"file": file}, **self.AJAX)

    def _elenco(self, email=("111@studenti.unimore.it",), corso="Informatica"):
        return _xlsx(
            COLONNE_FORMATO_A,
            [["1", corso, "Rossi", "Mario", "p@g.it", e] for e in email],
        )

    # --- Accesso ---------------------------------------------------------

    def test_docente_semplice_non_accede(self):
        resp = self._invia(self._elenco(), utente=self.docente)
        self.assertEqual(resp.status_code, 403)

    def test_studente_non_accede(self):
        resp = self._invia(self._elenco(), utente=self.studente)
        self.assertEqual(resp.status_code, 403)

    def test_senza_header_ajax_rifiutato(self):
        self.client.force_login(self.presidente)
        resp = self.client.post(self.url, {"file": self._elenco()})
        self.assertEqual(resp.status_code, 403)

    # --- Lettura ---------------------------------------------------------

    def test_corso_e_studenti_riconosciuti(self):
        resp = self._invia(self._elenco())
        self.assertEqual(resp.status_code, 200)
        dati = resp.json()
        self.assertEqual(dati["corso"], "Informatica")
        self.assertEqual([s["id"] for s in dati["studenti"]], [self.iscritto.pk])
        self.assertEqual(dati["mancanti"], [])

    def test_studente_non_registrato_segnalato(self):
        """Chi non e' nel database non si puo' iscrivere: va detto, non nascosto."""
        resp = self._invia(self._elenco(
            email=("111@studenti.unimore.it", "999@studenti.unimore.it")
        ))
        dati = resp.json()
        self.assertEqual([s["id"] for s in dati["studenti"]], [self.iscritto.pk])
        self.assertEqual(dati["mancanti"], ["999@studenti.unimore.it"])
        self.assertEqual(dati["totale_nel_file"], 2)

    def test_un_docente_nel_file_non_diventa_iscritto(self):
        """Solo chi e' nel gruppo studente puo' essere iscritto."""
        self.docente.email = "prof@unimore.it"
        self.docente.save()
        resp = self._invia(self._elenco(email=("prof@unimore.it",)))
        dati = resp.json()
        self.assertEqual(dati["studenti"], [])
        self.assertEqual(dati["mancanti"], ["prof@unimore.it"])

    def test_file_non_xlsx_rifiutato(self):
        resp = self._invia(SimpleUploadedFile("elenco.csv", b"a,b,c"))
        self.assertEqual(resp.status_code, 400)
        self.assertIn(".xlsx", resp.json()["errore"])

    def test_senza_file(self):
        self.client.force_login(self.presidente)
        resp = self.client.post(self.url, {}, **self.AJAX)
        self.assertEqual(resp.status_code, 400)


class CreazioneAppelloConStudentiTest(BaseSetup):
    """Gli studenti dell'elenco vengono iscritti insieme all'appello."""

    def setUp(self):
        super().setUp()
        self.presidente = User.objects.create_user("pres_y", password="pw")
        self.presidente.groups.add(
            self.g_docente, Group.objects.get(name="presidente")
        )
        self.altro_studente = User.objects.create_user(
            "s222", email="222@studenti.unimore.it"
        )
        self.altro_studente.groups.add(self.g_studente)
        self.client.force_login(self.presidente)

    def _crea(self, studenti):
        return self.client.post(reverse("appelli:crea_appello"), {
            "corso_di_laurea": "Ingegneria Informatica",
            "data": "2032-06-10",
            "ora": "09:00",
            "docenti": [self.docente.pk],
            "studenti": studenti,
        })

    def test_iscrizioni_create(self):
        self._crea([self.studente.pk, self.altro_studente.pk])
        appello = AppelloDiLaurea.objects.get(corso_di_laurea="Ingegneria Informatica")
        iscritti = set(
            appello.iscrizioni.values_list("studente_id", flat=True)
        )
        self.assertEqual(iscritti, {self.studente.pk, self.altro_studente.pk})

    # L'elenco vuoto NON e' piu' ammesso: la regola, con i suoi casi, sta in
    # RegoleNuoveAppelloTest insieme a quella sulla data.

    def test_un_docente_non_puo_essere_iscritto(self):
        """Il campo accetta solo utenti del gruppo studente."""
        resp = self._crea([self.docente.pk])
        self.assertEqual(resp.status_code, 200)   # form non valido
        self.assertFalse(
            AppelloDiLaurea.objects.filter(
                corso_di_laurea="Ingegneria Informatica"
            ).exists()
        )


class BackendPostaRotto(BaseEmailBackend):
    """Server di posta che non risponde: serve a provare il caso peggiore."""

    def send_messages(self, messaggi):
        raise OSError("server di posta irraggiungibile")


@override_settings(AVVISI_IN_BACKGROUND=False)
class AvvisiEmailTest(BaseSetup):
    """Email mandate alla creazione di un appello."""

    def setUp(self):
        super().setUp()
        self.g_presidente = Group.objects.get(name="presidente")
        self.presidente = User.objects.create_user(
            "presidente_test", password="pw", email="presidente@unimore.it"
        )
        self.presidente.groups.add(self.g_docente, self.g_presidente)

        self.docente.email = "docente@unimore.it"
        self.docente.save(update_fields=["email"])
        self.studente.email = "111111@studenti.unimore.it"
        self.studente.save(update_fields=["email"])

        self.studente2 = User.objects.create_user(
            "studente_test2", password="pw", email="222222@studenti.unimore.it"
        )
        self.studente2.groups.add(self.g_studente)

        self.client.force_login(self.presidente)

    def _crea(self, **extra):
        dati = {
            "corso_di_laurea": "Ingegneria Informatica",
            "data": "2031-06-01",
            "ora": "10:00",
            "docenti": [self.docente.pk, self.presidente.pk],
            "studenti": [self.studente.pk, self.studente2.pk],
        }
        dati.update(extra)
        return self.client.post(reverse("appelli:crea_appello"), dati, follow=True)

    def test_avviso_a_ogni_studente_e_a_ogni_docente(self):
        self._crea()
        destinatari = sorted(sum((m.to for m in mail.outbox), []))
        self.assertEqual(
            destinatari,
            [
                "111111@studenti.unimore.it",
                "222222@studenti.unimore.it",
                "docente@unimore.it",
                "presidente@unimore.it",
            ],
        )

    def test_email_studente_porta_alla_sua_pagina_della_tesi(self):
        self._crea()
        iscrizione = StudenteAppelloDiLaurea.objects.get(studente=self.studente)
        avviso = next(m for m in mail.outbox if m.to == [self.studente.email])
        self.assertIn(
            "http://testserver"
            + reverse("appelli:carica_tesi", args=[iscrizione.pk]),
            avviso.body,
        )

    def test_email_studente_non_nomina_la_commissione(self):
        """Regola del progetto: allo studente la commissione non si mostra."""
        self._crea()
        avviso = next(m for m in mail.outbox if m.to == [self.studente.email])
        self.assertNotIn("docente_test", avviso.body)
        self.assertNotIn("commissione", avviso.body.lower())

    def test_email_docente_porta_al_dettaglio_dell_appello(self):
        self._crea()
        appello = AppelloDiLaurea.objects.get(corso_di_laurea="Ingegneria Informatica")
        avviso = next(m for m in mail.outbox if m.to == [self.docente.email])
        self.assertIn(
            "http://testserver"
            + reverse("appelli:appello_detail", args=[appello.pk]),
            avviso.body,
        )

    def test_chi_non_ha_indirizzo_viene_segnalato(self):
        self.studente2.email = ""
        self.studente2.save(update_fields=["email"])
        resp = self._crea()
        self.assertEqual(len(mail.outbox), 3)
        self.assertContains(resp, "Nessun indirizzo email per")

    @override_settings(EMAIL_BACKEND="appelli.tests.BackendPostaRotto")
    def test_posta_guasta_non_fa_perdere_l_appello(self):
        """Un server di posta irraggiungibile non deve far fallire nulla.

        L'errore non arriva piu' a schermo (quando l'invio e' in sottofondo la
        risposta e' gia' partita): resta nei log, ed e' li' che va cercato.
        """
        with self.assertLogs("appelli.notifiche", level="ERROR") as registro:
            resp = self._crea()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            AppelloDiLaurea.objects.filter(
                corso_di_laurea="Ingegneria Informatica"
            ).exists()
        )
        self.assertIn("non riuscito", "\n".join(registro.output))

    def test_in_esercizio_l_invio_non_blocca_la_richiesta(self):
        """Con le impostazioni vere la consegna viene affidata a un thread.

        Contare i thread vivi non funzionerebbe: con il backend dei test la
        spedizione finisce prima del controllo. Si verifica invece che il
        thread venga creato e che dentro la richiesta non parta nulla.
        """
        from unittest import mock

        from appelli import notifiche

        with override_settings(AVVISI_IN_BACKGROUND=True):
            with mock.patch("appelli.notifiche.threading.Thread") as finto_thread:
                self._crea()

        self.assertTrue(finto_thread.called)
        self.assertIs(finto_thread.call_args.kwargs["target"], notifiche._spedisci)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(AVVISI_IN_BACKGROUND=False)
class AvvisoTutorTest(BaseSetup):
    """Email mandata al docente che uno studente sceglie come tutor.

    Lo scenario tiene due docenti diversi apposta: "esterno_test" e' tutor ma
    NON siede nella commissione (il caso normale, perche' il tutoraggio non
    passa dalla commissione) e "docente_test" invece si'. E' l'unica cosa che
    cambia il link contenuto nell'email.
    """

    def setUp(self):
        super().setUp()
        self.studente.first_name = "Mario"
        self.studente.last_name = "Rossi"
        self.studente.email = "111111@studenti.unimore.it"
        self.studente.save()

        self.docente.email = "docente@unimore.it"
        self.docente.save(update_fields=["email"])

        self.esterno = User.objects.create_user(
            "esterno_test", password="pw", email="esterno@unimore.it"
        )
        self.esterno.groups.add(self.g_docente)

        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.url = reverse("appelli:carica_tesi", args=[self.iscrizione.pk])
        self.client.force_login(self.studente)

    def tearDown(self):
        self.iscrizione.refresh_from_db()
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)

    TITOLO = "Un titolo di tesi"

    def _salva(self, tutor=None, **extra):
        """Salvataggio completo del modulo della tesi: titolo, tutor e PDF."""
        dati = {
            "titolo": self.TITOLO,
            "tutor": (tutor or self.esterno).pk,
            "modalita_video": "nessuno",
            "file_tesi": SimpleUploadedFile(
                "tesi.pdf", b"%PDF-1.7 contenuto", content_type="application/pdf"
            ),
        }
        dati.update(extra)
        return self.client.post(self.url, dati)

    def _avviso(self):
        self.assertEqual(len(mail.outbox), 1)
        return mail.outbox[0]

    def test_il_docente_scelto_riceve_l_avviso(self):
        """Una sola email, e va al tutor: lo studente non va avvisato di nulla."""
        resp = self._salva()
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        avviso = self._avviso()
        self.assertEqual(avviso.to, ["esterno@unimore.it"])

    def test_avviso_nomina_lo_studente_con_nome_cognome_ed_email(self):
        """E' il contenuto utile: chi e' e a che indirizzo gli si risponde."""
        self._salva()
        corpo = self._avviso().body
        self.assertIn("Mario Rossi", corpo)
        self.assertIn("111111@studenti.unimore.it", corpo)

    def test_avviso_nomina_l_appello(self):
        self._salva()
        self.assertIn(self.appello.etichetta_pubblica, self._avviso().body)

    def test_tutor_fuori_commissione_riceve_il_link_all_area_docente(self):
        """appello_detail gli risponderebbe 403: il link deve portarlo dove
        quel tutorato lo vede davvero, cioe' sulla sua riga in area docente."""
        self._salva()
        corpo = self._avviso().body
        self.assertIn(
            "http://testserver"
            + reverse("appelli:docente_dashboard")
            + f"#tutorato-{self.iscrizione.pk}",
            corpo,
        )
        self.assertNotIn(
            reverse("appelli:appello_detail", args=[self.appello.pk]), corpo
        )

    def test_tutor_in_commissione_riceve_il_link_al_dettaglio_appello(self):
        """Chi e' in commissione puo' aprire la pagina dell'appello: si da'
        quella, che e' la piu' completa."""
        self._salva(tutor=self.docente)
        self.assertIn(
            "http://testserver"
            + reverse("appelli:appello_detail", args=[self.appello.pk]),
            self._avviso().body,
        )

    def test_un_solo_avviso_anche_salvando_altre_volte(self):
        """Il tutor si sceglie una volta sola: i salvataggi successivi di
        titolo, tesi o video non devono rimandare lo stesso avviso."""
        self._salva()
        mail.outbox = []
        self._salva(titolo="Titolo corretto")
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Titolo corretto")
        self.assertEqual(mail.outbox, [])

    def test_nessun_avviso_se_il_modulo_viene_rifiutato(self):
        """Senza titolo il form non e' valido: nessun tutor salvato, quindi
        nessuno da avvisare. Altrimenti si annuncerebbe una nomina inesistente."""
        resp = self._salva(titolo="")
        self.assertEqual(resp.status_code, 200)
        self.iscrizione.refresh_from_db()
        self.assertIsNone(self.iscrizione.tutor_id)
        self.assertEqual(mail.outbox, [])

    def test_tutor_senza_indirizzo_finisce_nel_log(self):
        """Allo studente non si dice niente (non potrebbe farci nulla), ma la
        cosa non deve sparire in silenzio."""
        self.esterno.email = ""
        self.esterno.save(update_fields=["email"])
        with self.assertLogs("appelli.notifiche", level="WARNING") as registro:
            resp = self._salva()
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.tutor_id, self.esterno.pk)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Nessun indirizzo email per il tutor", "\n".join(registro.output))

    def test_in_esercizio_l_invio_non_blocca_lo_studente(self):
        """Come per gli avvisi di un nuovo appello: la consegna va in un thread
        e la pagina dello studente non aspetta la posta."""
        from unittest import mock

        from appelli import notifiche

        with override_settings(AVVISI_IN_BACKGROUND=True):
            with mock.patch("appelli.notifiche.threading.Thread") as finto_thread:
                self._salva()

        self.assertTrue(finto_thread.called)
        self.assertIs(finto_thread.call_args.kwargs["target"], notifiche._spedisci)
        self.assertEqual(mail.outbox, [])


class TutoratiEValutazioneTest(BaseSetup):
    """Sezione tutorati dell'area docente e valutazione del relatore.

    Lo scenario tiene separati i due ruoli: "relatore" segue gli studenti ma
    NON siede in commissione, "docente_test" (da BaseSetup) e' in commissione
    ma non e' relatore di nessuno. E' la combinazione che mette alla prova i
    permessi, perche' finche' le due cose coincidono non si distinguono.
    """

    def setUp(self):
        super().setUp()
        self.relatore = User.objects.create_user("relatore_test", password="pw")
        self.relatore.groups.add(self.g_docente)

        oggi = timezone.localdate()
        self.passato = AppelloDiLaurea.objects.create(
            data=oggi - datetime.timedelta(days=30),
            corso_di_laurea="Corso Passato",
            commissione=self.commissione,
        )
        # self.appello di BaseSetup e' nel 2030, quindi futuro.
        self.i_futura = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello,
            tutor=self.relatore, titolo="Tesi futura",
        )
        altro = User.objects.create_user("studente_due", password="pw")
        altro.groups.add(self.g_studente)
        altro.last_name = "Quaglia"
        altro.save()
        self.i_passata = StudenteAppelloDiLaurea.objects.create(
            studente=altro, appello=self.passato,
            tutor=self.relatore, titolo="Tesi passata",
        )
        self.url_valuta = reverse(
            "appelli:salva_valutazione", args=[self.i_futura.id]
        )

    def _sezione(self, query=""):
        """Solo la card dei tutorati, con gli spazi normalizzati.

        Ritagliarla e' necessario: lo stesso corso di laurea compare anche
        nella tabella "Altri appelli", quindi cercare nell'intera pagina darebbe
        risultati falsi.
        """
        self.client.force_login(self.relatore)
        html = self.client.get(
            reverse("appelli:docente_dashboard") + query
        ).content.decode()
        inizio = html.index("I miei tutorati")
        fine = html.index("I miei appelli")
        return re.sub(r"\s+", " ", html[inizio:fine])

    # --- Permessi --------------------------------------------------------

    def test_relatore_fuori_commissione_scarica_la_tesi(self):
        """Il relatore non e' detto sieda in commissione: deve poter scaricare."""
        self.i_futura.file_tesi.save(
            "t.pdf", SimpleUploadedFile("t.pdf", b"%PDF-1.7 x"), save=True
        )
        self.addCleanup(self.i_futura.file_tesi.delete, save=False)
        self.assertFalse(
            self.appello.commissione.docenti.filter(pk=self.relatore.pk).exists()
        )
        self.client.force_login(self.relatore)
        resp = self.client.get(
            reverse("appelli:scarica_tesi", args=[self.i_futura.id])
        )
        self.assertEqual(resp.status_code, 200)

    def test_commissario_non_relatore_non_valuta(self):
        """Essere in commissione non basta: la valutazione la scrive il relatore."""
        self.client.force_login(self.docente)
        resp = self.client.post(self.url_valuta, {"titolo": "X", "punteggio": "2"})
        self.assertEqual(resp.status_code, 403)
        self.i_futura.refresh_from_db()
        self.assertIsNone(self.i_futura.punteggio)

    def test_studente_non_valuta_se_stesso(self):
        self.client.force_login(self.studente)
        resp = self.client.post(self.url_valuta, {"titolo": "X", "punteggio": "2"})
        self.assertEqual(resp.status_code, 403)

    def test_relatore_salva_titolo_punteggio_e_giudizio(self):
        self.client.force_login(self.relatore)
        resp = self.client.post(self.url_valuta, {
            "titolo": "Titolo corretto",
            "punteggio": "1",
            "giudizio": "Lavoro solido.",
            "ritorno": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.i_futura.refresh_from_db()
        self.assertEqual(self.i_futura.titolo, "Titolo corretto")
        self.assertEqual(self.i_futura.punteggio, 1)
        self.assertEqual(self.i_futura.giudizio, "Lavoro solido.")

    def test_titolo_non_svuotabile_dal_relatore(self):
        """Vale la stessa regola dello studente: correggere si', svuotare no."""
        self.client.force_login(self.relatore)
        self.client.post(self.url_valuta, {
            "titolo": "", "punteggio": "1", "giudizio": "Va bene.",
        })
        self.i_futura.refresh_from_db()
        self.assertEqual(self.i_futura.titolo, "Tesi futura")

    def test_ritorno_manomesso_non_porta_fuori_dal_sito(self):
        """Del 'ritorno' si tengono solo i filtri: il percorso lo rifa' reverse()."""
        self.client.force_login(self.relatore)
        resp = self.client.post(self.url_valuta, {
            "titolo": "T", "punteggio": "1", "giudizio": "Va bene.",
            "ritorno": "q=ciao&next=https://esempio.invalido/rubato",
        })
        self.assertNotIn("esempio.invalido", resp["Location"])
        self.assertTrue(resp["Location"].startswith(reverse("appelli:docente_dashboard")))
        self.assertIn("q=ciao", resp["Location"])

    # --- Il punteggio non esce dall'area docenti -------------------------

    def test_area_studente_non_mostra_punteggio_ne_giudizio(self):
        self.i_futura.punteggio = 2
        self.i_futura.giudizio = "GIUDIZIO_RISERVATO"
        self.i_futura.save()
        self.client.force_login(self.studente)
        for url in (
            reverse("appelli:studente_dashboard"),
            reverse("appelli:carica_tesi", args=[self.i_futura.id]),
        ):
            with self.subTest(url=url):
                pagina = self.client.get(url).content.decode()
                self.assertNotIn("GIUDIZIO_RISERVATO", pagina)
                self.assertNotIn("punteggio", pagina.lower())

    # --- Vincolo sul punteggio -------------------------------------------

    def test_punteggio_fuori_intervallo_rifiutato_dal_modello(self):
        """Non solo dal form: full_clean e database devono dire di no entrambi."""
        for valore in (3, -1):
            with self.subTest(punteggio=valore):
                iscrizione = StudenteAppelloDiLaurea(
                    studente=self.studente, appello=self.passato, punteggio=valore
                )
                with self.assertRaises(ValidationError):
                    iscrizione.full_clean()
                with self.assertRaises(IntegrityError), transaction.atomic():
                    StudenteAppelloDiLaurea.objects.create(
                        studente=self.studente, appello=self.passato, punteggio=valore
                    )

    def test_zero_e_un_punteggio_valido_non_un_assenza(self):
        """Lo zero e' una proposta, non un "non valutato": vanno distinti."""
        self.i_futura.punteggio = 0
        self.i_futura.save()
        self.assertTrue(self.i_futura.valutata)
        self.assertFalse(self.i_passata.valutata)

        # Un secondo tutorato nello stesso appello, non valutato: e' il
        # confronto che conta, "0 punti" accanto a "Da valutare".
        terzo = User.objects.create_user("studente_zero", password="pw")
        terzo.groups.add(self.g_studente)
        StudenteAppelloDiLaurea.objects.create(
            studente=terzo, appello=self.appello, tutor=self.relatore
        )

        sezione = self._sezione()
        self.assertIn('punti-valore">0<', sezione)
        self.assertIn("/2 punti", sezione)
        self.assertIn("Da valutare", sezione)

    # --- Raggruppamento, filtro e ricerca --------------------------------

    def test_i_tutoraggi_passati_non_compaiono(self):
        """Una tesi gia' discussa non si valuta piu': fuori dall'elenco.

        Nemmeno passando a mano il vecchio parametro, che non esiste piu': il
        filtro e' nella query, non in una spunta dell'interfaccia.
        """
        for query in ("", "?passati=1"):
            with self.subTest(query=query):
                sezione = self._sezione(query)
                self.assertNotIn("Corso Passato", sezione)
                self.assertNotIn("Tesi passata", sezione)

    def test_la_ricerca_non_riporta_i_tutoraggi_passati(self):
        """Cercare non e' una scorciatoia per rivedere cio' che e' escluso."""
        sezione = self._sezione("?q=quaglia")
        self.assertNotIn("Tesi passata", sezione)
        self.assertIn("0 risultati", sezione)

    def test_la_ricerca_trova_per_cognome_e_per_titolo(self):
        sezione = self._sezione("?q=futura")
        self.assertIn("Tesi futura", sezione)
        self.assertIn("1 risultato", sezione)

    # --- Ricerca in tempo reale (endpoint interno) -----------------------

    def _cerca(self, utente, termine, ajax=True):
        self.client.force_login(utente)
        intestazioni = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"} if ajax else {}
        return self.client.get(
            reverse("appelli:cerca_tutorati"), {"q": termine}, **intestazioni
        )

    def test_endpoint_restituisce_le_righe_dei_propri_tutorati(self):
        resp = self._cerca(self.relatore, "futura")
        self.assertEqual(resp.status_code, 200)
        dati = resp.json()
        self.assertEqual(dati["numero"], 1)
        self.assertIn("Tesi futura", dati["html"])
        # Le righe arrivano complete del modulo di valutazione: e' la ragione
        # per cui l'endpoint risponde HTML invece che JSON.
        self.assertIn("csrfmiddlewaretoken", dati["html"])

    def test_endpoint_mostra_solo_i_propri_tutorati(self):
        """Il docente in commissione non e' relatore: per lui non c'e' nulla."""
        dati = self._cerca(self.docente, "futura").json()
        self.assertEqual(dati["numero"], 0)
        self.assertNotIn("Tesi futura", dati["html"])

    def test_endpoint_vietato_allo_studente(self):
        self.assertEqual(self._cerca(self.studente, "futura").status_code, 403)

    def test_endpoint_solo_dall_applicazione(self):
        """Senza l'intestazione delle richieste interne non risponde."""
        self.assertEqual(
            self._cerca(self.relatore, "futura", ajax=False).status_code, 403
        )

    def test_riepilogo_del_gruppo_conta_i_da_valutare(self):
        terzo = User.objects.create_user("studente_tre", password="pw")
        terzo.groups.add(self.g_studente)
        StudenteAppelloDiLaurea.objects.create(
            studente=terzo, appello=self.appello, tutor=self.relatore
        )
        self.i_futura.punteggio = 2
        self.i_futura.save()

        sezione = self._sezione()
        self.assertIn("2 studenti", sezione)
        self.assertIn("1 da valutare", sezione)

    def test_le_query_non_crescono_con_i_tutorati(self):
        """Il template non deve interrogare il database una volta per riga."""
        self.client.force_login(self.relatore)
        url = reverse("appelli:docente_dashboard")
        with CaptureQueriesContext(connection) as prima:
            self.client.get(url)

        for numero in range(10):
            extra = User.objects.create_user(f"studente_extra_{numero}", password="pw")
            extra.groups.add(self.g_studente)
            StudenteAppelloDiLaurea.objects.create(
                studente=extra, appello=self.appello, tutor=self.relatore
            )

        with CaptureQueriesContext(connection) as dopo:
            self.client.get(url)
        self.assertEqual(len(prima.captured_queries), len(dopo.captured_queries))


class RegoleNuoveAppelloTest(BaseSetup):
    """Data non nel passato e almeno uno studente, alla creazione di un appello."""

    def setUp(self):
        super().setUp()
        self.presidente = User.objects.create_user("pres_regole", password="pw")
        self.presidente.groups.add(
            self.g_docente, Group.objects.get(name="presidente")
        )
        self.client.force_login(self.presidente)

    def _dati(self, **extra):
        dati = {
            "corso_di_laurea": "Ingegneria Informatica",
            "data": (datetime.date.today() + datetime.timedelta(days=30)).isoformat(),
            "ora": "10:00",
            "docenti": [self.docente.pk],
            "studenti": [self.studente.pk],
        }
        dati.update(extra)
        return dati

    # --- Almeno uno studente ---------------------------------------------

    def test_senza_studenti_l_appello_non_nasce(self):
        dati = self._dati()
        del dati["studenti"]
        prima = AppelloDiLaurea.objects.count()
        resp = self.client.post(reverse("appelli:crea_appello"), dati)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AppelloDiLaurea.objects.count(), prima)
        self.assertContains(resp, "un appello senza studenti")

    def test_l_errore_sugli_studenti_e_in_un_box_di_avviso(self):
        dati = self._dati()
        del dati["studenti"]
        resp = self.client.post(reverse("appelli:crea_appello"), dati)
        self.assertContains(resp, "alert alert-danger")

    def test_con_studenti_l_appello_nasce(self):
        resp = self.client.post(reverse("appelli:crea_appello"), self._dati())
        self.assertEqual(resp.status_code, 302)
        appello = AppelloDiLaurea.objects.get(corso_di_laurea="Ingegneria Informatica")
        self.assertEqual(appello.iscrizioni.count(), 1)

    # --- Data non nel passato --------------------------------------------

    def test_data_passata_rifiutata(self):
        """Il limite del calendario e' solo un suggerimento: conta il server."""
        ieri = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        prima = AppelloDiLaurea.objects.count()
        resp = self.client.post(
            reverse("appelli:crea_appello"), self._dati(data=ieri)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AppelloDiLaurea.objects.count(), prima)
        self.assertContains(resp, "non può essere nel passato")

    def test_oggi_e_ammesso(self):
        oggi = datetime.date.today().isoformat()
        resp = self.client.post(
            reverse("appelli:crea_appello"), self._dati(data=oggi)
        )
        self.assertEqual(resp.status_code, 302)

    def test_il_calendario_parte_da_oggi(self):
        """L'attributo "min" evita all'utente di scegliere una data rifiutata."""
        resp = self.client.get(reverse("appelli:crea_appello"))
        self.assertContains(resp, 'min="%s"' % datetime.date.today().isoformat())


class ValutazioneObbligatoriaTest(BaseSetup):
    """Punteggio e giudizio vanno insieme: o tutti e due, o nessuno dei due."""

    def setUp(self):
        super().setUp()
        self.relatore = User.objects.create_user("rel_obbl", password="pw")
        self.relatore.groups.add(self.g_docente)
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello,
            tutor=self.relatore, titolo="Una tesi",
        )
        self.url = reverse("appelli:salva_valutazione", args=[self.iscrizione.id])
        self.client.force_login(self.relatore)

    def test_punteggio_senza_giudizio_non_salva(self):
        self.client.post(self.url, {"titolo": "Una tesi", "punteggio": "2"})
        self.iscrizione.refresh_from_db()
        self.assertIsNone(self.iscrizione.punteggio)

    def test_giudizio_senza_punteggio_non_salva(self):
        self.client.post(self.url, {"titolo": "Una tesi", "giudizio": "Ottimo."})
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.giudizio, "")

    def test_con_entrambi_salva(self):
        self.client.post(self.url, {
            "titolo": "Una tesi", "punteggio": "2", "giudizio": "Ottimo.",
        })
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.punteggio, 2)
        self.assertEqual(self.iscrizione.giudizio, "Ottimo.")

    def test_senza_nessuno_dei_due_si_salva_lo_stesso(self):
        """Il solo titolo resta correggibile su chi non e' ancora valutato."""
        resp = self.client.post(
            self.url, {"titolo": "Titolo corretto"}, follow=True
        )
        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.titolo, "Titolo corretto")
        self.assertIsNone(self.iscrizione.punteggio)
        self.assertNotIn("Modifica non salvata", resp.content.decode())

    # --- Niente deve andare perso ----------------------------------------

    def test_l_errore_non_fa_perdere_quello_che_era_stato_scritto(self):
        """La pagina si ridisegna con dentro il testo: non si riparte da zero."""
        resp = self.client.post(self.url, {
            "titolo": "Una tesi", "giudizio": "Un giudizio lungo da riscrivere.",
        })
        self.assertEqual(resp.status_code, 200)   # ridisegnata, non rimandata
        self.assertContains(resp, "Un giudizio lungo da riscrivere.")

    def test_il_pannello_torna_aperto_sulla_riga_sbagliata(self):
        resp = self.client.post(self.url, {
            "titolo": "Una tesi", "giudizio": "Solo il giudizio.",
        })
        # Gli spazi si normalizzano: nel template l'attributo id sta a capo.
        html = re.sub(r"\s+", " ", resp.content.decode())
        self.assertIn(
            'class="collapse js-modifica show" id="modifica-%d"' % self.iscrizione.id,
            html,
        )

    def test_la_ricerca_in_corso_non_si_perde(self):
        """I filtri arrivano dal campo "ritorno": la POST non ha querystring."""
        resp = self.client.post(self.url, {
            "titolo": "Una tesi", "giudizio": "Solo il giudizio.",
            "ritorno": "q=" + self.studente.username,
        })
        self.assertEqual(resp.context["ricerca_tutorati"], self.studente.username)

    def test_un_filtro_inventato_viene_scartato(self):
        """Del "ritorno" si tiene solo cio' che e' un filtro noto."""
        resp = self.client.post(self.url, {
            "titolo": "Una tesi", "giudizio": "Solo il giudizio.",
            "ritorno": "q=ciao&next=https://esempio.invalido/rubato",
        })
        self.assertEqual(resp.context["ricerca_tutorati"], "ciao")
        self.assertNotContains(resp, "esempio.invalido")

    def test_il_motivo_dice_quale_meta_manca(self):
        resp = self.client.post(
            self.url, {"titolo": "Una tesi", "punteggio": "2"}, follow=True
        )
        self.assertIn("scrivi anche il giudizio", resp.content.decode())

        resp = self.client.post(
            self.url, {"titolo": "Una tesi", "giudizio": "Ottimo."}, follow=True
        )
        self.assertIn("scegli anche il punteggio", resp.content.decode())


class MancanzeAreaStudenteTest(BaseSetup):
    """Ogni dato mancante ha il suo riquadro, dove il dato dovrebbe stare."""

    def setUp(self):
        super().setUp()
        self.iscrizione = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello
        )
        self.client.force_login(self.studente)

    def _pagina(self):
        return self.client.get(
            reverse("appelli:studente_dashboard")
        ).content.decode()

    def test_tre_riquadri_quando_manca_tutto(self):
        pagina = self._pagina()
        for atteso in ("Titolo mancante", "Tutor mancante",
                       "Tesi mancante"):
            with self.subTest(riquadro=atteso):
                self.assertIn(atteso, pagina)
        # class="badge-manca e non "badge-manca": la seconda forma conterebbe
        # anche la regola CSS che sta nel <style> della pagina.
        self.assertEqual(pagina.count('class="badge-manca'), 3)

    def test_il_riquadro_sparisce_quando_il_dato_c_e(self):
        self.iscrizione.titolo = "Un titolo"
        self.iscrizione.tutor = self.docente
        self.iscrizione.save()
        pagina = self._pagina()
        self.assertNotIn("Titolo mancante", pagina)
        self.assertNotIn("Tutor mancante", pagina)
        # La tesi manca ancora: il suo riquadro resta
        self.assertIn("Tesi mancante", pagina)

    def test_il_tutor_conta_fra_le_mancanze(self):
        """Altrimenti una card potrebbe dirsi completa e mostrare "Manca il tutor"."""
        self.iscrizione.titolo = "Un titolo"
        self.iscrizione.file_tesi.save(
            "t.pdf", SimpleUploadedFile("t.pdf", b"%PDF-1.7 x"), save=True
        )
        self.addCleanup(self.iscrizione.file_tesi.delete, save=False)
        self.assertEqual(self.iscrizione.mancanti, ["tutor"])
        self.assertIn("is-incompleto", self._pagina())


class DettaglioIscrittiRaggruppatiTest(BaseSetup):
    """Nel dettaglio dell'appello i propri laureandi stanno in cima, distinti."""

    def setUp(self):
        super().setUp()
        self.altro_docente = User.objects.create_user("doc_altro", password="pw")
        self.altro_docente.groups.add(self.g_docente)

        # Cognomi scelti apposta: in ordine alfabetico sarebbe Bianchi, Rossi,
        # Verdi, quindi se il raggruppamento non ci fosse Rossi (il proprio)
        # finirebbe in mezzo agli altri.
        self.mio = self._iscrivi("Mario", "Rossi", tutor=self.docente)
        self.suo1 = self._iscrivi("Anna", "Bianchi", tutor=self.altro_docente)
        self.suo2 = self._iscrivi("Luca", "Verdi", tutor=self.altro_docente)

        self.url = reverse("appelli:appello_detail", args=[self.appello.id])
        self.client.force_login(self.docente)

    def _iscrivi(self, nome, cognome, tutor):
        studente = User.objects.create_user(
            "%s_%s" % (nome.lower(), cognome.lower()), password="pw"
        )
        studente.first_name, studente.last_name = nome, cognome
        studente.save()
        studente.groups.add(self.g_studente)
        return StudenteAppelloDiLaurea.objects.create(
            studente=studente, appello=self.appello, tutor=tutor
        )

    def test_i_due_gruppi_contengono_le_persone_giuste(self):
        resp = self.client.get(self.url)
        self.assertEqual(list(resp.context["iscritti_miei"]), [self.mio])
        self.assertEqual(
            list(resp.context["iscritti_altri"]), [self.suo1, self.suo2]
        )

    def test_i_propri_laureandi_sono_in_cima(self):
        """Anche se il cognome li metterebbe in mezzo agli altri."""
        html = self.client.get(self.url).content.decode()
        self.assertLess(html.index("Mario Rossi"), html.index("Anna Bianchi"))

    def test_le_righe_dei_propri_sono_contrassegnate(self):
        html = self.client.get(self.url).content.decode()
        self.assertEqual(html.count('class="riga-mia"'), 1)
        self.assertIn("Di cui sei tutor", html)
        self.assertIn("Altri studenti", html)

    def test_senza_propri_laureandi_niente_intestazioni(self):
        """Un solo gruppo non ha bisogno di essere annunciato.

        Serve un commissario che non segua NESSUNO: altro_docente non va bene,
        perche' di suo e' relatore di due dei tre iscritti.
        """
        estraneo = User.objects.create_user("doc_estraneo", password="pw")
        estraneo.groups.add(self.g_docente)
        self.commissione.docenti.add(estraneo)
        self.client.force_login(estraneo)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("Di cui sei tutor", html)
        self.assertNotIn("Altri studenti", html)
        self.assertNotIn('class="riga-mia"', html)

    def test_dentro_un_gruppo_l_ordine_e_alfabetico(self):
        html = self.client.get(self.url).content.decode()
        self.assertLess(html.index("Anna Bianchi"), html.index("Luca Verdi"))


class ValutazioneDalDettaglioTest(BaseSetup):
    """Dal dettaglio dell'appello il relatore valuta i propri laureandi.

    "docente_test" (da BaseSetup) siede in commissione ed e' relatore di uno
    solo dei due iscritti: l'altro e' di un collega, e il suo modulo non deve
    comparire.
    """

    def setUp(self):
        super().setUp()
        self.collega = User.objects.create_user("doc_collega", password="pw")
        self.collega.groups.add(self.g_docente)

        self.mia = StudenteAppelloDiLaurea.objects.create(
            studente=self.studente, appello=self.appello,
            tutor=self.docente, titolo="Tesi mia",
        )
        altro = User.objects.create_user("studente_altro", password="pw")
        altro.groups.add(self.g_studente)
        self.sua = StudenteAppelloDiLaurea.objects.create(
            studente=altro, appello=self.appello,
            tutor=self.collega, titolo="Tesi sua",
        )
        self.url = reverse("appelli:appello_detail", args=[self.appello.id])
        self.url_valuta = reverse("appelli:salva_valutazione", args=[self.mia.id])
        self.client.force_login(self.docente)

    def _post(self, **dati):
        valori = {"titolo": "Tesi mia", "ritorno": self.url}
        valori.update(dati)
        return self.client.post(self.url_valuta, valori)

    # --- La pagina ---------------------------------------------------------

    def test_il_modulo_c_e_solo_per_i_propri_laureandi(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('id="modifica-%d"' % self.mia.id, html)
        self.assertNotIn('id="modifica-%d"' % self.sua.id, html)
        self.assertNotIn(
            reverse("appelli:salva_valutazione", args=[self.sua.id]), html
        )

    def test_il_ritorno_del_modulo_e_la_pagina_stessa(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="ritorno" value="%s"' % self.url, html)

    def test_punteggio_mostrato_come_voto(self):
        self.mia.punteggio = 0
        self.mia.giudizio = "Da rivedere."
        self.mia.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["punteggio_massimo"], PUNTEGGIO_MAX)
        html = re.sub(r"\s+", " ", resp.content.decode())
        self.assertIn('<span class="punti-scala">/%d punti</span>' % PUNTEGGIO_MAX, html)
        self.assertNotIn('class="pill-da-valutare"', html)

    def test_pagina_con_modale_e_script_condiviso(self):
        for url in (self.url, reverse("appelli:docente_dashboard")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn('id="modaleValutazione"', html)
                script = re.findall(r'<script src="[^"]*valutazione[^"]*\.js"', html)
                self.assertEqual(len(script), 1)

    # --- Il salvataggio ----------------------------------------------------

    def test_salvato_si_torna_al_dettaglio_sulla_riga(self):
        resp = self._post(punteggio="2", giudizio="Ottimo.")
        self.assertRedirects(
            resp, f"{self.url}#tutorato-{self.mia.id}", fetch_redirect_response=False
        )
        self.mia.refresh_from_db()
        self.assertEqual(self.mia.punteggio, 2)

    def test_errore_ridisegna_il_dettaglio_col_modulo_aperto(self):
        resp = self._post(giudizio="Solo il giudizio.")
        self.assertTemplateUsed(resp, "appelli/appello_detail.html")
        self.assertEqual(resp.context["valutazione_aperta"], self.mia.id)
        html = re.sub(r"\s+", " ", resp.content.decode())
        self.assertIn(
            'class="collapse js-modifica show" id="modifica-%d"' % self.mia.id, html
        )
        self.assertIn("Solo il giudizio.", html)

    def test_ritorno_di_un_altro_appello_non_accettato(self):
        """Solo il dettaglio dell'appello dello studente: il resto va in dashboard."""
        altro = AppelloDiLaurea.objects.create(
            data=datetime.date(2030, 2, 1),
            corso_di_laurea="Altro corso",
            commissione=self.commissione,
        )
        resp = self._post(
            punteggio="1", giudizio="Va bene.",
            ritorno=reverse("appelli:appello_detail", args=[altro.id]),
        )
        self.assertTrue(
            resp["Location"].startswith(reverse("appelli:docente_dashboard"))
        )

    def test_ritorno_manomesso_non_porta_fuori_dal_sito(self):
        resp = self._post(
            punteggio="1", giudizio="Va bene.",
            ritorno="https://esempio.invalido" + self.url,
        )
        self.assertNotIn("esempio.invalido", resp["Location"])
        self.assertTrue(
            resp["Location"].startswith(reverse("appelli:docente_dashboard"))
        )

    def test_relatore_fuori_commissione_non_riceve_il_dettaglio(self):
        """Sugli errori non gli si ridisegna una pagina che non potrebbe aprire."""
        self.commissione.docenti.remove(self.docente)
        resp = self._post(giudizio="Solo il giudizio.")
        self.assertTemplateUsed(resp, "appelli/docente_dashboard.html")
        self.assertNotContains(resp, "Tesi sua")

        resp = self._post(punteggio="1", giudizio="Va bene.")
        self.assertTrue(
            resp["Location"].startswith(reverse("appelli:docente_dashboard"))
        )
