(function() {
    // Données exemples
    var notificationsData = {
        stats: {
            totalEnvois: 1247,
            envoisMois: 245,
            tauxSucces: 98.2,
            smsRestants: 1250,
            enAttente: 12,
            repartition: { sms: 65, whatsapp: 25, email: 10 }
        },
        graphData: {
            labels: ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'],
            values: [145, 168, 189, 203, 176, 220, 198]
        },
        recentNotifications: [
            { id: 1, date: '2024-06-16 10:45', client: 'Jean Paul M.', type: 'Rappel J-1', canal: 'sms', statut: 'delivre' },
            { id: 2, date: '2024-06-16 10:30', client: 'Marie K.', type: 'Confirmation paiement', canal: 'email', statut: 'delivre' },
            { id: 3, date: '2024-06-16 10:15', client: 'Pierre M.', type: 'Rappel J-7', canal: 'sms', statut: 'echoue' },
            { id: 4, date: '2024-06-16 09:58', client: 'Alice B.', type: 'Bienvenue', canal: 'whatsapp', statut: 'delivre' },
            { id: 5, date: '2024-06-16 09:22', client: 'Paul L.', type: 'Rappel J-3', canal: 'sms', statut: 'delivre' }
        ],
        historique: [
            { id: 1, date: '2024-06-16 10:45', client: 'Jean Paul M.', type: 'Rappel J-1', canal: 'sms', message: 'Bonjour Jean, votre abonnement expire demain. Merci de renouveler.', statut: 'delivre', destinataire: '+243 97 97 10 633' },
            { id: 2, date: '2024-06-16 10:30', client: 'Marie K.', type: 'Confirmation paiement', canal: 'email', message: 'Merci pour votre paiement de 45$', statut: 'delivre', destinataire: 'marie@email.com' },
            { id: 3, date: '2024-06-16 10:15', client: 'Pierre M.', type: 'Rappel J-7', canal: 'sms', message: 'Bonjour Pierre, votre abonnement expire dans 7 jours.', statut: 'echoue', destinataire: '+243 81 234 567', erreur: 'Numéro invalide' },
            { id: 4, date: '2024-06-16 09:58', client: 'Alice B.', type: 'Bienvenue', canal: 'whatsapp', message: 'Bienvenue chez SmartClub Pro!', statut: 'delivre', destinataire: '+243 99 876 543' },
            { id: 5, date: '2024-06-16 09:22', client: 'Paul L.', type: 'Rappel J-3', canal: 'sms', message: 'Bonjour Paul, plus que 3 jours avant expiration.', statut: 'delivre', destinataire: '+243 82 345 678' }
        ],
        modeles: [
            { id: 1, nom: 'Rappel expiration J-7', canal: 'sms', type: 'rappel', contenu: 'Bonjour {prenom}, votre abonnement expire dans 7 jours le {date_expiration}. Renouvelez dès maintenant pour continuer à profiter de la salle.' },
            { id: 2, nom: 'Rappel expiration J-3', canal: 'sms', type: 'rappel', contenu: 'Bonjour {prenom}, plus que 3 jours avant l\'expiration de votre abonnement le {date_expiration}. Pensez à renouveler!' },
            { id: 3, nom: 'Rappel expiration J-1', canal: 'sms', type: 'rappel', contenu: 'Bonjour {prenom}, votre abonnement expire DEMAIN! Renouvelez dès aujourd\'hui pour éviter toute interruption.' },
            { id: 4, nom: 'Confirmation paiement', canal: 'sms', type: 'confirmation', contenu: 'Merci {prenom} ! Votre paiement de {montant} a été reçu. Votre abonnement est valable jusqu\'au {date_expiration}.' },
            { id: 5, nom: 'Bienvenue', canal: 'whatsapp', type: 'bienvenue', contenu: 'Bienvenue {prenom} chez SmartClub Pro ! Nous sommes ravis de vous compter parmi nos membres.' }
        ]
    };

    var currentTab = 'dashboard';
    var currentPage = 1;
    var itemsPerPage = 5;
    var filteredHistorique = notificationsData.historique.slice();
    var currentViewId = null;
    var notificationsChart = null;
    var canalChart = null;

    function showTab(tab) {
        currentTab = tab;
        var sectionTab = tab === 'planif' ? 'config' : tab;

        ['dashboard', 'modeles', 'planif', 'historique', 'config'].forEach(function(id) {
            var el = document.getElementById('nav-notifications-' + id);
            if (el) el.classList.toggle('active', id === tab);
        });

        document.getElementById('dashboardSection').style.display = 'none';
        document.getElementById('modelesSection').style.display = 'none';
        document.getElementById('historiqueSection').style.display = 'none';
        document.getElementById('configSection').style.display = 'none';
        document.getElementById(sectionTab + 'Section').style.display = 'block';

        var titles = { dashboard: 'Notifications - Tableau de bord', modeles: 'Notifications - Modèles', planif: 'Notifications - Planification', historique: 'Notifications - Historique', config: 'Notifications - Configuration' };
        var titleEl = document.getElementById('pageTitle');
        if (titleEl) titleEl.textContent = titles[tab] || titles.dashboard;

        var actionBtn = document.getElementById('actionButton');
        var actionBtnText = document.getElementById('actionButtonText');
        if (actionBtn && actionBtnText) {
            if (tab === 'modeles') {
                actionBtn.style.display = 'inline-flex';
                actionBtnText.textContent = 'Nouveau modèle';
            } else {
                actionBtn.style.display = 'none';
            }
        }

        var url = new URL(window.location);
        url.searchParams.set('tab', tab);
        window.history.replaceState({}, '', url);

        if (sectionTab === 'dashboard') renderDashboard();
        else if (sectionTab === 'modeles') renderModeles();
        else if (sectionTab === 'historique') renderHistorique();
    }

    function openAddModal() {
        if (currentTab === 'modeles') openAddTemplateModal();
    }

    function getCanalBadge(canal) {
        var t = canal === 'sms' ? 'SMS' : (canal === 'whatsapp' ? 'WhatsApp' : 'Email');
        var c = canal === 'sms' ? 'bg-primary' : (canal === 'whatsapp' ? 'bg-success' : 'bg-warning text-dark');
        return '<span class="badge ' + c + '">' + t + '</span>';
    }
    function getStatutBadge(statut) {
        var t = statut === 'delivre' ? 'Délivré' : (statut === 'echoue' ? 'Échoué' : 'En attente');
        var c = statut === 'delivre' ? 'bg-success' : (statut === 'echoue' ? 'bg-danger' : 'bg-secondary');
        return '<span class="badge ' + c + '">' + t + '</span>';
    }

    function renderDashboard() {
        document.getElementById('totalEnvois').textContent = notificationsData.stats.totalEnvois.toLocaleString();
        document.getElementById('envoisMois').textContent = '+' + notificationsData.stats.envoisMois;
        document.getElementById('tauxSucces').textContent = notificationsData.stats.tauxSucces + '%';
        document.getElementById('smsRestants').textContent = notificationsData.stats.smsRestants.toLocaleString();
        document.getElementById('enAttente').textContent = notificationsData.stats.enAttente;
        document.getElementById('smsPourcent').textContent = notificationsData.stats.repartition.sms + '%';
        document.getElementById('waPourcent').textContent = notificationsData.stats.repartition.whatsapp + '%';
        document.getElementById('emailPourcent').textContent = notificationsData.stats.repartition.email + '%';

        filterRecentTable();
        initCharts();
    }

    function getFilteredRecent() {
        var searchEl = document.getElementById('searchInputRecent');
        var canalEl = document.getElementById('filterRecentCanal');
        var statutEl = document.getElementById('filterRecentStatut');
        var q = (searchEl && searchEl.value) ? searchEl.value.trim().toLowerCase() : '';
        var canal = (canalEl && canalEl.value) ? canalEl.value : '';
        var statut = (statutEl && statutEl.value) ? statutEl.value : '';
        var list = notificationsData.recentNotifications.filter(function(n) {
            var matchSearch = !q || n.client.toLowerCase().indexOf(q) !== -1 || n.type.toLowerCase().indexOf(q) !== -1;
            var matchCanal = !canal || n.canal === canal;
            var matchStatut = !statut || n.statut === statut;
            return matchSearch && matchCanal && matchStatut;
        });
        return list;
    }

    function filterRecentTable() {
        var tbody = document.getElementById('recentNotificationsBody');
        if (!tbody) return;
        var list = getFilteredRecent();
        var html = '';
        list.forEach(function(n) {
            html += '<tr onclick="window.notifViewMessage(' + n.id + ')" style="cursor:pointer;"><td>' + n.date + '</td><td>' + n.client + '</td><td>' + n.type + '</td><td>' + getCanalBadge(n.canal) + '</td><td>' + getStatutBadge(n.statut) + '</td></tr>';
        });
        tbody.innerHTML = html;
    }

    function initCharts() {
        var ctx = document.getElementById('notificationsChart');
        if (!ctx) return;
        ctx = ctx.getContext('2d');
        if (notificationsChart) notificationsChart.destroy();
        notificationsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: notificationsData.graphData.labels,
                datasets: [{ label: 'Notifications envoyées', data: notificationsData.graphData.values, borderColor: '#3454d1', backgroundColor: 'rgba(52, 84, 209, 0.1)', tension: 0.3, fill: true, pointBackgroundColor: '#3454d1' }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
        });

        var ctx2 = document.getElementById('canalChart');
        if (!ctx2) return;
        ctx2 = ctx2.getContext('2d');
        if (canalChart) canalChart.destroy();
        canalChart = new Chart(ctx2, {
            type: 'doughnut',
            data: {
                labels: ['SMS', 'WhatsApp', 'Email'],
                datasets: [{ data: [65, 25, 10], backgroundColor: ['#1565c0', '#2e7d32', '#ef6c00'], borderWidth: 0 }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
        });
    }

    function updateGraph() {
        if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'success', title: 'Graphique mis à jour', text: 'Période modifiée avec succès', timer: 1500, showConfirmButton: false });
        }
    }

    function renderModeles() {
        var container = document.getElementById('modelesList');
        if (!container) return;
        var html = '';
        notificationsData.modeles.forEach(function(m) {
            var typeText = m.type === 'rappel' ? 'Rappel expiration' : (m.type === 'confirmation' ? 'Confirmation paiement' : (m.type === 'bienvenue' ? 'Bienvenue' : (m.type === 'suspension' ? 'Suspension' : 'Personnalisé')));
            html += '<div class="col-xxl-4 col-md-6 mb-3"><div class="card border h-100 cursor-pointer" onclick="window.notifEditTemplate(' + m.id + ')"><div class="card-body"><div class="d-flex justify-content-between align-items-start"><h6 class="mb-1">' + m.nom + '</h6>' + getCanalBadge(m.canal) + '</div><small class="text-muted">' + typeText + '</small><div class="border rounded p-2 mt-2 small bg-light">' + m.contenu.substring(0, 80) + '...</div><div class="mt-2 text-end"><span class="badge bg-light text-dark">' + m.contenu.length + ' caractères</span></div></div></div></div>';
        });
        container.innerHTML = html;
    }

    function openAddTemplateModal() {
        document.getElementById('addTemplateForm').reset();
        document.getElementById('templatePreview').textContent = 'Aperçu du message...';
        var modalEl = document.getElementById('addTemplateModal');
        if (window.bootstrap && modalEl) new bootstrap.Modal(modalEl).show();
    }

    function insertVariable(variable) {
        var textarea = document.getElementById('templateContenu');
        if (!textarea) return;
        var start = textarea.selectionStart, end = textarea.selectionEnd;
        textarea.value = textarea.value.substring(0, start) + variable + textarea.value.substring(end);
        updatePreview();
    }

    function updatePreview() {
        var contenu = document.getElementById('templateContenu');
        var preview = document.getElementById('templatePreview');
        if (!contenu || !preview) return;
        var apercu = contenu.value.replace(/\{prenom\}/g, 'Jean').replace(/\{nom\}/g, 'Paul').replace(/\{date_expiration\}/g, '30/06/2024').replace(/\{montant\}/g, '45$').replace(/\{code_membre\}/g, 'MB-001').replace(/\{nom_salle\}/g, 'SmartClub Pro');
        preview.textContent = apercu || 'Aperçu du message...';
    }

    function saveTemplate() {
        var nom = document.getElementById('templateNom').value;
        var canal = document.getElementById('templateCanal').value;
        var type = document.getElementById('templateType').value;
        var contenu = document.getElementById('templateContenu').value;
        if (!nom || !contenu) {
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'warning', title: 'Champs requis', text: 'Veuillez remplir le nom et le contenu.' });
            else alert('Veuillez remplir tous les champs obligatoires');
            return;
        }
        notificationsData.modeles.push({ id: notificationsData.modeles.length + 1, nom: nom, canal: canal, type: type, contenu: contenu });
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Modèle enregistré', text: 'Le modèle a été créé avec succès', timer: 2000, showConfirmButton: false });
        var modalEl = document.getElementById('addTemplateModal');
        if (window.bootstrap && modalEl) { var m = bootstrap.Modal.getInstance(modalEl); if (m) m.hide(); }
        renderModeles();
    }

    function editTemplate(id) {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'info', title: 'Édition de modèle', text: 'Fonctionnalité d\'édition du modèle #' + id + ' (simulation)', confirmButtonColor: '#3454d1' });
    }

    function renderHistorique() {
        var searchEl = document.getElementById('searchInput');
        var dateFromEl = document.getElementById('filterNotifDateFrom');
        var dateToEl = document.getElementById('filterNotifDateTo');
        var canalEl = document.getElementById('filterNotifCanal');
        var statutEl = document.getElementById('filterNotifStatut');
        var search = (searchEl && searchEl.value) ? searchEl.value.trim().toLowerCase() : '';
        var dateFrom = (dateFromEl && dateFromEl.value) ? dateFromEl.value : '';
        var dateTo = (dateToEl && dateToEl.value) ? dateToEl.value : '';
        var canal = (canalEl && canalEl.value) ? canalEl.value : '';
        var statut = (statutEl && statutEl.value) ? statutEl.value : '';

        var filtered = notificationsData.historique.slice();
        if (search) {
            filtered = filtered.filter(function(h) {
                return (h.client && h.client.toLowerCase().indexOf(search) !== -1) ||
                    (h.message && h.message.toLowerCase().indexOf(search) !== -1) ||
                    (h.destinataire && h.destinataire.toLowerCase().indexOf(search) !== -1);
            });
        }
        if (dateFrom) {
            filtered = filtered.filter(function(h) {
                var d = (h.date || '').substring(0, 10);
                return d >= dateFrom;
            });
        }
        if (dateTo) {
            filtered = filtered.filter(function(h) {
                var d = (h.date || '').substring(0, 10);
                return d <= dateTo;
            });
        }
        if (canal) filtered = filtered.filter(function(h) { return h.canal === canal; });
        if (statut) filtered = filtered.filter(function(h) { return h.statut === statut; });

        filteredHistorique = filtered;

        var tbody = document.getElementById('historiqueTableBody');
        var infoEl = document.getElementById('historiqueInfo');
        if (!tbody) return;
        var start = (currentPage - 1) * itemsPerPage;
        var end = start + itemsPerPage;
        var pageItems = filteredHistorique.slice(start, end);
        var html = '';
        if (pageItems.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center p-4">Aucun envoi trouvé</td></tr>';
        } else {
            pageItems.forEach(function(h) {
                html += '<tr><td>' + h.date + '</td><td>' + h.client + '</td><td>' + h.type + '</td><td>' + getCanalBadge(h.canal) + '</td><td>' + h.message.substring(0, 30) + '...</td><td>' + getStatutBadge(h.statut) + '</td><td class="text-end"><button type="button" class="btn btn-sm btn-light-brand" onclick="window.notifViewMessage(' + h.id + ')" title="Voir"><span class="material-icons" style="font-size:18px;">visibility</span></button></td></tr>';
            });
            tbody.innerHTML = html;
        }
        var total = filteredHistorique.length;
        var totalPages = Math.ceil(total / itemsPerPage) || 0;
        if (infoEl) infoEl.textContent = total > 0 ? 'Affichage ' + (start + 1) + '-' + Math.min(end, total) + ' sur ' + total + ' envois' : 'Aucun envoi';
        renderPagination(totalPages);
    }

    function renderPagination(totalPages) {
        var pagination = document.getElementById('historiquePagination');
        if (!pagination) return;
        var html = '';
        if (totalPages > 0) {
            html += '<li class="page-item ' + (currentPage === 1 ? 'disabled' : '') + '"><a class="page-link" href="javascript:void(0);" onclick="window.notifChangePage(' + (currentPage - 1) + ')"><span class="material-icons" style="font-size:18px;">chevron_left</span></a></li>';
            for (var i = 1; i <= totalPages; i++) {
                if (i === 1 || i === totalPages || (i >= currentPage - 1 && i <= currentPage + 1)) {
                    html += '<li class="page-item ' + (i === currentPage ? 'active' : '') + '"><a class="page-link" href="javascript:void(0);" onclick="window.notifChangePage(' + i + ')">' + i + '</a></li>';
                } else if (i === currentPage - 2 || i === currentPage + 2) html += '<li class="page-item disabled"><a class="page-link">...</a></li>';
            }
            html += '<li class="page-item ' + (currentPage === totalPages ? 'disabled' : '') + '"><a class="page-link" href="javascript:void(0);" onclick="window.notifChangePage(' + (currentPage + 1) + ')"><span class="material-icons" style="font-size:18px;">chevron_right</span></a></li>';
        }
        pagination.innerHTML = html;
    }

    function changePage(page) {
        var totalPages = Math.ceil(filteredHistorique.length / itemsPerPage);
        if (page >= 1 && page <= totalPages) { currentPage = page; renderHistorique(); }
    }

    function viewMessage(id) {
        currentViewId = id;
        var message = notificationsData.historique.find(function(h) { return h.id === id; });
        if (!message) return;
        document.getElementById('viewMessageClient').textContent = message.client;
        document.getElementById('viewMessageDate').textContent = message.date;
        document.getElementById('viewMessageType').textContent = message.type;
        document.getElementById('viewMessageCanal').textContent = message.canal === 'sms' ? 'SMS' : (message.canal === 'whatsapp' ? 'WhatsApp' : 'Email');
        document.getElementById('viewMessageStatut').innerHTML = getStatutBadge(message.statut);
        document.getElementById('viewMessageDest').textContent = message.destinataire || '';
        document.getElementById('viewMessagePar').textContent = 'Admin';
        document.getElementById('viewMessageContenu').textContent = message.message;
        var errEl = document.getElementById('viewMessageErreur');
        var reessayer = document.getElementById('viewMessageReessayer');
        if (message.statut === 'echoue' && message.erreur) {
            errEl.classList.remove('d-none');
            document.getElementById('viewMessageErreurTexte').textContent = message.erreur;
            if (reessayer) reessayer.style.display = 'inline-block';
        } else {
            errEl.classList.add('d-none');
            if (reessayer) reessayer.style.display = 'none';
        }
        var modalEl = document.getElementById('viewMessageModal');
        if (window.bootstrap && modalEl) new bootstrap.Modal(modalEl).show();
    }

    function retryMessage() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Réessai en cours', text: 'Le message a été remis dans la file d\'attente', timer: 2000, showConfirmButton: false });
        var modalEl = document.getElementById('viewMessageModal');
        if (window.bootstrap && modalEl) { var m = bootstrap.Modal.getInstance(modalEl); if (m) m.hide(); }
    }

    function testConnexion(type) {
        var service = type === 'sms' ? 'SMS' : (type === 'wa' ? 'WhatsApp' : 'Email');
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Connexion réussie', text: 'API ' + service + ' configurée correctement', timer: 2000, showConfirmButton: false });
    }

    function saveConfig() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Configuration enregistrée', text: 'Les paramètres de notification ont été mis à jour', timer: 2000, showConfirmButton: false });
    }

    function applyFiltersHistorique() {
        currentPage = 1;
        renderHistorique();
    }

    // Exposer pour onclick
    window.notifViewMessage = viewMessage;
    window.notifEditTemplate = editTemplate;
    window.notifOpenAddModal = openAddModal;
    window.notifApplyFiltersHistorique = applyFiltersHistorique;
    window.notifChangePage = changePage;

    document.getElementById('templateContenu') && document.getElementById('templateContenu').addEventListener('keyup', updatePreview);

    document.addEventListener('DOMContentLoaded', function() {
        if (document.querySelector('.b-brand .logo-sm')) document.querySelector('.b-brand .logo-sm').style.display = 'none';
        var urlParams = new URLSearchParams(window.location.search);
        var tabParam = urlParams.get('tab');
        var validTabs = ['dashboard', 'modeles', 'planif', 'historique', 'config'];
        var initialTab = validTabs.indexOf(tabParam) !== -1 ? tabParam : 'dashboard';
        showTab(initialTab);

        ['dashboard', 'modeles', 'planif', 'historique', 'config'].forEach(function(t) {
            var el = document.getElementById('nav-notifications-' + t);
            if (el) {
                var a = el.querySelector('a');
                if (a) a.addEventListener('click', function(e) {
                    if (window.location.pathname.indexOf('notification') !== -1) { e.preventDefault(); showTab(t); }
                });
            }
        });
    });
})();