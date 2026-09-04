"""Elimina i file orfani nella cartella dei media delle tesi.

Un file e' "orfano" se si trova sotto MEDIA_ROOT/tesi/ ma non e' piu'
referenziato da nessuna iscrizione (ne' da file_tesi ne' da file_video).
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
        # L'anteprima e' il comportamento predefinito: un comando che cancella
        # file non deve poterlo fare per una battitura distratta.
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Esegue la cancellazione. Senza questo flag mostra solo l'anteprima.",
        )

    def handle(self, *args, **options):
        """Confronta i file su disco con quelli referenziati e riporta gli orfani."""
        applica = options["apply"]
        base_tesi = os.path.join(settings.MEDIA_ROOT, SOTTOCARTELLA)

        if not os.path.isdir(base_tesi):
            self.stdout.write(f"Nessuna cartella «{base_tesi}»: niente da pulire.")
            return

        # Percorsi (assoluti) dei file ancora referenziati nel database.
        # ATTENZIONE: vanno inclusi TUTTI i campi file dell'iscrizione, non
        # solo la tesi. Ogni campo dimenticato qui diventa un file che questo
        # comando cancella pur essendo ancora in uso.
        referenziati = set()
        for tesi, video in StudenteAppelloDiLaurea.objects.values_list(
            "file_tesi", "file_video"
        ):
            for nome in (tesi, video):
                if not nome:
                    continue
                referenziati.add(
                    os.path.normpath(os.path.join(settings.MEDIA_ROOT, nome))
                )

        # Tutto cio' che sta sotto tesi/ e non compare fra i referenziati non
        # appartiene piu' a nessuna iscrizione.
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
        # topdown=False visita prima le sottocartelle: cosi' una cartella che
        # si svuota perche' e' stato eliminato il suo contenuto viene a sua
        # volta rimossa nella stessa passata.
        cartelle_rimosse = 0
        if applica:
            for radice, _cartelle, _files in os.walk(base_tesi, topdown=False):
                # La radice tesi/ resta: e' la cartella che l'applicazione si
                # aspetta di trovare.
                if radice == base_tesi:
                    continue
                if not os.listdir(radice):
                    try:
                        os.rmdir(radice)
                        cartelle_rimosse += 1
                    except OSError:
                        # Cartella non piu' vuota o non rimovibile: si tratta
                        # comunque di pulizia accessoria, non di un errore che
                        # debba fermare il comando.
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
