from django.db import migrations

GRUPPI = ["studente", "docente"]


def crea_gruppi(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nome in GRUPPI:
        Group.objects.get_or_create(name=nome)


def elimina_gruppi(apps, schema_editor):
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
