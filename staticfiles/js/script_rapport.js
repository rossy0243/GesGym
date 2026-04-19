
// ====================================================
// DONNÉES DE SIMULATION POUR SMARTCLUB PRO - RAPPORTS
// ====================================================

// Configuration
let config = {
    currentReportTab: 'journalier',
    currentSite: 'all',
    currentPeriod: 'week',
    dateFrom: null,
    dateTo: null
};

// État de la clôture journalière (verrou + ajustements)
const dailyClosureState = {
    isClosed: false,
    adjustments: [] // { date, motif, responsable }
};

// Données de démonstration
let reportsData = {
    daily: {
        revenue: 2450,
        revenueTrend: 8,
        transactions: 48,
        newClients: 12,
        visits: 187,
        paymentMethods: {
            cash: 36,
            card: 12
        },
        transactionsList: [
            { time: "09:30", client: "Jean Kazadi", type: "Abonnement 1 mois", method: "Carte", amount: 45, status: "paye", ref: "#TX-001" },
            { time: "10:15", client: "Marie Lukusa", type: "Abonnement 3 mois", method: "M-Pesa", amount: 120, status: "paye", ref: "#TX-002" },
            { time: "11:45", client: "Paul Mbuyi", type: "Accès journalier", method: "Cash", amount: 10, status: "paye", ref: "#TX-003" },
            { time: "14:20", client: "Sophie Kabeya", type: "Abonnement 6 mois", method: "Orange Money", amount: 250, status: "impaye", ref: "#TX-004" },
            { time: "16:00", client: "Pierre Luntala", type: "Renouvellement 1 an", method: "Airtel Money", amount: 420, status: "paye", ref: "#TX-005" }
        ]
    },
    monthly: {
        revenue: 45280,
        revenueTrend: 15,
        newMembers: 56,
        newTrend: 8,
        renewals: 128,
        retention: 78,
        visits: 4250,
        salesChart: {
            labels: ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun'],
            values: [38500, 40200, 42100, 43800, 45280, 46800]
        }
    }
};

// Variables pour les graphiques
let dailyPaymentChart = null;
let monthlySalesChart = null;

// ====================================================
// FONCTIONS DE NAVIGATION
// ====================================================
// ====================================================
// GESTION DES ONGLETS DE RAPPORTS
// ====================================================
function showReportTab(tab) {
    config.currentReportTab = tab;

    // Sous-menu actif (barre latérale)
    ['journalier', 'mensuel', 'personnalise'].forEach(function(id) {
        var el = document.getElementById('nav-rapports-' + id);
        if (el) el.classList.toggle('active', id === tab);
    });
    var url = new URL(window.location);
    url.searchParams.set('tab', tab);
    window.history.replaceState({}, '', url);

    // Afficher/masquer les sections
    document.getElementById('journalierSection').style.display = 'none';
    document.getElementById('mensuelSection').style.display = 'none';
    document.getElementById('personnaliseSection').style.display = 'none';

    document.getElementById(tab + 'Section').style.display = 'block';

    // Mettre à jour le titre
    let title = 'Rapports';
    switch(tab) {
        case 'journalier': title = 'Rapports - Journalier'; break;
        case 'mensuel': title = 'Rapports - Mensuel'; break;
        case 'personnalise': title = 'Rapports - Personnalisé'; break;
    }
    document.getElementById('pageTitle').textContent = title;

    // Mettre à jour la navigation active
    document.querySelectorAll('#nav-rapports-journalier, #nav-rapports-mensuel, #nav-rapports-personnalise').forEach(el => {
        el.classList.remove('active');
    });
    const navEl = document.getElementById('nav-rapports-' + tab);
    if (navEl) navEl.classList.add('active');

    // Mettre à jour le libellé du bouton de clôture quand on revient sur Journalier
    if (tab === 'journalier') {
        const label = document.getElementById('dailyClosureLabel');
        if (label) label.textContent = dailyClosureState.isClosed ? 'Journée clôturée' : 'Clôturer la journée';
    }

    // Adapter les filtres selon l'onglet
    updateFiltersForTab(tab);

    // Re-rendre les graphiques si nécessaire
    if (tab === 'journalier' && !dailyPaymentChart) {
        renderDailyChart();
    } else if (tab === 'mensuel' && !monthlySalesChart) {
        renderMonthlyChart();
    }
}

function updateFiltersForTab(tab) {
    const periodFilter = document.getElementById('periodFilter');
    const dateFrom = document.getElementById('dateFrom');
    const dateTo = document.getElementById('dateTo');

    if (tab === 'journalier') {
        periodFilter.innerHTML = `
            <option value="today">Aujourd'hui</option>
            <option value="yesterday">Hier</option>
            <option value="week" selected>Cette semaine</option>
        `;
        dateFrom.style.display = 'none';
        dateTo.style.display = 'none';
    } else if (tab === 'mensuel') {
        periodFilter.innerHTML = `
            <option value="month" selected>Ce mois</option>
            <option value="lastmonth">Mois dernier</option>
            <option value="year">Cette année</option>
        `;
        dateFrom.style.display = 'none';
        dateTo.style.display = 'none';
    } else if (tab === 'personnalise') {
        periodFilter.value = 'custom';
        dateFrom.style.display = 'inline-block';
        dateTo.style.display = 'inline-block';
    }
}

function filterReports() {
    config.currentSite = document.getElementById('siteFilter').value;
    config.currentPeriod = document.getElementById('periodFilter').value;

    if (config.currentPeriod === 'custom') {
        config.dateFrom = document.getElementById('dateFrom').value;
        config.dateTo = document.getElementById('dateTo').value;
    }

    console.log(`Filtrage: Site=${config.currentSite}, Période=${config.currentPeriod}`);

    // Simulation de mise à jour des données
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'success',
            title: 'Rapport filtré',
            text: `Données mises à jour pour la période sélectionnée`,
            confirmButtonColor: '#3454d1',
            timer: 1500,
            showConfirmButton: false
        });
    }
}

// ====================================================
// FONCTIONS DE GÉNÉRATION DE RAPPORTS
// ====================================================
function generateSelectedReport() {
    let reportType = config.currentReportTab;

    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'info',
            title: 'Génération en cours',
            text: `Préparation du rapport ${reportType}...`,
            confirmButtonColor: '#3454d1'
        });
    } else {
        alert(`Génération du rapport ${reportType}...`);
    }
}

// ====================================================
// CLÔTURE JOURNALIÈRE & AJUSTEMENTS
// ====================================================
function toggleDailyClosure() {
    if (!dailyClosureState.isClosed) {
        Swal.fire({
            title: 'Clôturer la journée ?',
            text: 'Après clôture, les ajustements devront être justifiés.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Oui, clôturer',
            cancelButtonText: 'Annuler',
            confirmButtonColor: '#3454d1'
        }).then((result) => {
            if (result.isConfirmed) {
                dailyClosureState.isClosed = true;
                const label = document.getElementById('dailyClosureLabel');
                if (label) label.textContent = 'Journée clôturée';
                Swal.fire('Clôturée', 'La clôture journalière est enregistrée.', 'success');
            }
        });
    } else {
        Swal.fire('Déjà clôturée', 'La journée est déjà clôturée. Utilisez un ajustement.', 'info');
    }
}

function openDailyAdjustmentDialog() {
    if (!dailyClosureState.isClosed) {
        Swal.fire('Non clôturée', 'Vous devez d\'abord clôturer la journée.', 'info');
        return;
    }

    Swal.fire({
        title: 'Ajustement après clôture',
        html: `
            <div class="mb-2 text-start">
                <label class="form-label">Motif de l'ajustement</label>
                <textarea id="adjMotif" class="form-control" rows="2"
                    placeholder="Ex: Correction de caisse, erreur de saisie..."></textarea>
            </div>
            <div class="mb-2 text-start">
                <label class="form-label">Responsable</label>
                <input id="adjResponsable" class="form-control" placeholder="Nom du responsable">
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: 'Enregistrer',
        cancelButtonText: 'Annuler',
        preConfirm: () => {
            const motif = document.getElementById('adjMotif').value.trim();
            const responsable = document.getElementById('adjResponsable').value.trim();
            if (!motif || !responsable) {
                Swal.showValidationMessage('Motif et responsable sont obligatoires.');
                return false;
            }
            return { motif, responsable };
        }
    }).then(result => {
        if (result.isConfirmed && result.value) {
            dailyClosureState.adjustments.push({
                date: new Date().toISOString(),
                motif: result.value.motif,
                responsable: result.value.responsable
            });
            Swal.fire('Ajustement enregistré', 'L\'ajustement a été ajouté avec justificatif.', 'success');
        }
    });
}

function generateCustomReport() {
    const dataType = document.getElementById('reportDataType').selectedOptions;
    const from = document.getElementById('customDateFrom').value;
    const to = document.getElementById('customDateTo').value;

    let types = [];
    for (let option of dataType) {
        types.push(option.value);
    }

    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'success',
            title: 'Rapport généré',
            html: `Rapport personnalisé créé avec succès<br><small>Données: ${types.join(', ')}<br>Période: du ${from} au ${to}</small>`,
            confirmButtonColor: '#3454d1'
        });
    }
}

function saveReportTemplate() {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'success',
            title: 'Modèle sauvegardé',
            text: 'Votre configuration de rapport a été enregistrée',
            confirmButtonColor: '#3454d1'
        });
    }
}

function loadTemplate(template) {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'info',
            title: 'Modèle chargé',
            text: `Configuration "${template}" appliquée`,
            confirmButtonColor: '#3454d1'
        });
    }
}

// ====================================================
// FONCTIONS D'EXPORT
// ====================================================
function exportReport(format) {
    let reportName = config.currentReportTab;

    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'success',
            title: 'Export en cours',
            text: `Le rapport ${reportName} est en cours d'export au format ${format.toUpperCase()}`,
            confirmButtonColor: '#3454d1'
        });
    } else {
        alert(`Export du rapport ${reportName} au format ${format}`);
    }
}

function exportCurrentView(format) {
    exportReport(format);
}

function printCurrentView() {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'info',
            title: 'Impression',
            text: 'Préparation de la vue pour impression...',
            confirmButtonColor: '#3454d1'
        });
    }
}

// ====================================================
// GRAPHIQUES AVEC CHART.JS
// ====================================================
function renderDailyChart() {
    const ctx = document.getElementById('dailyPaymentChart')?.getContext('2d');
    if (!ctx) return;

    if (dailyPaymentChart) {
        dailyPaymentChart.destroy();
    }

    dailyPaymentChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Cash', 'Cartes & Mobile Money'],
            datasets: [{
                data: [36, 12],
                backgroundColor: ['#10b981', '#3454d1'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom'
                }
            },
            cutout: '70%'
        }
    });
}

function renderMonthlyChart() {
    const ctx = document.getElementById('monthlySalesChart')?.getContext('2d');
    if (!ctx) return;

    if (monthlySalesChart) {
        monthlySalesChart.destroy();
    }

    monthlySalesChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: reportsData.monthly.salesChart.labels,
            datasets: [{
                label: 'Revenus (en USD)',
                data: reportsData.monthly.salesChart.values,
                borderColor: '#3454d1',
                backgroundColor: 'rgba(52, 84, 209, 0.1)',
                tension: 0.3,
                fill: true,
                pointBackgroundColor: '#3454d1',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { mode: 'index', intersect: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: function(value) { return value + ' $'; } }
                }
            }
        }
    });
}

// ====================================================
// INITIALISATION
// ====================================================
document.addEventListener('DOMContentLoaded', function() {
    // Initialiser la navigation (logo compact si besoin)
    if (document.querySelector('.b-brand .logo-sm')) {
        document.querySelector('.b-brand .logo-sm').style.display = 'none';
    }

    // Lire l'onglet depuis l'URL
    const urlParams = new URLSearchParams(window.location.search);
    const tabParam = urlParams.get('tab');
    const validTabs = ['journalier', 'mensuel', 'personnalise'];
    const initialTab = validTabs.includes(tabParam) ? tabParam : 'journalier';

    showReportTab(initialTab);

    // Clics sur le sous-menu Rapports (éviter rechargement)
    ['journalier', 'mensuel', 'personnalise'].forEach(t => {
        const el = document.getElementById('nav-rapports-' + t);
        if (el) {
            const a = el.querySelector('a');
            if (a) a.addEventListener('click', function(e) {
                if (window.location.pathname.replace(/^.*[/\\]/, '').toLowerCase().includes('rapport')) {
                    e.preventDefault();
                    showReportTab(t);
                }
            });
        }
    });

    // Initialiser les graphiques
    renderDailyChart();
    renderMonthlyChart();

    // Gérer l'affichage des dates personnalisées
    document.getElementById('periodFilter').addEventListener('change', function(e) {
        const dateFrom = document.getElementById('dateFrom');
        const dateTo = document.getElementById('dateTo');

        if (e.target.value === 'custom') {
            dateFrom.style.display = 'inline-block';
            dateTo.style.display = 'inline-block';

            // Définir des valeurs par défaut si vides
            if (!dateFrom.value) {
                const today = new Date();
                const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
                dateFrom.value = firstDay.toISOString().split('T')[0];
            }
            if (!dateTo.value) {
                dateTo.value = new Date().toISOString().split('T')[0];
            }
        } else {
            dateFrom.style.display = 'none';
            dateTo.style.display = 'none';
        }
    });
});
