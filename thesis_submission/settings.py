"""Configurazione del progetto thesis_submission.

Generato da 'django-admin startproject' con Django 6.0.5, poi adattato al
deploy dietro reverse proxy con autenticazione Shibboleth.

Un unico file serve entrambi gli ambienti: cio' che cambia fra lo sviluppo in
locale e la produzione arriva dalle variabili d'ambiente (vedi .env.example e
docker-compose.prod.yml), non da file di impostazioni separati.

Riferimenti:
https://docs.djangoproject.com/en/6.0/topics/settings/
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

import os
from pathlib import Path

# Radice del progetto: i percorsi si costruiscono come BASE_DIR / 'sottocartella'.
BASE_DIR = Path(__file__).resolve().parent.parent


# --- Sicurezza ---------------------------------------------------------------
# Lista di controllo prima di andare in produzione:
# https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# ATTENZIONE: in produzione DEBUG deve restare disattivo (le pagine di errore
# di Django espongono codice e impostazioni). Il valore predefinito e' quindi
# "spento": per accenderlo serve un DJANGO_DEBUG=1 esplicito.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# La chiave firma sessioni, token CSRF e link di reset password: chi la conosce
# puo' falsificarli, quindi non sta in git ma nel file .env (vedi .env.example).
# In sviluppo, se manca, se ne usa una di comodo; in produzione l'avvio si
# ferma, invece di partire con una chiave nota a tutti.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("DJANGO_SECRET_KEY non impostata.")
    SECRET_KEY = "django-insecure-solo-per-sviluppo"

# Nomi di host da cui l'applicazione accetta richieste, separati da virgola.
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")

# --- Reverse proxy HTTPS (Traefik -> Gunicorn) -------------------------------
# In produzione il browser parla HTTPS con il proxy, ma verso Gunicorn la
# richiesta arriva in HTTP: senza questo Django vede request.scheme="http" e il
# controllo CSRF sull'header Origin fallisce su ogni POST (errore 403 "Verifica
# CSRF fallita"), logout compreso. X-Forwarded-Proto dice a Django lo schema
# reale. NB: il proxy deve impostare/sovrascrivere lui questo header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Origini di cui Django si fida per il CSRF (schema incluso, separate da virgola).
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "https://tesi.ing.unimore.it"
    ).split(",") if o
]

# Traefik parla gia' solo HTTPS con il browser, quindi qui sotto e' difesa in
# profondita': protegge dai casi in cui una richiesta in chiaro non passa da
# Traefik (rete compromessa fra client e proxy, redirect futuro cambiato per
# errore). In locale (DEBUG=1) resterebbero attive senza motivo, dato che li'
# non c'e' alcun HTTPS: per questo valgono solo in produzione.
if not DEBUG:
    # Il cookie di sessione e quello CSRF non vengono mai mandati su HTTP.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Se una richiesta arrivasse comunque in HTTP, Django la rimanda in HTTPS
    # invece di servirla in chiaro (si affida a SECURE_PROXY_SSL_HEADER sopra
    # per sapere lo schema reale della richiesta originale).
    SECURE_SSL_REDIRECT = True
    # Dice al browser di andare sempre in HTTPS anche per il primo indirizzo
    # digitato senza schema, PRIMA che la richiesta parta in rete: e' l'unica
    # difesa contro chi intercetta la primissima richiesta in chiaro, che un
    # redirect lato server non puo' prevenire (per redirigerla dovrebbe prima
    # riceverla). Valore basso apposta: e' quasi irreversibile una volta
    # ricordato dal browser, da alzare gradualmente dopo aver verificato che
    # tutto funzioni in HTTPS.
    SECURE_HSTS_SECONDS = 3600


# --- Applicazioni e middleware -----------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'appelli',
    # Cancella automaticamente i file (media) quando l'oggetto viene eliminato
    # o quando il FileField cambia/viene svuotato. Deve stare per ultima.
    'django_cleanup.apps.CleanupConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serve i file statici; va subito dopo SecurityMiddleware.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Il middleware Shibboleth si attiva solo dove il SP e' davvero presente: in
# locale gli header X-Shib-* non arrivano e nessuno sarebbe mai autenticato.
# Va subito DOPO AuthenticationMiddleware, che e' quello che popola
# request.user: inserito prima, non troverebbe nulla su cui lavorare.
if os.environ.get("SHIB_ENABLED", "0") == "1":
    _i = MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")
    MIDDLEWARE.insert(_i + 1, "thesis_submission.assign_user.AssignUserMiddleware")

ROOT_URLCONF = 'thesis_submission.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # URL del pulsante "Accedi", diverso fra locale e produzione.
                'appelli.context_processors.login_url',
            ],
        },
    },
]

WSGI_APPLICATION = 'thesis_submission.wsgi.application'


# --- Database ----------------------------------------------------------------
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases
# Le credenziali arrivano dall'ambiente: non vanno versionate. utf8mb4 e' la
# sola codifica MySQL che copre tutto Unicode, accenti e simboli compresi: un
# titolo di tesi puo' contenere qualsiasi carattere.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "appelli"),
        "USER": os.environ.get("DB_USER", "appelli"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}


# --- Autenticazione ----------------------------------------------------------

# Regole di robustezza delle password. Riguardano solo gli account locali
# (amministratori e utenti demo): chi entra da Shibboleth non ha una password
# su questo sito.
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# --- Lingua e fuso orario ----------------------------------------------------
# https://docs.djangoproject.com/en/6.0/topics/i18n/
# La lingua vale anche per i messaggi di Django (errori dei form, area
# amministrativa), che sarebbero altrimenti in inglese in mezzo al resto.

LANGUAGE_CODE = 'it'

TIME_ZONE = 'Europe/Rome'

USE_I18N = True

USE_TZ = True


# --- File statici (CSS, JavaScript, immagini) --------------------------------
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

# Cartelle di progetto (non legate a una app) in cui Django cerca i file
# statici: qui c'e' l'immagine del footer (thesis_submission/static/).
STATICFILES_DIRS = [BASE_DIR / 'thesis_submission' / 'static']

# Cartella in cui 'collectstatic' raccoglie i file statici e da cui WhiteNoise
# li serve (admin, app, ecc.). Va popolata con: python manage.py collectstatic
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise: comprime i file e aggiunge un hash al nome per il caching.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# --- File caricati dagli utenti (tesi e video) -------------------------------
# https://docs.djangoproject.com/en/6.0/topics/files/
# A differenza dei file statici NON vengono serviti da WhiteNoise: sono
# riservati, e passano dalle view di download che ne verificano i permessi.

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Dopo il login si passa da /dashboard/ (percorso protetto) che smista per ruolo.
LOGIN_REDIRECT_URL = 'appelli:dashboard'

# URL del pulsante "Accedi" (e a cui reindirizzare chi non e' autenticato).
# In produzione avvia l'autenticazione Shibboleth tramite l'handler Login del
# SP (su services-host); 'target' riporta a /dashboard/ (protetto) dopo il
# login, non alla home pubblica '/'. In locale (senza Shibboleth) si usa il
# form di login di Django.
if os.environ.get("SHIB_ENABLED", "0") == "1":
    LOGIN_URL = os.environ.get(
        "DJANGO_SHIB_LOGIN_URL",
        "https://services-host.ing.unimore.it/Shibboleth.sso/Login"
        "?target=https://tesi.ing.unimore.it/dashboard/",
    )
else:
    LOGIN_URL = 'login'

# Dove mandare l'utente dopo il logout di Django. Per chiudere DAVVERO anche la
# sessione Shibboleth (altrimenti il cookie _shibsession_ resta valido e il
# middleware ri-autentica subito) bisogna rimandare al logout del SP, che nel
# nostro deploy sta su un altro host (services-host, non tesi): l'URL preciso
# va quindi impostato via DJANGO_LOGOUT_REDIRECT_URL nel docker-compose.prod.
# Default sicuri (nessun 404) se la variabile non e' impostata:
#   - con Shibboleth: torna alla home ("/"), che riparte dall'autenticazione;
#   - in locale (senza Shibboleth): torna al form di login di Django.
if os.environ.get("SHIB_ENABLED", "0") == "1":
    _default_logout = "/"
else:
    _default_logout = "login"
LOGOUT_REDIRECT_URL = os.environ.get("DJANGO_LOGOUT_REDIRECT_URL", _default_logout)

# --- Posta ------------------------------------------------------------------
# Gli avvisi di iscrizione (appelli/notifiche.py) partono da qui.
#
# Senza un server SMTP configurato si usa il backend "console": le email non
# escono, vengono stampate nei log del container. E' il comportamento giusto
# in locale, dove non si vuole (e non si puo') scrivere a indirizzi veri.
# Basta valorizzare DJANGO_EMAIL_HOST perche' l'invio diventi reale.
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT") or "587")
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "1") == "1"

# Gli avvisi di un nuovo appello partono in un thread separato, cosi' la
# pagina del presidente non aspetta la posta (mezzo secondo di handshake piu'
# una frazione per destinatario: con molti laureandi si sente). I test lo
# spengono per poter controllare i messaggi subito dopo la creazione.
AVVISI_IN_BACKGROUND = os.environ.get("DJANGO_AVVISI_IN_BACKGROUND", "1") == "1"

# Secondi di attesa massima verso il server di posta. Senza limite, un SMTP
# che non risponde terrebbe bloccato il worker che sta creando l'appello.
EMAIL_TIMEOUT = int(os.environ.get("DJANGO_EMAIL_TIMEOUT") or "10")

# Mittente usato quando il messaggio non ne indica uno.
DEFAULT_FROM_EMAIL = (
    os.environ.get("DJANGO_DEFAULT_FROM_EMAIL")
    or "Consegna Tesi <tesi.ing@unimore.it>"
)

# Tipo di chiave primaria assegnato ai modelli che non ne dichiarano una.
# https://docs.djangoproject.com/en/6.0/ref/settings/#default-auto-field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# I backend si provano in ordine, dal primo che riconosce l'utente. Shibboleth
# viene prima perche' in produzione e' la via normale di accesso; il backend
# classico resta come seconda scelta per l'area amministrativa.
AUTHENTICATION_BACKENDS = [
    "thesis_submission.assign_user.AssignUserBackend",
    "django.contrib.auth.backends.ModelBackend",  # login classico per l'admin in locale
]
