"""Storage dei file caricati che sovrascrive invece di rinominare."""
from django.core.files.storage import FileSystemStorage


class SovrascriviStorage(FileSystemStorage):
    """FileSystemStorage che riusa il nome richiesto anche se gia' occupato.

    Comportamento predefinito di Django: prima di scrivere, lo storage chiama
    ``get_available_name`` e, se il nome esiste gia', ne restituisce uno libero
    aggiungendo sette caratteri casuali (``tesi.pdf`` -> ``tesi_a8Fk2Pq.pdf``).
    Caricando una nuova versione della tesi con lo stesso nome del file
    precedente il caso si verifica sempre: il file vecchio e' ancora sul disco
    perche' django-cleanup lo rimuove solo DOPO il salvataggio.

    Qui il vecchio file viene eliminato prima, cosi' il nome torna libero e la
    tesi conserva il nome scelto dallo studente. E' sicuro perche' ogni
    iscrizione ha una cartella tutta sua (vedi ``percorso_file_tesi``) che
    contiene una sola tesi: l'unico file che si puo' sovrascrivere e' la
    versione precedente della stessa tesi, che va comunque sostituita.
    """

    def get_available_name(self, name, max_length=None):
        if self.exists(name):
            self.delete(name)
        # super() gestisce il troncamento su max_length e resta come rete di
        # sicurezza nel caso (ormai improbabile) il nome sia ancora occupato.
        return super().get_available_name(name, max_length=max_length)
