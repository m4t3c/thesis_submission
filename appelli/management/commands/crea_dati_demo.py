"""Crea dati di esempio per provare l'applicazione.

Uso:  python manage.py crea_dati_demo

Crea (se non esistono):
  - studente1 / studente2   (gruppo "studente")
  - docente1  / docente2    (gruppo "docente")
  - una Commissione con i due docenti
  - un AppelloDiLaurea associato a quella commissione
Tutte le password sono "password123".
"""
import datetime

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from appelli.models import AppelloDiLaurea, Commissione

PASSWORD = "password123"


class Command(BaseCommand):
    help = "Crea utenti, gruppi, una commissione e un appello di esempio."

    def _crea_utente(self, username, gruppo):
        """Utente demo con password nota, creato o riportato allo stato atteso.

        Il comando deve poter essere rilanciato senza effetti collaterali: si
        riparte sempre dagli utenti gia' presenti invece di duplicarli.
        """
        user, _creato = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com"},
        )
        # La password si reimposta ogni volta che non e' quella attesa, non
        # solo alla creazione: un utente demo gia' presente ma senza password
        # valida (creato a mano, o da un get_or_create che lascia il campo
        # vuoto) resterebbe altrimenti inaccessibile per sempre, e il comando
        # direbbe comunque che la password e' "password123".
        if not user.check_password(PASSWORD):
            user.set_password(PASSWORD)
            user.save()
        user.groups.add(Group.objects.get(name=gruppo))
        return user

    def handle(self, *args, **options):
        """Crea i tre profili di prova (studente, docente, presidente) e un appello."""
        studenti = [self._crea_utente(f"studente{i}", "studente") for i in (1, 2)]
        docenti = [self._crea_utente(f"docente{i}", "docente") for i in (1, 2)]
        # Il presidente e' un docente con in piu' il gruppo "presidente":
        # quel gruppo non arriva da Shibboleth, si assegna a mano.
        presidente = self._crea_utente("presidente1", "docente")
        presidente.groups.add(Group.objects.get(name="presidente"))

        commissione, _ = Commissione.objects.get_or_create(nome="Commissione A")
        commissione.docenti.set(docenti)

        # La commissione fa parte della chiave logica dell'appello, quindi va
        # nella ricerca e non nei soli defaults.
        appello, _ = AppelloDiLaurea.objects.get_or_create(
            data=datetime.date.today() + datetime.timedelta(days=30),
            corso_di_laurea="Informatica",
            commissione=commissione,
        )

        self.stdout.write(self.style.SUCCESS("Dati demo creati."))
        self.stdout.write(
            "Utenti: "
            + ", ".join(u.username for u in studenti + docenti + [presidente])
            + f" (password: {PASSWORD})"
        )
