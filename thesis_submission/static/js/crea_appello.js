/*
 * Creazione di un appello (crea_appello.html).
 *
 * Gli indirizzi delle richieste li scrive il template negli attributi
 * data-url-* (un file statico non puo' usare {% url %}): la ricerca dei
 * docenti sul campo #ricerca-docenti, la lettura dell'elenco sulla #zona-drop.
 * I dati con cui ripristinare il form arrivano dai blocchi json_script.
 */
(function () {
    var form = document.getElementById('appello-form');
    var input = document.getElementById('ricerca-docenti');
    var elencoRisultati = document.getElementById('risultati-docenti');
    var elencoScelti = document.getElementById('docenti-scelti');
    var contenitoreHidden = document.getElementById('docenti-hidden');
    var vuoto = document.getElementById('nessun-docente');
    var boxMembri = document.getElementById('box-membri');
    if (!input) return;
    var URL_RICERCA = input.dataset.urlRicerca;

    var telefono = window.matchMedia('(max-width: 575.98px)');

    var scelti = [];          // [{id, nome, cognome, username, email}]
    var attesa = null;        // timer del debounce
    var richiesta = null;     // ricerca in corso, da annullare se ne parte un'altra

    function nomeCompleto(d) {
        var pezzi = [d.nome, d.cognome].filter(Boolean).join(' ');
        return pezzi ? pezzi + ' (' + d.username + ')' : d.username;
    }

    // --- Selezionati ---------------------------------------------------
    function disegnaScelti() {
        elencoScelti.textContent = '';
        contenitoreHidden.textContent = '';
        scelti.forEach(function (d) {
            var riga = document.createElement('div');
            riga.className = 'membro';

            var icona = document.createElement('i');
            icona.className = 'bi bi-person-fill membro-icona';
            icona.setAttribute('aria-hidden', 'true');

            var testo = document.createElement('div');
            testo.className = 'membro-testo';
            var riga1 = document.createElement('div');
            riga1.className = 'riga-docente-nome text-truncate';
            riga1.textContent = nomeCompleto(d);
            var riga2 = document.createElement('div');
            riga2.className = 'riga-docente-mail text-truncate';
            riga2.textContent = d.email || '';
            testo.appendChild(riga1);
            testo.appendChild(riga2);

            var togli = document.createElement('button');
            togli.type = 'button';
            togli.className = 'btn btn-sm btn-danger membro-rimuovi';
            togli.setAttribute('aria-label', 'Rimuovi ' + nomeCompleto(d));
            togli.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
            togli.addEventListener('click', function () {
                scelti = scelti.filter(function (x) { return x.id !== d.id; });
                disegnaScelti();
            });

            riga.appendChild(icona);
            riga.appendChild(testo);
            riga.appendChild(togli);
            elencoScelti.appendChild(riga);

            var hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'docenti';
            hidden.value = d.id;
            contenitoreHidden.appendChild(hidden);
        });
        vuoto.hidden = scelti.length > 0;
        boxMembri.classList.toggle('pieno', scelti.length > 0);
        aggiornaStato();
    }

    function aggiungi(d) {
        if (!scelti.some(function (x) { return x.id === d.id; })) {
            scelti.push(d);
            disegnaScelti();
        }
        input.value = '';
        chiudiRisultati();
        input.focus();
    }

    // --- Tendina dei risultati ------------------------------------------
    function chiudiRisultati() {
        elencoRisultati.hidden = true;
        elencoRisultati.textContent = '';
        input.setAttribute('aria-expanded', 'false');
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

            var riga1 = document.createElement('div');
            riga1.className = 'riga-docente-nome';
            riga1.textContent = nomeCompleto(d);
            var riga2 = document.createElement('div');
            riga2.className = 'riga-docente-mail';
            riga2.textContent = d.email || '';
            voce.appendChild(riga1);
            voce.appendChild(riga2);

            voce.addEventListener('click', function () { aggiungi(d); });
            elencoRisultati.appendChild(voce);
        });
        elencoRisultati.hidden = false;
        input.setAttribute('aria-expanded', 'true');
    }

    function cerca(termine) {
        if (richiesta) richiesta.abort();
        richiesta = new AbortController();
        fetch(URL_RICERCA + '?q=' + encodeURIComponent(termine), {
            headers: {'X-Requested-With': 'XMLHttpRequest'},
            credentials: 'same-origin',
            signal: richiesta.signal
        })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (dati) {
            // Chi e' gia' stato scelto non va riproposto.
            disegnaRisultati(dati.risultati.filter(function (d) {
                return !scelti.some(function (x) { return x.id === d.id; });
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
        // Invio nel campo di ricerca non deve inviare tutto il form.
        if (e.key === 'Enter') e.preventDefault();
    });

    document.addEventListener('click', function (e) {
        if (!elencoRisultati.contains(e.target) && e.target !== input) chiudiRisultati();
    });

    // Il segnaposto non si puo' accorciare da CSS: si scambia qui.
    var SEGNAPOSTO_LUNGO = input.placeholder;
    function adattaSegnaposto() {
        input.placeholder = telefono.matches ? input.dataset.placeholderBreve : SEGNAPOSTO_LUNGO;
    }

    // --- Elenco laureandi (.xlsx) ----------------------------------------
    var zona = document.getElementById('zona-drop');
    var URL_XLSX = zona.dataset.urlAnalisi;
    var inputFile = document.getElementById('file-xlsx');
    var nomeFile = document.getElementById('nome-file');
    var conteggioFile = document.getElementById('conteggio-file');
    var esito = document.getElementById('esito-xlsx');
    var elencoStudenti = document.getElementById('studenti-scelti');
    var vediTutti = document.getElementById('vedi-tutti');
    var campiAppello = document.getElementById('campi-appello');
    var btnCrea = document.getElementById('btn-crea-appello');
    var corso = document.getElementById('id_corso_di_laurea');
    var campoData = document.getElementById('id_data');
    var statoAzioni = document.getElementById('stato-azioni');

    // Vero quando l'elenco e' stato letto: e' cio' che accende il modulo.
    var datiCaricati = false;
    var studenti = [];        // [{id, nome, cognome, username, email}]

    function messaggio(testo, tipo) {
        esito.className = 'mt-2 alert alert-' + tipo + ' shadow-sm';
        esito.setAttribute('role', tipo === 'info' ? 'status' : 'alert');
        esito.textContent = testo;
        esito.hidden = false;
    }

    function nomeStudente(d) {
        var pezzi = [d.cognome, d.nome].filter(Boolean).join(' ');
        return pezzi || d.username;
    }

    function caselleSpuntate() {
        return elencoStudenti.querySelectorAll('input[name="studenti"]:checked');
    }

    // Le caselle SONO gli input "studenti" del form: una casella tolta non
    // viene inviata, quindi quello studente non viene iscritto.
    function disegnaStudenti() {
        elencoStudenti.textContent = '';
        elencoStudenti.classList.remove('aperto');
        if (!studenti.length) {
            var nessuno = document.createElement('p');
            nessuno.className = 'vuoto-studenti';
            nessuno.textContent = 'Nessuno studente del file è registrato nel sistema.';
            elencoStudenti.appendChild(nessuno);
        }
        studenti.forEach(function (d) {
            var riga = document.createElement('label');
            riga.className = 'riga-studente';

            var casella = document.createElement('input');
            casella.type = 'checkbox';
            casella.className = 'form-check-input';
            casella.name = 'studenti';
            casella.value = d.id;
            casella.checked = true;

            var testo = document.createElement('span');
            testo.className = 'riga-studente-testo';

            var nome = document.createElement('span');
            nome.className = 'riga-studente-nome';
            nome.textContent = nomeStudente(d);

            var email = document.createElement('span');
            email.className = 'riga-studente-email';
            email.textContent = d.email || '';

            testo.appendChild(nome);
            testo.appendChild(email);
            riga.appendChild(casella);
            riga.appendChild(testo);
            elencoStudenti.appendChild(riga);
        });
        conteggioFile.textContent = studenti.length;
        aggiornaVediTutti();
        aggiornaStato();
    }

    function aggiornaVediTutti() {
        var limite = telefono.matches ? 4 : 8;
        var aperto = elencoStudenti.classList.contains('aperto');
        vediTutti.hidden = studenti.length <= limite;
        vediTutti.textContent = aperto ? 'Mostra meno' : 'Vedi tutti i ' + studenti.length;
        vediTutti.setAttribute('aria-expanded', aperto ? 'true' : 'false');
    }

    vediTutti.addEventListener('click', function () {
        elencoStudenti.classList.toggle('aperto');
        aggiornaVediTutti();
    });

    elencoStudenti.addEventListener('change', aggiornaStato);

    // --- Stato della pagina ----------------------------------------------
    function plurale(n, uno, tanti) { return n + ' ' + (n === 1 ? uno : tanti); }

    function aggiornaStato() {
        if (!elencoStudenti) return;   // chiamata durante l'avvio
        var nSpuntati = caselleSpuntate().length;

        form.classList.toggle('stato-vuoto', !datiCaricati);
        campiAppello.disabled = !datiCaricati;
        btnCrea.disabled = !datiCaricati || nSpuntati === 0;
        document.getElementById('studenti-selezionati').textContent = nSpuntati;

        var corsoTesto = corso ? corso.value.trim() : '';

        if (!datiCaricati) {
            statoAzioni.textContent = "Manca l'elenco laureandi";
        } else if (nSpuntati === 0) {
            statoAzioni.textContent = 'Nessuno studente da iscrivere';
        } else {
            statoAzioni.textContent = plurale(nSpuntati, 'studente', 'studenti') + ', ' +
                plurale(scelti.length, 'membro', 'membri') + ' di commissione';
        }
    }

    if (corso) corso.addEventListener('input', aggiornaStato);
    if (campoData) campoData.addEventListener('input', aggiornaStato);

    // --- Scelta e lettura del file ---------------------------------------
    // Tipo MIME dei .xlsx: e' l'unica informazione che il browser espone
    // durante il trascinamento, prima che il file venga rilasciato.
    var MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    var NON_SUPPORTATO = 'File non supportato. L’unico tipo di file accettato è un file .xlsx';
    var UN_SOLO_FILE = 'Trascina un solo file xlsx per volta.';

    function estensioneOk(nome) {
        return /\.xlsx$/i.test(nome || '');
    }

    // La lettura parte appena il file e' scelto. Se non riesce, quello che era
    // gia' stato caricato resta com'era: un file sbagliato non cancella il
    // lavoro fatto con quello giusto.
    function leggiFile(file) {
        inputFile.value = '';
        if (!file) return;
        if (!estensioneOk(file.name)) {
            messaggio(NON_SUPPORTATO, 'danger');
            return;
        }
        var dati = new FormData();
        dati.append('file', file);
        zona.classList.add('in-lettura');
        messaggio('Lettura del file in corso…', 'info');

        fetch(URL_XLSX, {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value || ''
            },
            credentials: 'same-origin',
            body: dati
        })
        .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
        .then(function (res) {
            zona.classList.remove('in-lettura');
            if (!res.ok) {
                messaggio(res.j.errore || 'Lettura non riuscita.', 'danger');
                return;
            }
            if (corso && res.j.corso) corso.value = res.j.corso;
            studenti = ordina(res.j.studenti || []);
            nomeFile.textContent = file.name;
            zona.classList.add('con-file');
            datiCaricati = true;
            disegnaStudenti();

            var mancanti = res.j.mancanti || [];
            if (mancanti.length) {
                messaggio('Non ancora registrati nel sistema e quindi non iscrivibili: ' +
                          mancanti.join(', '), 'warning');
            } else {
                esito.hidden = true;
            }
        })
        .catch(function () {
            zona.classList.remove('in-lettura');
            messaggio('Errore di rete durante la lettura del file.', 'danger');
        });
    }

    function ordina(elenco) {
        return elenco.slice().sort(function (a, b) {
            return nomeStudente(a).localeCompare(nomeStudente(b), 'it');
        });
    }

    // L'avviso mostrato durante il trascinamento e' provvisorio: se il file non
    // viene poi rilasciato non e' successo niente, quindi il riquadro torna
    // com'era invece di lasciare un errore che non riguarda il file caricato.
    var statoPrimaDelTrascinamento = null;

    function avvisoTrascinamento(testo) {
        if (statoPrimaDelTrascinamento === null) {
            statoPrimaDelTrascinamento = {
                classe: esito.className,
                testo: esito.textContent,
                nascosto: esito.hidden
            };
        }
        messaggio(testo, 'danger');
    }

    function fineTrascinamento() {
        if (statoPrimaDelTrascinamento === null) return;
        esito.className = statoPrimaDelTrascinamento.classe;
        esito.textContent = statoPrimaDelTrascinamento.testo;
        esito.hidden = statoPrimaDelTrascinamento.nascosto;
        statoPrimaDelTrascinamento = null;
    }

    // In dragover il nome del file non e' leggibile: si guarda il tipo MIME,
    // che pero' puo' essere vuoto. In quel caso si lascia passare e si
    // controlla l'estensione al rilascio. Torna il motivo, o null se va bene.
    function motivoRifiuto(dt) {
        if (!dt || !dt.items || !dt.items.length) return null;
        if (dt.items.length > 1) return UN_SOLO_FILE;
        var elemento = dt.items[0];
        if (elemento.kind !== 'file') return NON_SUPPORTATO;
        if (elemento.type !== '' && elemento.type !== MIME_XLSX) return NON_SUPPORTATO;
        return null;
    }

    zona.addEventListener('click', function (e) {
        if (e.target !== inputFile) inputFile.click();
    });
    zona.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputFile.click();
        }
    });
    inputFile.addEventListener('change', function () {
        leggiFile(inputFile.files[0]);
    });
    ['dragenter', 'dragover'].forEach(function (ev) {
        zona.addEventListener(ev, function (e) {
            e.preventDefault();
            var motivo = motivoRifiuto(e.dataTransfer);
            if (e.dataTransfer) {
                e.dataTransfer.dropEffect = motivo ? 'none' : 'copy';
            }
            zona.classList.toggle('rifiuta', !!motivo);
            zona.classList.toggle('sopra', !motivo);
            // Con dropEffect 'none' il rilascio non avviene e l'evento
            // 'drop' non arriva mai: l'errore va mostrato gia' qui.
            if (motivo) { avvisoTrascinamento(motivo); }
            else { fineTrascinamento(); }
        });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
        zona.addEventListener(ev, function (e) {
            e.preventDefault();
            zona.classList.remove('sopra');
            zona.classList.remove('rifiuta');
            fineTrascinamento();
        });
    });
    zona.addEventListener('drop', function (e) {
        var files = e.dataTransfer.files;
        if (!files || !files.length) return;
        if (files.length > 1) {
            messaggio(UN_SOLO_FILE, 'danger');
            return;
        }
        leggiFile(files[0]);
    });

    // --- Barra azioni su telefono ----------------------------------------
    // Il fondo pagina di base.html e' fisso: la barra ancorata deve fermarsi
    // sopra di lui, non finirci sotto.
    var fondo = document.getElementById('footer');
    function adattaAltezzaFondo() {
        form.style.setProperty('--altezza-fondo', (fondo ? fondo.offsetHeight : 0) + 'px');
    }

    function adattaSchermo() {
        adattaSegnaposto();
        adattaAltezzaFondo();
        aggiornaVediTutti();
    }
    if (telefono.addEventListener) telefono.addEventListener('change', adattaSchermo);
    window.addEventListener('resize', adattaAltezzaFondo);

    // --- Avvio ------------------------------------------------------------
    // Ripristina la selezione quando il form torna indietro con un errore.
    function datiIniziali(id) {
        var el = document.getElementById(id);
        if (!el) return [];
        try { return JSON.parse(el.textContent) || []; } catch (e) { return []; }
    }
    scelti = datiIniziali('docenti-iniziali');
    studenti = ordina(datiIniziali('studenti-iniziali'));
    if (studenti.length) {
        datiCaricati = true;
        zona.classList.add('con-file');
    }
    disegnaScelti();
    disegnaStudenti();
    adattaSchermo();

    // --- Conferma all'uscita se ci sono modifiche non salvate ------------
    // Si confronta lo stato iniziale del form con quello attuale: cosi' vale
    // per corso, data, orario, membri e studenti senza doverli elencare a mano.
    function istantanea() {
        var parti = scelti.map(function (d) { return d.id; }).sort();
        caselleSpuntate().forEach(function (c) { parti.push('s' + c.value); });
        form.querySelectorAll('input[type="text"], input[type="date"], input[type="time"]')
            .forEach(function (i) {
                if (i.id !== 'ricerca-docenti') parti.push(i.name + '=' + i.value);
            });
        return parti.join('|');
    }
    var statoIniziale = istantanea();

    document.querySelectorAll('a.js-esci').forEach(function (link) {
        link.addEventListener('click', function (e) {
            if (istantanea() !== statoIniziale && window.bootstrap) {
                e.preventDefault();
                bootstrap.Modal.getOrCreateInstance(
                    document.getElementById('unsavedModal')
                ).show();
            }
        });
    });

    var salvaEsci = document.getElementById('btn-salva-esci');
    if (salvaEsci) {
        salvaEsci.addEventListener('click', function () {
            bootstrap.Modal.getOrCreateInstance(
                document.getElementById('unsavedModal')
            ).hide();
            // requestSubmit (non submit) fa scattare la validazione del browser
            // e gli eventuali gestori di 'submit'.
            if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
        });
    }
})();
