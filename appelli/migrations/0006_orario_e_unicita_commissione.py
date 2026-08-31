"""Orario dell'appello e nuovo vincolo di unicita' data + corso + commissione.

Il vincolo nuovo e' piu' permissivo di quello che sostituisce (aggiunge una
colonna alla chiave), quindi qualsiasi dato che rispettava il precedente
rispetta anche questo: non puo' fallire su un database gia' popolato.
Il campo "ora" nasce NULL sugli appelli esistenti.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appelli', '0005_storage_sovrascrivi'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='appellodilaurea',
            options={'ordering': ['-data', '-ora'], 'verbose_name': 'Appello di laurea', 'verbose_name_plural': 'Appelli di laurea'},
        ),
        migrations.RemoveConstraint(
            model_name='appellodilaurea',
            name='unique_appello_data_corso',
        ),
        migrations.AddField(
            model_name='appellodilaurea',
            name='ora',
            field=models.TimeField(blank=True, help_text='Orario di inizio della seduta (facoltativo).', null=True, verbose_name='Orario'),
        ),
        migrations.AddConstraint(
            model_name='appellodilaurea',
            constraint=models.UniqueConstraint(fields=('data', 'corso_di_laurea', 'commissione'), name='unique_appello_data_corso_commissione'),
        ),
    ]
