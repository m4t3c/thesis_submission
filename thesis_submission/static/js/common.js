/* Script condivisi da tutte le pagine (collegato in base.html). */

// Ogni form con class "js-confirm" apre prima la modale di conferma.
// I testi/varianti si passano via attributi data-confirm-*.
document.addEventListener('DOMContentLoaded', function () {
    var modalEl = document.getElementById('confirmModal');
    if (!modalEl || !window.bootstrap) return;
    var modal = new bootstrap.Modal(modalEl);
    var okBtn = document.getElementById('confirmModalOk');
    var pending = null;

    document.querySelectorAll('form.js-confirm').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            pending = form;
            document.getElementById('confirmModalTitle').textContent =
                form.dataset.confirmTitle || 'Conferma';
            document.getElementById('confirmModalBody').textContent =
                form.dataset.confirmBody || "Confermi l'operazione?";
            okBtn.className = 'btn ' + (form.dataset.confirmVariant || 'btn-primary');
            okBtn.textContent = form.dataset.confirmOk || 'Conferma';
            modal.show();
        });
    });

    okBtn.addEventListener('click', function () {
        if (pending) {
            var f = pending;
            pending = null;
            f.submit();  // submit nativo: non ritriggera l'evento (niente loop)
        }
    });
});

// Barra in alto e fondo pagina sono FISSI, cioe' fuori dal flusso: senza
// rimedio il contenuto scorrerebbe sotto l'una e sotto l'altro. Si riserva
// quindi sul body uno spazio pari alla loro altezza REALE, misurata invece
// che scritta a mano: entrambe cambiano altezza (il fondo pagina va a capo
// su telefono, la barra in alto dipende dal titolo) e un valore fisso
// sarebbe sbagliato per meta' degli schermi.
// Ricalcolato al ridimensionamento e quando una delle due cambia altezza.
(function () {
    var barra = document.querySelector('.navbar-app');
    var footer = document.getElementById('footer');
    function adegua() {
        if (barra) document.body.style.paddingTop = barra.offsetHeight + 'px';
        if (footer) document.body.style.paddingBottom = footer.offsetHeight + 'px';
    }
    adegua();
    window.addEventListener('load', adegua);
    window.addEventListener('resize', adegua);
    if (window.ResizeObserver) {
        var osserva = new ResizeObserver(adegua);
        if (barra) osserva.observe(barra);
        if (footer) osserva.observe(footer);
    }
})();

// Spunte che filtrano un elenco (per ora "mostra anche gli appelli passati"):
// con JavaScript si applicano da sole al cambio, e il pulsante che serviva a
// inviare il form sparisce perche' non ha piu' niente da fare.
// Senza script il pulsante resta, e la spunta funziona lo stesso.
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.js-invia-al-cambio').forEach(function (spunta) {
        var form = spunta.form;
        if (!form) return;
        form.querySelectorAll('.js-serve-senza-script').forEach(function (el) {
            el.hidden = true;
        });
        spunta.addEventListener('change', function () {
            form.submit();
        });
    });
});
