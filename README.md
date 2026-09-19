# Thesis Submission

Applicazione Django per la gestione degli appelli di laurea di un corso di
studi: iscrizione degli studenti agli appelli, caricamento della tesi (e di
un eventuale video), scelta del tutor e sua valutazione, gestione delle
commissioni. Pensata per essere usata dietro autenticazione Shibboleth
d'ateneo (UniMoRe), con smistamento automatico in tre aree per ruolo:
studente, docente, presidente di commissione.

## Ruoli e aree dell'applicazione

L'appartenenza ai gruppi Django `studente` e `docente` decide a quale area si viene reindirizzati
dopo il login (`/dashboard/`). Un utente può appartenere a entrambi i gruppi però ad ogni login viene assegnato uno solo dei due ruoli.

- **Area studente** (`/studente/`) — le proprie iscrizioni agli appelli
  futuri, con lo stato di consegna (titolo, tutor, tesi, eventuale video) e
  l'elenco degli appelli disponibili. L'iscrizione viene fatta automaticamente nel momento in cui il presidente crea l'appello caricando l'elenco studenti, ovvero non esiste un
  endpoint di iscrizione manuale per gli studenti.
  Nel momento in cui uno studente viene iscritto dal presidente, riceve un'email.
- **Area docente** (`/docente/`) — la
  sezione "I miei tutorati", dove si valutano i propri studenti (titolo,
  punteggio, giudizio), gli appelli delle proprie commissioni (con accesso al dettaglio, agli iscritti e al download delle tesi) e gli altri appelli disponibili. Per tutte le tabelle sono nascosti i dati relativi agli appelli passati ma per le ultime due è presente un interruttore
  indipendente per mostrarli di nuovo.
  Nel momento in cui un docente viene inserito nella commissione di un appello creato dal presidente, riceve un'email.
  Inoltre, riceve un'email anche nel caso in cui uno studente lo scelga come tutor.
- **Area presidente** (`/presidente/`) — la stessa pagina del docente, con
  in più la possibilità di creare un nuovo appello caricando l'elenco dei
  laureandi da un file xlsx (vedi `appelli/xlsx.py`).
  Per quanto riguarda le email, il funzionamento è uguale a quello del docente.

Il ruolo di "presidente" non arriva da Shibboleth ed è gestito e assegnato manualmente dall'area amministrativa da un super user.

## Stack tecnico

- **Python 3 / Django 6** (vedi `requirements.txt` per le versioni esatte)
- **MySQL 8** come database
- **Gunicorn** + **WhiteNoise** per servire l'app e i file statici in
  produzione, dietro un reverse proxy (Traefik) con autenticazione
  Shibboleth
- **Bootstrap 5** (via CDN) per l'interfaccia, con CSS e JavaScript propri
  dell'app sotto `thesis_submission/static/`
- **django-cleanup** per cancellare dal disco i file caricati (tesi, video)
  quando l'iscrizione viene eliminata o il file sostituito
- **openpyxl** per leggere gli elenchi laureandi in xlsx

## Avvio in locale con Docker

È il modo più semplice per provare l'applicazione: non serve installare
Python, MySQL né alcuna dipendenza sulla propria macchina.

```bash
cp .env.example .env
# apri .env e imposta una password per DB_PASSWORD / MYSQL_ROOT_PASSWORD
# (in locale può essere una password qualsiasi)

docker compose up --build
```

Al primo avvio il servizio `web` esegue da solo le migrazioni e il
`collectstatic`. L'app risponde su <http://localhost:8000>.

In locale `SHIB_ENABLED=0`, quindi non c'è autenticazione Shibboleth: per
accedere servono utenti creati a mano. Il comando

```bash
docker compose exec web python manage.py crea_dati_demo
```

crea due studenti, due docenti, una commissione e un appello di esempio
(password `password123` per tutti), utile per esplorare rapidamente le
diverse aree.

## Avvio in locale senza Docker

Serve un'istanza MySQL raggiungibile (o le variabili `DB_*` puntate a
un'istanza esistente) e Python 3 con le dipendenze di `requirements.txt`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DJANGO_DEBUG=1
export DB_HOST=127.0.0.1  # e le altre variabili DB_* / DJANGO_SECRET_KEY se serve

python manage.py migrate
python manage.py crea_dati_demo   # opzionale, per dei dati di prova
python manage.py runserver
```

Con `DJANGO_DEBUG=1` non è obbligatorio impostare `DJANGO_SECRET_KEY`: viene
usata una chiave di comodo (vedi `thesis_submission/settings.py`). In
produzione la sua assenza blocca l'avvio.

## Test

```bash
python manage.py test appelli
```

La suite copre permessi e confini fra le aree, il flusso di caricamento
tesi/video, la valutazione dei tutorati, la lettura degli xlsx e le regole di
visibilità degli appelli passati. Richiede un database configurato (anche
solo per la durata dei test, che lavorano su un database di test separato
creato e distrutto automaticamente).

## Struttura del progetto

```
appelli/                   App Django principale
├── models.py               Commissione, AppelloDiLaurea, StudenteAppelloDiLaurea (iscrizione)
├── views.py                Viste delle tre aree, permessi, logica di dashboard
├── forms.py                Moduli di iscrizione, caricamento tesi, valutazione, creazione appello
├── urls.py                 Rotte dell'app (namespace "appelli")
├── admin.py                Configurazione dell'admin Django
├── xlsx.py                 Lettura dell'elenco laureandi da file xlsx
├── notifiche.py            Invio delle email (iscrizione, nomina in commissione/tutor)
├── storage.py               Storage personalizzato per i file caricati
├── templatetags/            Filtri per i template (es. resa "Cognome Nome")
├── management/commands/     crea_dati_demo, pulisci_tesi_orfane
├── migrations/               Migrazioni, incluse quelle che creano gruppi e dati demo
└── templates/appelli/        Template HTML, con partial riusati fra le pagine (prefisso "_")

thesis_submission/          Configurazione del progetto Django
├── settings.py              Impostazioni, guidate da variabili d'ambiente
└── static/{css,js}/         Stili e script propri dell'app, per pagina + comuni (common.*)
```

## Note per il deploy in produzione

- `DEBUG` resta spento di default: va acceso solo con `DJANGO_DEBUG=1`
  esplicito.
- In produzione `DJANGO_SECRET_KEY` è obbligatoria: senza, l'avvio si
  interrompe.
- `docker-compose.prod.yml` aggiunge Traefik come reverse proxy con
  autenticazione Shibboleth e non espone la porta del database
  all'esterno.
- `pulisci_tesi_orfane` (in modalità anteprima di default) individua i file
  rimasti sul disco senza più un'iscrizione che li referenzi, utile come
  manutenzione periodica. Il comando è:
  ```bash
  docker compose exec web python manage.py pulisci_tesi_orfane
  ```
