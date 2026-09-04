#!/usr/bin/env python
"""Utilita' da riga di comando di Django (migrazioni, test, avvio locale)."""
import os
import sys


def main():
    """Esegue il comando ricevuto da riga di comando."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'thesis_submission.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
