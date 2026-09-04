"""Punto di ingresso ASGI del progetto.

Espone come ``application`` l'oggetto richiamato da un server asincrono. Il
deploy usa WSGI (vedi wsgi.py): questo file resta a disposizione nel caso in
futuro servisse un server ASGI.

https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'thesis_submission.settings')

application = get_asgi_application()
