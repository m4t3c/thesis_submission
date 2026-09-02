import datetime
import os

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .forms import MAX_BYTE_VIDEO
from .models import AppelloDiLaurea, Commissione, StudenteAppelloDiLaurea


class BaseSetup(TestCase):
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
    def test_studente_redirezione_home(self):
        self.client.force_login(self.studente)
        resp = self.client.get(reverse("appelli:home"))
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))

    def test_docente_redirezione_home(self):
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:home"))
        self.assertRedirects(resp, reverse("appelli:docente_dashboard"))

    def test_docente_non_accede_area_studente(self):
        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:studente_dashboard"))
        self.assertEqual(resp.status_code, 403)


class IscrizioneTest(BaseSetup):
    def test_studente_si_iscrive(self):
        self.client.force_login(self.studente)
        resp = self.client.post(
            reverse("appelli:iscriviti", args=[self.appello.id])
        )
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.assertTrue(
            StudenteAppelloDiLaurea.objects.filter(
                studente=self.studente, appello=self.appello
            ).exists()
        )

    def test_docente_non_si_iscrive(self):
        # Vincolo applicato lato view: il docente non puo' iscriversi.
        self.client.force_login(self.docente)
        resp = self.client.post(
            reverse("appelli:iscriviti", args=[self.appello.id])
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(StudenteAppelloDiLaurea.objects.exists())


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
        """POST completo: il titolo e' obbligatorio in ogni salvataggio."""
        dati = {"titolo": self.TITOLO, "modalita_video": "nessuno"}
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

    def test_invio_a_vuoto_senza_tesi_da_errore(self):
        resp = self.client.post(self.url, self._dati())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "obbligatorio")

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
        self.assertIn("Commissione B", str(con))
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

        # E si puo' iscrivere proprio a quello scelto.
        self.client.post(reverse("appelli:iscriviti", args=[secondo.id]))
        self.assertTrue(
            StudenteAppelloDiLaurea.objects.filter(
                studente=self.studente, appello=secondo
            ).exists()
        )

    def test_messaggi_allo_studente_senza_commissione(self):
        """I messaggi delle view usano etichetta_pubblica, non __str__."""
        self.client.force_login(self.studente)

        resp = self.client.post(
            reverse("appelli:iscriviti", args=[self.appello.id]), follow=True
        )
        testo = resp.content.decode()
        self.assertIn("Iscrizione a", testo)
        self.assertNotIn("Commissione A", testo)

        resp = self.client.get(reverse("appelli:studente_dashboard"))
        self.assertNotIn("Commissione A", resp.content.decode())

    def test_etichetta_pubblica_e_str(self):
        altra = Commissione.objects.create(nome="Commissione B")
        appello = self._altro_appello(altra, ora=datetime.time(9, 30))
        # Pubblica: corso, data, ora. Mai la commissione.
        self.assertIn("09:30", appello.etichetta_pubblica)
        self.assertNotIn("Commissione", appello.etichetta_pubblica)
        # Completa (admin / area docente): include la commissione.
        self.assertIn("Commissione B", str(appello))


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
    """Titolo obbligatorio e non rimovibile; video facoltativo, file O link."""

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
        dati = {"titolo": "Titolo iniziale", "modalita_video": "nessuno"}
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
        """La lista del docente e' costruita nel template, non in una view."""
        tardi = self._appello(20)
        presto = self._appello(5)

        self.client.force_login(self.docente)
        resp = self.client.get(reverse("appelli:docente_dashboard"))
        commissioni = list(resp.context["commissioni"])
        appelli = list(commissioni[0].appelli.all())
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
