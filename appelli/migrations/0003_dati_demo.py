"""Inserisce gli utenti (e i dati) di esempio direttamente nel database.

Stanno in una migrazione, e non solo nel comando omonimo, per renderli
riproducibili dal codice versionato senza dipendere dal file db.sqlite3, che
e' escluso da git.

Stessi dati del comando `python manage.py crea_dati_demo`:
  - studente1 / studente2   (gruppo "studente")
  - docente1  / docente2    (gruppo "docente")
  - una Commissione con i due docenti
  - un AppelloDiLaurea associato a quella commissione
Password di tutti gli utenti: "password123".
"""
import datetime

from django.contrib.auth.hashers import make_password
from django.db import migrations

PASSWORD = "password123"
STUDENTI = ["studente1", "studente2"]
DOCENTI = ["docente1", "docente2"]


def crea_dati(apps, schema_editor):
    """Crea utenti, commissione e appello di esempio, se non ci sono gia'.

    I modelli si prendono da ``apps`` e non con un import: una migrazione deve
    vedere le tabelle com'erano al momento in cui e' stata scritta, altrimenti
    smetterebbe di funzionare al primo campo aggiunto in seguito.
    """
    User = apps.get_model("auth", "User")
    Group = apps.get_model("auth", "Group")
    Commissione = apps.get_model("appelli", "Commissione")
    AppelloDiLaurea = apps.get_model("appelli", "AppelloDiLaurea")

    g_studente = Group.objects.get(name="studente")
    g_docente = Group.objects.get(name="docente")
    password_hash = make_password(PASSWORD)

    def crea_utente(username, gruppo):
        user, creato = User.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "password": password_hash,
            },
        )
        user.groups.add(gruppo)
        return user

    for username in STUDENTI:
        crea_utente(username, g_studente)
    docenti = [crea_utente(username, g_docente) for username in DOCENTI]

    commissione, _ = Commissione.objects.get_or_create(nome="Commissione A")
    commissione.docenti.set(docenti)

    AppelloDiLaurea.objects.get_or_create(
        data=datetime.date.today() + datetime.timedelta(days=30),
        corso_di_laurea="Informatica",
        defaults={"commissione": commissione},
    )


def elimina_dati(apps, schema_editor):
    """Rimuove i soli utenti demo in caso di annullamento della migrazione.

    Commissione e appello restano: potrebbero nel frattempo essere stati usati
    per dati veri, e cancellarli a catena farebbe piu' danno che pulizia.
    """
    User = apps.get_model("auth", "User")
    User.objects.filter(username__in=STUDENTI + DOCENTI).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appelli", "0002_gruppi_utenti"),
    ]

    operations = [
        migrations.RunPython(crea_dati, elimina_dati),
    ]
