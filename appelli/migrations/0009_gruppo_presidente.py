"""Crea il gruppo "presidente".

A differenza di "studente" e "docente", questo gruppo NON viene assegnato
automaticamente al login: l'affiliation Shibboleth di un presidente e' identica
a quella di un qualunque docente ({member, employee, faculty}), quindi non c'e'
modo di distinguerlo dagli attributi. L'assegnazione si fa a mano dall'area
amministrativa, ed e' proprio per questo che il gruppo NON compare in
GRUPPI_NOTI di assign_user.py: se ci fosse, verrebbe revocato a ogni accesso.
"""
from django.db import migrations

GRUPPO = "presidente"


def crea_gruppo(apps, schema_editor):
    """Aggiunge il gruppo, se non esiste gia'."""
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=GRUPPO)


def elimina_gruppo(apps, schema_editor):
    """Rimuove il gruppo in caso di annullamento della migrazione."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name=GRUPPO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("appelli", "0008_ordine_appelli_crescente"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(crea_gruppo, elimina_gruppo),
    ]
