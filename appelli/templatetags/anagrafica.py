"""Filtri per la resa dei nomi delle persone nei template."""
from django import template

register = template.Library()


@register.filter
def cognome_nome(utente):
    """Nome della persona nella forma "Cognome Nome".

    Negli elenchi di studenti l'ordinamento e' alfabetico per cognome: se la
    colonna mostrasse "Nome Cognome" l'ordine sembrerebbe casuale, perche' la
    parola su cui si ordina non sarebbe quella che si legge per prima.

    Si adatta all'anagrafica incompleta, che con l'import da xlsx e' la norma
    finche' lo studente non entra almeno una volta: con un solo campo valorizzato
    restituisce quello, e senza nessuno ripiega sullo username (com'e' sempre
    stato, per non lasciare una cella vuota).
    """
    if not utente:
        return ""
    parti = [p for p in (utente.last_name, utente.first_name) if p]
    return " ".join(parti) or utente.get_username()
