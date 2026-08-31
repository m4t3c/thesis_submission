import datetime
import os

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

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
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)

    def _pdf(self, nome="tesi.pdf"):
        return SimpleUploadedFile(nome, b"%PDF-1.7 contenuto", content_type="application/pdf")

    def test_pdf_accettato(self):
        resp = self.client.post(self.url, {"file_tesi": self._pdf()})
        self.assertRedirects(resp, reverse("appelli:studente_dashboard"))
        self.iscrizione.refresh_from_db()
        self.assertTrue(self.iscrizione.file_tesi)

    def test_estensione_non_pdf_rifiutata(self):
        file = SimpleUploadedFile("tesi.docx", b"contenuto", content_type="application/msword")
        resp = self.client.post(self.url, {"file_tesi": file})
        self.assertEqual(resp.status_code, 200)  # resta sul form con l'errore
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_tesi)

    def test_finto_pdf_rifiutato(self):
        # Estensione e content-type giusti, ma il contenuto non e' un PDF.
        file = SimpleUploadedFile("tesi.pdf", b"PK\x03\x04 zip", content_type="application/pdf")
        resp = self.client.post(self.url, {"file_tesi": file})
        self.assertEqual(resp.status_code, 200)
        self.iscrizione.refresh_from_db()
        self.assertFalse(self.iscrizione.file_tesi)

    def test_file_non_rimovibile(self):
        self.client.post(self.url, {"file_tesi": self._pdf()})
        self.iscrizione.refresh_from_db()
        nome_iniziale = self.iscrizione.file_tesi.name

        # Tentativo di svuotamento: checkbox "clear" di Django e invio a vuoto.
        self.client.post(self.url, {"file_tesi-clear": "on"})
        self.client.post(self.url, {})

        self.iscrizione.refresh_from_db()
        self.assertEqual(self.iscrizione.file_tesi.name, nome_iniziale)

    def test_sostituzione_consentita(self):
        self.client.post(self.url, {"file_tesi": self._pdf("prima.pdf")})
        self.iscrizione.refresh_from_db()
        primo = self.iscrizione.file_tesi.name

        self.client.post(self.url, {"file_tesi": self._pdf("seconda.pdf")})
        self.iscrizione.refresh_from_db()
        self.assertNotEqual(self.iscrizione.file_tesi.name, primo)
        self.assertIn("seconda", self.iscrizione.file_tesi.name)

    def test_invio_a_vuoto_senza_tesi_da_errore(self):
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "obbligatorio")

    def test_stesso_nome_non_viene_rinominato(self):
        """Ricaricare un file con lo stesso nome non aggiunge suffissi casuali."""
        self.client.post(self.url, {"file_tesi": self._pdf("tesi.pdf")})
        self.iscrizione.refresh_from_db()
        primo = self.iscrizione.file_tesi.name
        self.assertTrue(primo.endswith("/tesi.pdf"), primo)

        nuovo = SimpleUploadedFile(
            "tesi.pdf", b"%PDF-1.7 versione aggiornata", content_type="application/pdf"
        )
        self.client.post(self.url, {"file_tesi": nuovo})
        self.iscrizione.refresh_from_db()

        # Stesso percorso di prima e contenuto aggiornato: e' stato sovrascritto.
        self.assertEqual(self.iscrizione.file_tesi.name, primo)
        with self.iscrizione.file_tesi.open("rb") as f:
            self.assertEqual(f.read(), b"%PDF-1.7 versione aggiornata")

        # Nella cartella dell'iscrizione resta un solo file.
        cartella = os.path.dirname(self.iscrizione.file_tesi.path)
        self.assertEqual(os.listdir(cartella), ["tesi.pdf"])
