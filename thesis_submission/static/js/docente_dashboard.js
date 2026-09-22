/*
 * Pagina degli appelli di docente e presidente (docente_dashboard.html).
 *
 * Solo la ricerca mentre si scrive: il comportamento dei moduli di
 * valutazione sta in valutazione.js (vedi _modale_valutazione.html).
 *
 * L'indirizzo della ricerca lo scrive il template nell'attributo
 * data-url-ricerca del campo: un file statico non puo' usare {% url %}.
 */
document.addEventListener('DOMContentLoaded', function () {
    var input = document.getElementById('ricerca-laureandi');
    var URL_RICERCA = input ? input.dataset.urlRicerca : '';
    var azzera = document.getElementById('azzera-ricerca');
    var risultati = document.getElementById('risultati-laureandi');
    var elenco = document.getElementById('elenco-laureandi');
    var attesa = null;     // timer del debounce
    var richiesta = null;  // ricerca in corso, da annullare se ne parte un'altra

    // --- Ricerca mentre si scrive ---------------------------------------
    if (input) {
        // I gruppi restano nella pagina: tornare all'elenco completo e'
        // scoprirli di nuovo, non richiederli al server.
        var mostraElenco = function () {
            risultati.hidden = true;
            risultati.textContent = '';
            elenco.hidden = false;
        };

        // Riscrive il solo parametro della ricerca, lasciando stare gli altri:
        // sull'URL c'e' anche la spunta degli appelli passati, e sostituire la
        // querystring per intero la spegnerebbe al primo tasto premuto.
        var aggiornaUrl = function (termine) {
            var voci = new URLSearchParams(window.location.search);
            if (termine) {
                voci.set('q', termine);
            } else {
                voci.delete('q');
            }
            var query = voci.toString();
            history.replaceState(
                null, '', window.location.pathname + (query ? '?' + query : '')
            );
        };

        var annulla = function () {
            if (richiesta) { richiesta.abort(); richiesta = null; }
            clearTimeout(attesa);
            input.value = '';
            azzera.hidden = true;
            mostraElenco();
            // L'URL torna pulito senza ricaricare: altrimenti un aggiornamento
            // della pagina (o il salvataggio di una valutazione) riporterebbe
            // una ricerca che sullo schermo era gia' stata annullata.
            aggiornaUrl(null);
            input.focus();
        };

        var cerca = function (termine) {
            if (richiesta) richiesta.abort();
            richiesta = new AbortController();
            fetch(URL_RICERCA + '?q=' + encodeURIComponent(termine), {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                credentials: 'same-origin',
                signal: richiesta.signal
            })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
            .then(function (dati) {
                // Il contenuto arriva dal nostro template, gia' messo in salvo
                // da Django: non e' testo dell'utente rimesso in pagina.
                risultati.innerHTML = dati.html;
                risultati.hidden = false;
                elenco.hidden = true;
                // Anche l'URL segue la ricerca: ricaricando, o tornando dopo
                // aver salvato, si ritrovano gli stessi risultati.
                aggiornaUrl(termine);
            })
            .catch(function (e) { if (e.name !== 'AbortError') mostraElenco(); });
        };

        input.addEventListener('input', function () {
            clearTimeout(attesa);
            var termine = input.value.trim();
            if (termine.length < 2) {
                // Sotto le due lettere i risultati sarebbero troppi per essere
                // utili: e' la stessa soglia della ricerca dei docenti.
                mostraElenco();
            } else {
                // Si aspetta una breve pausa nella digitazione: senza, ogni
                // tasto premuto produrrebbe una query al database.
                attesa = setTimeout(function () { cerca(termine); }, 250);
            }
            azzera.hidden = termine.length === 0;
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { annulla(); return; }
            // La ricerca e' gia' partita da sola: inviare il form mostrerebbe
            // lo stesso risultato, solo dopo un giro completo di pagina.
            if (e.key === 'Enter') e.preventDefault();
        });

        azzera.addEventListener('click', annulla);
        // Il collegamento dentro i risultati e' un vero link, e senza
        // JavaScript ricarica la pagina: qui lo si intercetta per evitarlo.
        risultati.addEventListener('click', function (e) {
            if (!e.target.closest('.js-annulla-ricerca')) return;
            e.preventDefault();
            annulla();
        });

        // Pagina aperta con una ricerca gia' nell'URL (o tornata da un
        // salvataggio): il campo e' pieno, quindi la crocetta deve esserci.
        if (input.value.trim()) azzera.hidden = false;
    }
});
