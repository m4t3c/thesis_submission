import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Rinomina il related_name del tutor da "tutorati" a "laureandi".

    Cambia solo lo stato: il related_name non tocca lo schema del database.
    """

    dependencies = [
        ('appelli', '0011_valutazione_relatore'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='studenteappellodilaurea',
            name='tutor',
            field=models.ForeignKey(blank=True, help_text='Docente che segue lo studente per questa tesi.', limit_choices_to={'groups__name': 'docente'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='laureandi', to=settings.AUTH_USER_MODEL, verbose_name='Tutor'),
        ),
    ]
