"""Assegna al file della tesi lo storage che sovrascrive invece di rinominare.

Come la 0004, cambia solo i metadati del campo: a livello di database non
viene toccato nulla.
"""

import appelli.models
import appelli.storage
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appelli', '0004_solo_pdf'),
    ]

    operations = [
        migrations.AlterField(
            model_name='studenteappellodilaurea',
            name='file_tesi',
            field=models.FileField(blank=True, help_text='File della tesi di laurea, in formato PDF.', null=True, storage=appelli.storage.SovrascriviStorage(), upload_to=appelli.models.percorso_file_tesi, validators=[django.core.validators.FileExtensionValidator(allowed_extensions=['pdf'])]),
        ),
    ]
