import datetime

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import AppelloDiLaurea, Commissione, StudenteAppelloDiLaurea


class BaseSetup(TestCase):
    def setUp(self):
        self.g_studente = Group.objects.get(name="studente")
        self.g_docente = Group.objects.get(name="docente")

        self.studente = User.objects.create_user("studente1", password="pw")
        self.studente.groups.add(self.g_studente)

        self.docente = User.objects.create_user("docente1", password="pw")
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
        altro = User.objects.create_user("docente2", password="pw")
        altro.groups.add(self.g_docente)
        self.client.force_login(altro)
        resp = self.client.get(
            reverse("appelli:scarica_tesi", args=[self.iscrizione.id])
        )
        self.assertEqual(resp.status_code, 403)

    def tearDown(self):
        if self.iscrizione.file_tesi:
            self.iscrizione.file_tesi.delete(save=False)
