/*
 * Modulo di valutazione dei tutorati: chiusura esclusiva dei pannelli,
 * controllo punteggio+giudizio, uscita con modifiche non salvate, fumetti.
 *
 * Condiviso dall'area docente (sezione "I miei tutorati") e dal dettaglio di
 * un appello: lo include _modale_valutazione.html, che porta anche la modale
 * a cui questo script si appoggia. Si aspetta i moduli di
 * _modulo_valutazione.html.
 *
 * DOMContentLoaded non e' una precauzione di rito: bootstrap.bundle.js e'
 * caricato in fondo a base.html, cioe' DOPO questo file. Eseguendo subito,
 * "bootstrap" non esisterebbe ancora.
 */
document.addEventListener('DOMContentLoaded', function () {
    // --- Modulo di valutazione ------------------------------------------
    // Gli ascoltatori stanno sul documento e non sui singoli moduli: dopo una
    // ricerca le righe sono NUOVE, e ascoltatori agganciati all'avvio non le
    // conoscerebbero. Gli eventi di Bootstrap risalgono, quindi la delega vale
    // anche per le righe arrivate dopo.
    //
    // NON si usa data-bs-parent per l'esclusivita': chiuderebbe anche i
    // gruppi, che sono collapse pure loro.
    document.addEventListener('show.bs.collapse', function (e) {
        var modulo = e.target;
        if (!modulo.classList.contains('js-modifica')) return;
        document.querySelectorAll('.js-modifica.show').forEach(function (altro) {
            if (altro !== modulo) bootstrap.Collapse.getOrCreateInstance(altro).hide();
        });
        var riga = modulo.closest('.tutorato');
        if (riga) riga.classList.add('is-aperto');
        // Fotografia dei valori all'apertura: e' il metro con cui si decide
        // se all'uscita c'e' qualcosa da salvare.
        var form = modulo.querySelector('form');
        if (form) form.dataset.iniziale = istantanea(form);
    });
    document.addEventListener('hide.bs.collapse', function (e) {
        var modulo = e.target;
        if (!modulo.classList.contains('js-modifica')) return;
        var riga = modulo.closest('.tutorato');
        if (riga) riga.classList.remove('is-aperto');
    });

    // --- Fumetti di spiegazione -----------------------------------------
    // Un solo oggetto per tutta la pagina, con "selector": Bootstrap aggancia
    // da se' gli elementi che compaiono dopo (le righe dei risultati di
    // ricerca), cosa che inizializzarli uno per uno all'avvio non farebbe.
    if (window.bootstrap) {
        new bootstrap.Tooltip(document.body, {
            selector: '[data-bs-toggle="tooltip"]',
        });
    }

    // Dopo un salvataggio rifiutato la pagina si ridisegna con il modulo
    // aperto: va portato davanti agli occhi, altrimenti si atterra in cima
    // alla pagina e sembra non sia successo niente. Il pannello aperto lo
    // mette il server solo in quel caso. Nell'area docente si centra l'intera
    // riga del tutorato; nella tabella del dettaglio il modulo sta in una riga
    // a se', e si centra quello.
    var daCorreggere = document.querySelector('.js-modifica.show');
    if (daCorreggere) {
        (daCorreggere.closest('.tutorato') || daCorreggere).scrollIntoView({block: 'center'});
    }

    // --- Punteggio e giudizio vanno insieme -------------------------------
    // La regola vive sul server (ValutazioneForm.clean), che resta l'unico
    // controllo che conta. Qui si evita il viaggio: senza, per una meta'
    // dimenticata la pagina si ricaricherebbe e chi aveva scritto il giudizio
    // se lo ritroverebbe cancellato.
    var MESSAGGI_COPPIA = {
        giudizio: 'Hai scelto un punteggio: scrivi anche il giudizio che lo motiva.',
        punteggio: 'Hai scritto un giudizio: scegli anche il punteggio da proporre.',
    };

    function pulisciErroreCoppia(form) {
        form.querySelectorAll('.js-errore-coppia').forEach(function (n) { n.remove(); });
    }

    function mostraErroreCoppia(form, campo) {
        pulisciErroreCoppia(form);
        var avviso = document.createElement('div');
        avviso.className = 'text-danger small mt-1 js-errore-coppia';
        avviso.textContent = MESSAGGI_COPPIA[campo];
        var dopo = campo === 'giudizio'
            ? form.querySelector('textarea[name="giudizio"]')
            : form.querySelector('.segmento-punti');
        if (!dopo) return;
        dopo.parentNode.insertBefore(avviso, dopo.nextSibling);
        (campo === 'giudizio' ? dopo : dopo.querySelector('label')).focus();
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form.closest || !form.closest('.js-modifica')) return;
        var giudizio = form.querySelector('textarea[name="giudizio"]');
        var punteggio = form.querySelector('input[name="punteggio"]:checked');
        var conGiudizio = !!(giudizio && giudizio.value.trim());
        var conPunteggio = !!punteggio;
        if (conGiudizio === conPunteggio) {   // o tutti e due, o nessuno
            pulisciErroreCoppia(form);
            return;
        }
        e.preventDefault();
        mostraErroreCoppia(form, conPunteggio ? 'giudizio' : 'punteggio');
    });

    // --- Uscita con modifiche non salvate --------------------------------
    var modale = document.getElementById('modaleValutazione');
    var moduloInSospeso = null;

    /**
     * Valori correnti del modulo, serializzati per un confronto fra stringhe.
     *
     * Il token CSRF e' escluso: cambia a ogni pagina ma non e' un dato che
     * l'utente ha modificato, e includerlo non cambierebbe nulla al confronto.
     *
     * @param {HTMLFormElement} form Modulo di valutazione.
     * @returns {string} Coppie nome=valore unite da "&".
     */
    function istantanea(form) {
        var pezzi = [];
        new FormData(form).forEach(function (valore, nome) {
            if (nome !== 'csrfmiddlewaretoken') pezzi.push(nome + '=' + valore);
        });
        return pezzi.join('&');
    }

    /**
     * Chiude il pannello di un tutorato, scartando se richiesto le modifiche.
     *
     * reset() riporta i campi ai valori resi dal server, cioe' a quelli
     * salvati nel database: e' esattamente "esci senza salvare".
     *
     * @param {HTMLElement} modulo Contenitore collapse del modulo.
     * @param {boolean} ripristina Se riportare i campi ai valori salvati.
     */
    function chiudiModulo(modulo, ripristina) {
        var form = modulo.querySelector('form');
        if (form && ripristina) form.reset();
        bootstrap.Collapse.getOrCreateInstance(modulo).hide();
    }

    document.addEventListener('click', function (e) {
        var bottone = e.target.closest('.js-annulla-valutazione');
        if (!bottone) return;
        var modulo = document.querySelector(bottone.dataset.bsTarget);
        if (!modulo) return;
        var form = modulo.querySelector('form');

        // Niente da perdere (o niente Bootstrap): si chiude e basta.
        if (!form || !modale || !window.bootstrap ||
            istantanea(form) === form.dataset.iniziale) {
            chiudiModulo(modulo, true);
            return;
        }
        moduloInSospeso = modulo;
        bootstrap.Modal.getOrCreateInstance(modale).show();
    });

    var btnEsci = document.getElementById('btn-esci-senza-salvare');
    if (btnEsci) {
        btnEsci.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(modale).hide();
            if (!moduloInSospeso) return;
            chiudiModulo(moduloInSospeso, true);
            moduloInSospeso = null;
        });
    }

    var btnSalvaEsci = document.getElementById('btn-salva-esci-valutazione');
    if (btnSalvaEsci) {
        btnSalvaEsci.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(modale).hide();
            if (!moduloInSospeso) return;
            var form = moduloInSospeso.querySelector('form');
            moduloInSospeso = null;
            if (!form) return;
            // requestSubmit e non submit: fa scattare la validazione del
            // browser sui campi obbligatori, invece di scavalcarla.
            if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
        });
    }

    // --- Ritorno dopo un salvataggio ----------------------------------------
    // Si torna con l'ancora della riga. Se quella riga sta in un gruppo chiuso
    // (area docente) va aperto, altrimenti si atterrerebbe su un punto della
    // pagina che non mostra nulla.
    if (!location.hash) return;
    var bersaglio = null;
    // L'ancora arriva dall'URL e puo' non essere un selettore CSS valido
    // (un id che inizia con una cifra, un frammento scritto a mano):
    // querySelector lancerebbe un'eccezione e fermerebbe il resto dello script.
    try { bersaglio = document.querySelector(location.hash); } catch (e) { return; }
    if (!bersaglio) return;
    var gruppo = bersaglio.closest('.collapse');
    if (gruppo && !gruppo.classList.contains('show')) {
        bootstrap.Collapse.getOrCreateInstance(gruppo).show();
    }
    bersaglio.scrollIntoView({block: 'center'});
});
