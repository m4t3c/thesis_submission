"""Limita il file della tesi al solo formato PDF.

Modifica solo i metadati del campo (validatori e help_text): a livello di
database non cambia nulla, ma Django richiede comunque una migrazione per
tenere allineato lo stato dei modelli.
"""
import django.core.validators
from django.db import migrations, models

import appelli.models


class Migration(migrations.Migration):

    dependencies = [
        ("appelli", "0003_dati_demo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studenteappellodilaurea",
            name="file_tesi",
            field=models.FileField(
                blank=True,
                help_text="File della tesi di laurea, in formato PDF.",
                null=True,
                upload_to=appelli.models.percorso_file_tesi,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["pdf"]
                    )
                ],
            ),
        ),
    ]
