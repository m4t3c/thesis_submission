"""Elimina i file orfani nella cartella dei media delle tesi.

Un file e' "orfano" se si trova sotto MEDIA_ROOT/tesi/ ma non e' piu'
referenziato da nessuna iscrizione (StudenteAppelloDiLaurea.file_tesi).
Questi file si accumulano per i caricamenti fatti PRIMA dell'introduzione di
django-cleanup (sostituzioni e svuotamenti del file non cancellavano il
vecchio file dal disco).

Uso:
  python manage.py pulisci_tesi_orfane            # ANTEPRIMA (non cancella)
  python manage.py pulisci_tesi_orfane --apply    # cancella davvero

Di default lavora in modalita' anteprima (dry-run): elenca cosa verrebbe
cancellato senza toccare nulla. Aggiungi --apply per eseguire la cancellazione.
Rimuove anche le cartelle rimaste vuote sotto tesi/.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from appelli.models import StudenteAppelloDiLaurea

SOTTOCARTELLA = "tesi"


class Command(BaseCommand):
    help = "Elimina i file delle tesi non piu' referenziati da nessuna iscrizione."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Esegue la cancellazione. Senza questo flag mostra solo l'anteprima.",
        )

    def handle(self, *args, **options):
        applica = options["apply"]
        base_tesi = os.path.join(settings.MEDIA_ROOT, SOTTOCARTELLA)

        if not os.path.isdir(base_tesi):
            self.stdout.write(f"Nessuna cartella «{base_tesi}»: niente da pulire.")
            return

        # Percorsi (assoluti) dei file ancora referenziati nel database.
        referenziati = set()
        for nome in (
            StudenteAppelloDiLaurea.objects.exclude(file_tesi="")
            .exclude(file_tesi__isnull=True)
            .values_list("file_tesi", flat=True)
        ):
            referenziati.add(os.path.normpath(os.path.join(settings.MEDIA_ROOT, nome)))

        orfani = []
        for radice, _cartelle, files in os.walk(base_tesi):
            for f in files:
                percorso = os.path.normpath(os.path.join(radice, f))
                if percorso not in referenziati:
                    orfani.append(percorso)

        if not orfani:
            self.stdout.write(self.style.SUCCESS("Nessun file orfano trovato."))
        else:
            intestazione = (
                "File orfani ELIMINATI:" if applica else "File orfani (anteprima):"
            )
            self.stdout.write(intestazione)
            for percorso in orfani:
                rel = os.path.relpath(percorso, settings.MEDIA_ROOT)
                if applica:
                    try:
                        os.remove(percorso)
                        self.stdout.write(self.style.WARNING(f"  - {rel}"))
                    except OSError as exc:
                        self.stdout.write(
                            self.style.ERROR(f"  ! impossibile eliminare {rel}: {exc}")
                        )
                else:
                    self.stdout.write(f"  - {rel}")

        # Rimuove le cartelle rimaste vuote (solo in modalita' --apply).
        cartelle_rimosse = 0
        if applica:
            for radice, _cartelle, _files in os.walk(base_tesi, topdown=False):
                if radice == base_tesi:
                    continue
                if not os.listdir(radice):
                    try:
                        os.rmdir(radice)
                        cartelle_rimosse += 1
                    except OSError:
                        pass

        # Riepilogo finale.
        if applica:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Fatto: {len(orfani)} file eliminati, "
                    f"{cartelle_rimosse} cartelle vuote rimosse."
                )
            )
        elif orfani:
            self.stdout.write(
                f"\n{len(orfani)} file verrebbero eliminati. "
                "Rilancia con --apply per procedere."
            )
