"""Schema iniziale: commissioni, appelli di laurea e iscrizioni.

Traduce in tabelle il diagramma ER della tesi. I vincoli qui definiti sono
poi stati allargati dalle migrazioni successive (la 0006 aggiunge la
commissione alla chiave dell'appello); questa resta come punto di partenza di
un database vuoto.
"""

# Generato da Django 6.0.5 il 2026-06-29 13:46

import appelli.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Commissione',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(blank=True, max_length=255)),
                ('docenti', models.ManyToManyField(help_text='Docenti che fanno parte della commissione.', limit_choices_to={'groups__name': 'docente'}, related_name='commissioni', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Commissione',
                'verbose_name_plural': 'Commissioni',
            },
        ),
        migrations.CreateModel(
            name='AppelloDiLaurea',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data', models.DateField()),
                ('corso_di_laurea', models.CharField(max_length=255)),
                ('commissione', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appelli', to='appelli.commissione')),
            ],
            options={
                'verbose_name': 'Appello di laurea',
                'verbose_name_plural': 'Appelli di laurea',
                'ordering': ['-data'],
            },
        ),
        migrations.CreateModel(
            name='StudenteAppelloDiLaurea',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('data_iscrizione', models.DateTimeField(auto_now_add=True)),
                ('file_tesi', models.FileField(blank=True, help_text='File della tesi di laurea.', null=True, upload_to=appelli.models.percorso_file_tesi)),
                ('appello', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='iscrizioni', to='appelli.appellodilaurea')),
                ('studente', models.ForeignKey(limit_choices_to={'groups__name': 'studente'}, on_delete=django.db.models.deletion.CASCADE, related_name='iscrizioni', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Iscrizione',
                'verbose_name_plural': 'Iscrizioni',
                'ordering': ['-data_iscrizione'],
            },
        ),
        migrations.AddConstraint(
            model_name='appellodilaurea',
            constraint=models.UniqueConstraint(fields=('data', 'corso_di_laurea'), name='unique_appello_data_corso'),
        ),
        migrations.AddConstraint(
            model_name='studenteappellodilaurea',
            constraint=models.UniqueConstraint(fields=('studente', 'appello'), name='unique_iscrizione_studente_appello'),
        ),
    ]
