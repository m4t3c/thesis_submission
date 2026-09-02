"""Titolo della tesi e video di presentazione (file oppure link).

Tutti campi nuovi e facoltativi a livello di database: le iscrizioni gia'
esistenti restano valide con titolo vuoto e nessun video. Il CheckConstraint
impedisce che file e link siano valorizzati insieme; essendo entrambi vuoti
sulle righe esistenti, il vincolo e' soddisfatto da subito.
"""

import appelli.models
import appelli.storage
import django.core.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appelli', '0006_orario_e_unicita_commissione'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='studenteappellodilaurea',
            name='file_video',
            field=models.FileField(blank=True, help_text='Video di presentazione (facoltativo).', storage=appelli.storage.SovrascriviStorage(), upload_to=appelli.models.percorso_file_video, validators=[django.core.validators.FileExtensionValidator(allowed_extensions=['mp4', 'mov', 'm4v', 'webm', 'mkv', 'avi'])], verbose_name='File video'),
        ),
        migrations.AddField(
            model_name='studenteappellodilaurea',
            name='link_video',
            field=models.URLField(blank=True, help_text="Indirizzo di un video gia' pubblicato online (facoltativo).", max_length=500, verbose_name='Link al video'),
        ),
        migrations.AddField(
            model_name='studenteappellodilaurea',
            name='titolo',
            field=models.CharField(blank=True, help_text='Titolo della tesi di laurea.', max_length=500, verbose_name='Titolo della tesi'),
        ),
        migrations.AddConstraint(
            model_name='studenteappellodilaurea',
            constraint=models.CheckConstraint(condition=models.Q(('file_video', ''), ('link_video', ''), _connector='OR'), name='video_file_o_link_non_entrambi'),
        ),
    ]
