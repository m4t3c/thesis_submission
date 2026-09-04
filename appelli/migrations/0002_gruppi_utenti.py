"""Crea i gruppi "studente" e "docente", su cui si reggono i ruoli.

Sono gruppi di Django ordinari, ma l'applicazione li da' per esistenti: le
view ci filtrano sopra e il login Shibboleth ci assegna l'utente. Crearli qui
invece che a mano significa che un database appena migrato e' gia' pronto
all'uso, in qualunque ambiente.
"""
from django.db import migrations

GRUPPI = ["studente", "docente"]


def crea_gruppi(apps, schema_editor):
    """Aggiunge i gruppi mancanti, lasciando intatti quelli gia' presenti."""
    Group = apps.get_model("auth", "Group")
    for nome in GRUPPI:
        Group.objects.get_or_create(name=nome)


def elimina_gruppi(apps, schema_editor):
    """Rimuove i gruppi in caso di annullamento della migrazione."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GRUPPI).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appelli", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(crea_gruppi, elimina_gruppi),
    ]
