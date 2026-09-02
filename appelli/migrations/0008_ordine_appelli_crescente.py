"""Ordina gli appelli dal piu' vecchio al piu' recente.

Cambia solo Meta.ordering: nessuna modifica allo schema, e nessun effetto
sui dati. Vale per ogni elenco di appelli, comprese le liste costruite nei
template.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appelli', '0007_titolo_e_video'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='appellodilaurea',
            options={'ordering': ['data', models.OrderBy(models.F('ora'), nulls_last=True)], 'verbose_name': 'Appello di laurea', 'verbose_name_plural': 'Appelli di laurea'},
        ),
    ]
