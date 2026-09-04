"""Punto di ingresso WSGI del progetto: e' quello usato in produzione.

Espone come ``application`` l'oggetto che Gunicorn richiama a ogni richiesta.

https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'thesis_submission.settings')

application = get_wsgi_application()
