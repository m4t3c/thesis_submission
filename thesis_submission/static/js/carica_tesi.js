/*
 * Consegna della tesi da parte dello studente (carica_tesi.html).
 *
 * Cio' che dipende dai dati della pagina lo scrive il template negli
 * attributi data-* (un file statico non puo' usare i tag di Django):
 * - sul form #tesi-form: data-tesi-salvata, data-titolo-salvato,
 *   data-video-salvato ("true"/"false") e data-formati-video;
 * - sul campo #ricerca-tutor: data-url-ricerca;
 * - sulla barra dello stato consegna: data-percentuale.
 */

// Riempimento della barra "Stato consegna". La percentuale la calcola la
// view (_stato_consegna): qui la si applica soltanto.
document.querySelectorAll('.stato-barra-riempimento[data-percentuale]').forEach(function (barra) {
    barra.style.width = barra.dataset.percentuale + '%';
});

(function () {
    var form = document.getElementById('tesi-form');
    if (!form) return;

    // --- Mostra solo il pannello della modalita' video selezionata ---
    var radios = form.querySelectorAll('input[name="modalita_video"]');
    var pannelli = form.querySelectorAll('.js-video-pannello');
    var riquadriVideo = form.querySelectorAll('.js-video-scelta');

    function modalitaScelta() {
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) return radios[i].value;
        }
        return 'nessuno';
    }
    function aggiornaPannelli() {
        var scelta = modalitaScelta();
        pannelli.forEach(function (p) {
            p.hidden = (p.dataset.modalita !== scelta);
        });
        // Il riquadro scelto si evidenzia. Lo fa anche il CSS con :has(),
        // ma non tutti i browser in uso lo supportano: la classe e' la
        // strada che funziona comunque.
        riquadriVideo.forEach(function (r) {
            r.classList.toggle('attiva', r.dataset.modalita === scelta);
        });
    }
    radios.forEach(function (r) {
        r.addEventListener('change', aggiornaPannelli);
    });
    aggiornaPannelli();

    // --- Nome e cognome di un docente ---------------------------------
    // Serve alla ricerca del tutor e alla finestra di conferma: tenerlo
    // qui evita che le due parti compongano il nome ognuna a modo suo.
    function nomeDocente(d) {
        if (!d) return '';
        var completo = ((d.nome || '') + ' ' + (d.cognome || '')).trim();
        return completo || d.username || '';
    }

    // Tutor scelto adesso e non ancora salvato. Lo riempie la ricerca, lo
    // legge l'invio del modulo per chiedere conferma: e' l'unico dato che
    // deve viaggiare fra i due blocchi.
    var tutorInfo = {nuovo: null};

    // --- Aree di caricamento (trascina oppure sfoglia) ----------------
    // Il campo file vero e' fuori campo e al suo posto si mostra l'area
    // tratteggiata: senza queste righe lo studente non vedrebbe nemmeno
    // il nome del file appena scelto.
    function mostraNomeScelto(input) {
        var nome = (input.files && input.files[0]) ? input.files[0].name : '';
        document.querySelectorAll('[data-nome-per="' + input.id + '"]').forEach(function (el) {
            el.textContent = nome ? (el.dataset.prefisso || '') + nome : '';
            el.hidden = !nome;
        });
        // Dove c'e' il nome del file, l'invito a scegliere non serve piu'.
        document.querySelectorAll('[data-testo-per="' + input.id + '"]').forEach(function (el) {
            el.hidden = !!nome;
        });
    }

    form.querySelectorAll('.js-dropzone').forEach(function (zona) {
        var input = document.getElementById(zona.getAttribute('for'));
        if (!input) return;

        // Il clic apre la finestra di scelta da solo: la zona e' una
        // <label> legata al campo, non serve JavaScript per quello.
        ['dragenter', 'dragover'].forEach(function (evento) {
            zona.addEventListener(evento, function (e) {
                e.preventDefault();
                zona.classList.add('sopra');
            });
        });
        ['dragleave', 'dragend', 'drop'].forEach(function (evento) {
            zona.addEventListener(evento, function () {
                zona.classList.remove('sopra');
            });
        });
        zona.addEventListener('drop', function (e) {
            e.preventDefault();
            if (!e.dataTransfer || !e.dataTransfer.files.length) return;
            // Il file trascinato va messo DENTRO il campo, non ricordato a
            // parte: e' il campo che viene inviato al server.
            try {
                var trasferimento = new DataTransfer();
                trasferimento.items.add(e.dataTransfer.files[0]);
                input.files = trasferimento.files;
            } catch (err) {
                return;   // browser che non lo permette: resta lo "sfoglia"
            }
            // L'evento fa scattare i controlli su formato e dimensione,
            // gli stessi della scelta da finestra.
            input.dispatchEvent(new Event('change', {bubbles: true}));
        });
    });

    // Vale per le aree tratteggiate e per i pulsanti "Sostituisci…": in
    // entrambi i casi il nome del file scelto va mostrato da qualche parte.
    form.querySelectorAll('input[type="file"]').forEach(function (input) {
        input.addEventListener('change', function () { mostraNomeScelto(input); });
        mostraNomeScelto(input);
    });

    // "Sostituisci…": apre il campo file che non si vede.
    form.querySelectorAll('[data-apre-file]').forEach(function (bottone) {
        bottone.addEventListener('click', function () {
            var input = document.getElementById(bottone.dataset.apreFile);
            if (input) input.click();
        });
    });

    // --- Conferma all'uscita se ci sono modifiche non salvate ---
    // Si confronta lo stato iniziale del form con quello attuale, cosi'
    // vale per titolo, file e link senza doverli elencare a mano.
    function istantanea() {
        var parti = [modalitaScelta()];
        // Il tutor viaggia in un input nascosto: va guardato a parte,
        // altrimenti sceglierlo non risulterebbe una modifica.
        var campoTutor = form.querySelector('input[name="tutor"]');
        parti.push('tutor=' + (campoTutor ? campoTutor.value : ''));
        form.querySelectorAll('input[type="text"], input[type="url"]').forEach(function (i) {
            // La casella di ricerca non e' un dato del modulo: conta il
            // docente scelto, non quello che si e' digitato per trovarlo.
            if (i.id === 'ricerca-tutor') return;
            parti.push(i.name + '=' + i.value);
        });
        form.querySelectorAll('input[type="file"]').forEach(function (i) {
            parti.push(i.name + '=' + (i.files.length ? i.files[0].name : ''));
        });
        return parti.join('|');
    }
    var iniziale = istantanea();

    // --- Caricamento con barra di avanzamento -------------------------
    // Il form viene inviato via XMLHttpRequest per poter leggere gli
    // eventi di progresso, che fetch() non espone per l'upload. Se il
    // browser non li supporta si lascia partire l'invio classico: la
    // pagina funziona lo stesso, solo senza barra.
    var supportoProgresso = (function () {
        try {
            return !!(window.FormData && 'upload' in new XMLHttpRequest());
        } catch (e) {
            return false;
        }
    })();

    // Sotto questa soglia il caricamento e' istantaneo e la barra
    // comparirebbe solo per un lampo: si invia il form normalmente.
    var SOGLIA_BYTE = 2 * 1024 * 1024;

    var pannello = document.getElementById('pannello-avanzamento');
    var barra = document.getElementById('barra-avanzamento');
    var etichettaByte = document.getElementById('avanzamento-byte');
    var etichettaStima = document.getElementById('avanzamento-stima');
    var etichettaVelocita = document.getElementById('avanzamento-velocita');
    var boxErrore = document.getElementById('errore-caricamento');
    var btnAnnullaCaricamento = document.getElementById('btn-annulla-caricamento');
    var progressoModale = document.getElementById('annulla-progresso');
    var elModaleAnnulla = document.getElementById('annullaModal');
    var richiesta = null;

    function chiudiModaleAnnulla() {
        if (!elModaleAnnulla || !window.bootstrap) return;
        var m = bootstrap.Modal.getInstance(elModaleAnnulla);
        if (m) m.hide();
    }

    // Sceglie l'unita' in base alla dimensione: un file da 800 KB non deve
    // comparire come "0,8 MB", ne' una velocita' lenta come "0,1 MB/s".
    function mb(byte) {
        var unita = ['B', 'KB', 'MB', 'GB'];
        var i = 0;
        while (byte >= 1024 && i < unita.length - 1) {
            byte = byte / 1024;
            i++;
        }
        var decimali = (i === 0 || byte >= 100) ? 0 : 1;
        return byte.toFixed(decimali).replace('.', ',') + ' ' + unita[i];
    }
    function durata(secondi) {
        if (!isFinite(secondi) || secondi < 0) return '';
        secondi = Math.round(secondi);
        if (secondi < 60) return secondi + ' secondi';
        var m = Math.floor(secondi / 60), sec = secondi % 60;
        return m + ' min ' + (sec < 10 ? '0' : '') + sec + ' s';
    }
    function byteDaInviare() {
        var totale = 0;
        form.querySelectorAll('input[type="file"]').forEach(function (i) {
            if (i.files && i.files[0]) totale += i.files[0].size;
        });
        return totale;
    }

    function mostraPannello() {
        form.hidden = true;
        boxErrore.hidden = true;
        pannello.hidden = false;
    }
    function tornaAlForm(messaggio) {
        pannello.hidden = true;
        form.hidden = false;
        if (messaggio) {
            boxErrore.textContent = messaggio;
            boxErrore.hidden = false;
        }
    }
    /**
     * Aggiorna barra, byte inviati, tempo residuo e velocita'.
     *
     * La velocita' e' la media dall'inizio del caricamento, non quella
     * dell'ultimo intervallo: oscilla molto meno, e la stima del tempo
     * residuo non salta avanti e indietro a ogni evento di progresso.
     * Nel primo secondo non si mostra, perche' su pochi campioni sarebbe
     * comunque inattendibile.
     *
     * @param {number} inviati Byte gia' trasmessi.
     * @param {number} totale Byte complessivi della richiesta.
     * @param {number} avvio Istante di inizio, in millisecondi (Date.now()).
     */
    function aggiornaBarra(inviati, totale, avvio) {
        var perc = totale ? Math.round((inviati / totale) * 100) : 0;
        barra.style.width = perc + '%';
        barra.textContent = perc + '%';
        barra.parentNode.setAttribute('aria-valuenow', perc);
        etichettaByte.textContent = mb(inviati) + ' di ' + mb(totale);
        if (progressoModale) {
            progressoModale.textContent = perc + '% (' + mb(inviati) + ' di ' + mb(totale) + ')';
        }

        var trascorsi = (Date.now() - avvio) / 1000;
        if (trascorsi > 1 && inviati > 0) {
            var velocita = inviati / trascorsi;              // byte al secondo
            etichettaStima.textContent = durata((totale - inviati) / velocita) || '—';
            etichettaVelocita.textContent = mb(velocita) + '/s';
        }
    }
    function faseSalvataggio() {
        barra.classList.remove('progress-bar-animated');
        etichettaStima.textContent = 'Salvataggio in corso…';
        etichettaVelocita.textContent = '—';
    }

    // --- Controlli PRIMA di inviare il form ----------------------------
    // Gli stessi controlli esistono lato server, che resta l'autorita':
    // qui servono a non far partire una richiesta destinata a essere
    // rifiutata. Senza, l'utente carica per intero titolo, PDF ed
    // eventuale video (anche centinaia di MB), aspetta, e si ritrova il
    // form indietro con un errore e NIENTE salvato.
    var inputTitolo = form.querySelector('[name="titolo"]');
    var inputTesi = form.querySelector('[name="file_tesi"]');
    var inputVideo = form.querySelector('[name="file_video"]');
    var inputLink = form.querySelector('[name="link_video"]');
    // Cosa c'e' gia' sull'iscrizione: se la tesi (o il video) e' gia'
    // stata caricata, non sceglierne una nuova significa "lasciala
    // com'e'", non "campo vuoto".
    // I tre valori li scrive il template negli attributi data-* del form.
    var TESI_SALVATA = form.dataset.tesiSalvata === 'true';
    // Il titolo gia' salvato si corregge ma non si svuota (vedi
    // TesiUploadForm.clean_titolo).
    var TITOLO_SALVATO = form.dataset.titoloSalvato === 'true';
    var VIDEO_SALVATO = form.dataset.videoSalvato === 'true';
    // Prima del primo "Salva" non si segnala che un campo e' vuoto: lo si
    // farebbe mentre l'utente lo sta ancora compilando.
    var giaInviato = false;

    /**
     * Dove va messo il riquadro d'errore di un campo.
     *
     * Di norma subito dopo il campo stesso, ma due contenitori non lo
     * sopportano al loro interno e vanno scavalcati:
     * - .campo-file-nascosto e' RITAGLIATO (il campo file lo rappresenta
     *   l'area tratteggiata): un messaggio li' dentro non si vedrebbe;
     * - .ricerca-con-icona tiene l'icona centrata sul 50% della PROPRIA
     *   altezza: infilandoci dentro il messaggio il contenitore raddoppia
     *   e l'icona scivola sopra al messaggio stesso.
     *
     * @param {HTMLElement} elemento Campo a cui si riferisce l'errore.
     * @returns {HTMLElement} Elemento dopo il quale inserire il riquadro.
     */
    function ancoraErrore(elemento) {
        return elemento.closest('.campo-file-nascosto, .ricerca-con-icona')
            || elemento;
    }

    function erroreCampo(elemento, messaggio) {
        var ancora = ancoraErrore(elemento);
        var contenitore = ancora.parentNode;
        // L'errore arrivato dal server riguarda l'invio precedente: appena
        // il controllo lato client si esprime sullo stesso campo, va tolto
        // di mezzo, altrimenti restano due riquadri rossi in colonna.
        var vecchio = contenitore.querySelector('.errore-server');
        if (vecchio) vecchio.remove();

        var box = contenitore.querySelector('.errore-campo');
        if (!messaggio) {
            if (box) box.remove();
            elemento.classList.remove('is-invalid');
            return;
        }
        if (!box) {
            box = document.createElement('div');
            box.className = 'errore-campo alert alert-danger shadow-sm mt-2';
            box.setAttribute('role', 'alert');
            ancora.insertAdjacentElement('afterend', box);
        }
        // Si ricostruisce il contenuto con nodi DOM invece di innerHTML.
        box.textContent = '';
        var icona = document.createElement('i');
        icona.className = 'bi bi-exclamation-triangle-fill me-1';
        icona.setAttribute('aria-hidden', 'true');
        box.appendChild(icona);
        box.appendChild(document.createTextNode(messaggio));
        elemento.classList.add('is-invalid');
    }

    function estensioneAmmessa(input) {
        // I formati ammessi sono quelli che il campo stesso dichiara
        // (attributo accept, scritto dal form): cosi' non ne esiste una
        // seconda copia qui, da tenere allineata a mano.
        if (!input.files || !input.files[0]) return true;
        var estensioni = (input.getAttribute('accept') || '').split(',')
            .map(function (voce) { return voce.trim().toLowerCase(); })
            .filter(function (voce) { return voce.charAt(0) === '.'; });
        if (!estensioni.length) return true;
        var nome = input.files[0].name.toLowerCase();
        return estensioni.some(function (est) {
            return nome.slice(-est.length) === est;
        });
    }

    function dimensioneAmmessa(input) {
        var max = parseInt(input.getAttribute('data-max-byte') || '0', 10);
        if (!max || !input.files || !input.files[0]) return true;
        return input.files[0].size <= max;
    }

    /**
     * Approssimazione lato browser della validazione di URLField.
     *
     * Stessa regola del server (URLField di Django): schema http o https,
     * sottinteso quando manca, e un nome di dominio vero. Il costruttore
     * URL da solo non basta, perche' accetta come host anche una parola
     * senza punti ("https://video"), che il server invece rifiuta.
     *
     * @param {string} valore Testo inserito, gia' privo di spazi ai bordi.
     * @returns {boolean} true se il link ha la forma di un indirizzo web.
     */
    function linkValido(valore) {
        if (/\s/.test(valore)) return false;
        var testo = /^[a-z][a-z0-9+.-]*:\/\//i.test(valore)
            ? valore : 'https://' + valore;
        var url;
        try {
            url = new URL(testo);
        } catch (e) {
            return false;
        }
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
        return url.hostname === 'localhost' || url.hostname.indexOf('.') > 0;
    }

    // Ogni controllo restituisce il messaggio da mostrare, o '' se il
    // campo va bene.
    //
    // Titolo e tesi vanno a coppia (vedi TesiUploadForm.clean): nessuno
    // dei due e' obbligatorio da solo, ma chi c'e' chiama l'altro. "C'e'"
    // vuol dire scelto adesso OPPURE gia' salvato: una tesi gia' caricata
    // non va ricaricata per correggere il titolo.
    function titoloPresente() {
        return !!(inputTitolo && inputTitolo.value.trim());
    }
    function tesiPresente() {
        return TESI_SALVATA || !!(inputTesi && inputTesi.files && inputTesi.files[0]);
    }

    function erroreTitolo() {
        if (!inputTitolo || titoloPresente()) return '';
        if (TITOLO_SALVATO) return 'Il titolo della tesi non può essere svuotato.';
        return tesiPresente() ? 'Hai caricato la tesi: indica anche il titolo.' : '';
    }

    function erroreTesi() {
        if (!inputTesi) return '';
        if (!inputTesi.files || !inputTesi.files[0]) {
            return (TESI_SALVATA || !titoloPresente())
                ? '' : 'Hai indicato il titolo: carica anche il file della tesi.';
        }
        if (!estensioneAmmessa(inputTesi)) {
            return 'La tesi deve essere un file PDF.';
        }
        return '';
    }

    function erroreVideoFile() {
        if (!inputVideo) return '';
        var file = inputVideo.files && inputVideo.files[0];
        if (!file) {
            return VIDEO_SALVATO ? '' : 'Scegli il file video da caricare, ' +
                'oppure seleziona un\'altra opzione.';
        }
        if (!estensioneAmmessa(inputVideo)) {
            return 'Formato del video non ammesso. Formati accettati: ' +
                form.dataset.formatiVideo + '.';
        }
        if (!dimensioneAmmessa(inputVideo)) {
            return 'Il file scelto occupa ' + mb(file.size) + ', oltre il limite di ' +
                mb(parseInt(inputVideo.getAttribute('data-max-byte'), 10)) +
                '. Scegline uno più piccolo, oppure indica il link a ' +
                'un video già pubblicato online.';
        }
        return '';
    }

    function erroreLink() {
        if (!inputLink) return '';
        var valore = inputLink.value.trim();
        if (!valore) {
            return 'Inserisci il link al video, oppure seleziona un\'altra opzione.';
        }
        if (!linkValido(valore)) {
            return 'Il link non sembra un indirizzo valido: deve essere del tipo ' +
                'https://www.esempio.it/video.';
        }
        return '';
    }

    // Il tutor ha un riquadro d'errore proprio: il campo vero e' nascosto,
    // quindi il messaggio non puo' stargli accanto come per gli altri.
    // Quando il tutor e' gia' stato salvato la ricerca non viene nemmeno
    // disegnata, e allora non c'e' niente da controllare.
    var boxErroreTutor = document.getElementById('errore-tutor');

    function tutorScelto() {
        // Si rilegge ogni volta: l'input nascosto viene ricreato a ogni
        // ridisegno della selezione, quindi un riferimento tenuto da parte
        // punterebbe a un elemento non piu' nel documento.
        var campo = form.querySelector('input[name="tutor"]');
        return !!(campo && campo.value);
    }

    function erroreTutor() {
        if (!document.getElementById('ricerca-tutor')) return '';
        return tutorScelto() ? '' : 'Scegli il docente che ti farà da tutor.';
    }

    function mostraErroreTutor(messaggio) {
        if (!boxErroreTutor) return;
        // Come in erroreCampo: l'errore arrivato dal server riguarda
        // l'invio precedente e va tolto appena il controllo lato client si
        // esprime, altrimenti restano due riquadri rossi in colonna.
        var vecchio = boxErroreTutor.parentNode.querySelector('.errore-server');
        if (vecchio) vecchio.remove();

        boxErroreTutor.textContent = '';
        if (!messaggio) {
            boxErroreTutor.hidden = true;
            return;
        }
        var icona = document.createElement('i');
        icona.className = 'bi bi-exclamation-triangle-fill me-1';
        icona.setAttribute('aria-hidden', 'true');
        boxErroreTutor.appendChild(icona);
        boxErroreTutor.appendChild(document.createTextNode(messaggio));
        boxErroreTutor.hidden = false;
    }

    // Controlla tutti i campi in gioco, mostra gli errori e restituisce il
    // RIQUADRO del primo errore (null se e' tutto a posto): e' quello da
    // richiamare all'attenzione. Del video si controlla solo la modalita'
    // scelta: gli altri pannelli non vengono nemmeno inviati.
    // L'ordine dell'elenco segue quello dei campi nella pagina, cosi' si
    // scorre al primo problema che l'utente incontra leggendo.
    function validaModulo() {
        var modalita = modalitaScelta();
        var controlli = [
            {campo: inputTitolo, messaggio: erroreTitolo()},
            {tutor: true,        messaggio: erroreTutor()},
            {campo: inputTesi,   messaggio: erroreTesi()},
            {campo: inputVideo,  messaggio: modalita === 'file' ? erroreVideoFile() : ''},
            {campo: inputLink,   messaggio: modalita === 'link' ? erroreLink() : ''}
        ];
        var primo = null;
        controlli.forEach(function (c) {
            var box;
            if (c.tutor) {
                mostraErroreTutor(c.messaggio);
                box = boxErroreTutor;
            } else {
                if (!c.campo) return;
                erroreCampo(c.campo, c.messaggio);
                box = ancoraErrore(c.campo).parentNode.querySelector('.errore-campo');
            }
            if (c.messaggio && !primo) primo = box;
        });
        return primo;
    }

    function evidenziaErrore(box) {
        if (!box) return;
        // Togliere e rimettere la classe (con una lettura forzata del
        // layout in mezzo) fa ripartire l'animazione anche al secondo
        // tentativo: senza, il richiamo si vedrebbe una volta sola.
        box.classList.remove('evidenzia');
        void box.offsetWidth;
        box.classList.add('evidenzia');
        box.scrollIntoView({block: 'center', behavior: 'smooth'});
    }

    // Dopo il primo tentativo i messaggi si aggiornano mentre si corregge:
    // l'errore sparisce appena il campo diventa valido.
    function ricontrolla() {
        if (giaInviato) validaModulo();
    }
    if (inputTitolo) inputTitolo.addEventListener('input', ricontrolla);
    if (inputLink) inputLink.addEventListener('input', ricontrolla);
    radios.forEach(function (r) {
        r.addEventListener('change', function () {
            // Cambiando modalita' gli errori dell'altra non c'entrano piu'.
            if (inputVideo) erroreCampo(inputVideo, '');
            if (inputLink) erroreCampo(inputLink, '');
            ricontrolla();
        });
    });

    // Su un file scelto l'avviso e' immediato, anche prima del primo
    // "Salva": formato e dimensione si conoscono subito, e far aspettare
    // il salvataggio per dirlo fa perdere tempo. Il solo "campo
    // obbligatorio" resta invece rimandato all'invio.
    if (inputTesi) {
        inputTesi.addEventListener('change', function () {
            if (inputTesi.files && inputTesi.files[0]) erroreCampo(inputTesi, erroreTesi());
            // Il file scelto cambia anche la risposta sul titolo (coppia):
            // dopo il primo invio va riletto l'intero modulo.
            ricontrolla();
        });
    }
    if (inputVideo) {
        inputVideo.addEventListener('change', function () {
            if (inputVideo.files && inputVideo.files[0]) erroreCampo(inputVideo, erroreVideoFile());
            else ricontrolla();
        });
    }

    // --- Ricerca del tutor ---------------------------------------------
    // Stessa meccanica della ricerca docenti nella creazione appello, ma
    // con una persona sola: sceglierne un'altra sostituisce la precedente.
    // Se il tutor e' gia' salvato la casella di ricerca non viene disegnata
    // e tutto questo blocco non parte.
    (function () {
        var input = document.getElementById('ricerca-tutor');
        if (!input) return;

        var URL_RICERCA = input.dataset.urlRicerca;
        var elencoRisultati = document.getElementById('risultati-tutor');
        var contenitoreScelto = document.getElementById('tutor-scelto');
        var contenitoreHidden = document.getElementById('tutor-hidden');
        var vuoto = document.getElementById('nessun-tutor');
        var box = document.getElementById('box-tutor');
        var attesa = null;            // timer del debounce
        var richiestaRicerca = null;  // ricerca in corso, da annullare
        var scelto = null;

        function nome(d) { return d.etichetta || d.username; }

        function chiudiRisultati() {
            elencoRisultati.hidden = true;
            elencoRisultati.textContent = '';
            input.setAttribute('aria-expanded', 'false');
        }

        function disegnaScelto() {
            // Chi sta per essere confermato: lo legge l'invio del modulo,
            // che prima di salvare chiede conferma nominando il docente.
            tutorInfo.nuovo = scelto;

            contenitoreScelto.textContent = '';
            // L'input nascosto viene ricreato da zero: cosi' "nessun tutor"
            // significa davvero nessun campo inviato, e il server se ne
            // accorge invece di ricevere un valore vuoto.
            contenitoreHidden.textContent = '';

            if (scelto) {
                var riga = document.createElement('div');
                riga.className = 'membro';

                var icona = document.createElement('i');
                icona.className = 'bi bi-person-video3 membro-icona';
                icona.setAttribute('aria-hidden', 'true');

                var testo = document.createElement('div');
                testo.className = 'membro-testo';
                var r1 = document.createElement('div');
                r1.className = 'riga-docente-nome text-truncate';
                r1.textContent = nome(scelto);
                var r2 = document.createElement('div');
                r2.className = 'riga-docente-mail text-truncate';
                r2.textContent = scelto.email || '';
                testo.appendChild(r1);
                testo.appendChild(r2);

                var togli = document.createElement('button');
                togli.type = 'button';
                togli.className = 'btn btn-sm btn-danger membro-rimuovi';
                togli.setAttribute('aria-label', 'Togli ' + nome(scelto));
                togli.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
                togli.addEventListener('click', function () {
                    scelto = null;
                    disegnaScelto();
                });

                riga.appendChild(icona);
                riga.appendChild(testo);
                riga.appendChild(togli);
                contenitoreScelto.appendChild(riga);

                var hidden = document.createElement('input');
                hidden.type = 'hidden';
                hidden.name = 'tutor';
                hidden.value = scelto.id;
                contenitoreHidden.appendChild(hidden);
            }

            vuoto.hidden = !!scelto;
            box.classList.toggle('pieno', !!scelto);
            // L'avviso "manca il tutor" sparisce appena se ne sceglie uno.
            ricontrolla();
        }

        function scegli(d) {
            scelto = d;
            disegnaScelto();
            input.value = '';
            chiudiRisultati();
            input.focus();
        }

        function disegnaRisultati(risultati) {
            elencoRisultati.textContent = '';
            if (!risultati.length) {
                var vuotoEl = document.createElement('div');
                vuotoEl.className = 'list-group-item text-muted';
                vuotoEl.textContent = 'Nessun docente trovato.';
                elencoRisultati.appendChild(vuotoEl);
            }
            risultati.forEach(function (d) {
                var voce = document.createElement('button');
                voce.type = 'button';
                voce.className = 'list-group-item list-group-item-action';
                voce.setAttribute('role', 'option');

                var r1 = document.createElement('div');
                r1.className = 'riga-docente-nome';
                r1.textContent = nome(d);
                var r2 = document.createElement('div');
                r2.className = 'riga-docente-mail';
                r2.textContent = d.email || '';
                voce.appendChild(r1);
                voce.appendChild(r2);

                voce.addEventListener('click', function () { scegli(d); });
                elencoRisultati.appendChild(voce);
            });
            elencoRisultati.hidden = false;
            input.setAttribute('aria-expanded', 'true');
        }

        function cerca(termine) {
            if (richiestaRicerca) richiestaRicerca.abort();
            richiestaRicerca = new AbortController();
            fetch(URL_RICERCA + '?q=' + encodeURIComponent(termine), {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
                signal: richiestaRicerca.signal
            })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (dati) {
                // Chi e' gia' scelto non va riproposto.
                disegnaRisultati(dati.risultati.filter(function (d) {
                    return !scelto || d.id !== scelto.id;
                }));
            })
            .catch(function (e) { if (e.name !== 'AbortError') chiudiRisultati(); });
        }

        // Si aspetta una breve pausa nella digitazione: senza, ogni tasto
        // premuto produrrebbe una query al database.
        input.addEventListener('input', function () {
            clearTimeout(attesa);
            var termine = input.value.trim();
            if (termine.length < 2) { chiudiRisultati(); return; }
            attesa = setTimeout(function () { cerca(termine); }, 250);
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') chiudiRisultati();
            // Invio nella casella di ricerca non deve inviare tutto il form.
            if (e.key === 'Enter') e.preventDefault();
        });

        document.addEventListener('click', function (e) {
            if (!elencoRisultati.contains(e.target) && e.target !== input) chiudiRisultati();
        });

        var seme = document.getElementById('tutor-iniziale');
        if (seme) {
            try { scelto = JSON.parse(seme.textContent) || null; }
            catch (e) { scelto = null; }
        }
        disegnaScelto();
    })();

    // Lo stato di partenza va riletto DOPO aver disegnato il tutor: il
    // disegno ricrea l'input nascosto, e un'istantanea presa prima
    // segnalerebbe una modifica che l'utente non ha fatto.
    iniziale = istantanea();

    // --- Conferma della scelta del tutor -------------------------------
    // Una volta data, l'invio riparte da solo e non viene piu' chiesta:
    // il modulo si puo' salvare ancora molte volte per titolo, tesi e
    // video, e richiederla ogni volta la svuoterebbe di significato.
    var tutorConfermato = false;
    var elModaleTutor = document.getElementById('tutorModal');

    // requestSubmit (non submit) fa scattare l'evento 'submit', quindi
    // l'invio passa comunque dai controlli e dalla barra di avanzamento.
    // form.submit() li scavalcherebbe entrambi.
    function inviaModulo() {
        if (form.requestSubmit) {
            form.requestSubmit();
        } else {
            form.submit();
        }
    }

    function chiediConfermaTutor(docente) {
        if (!elModaleTutor || !window.bootstrap) {
            // Senza Bootstrap la finestra non c'e': si salva comunque.
            // Perdere il lavoro fatto sarebbe peggio che non chiedere.
            tutorConfermato = true;
            inviaModulo();
            return;
        }
        var nomeEl = document.getElementById('tutor-da-confermare');
        if (nomeEl) nomeEl.textContent = nomeDocente(docente);
        bootstrap.Modal.getOrCreateInstance(elModaleTutor).show();
    }

    var btnConfermaTutorModale = document.getElementById('btn-conferma-tutor-modale');
    if (btnConfermaTutorModale) {
        btnConfermaTutorModale.addEventListener('click', function () {
            tutorConfermato = true;
            bootstrap.Modal.getOrCreateInstance(elModaleTutor).hide();
            inviaModulo();
        });
    }

    form.addEventListener('submit', function (e) {
        giaInviato = true;
        // Vale per entrambe le strade (con e senza barra di avanzamento):
        // un modulo incompleto non deve partire in nessun caso.
        var primoErrore = validaModulo();
        if (primoErrore) {
            e.preventDefault();
            evidenziaErrore(primoErrore);
            return;
        }
        // La scelta del tutor va confermata a parte. Si chiede DOPO la
        // validazione, non prima: far confermare una scelta definitiva in
        // un modulo che verra' comunque rifiutato sarebbe una domanda
        // fatta a vuoto (e allarmante due volte).
        if (tutorInfo.nuovo && !tutorConfermato) {
            e.preventDefault();
            chiediConfermaTutor(tutorInfo.nuovo);
            return;
        }
        if (!supportoProgresso) return;          // invio classico
        var totale = byteDaInviare();
        if (totale < SOGLIA_BYTE) return;        // troppo piccolo: inutile
        e.preventDefault();

        var dati = new FormData(form);
        var avvio = Date.now();
        richiesta = new XMLHttpRequest();
        richiesta.open('POST', form.action || window.location.href);
        richiesta.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

        richiesta.upload.addEventListener('progress', function (ev) {
            if (ev.lengthComputable) aggiornaBarra(ev.loaded, ev.total, avvio);
        });
        // Byte finiti: ora e' il server a lavorare (validazione, scrittura).
        richiesta.upload.addEventListener('load', faseSalvataggio);

        richiesta.addEventListener('load', function () {
            richiesta = null;   // sblocca l'avviso di chiusura pagina
            // Se la conferma di annullamento era aperta va chiusa: il
            // caricamento e' gia' finito e non c'e' piu' nulla da fermare.
            chiudiModaleAnnulla();
            if (this.status >= 200 && this.status < 400) {
                // La view reindirizza alla dashboard quando il salvataggio
                // riesce; se invece resta su questa pagina sono errori di
                // validazione, e si ridisegna la pagina per mostrarli.
                // XMLHttpRequest segue i redirect da solo e non espone il
                // 302: l'unico modo di sapere dove si e' arrivati e'
                // confrontare responseURL con l'indirizzo di questa pagina.
                var arrivo = this.responseURL || '';
                if (arrivo && arrivo.indexOf('carica-tesi') === -1) {
                    iniziale = istantanea();   // niente avviso "non salvato"
                    window.location.href = arrivo;
                    return;
                }
                // Si sostituisce l'intero documento con la risposta invece
                // di ricostruire gli errori in JavaScript: cosi' restano
                // quelli resi dal template, identici all'invio classico.
                document.open();
                document.write(this.responseText);
                document.close();
                return;
            }
            tornaAlForm('Il server ha risposto con un errore (codice ' +
                        this.status + '). Riprova.');
        });
        richiesta.addEventListener('error', function () {
            richiesta = null;
            chiudiModaleAnnulla();
            tornaAlForm('Caricamento interrotto: controlla la connessione e riprova.');
        });
        richiesta.addEventListener('abort', function () {
            richiesta = null;
            chiudiModaleAnnulla();
            tornaAlForm('Caricamento annullato. Nessuna modifica è stata salvata.');
        });

        if (progressoModale) progressoModale.textContent = '0%';
        mostraPannello();
        richiesta.send(dati);
    });

    if (btnAnnullaCaricamento) {
        btnAnnullaCaricamento.addEventListener('click', function () {
            // Si apre solo la conferma: la richiesta NON viene toccata e
            // i byte continuano a partire mentre l'utente decide.
            if (!richiesta) return;
            if (elModaleAnnulla && window.bootstrap) {
                bootstrap.Modal.getOrCreateInstance(elModaleAnnulla).show();
            } else {
                richiesta.abort();   // senza Bootstrap: comportamento diretto
            }
        });
    }
    var btnConfermaAnnulla = document.getElementById('btn-conferma-annulla');
    if (btnConfermaAnnulla) {
        btnConfermaAnnulla.addEventListener('click', function () {
            chiudiModaleAnnulla();
            if (richiesta) richiesta.abort();
        });
    }

    // Chiudere la scheda durante il caricamento lo annulla: va chiesto.
    window.addEventListener('beforeunload', function (ev) {
        if (richiesta) {
            // preventDefault basta ai browser recenti; returnValue serve
            // a quelli meno recenti, che altrimenti non chiedono conferma.
            ev.preventDefault();
            ev.returnValue = '';
        }
    });

    Array.prototype.forEach.call(
        document.querySelectorAll('.js-esci'),
        function (uscita) {
            uscita.addEventListener('click', function (e) {
                if (istantanea() !== iniziale && window.bootstrap) {
                    e.preventDefault();
                    bootstrap.Modal.getOrCreateInstance(
                        document.getElementById('unsavedModal')
                    ).show();
                }
            });
        }
    );
    var salvaEsci = document.getElementById('btn-salva-esci');
    if (salvaEsci) {
        salvaEsci.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(
                document.getElementById('unsavedModal')
            ).hide();
            inviaModulo();
        });
    }
})();
