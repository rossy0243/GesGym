(function() {
    const config = { exchangeRate: 2850, currencies: ['USD', 'CDF'] };
    var avatarUrl = (typeof window.STATIC_AVATAR_URL !== 'undefined') ? window.STATIC_AVATAR_URL : '/static/avatar/1.png';
    let clients = [
        { id: 1, nom: "Jean Dupont", email: "jean.dupont@email.com", phone: "+243812345678", code_membre: "MB-001", photo: avatarUrl, statut: "actif" },
        { id: 2, nom: "Marie Kabeya", email: "marie.k@email.com", phone: "+243822345679", code_membre: "MB-002", photo: avatarUrl, statut: "actif" },
        { id: 3, nom: "Pierre Kasongo", email: "pierre.k@email.com", phone: "+243832345680", code_membre: "MB-003", photo: avatarUrl, statut: "expire" },
        { id: 4, nom: "Sophie Lukusa", email: "sophie.l@email.com", phone: "+243842345681", code_membre: "MB-004", photo: avatarUrl, statut: "suspendu" },
        { id: 5, nom: "Paul Mbuyi", email: "paul.m@email.com", phone: "+243852345682", code_membre: "MB-005", photo: avatarUrl, statut: "actif" }
    ];
    let abonnements = [
        { id: 1, client_id: 1, formule: "12 mois", montant: 500000, devise: "CDF", date_expiration: "2025-06-15", num_abonnement: "AB-2024-001" },
        { id: 3, client_id: 2, formule: "6 mois", montant: 300000, devise: "CDF", date_expiration: "2025-02-28", num_abonnement: "AB-2024-002" },
        { id: 5, client_id: 3, formule: "3 mois", montant: 150000, devise: "CDF", date_expiration: "2024-09-15", num_abonnement: "AB-2024-003" },
        { id: 6, client_id: 4, formule: "1 mois", montant: 45000, devise: "CDF", date_expiration: "2024-08-01", num_abonnement: "AB-2024-004" },
        { id: 7, client_id: 5, formule: "1 mois", montant: 45, devise: "USD", date_expiration: "2025-03-20", num_abonnement: "AB-2024-005" }
    ];
    const promotions = [ { code: "FETE25", reduction: 25 }, { code: "WELCOME", reduction: 15 } ];
    let caisses = [
        { id: 1, site: "Salle Centre", devise: "USD", solde: 1250.00 },
        { id: 2, site: "Salle Centre", devise: "CDF", solde: 3250000.00 },
        { id: 3, site: "Salle Nord", devise: "USD", solde: 850.00 },
        { id: 4, site: "Salle Nord", devise: "CDF", solde: 1850000.00 },
        { id: 5, site: "Salle Ouest", devise: "USD", solde: 650.00 },
        { id: 6, site: "Salle Ouest", devise: "CDF", solde: 1420000.00 }
    ];
    let cashPayments = [
        { id: 1, date: "2024-06-16 09:15", client: "Jean Dupont", abonnement: "12 mois", montant: 500000, devise: "CDF", mode: "Espèces", statut: "success", reçu: "REC-001" },
        { id: 2, date: "2024-06-16 10:30", client: "Marie Kabeya", abonnement: "6 mois", montant: 175, devise: "USD", mode: "Carte", statut: "success", reçu: "REC-002" },
        { id: 3, date: "2024-06-15 14:20", client: "Pierre Kasongo", abonnement: "1 mois", montant: 85, devise: "USD", mode: "Espèces", statut: "success", reçu: "REC-003" }
    ];
    let onlineTransactions = [
        { id: 1, date: "2024-06-16 14:35", client: "Jean Dupont", abonnement: "12 mois", montant: 500000, devise: "CDF", mode: "M-Pesa", statut: "success", callback: "CB-156", signature: "3a8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d" },
        { id: 2, date: "2024-06-16 11:22", client: "Pierre Kasongo", abonnement: "1 mois", montant: 85, devise: "USD", mode: "Carte", statut: "pending", callback: "CB-155", signature: "2b7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d" },
        { id: 3, date: "2024-06-15 09:45", client: "Marie Kabeya", abonnement: "6 mois", montant: 300000, devise: "CDF", mode: "Orange Money", statut: "success", callback: "CB-154", signature: "1a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d" }
    ];
    let webhooks = [
        { id: 1, date: "2024-06-16 14:35:22", transaction: "CB-156", statut: "success", message: "Paiement confirmé - Signature HMAC validée", montant: 500000 },
        { id: 2, date: "2024-06-16 11:22:30", transaction: "CB-155", statut: "pending", message: "En attente de confirmation opérateur", montant: 85 },
        { id: 3, date: "2024-06-15 09:45:10", transaction: "CB-154", statut: "success", message: "Paiement confirmé - Idempotence OK", montant: 300000 }
    ];
    let journal = [
        { id: 1, date: "2024-06-16 14:35:22", trans_id: "TR-2024-156", client: "Jean Dupont", type: "Paiement en ligne", montant: 500000, devise: "CDF", statut: "success", mode: "M-Pesa", reference: "CB-156" },
        { id: 2, date: "2024-06-16 10:30:15", trans_id: "TR-2024-157", client: "Marie Kabeya", type: "Caisse physique", montant: 175, devise: "USD", statut: "success", mode: "Carte", reference: "REC-002" },
        { id: 3, date: "2024-06-16 09:15:05", trans_id: "TR-2024-158", client: "Jean Dupont", type: "Caisse physique", montant: 500000, devise: "CDF", statut: "success", mode: "Espèces", reference: "REC-001" },
        { id: 4, date: "2024-06-15 14:20:30", trans_id: "TR-2024-159", client: "Pierre Kasongo", type: "Caisse physique", montant: 85, devise: "USD", statut: "success", mode: "Espèces", reference: "REC-003" },
        { id: 5, date: "2024-06-15 09:45:10", trans_id: "TR-2024-160", client: "Marie Kabeya", type: "Paiement en ligne", montant: 300000, devise: "CDF", statut: "success", mode: "Orange Money", reference: "CB-154" }
    ];

    let currentTab = 'caisse';
    let currentStep = 1;
    let selectedClient = null;
    let selectedAbonnement = null;
    let selectedPaymentMethod = null;
    let paymentAmountUSD = 0;
    let paymentAmountCDF = 0;
    let promoReduction = 0;

    function showTab(tab) {
        currentTab = tab;
        ['caisse', 'online', 'journal'].forEach(function(id) {
            var el = document.getElementById('nav-paiements-' + id);
            if (el) el.classList.toggle('active', id === tab);
        });
        document.getElementById('caisseSection').style.display = tab === 'caisse' ? 'block' : 'none';
        document.getElementById('onlineSection').style.display = tab === 'online' ? 'block' : 'none';
        document.getElementById('journalSection').style.display = tab === 'journal' ? 'block' : 'none';
        var url = new URL(window.location);
        url.searchParams.set('tab', tab === 'online' ? 'enligne' : tab);
        window.history.replaceState({}, '', url);
        if (tab === 'caisse') { renderCaisses(); renderCashPayments(); }
        else if (tab === 'online') { renderOnlineStats(); renderWebhooks(); renderOnlinePayments(); }
        else if (tab === 'journal') { renderJournal(); }
    }

    function renderCaisses() {
        const container = document.getElementById('caissesList');
        if (!container) return;
        let html = '';
        caisses.forEach(function(c) {
            html += '<div class="col-md-4 mb-3"><div class="card h-100"><div class="card-header"><h6 class="mb-0">' + c.site + ' - ' + c.devise + '</h6></div><div class="card-body"><div class="fs-4 fw-bold">' + (c.devise === 'USD' ? c.solde.toFixed(2) : c.solde.toLocaleString()) + ' ' + c.devise + '</div><button class="btn btn-sm btn-primary mt-2" onclick="openPaymentModal()"><span class="material-icons me-1" style="font-size: 18px;">add</span>Paiement rapide</button></div></div></div>';
        });
        container.innerHTML = html;
        updateCashStats();
    }

    function updateCashStats() {
        var totalUSD = caisses.filter(function(c) { return c.devise === 'USD'; }).reduce(function(s, c) { return s + c.solde; }, 0);
        var totalCDF = caisses.filter(function(c) { return c.devise === 'CDF'; }).reduce(function(s, c) { return s + c.solde; }, 0);
        var elUSD = document.getElementById('totalUSD');
        var elCDF = document.getElementById('totalCDF');
        if (elUSD) elUSD.textContent = totalUSD.toFixed(2) + ' $';
        if (elCDF) elCDF.textContent = totalCDF.toLocaleString() + ' CDF';
        var today = new Date().toISOString().split('T')[0];
        var todayEntries = cashPayments.filter(function(p) { return p.date.startsWith(today); }).reduce(function(s, p) { return s + (p.devise === 'USD' ? p.montant * config.exchangeRate : p.montant); }, 0);
        var elEnt = document.getElementById('todayEntries');
        if (elEnt) elEnt.textContent = todayEntries.toLocaleString() + ' CDF';
    }

    function renderCashPayments() {
        var elSearch = document.getElementById('filterCaisseSearch');
        var elStatut = document.getElementById('filterCaisseStatut');
        var elMode = document.getElementById('filterCaisseMode');
        var search = (elSearch && elSearch.value ? elSearch.value : '').toLowerCase();
        var statut = elStatut ? elStatut.value : '';
        var mode = elMode ? elMode.value : '';
        var filtered = cashPayments.filter(function(p) {
            var matchSearch = !search || (p.client && p.client.toLowerCase().includes(search)) || (p.abonnement && p.abonnement.toLowerCase().includes(search)) || (String(p.montant).includes(search));
            var matchStatut = !statut || p.statut === statut;
            var matchMode = !mode || p.mode === mode;
            return matchSearch && matchStatut && matchMode;
        });
        var tbody = document.getElementById('cashPaymentsBody');
        if (!tbody) return;
        var html = '';
        filtered.forEach(function(p) {
            var badge = p.statut === 'success' ? 'badge-success' : 'badge-warning';
            html += '<tr><td>' + p.date + '</td><td>' + p.client + '</td><td>' + p.abonnement + '</td><td>' + (p.devise === 'USD' ? p.montant.toFixed(2) + ' USD' : p.montant.toLocaleString() + ' CDF') + '</td><td>' + p.mode + '</td><td><span class="' + badge + '">' + p.statut + '</span></td><td class="text-end"><button class="btn btn-sm btn-light-brand" onclick="viewTransaction(' + p.id + ', \'cash\')" title="Voir"><span class="material-icons" style="font-size: 18px;">visibility</span></button> <button class="btn btn-sm btn-light-brand" onclick="printReceipt(\'' + p.reçu + '\')" title="Imprimer"><span class="material-icons" style="font-size: 18px;">print</span></button></td></tr>';
        });
        tbody.innerHTML = html;
    }

    function renderOnlineStats() {
        var success = onlineTransactions.filter(function(t) { return t.statut === 'success'; }).length;
        var pending = onlineTransactions.filter(function(t) { return t.statut === 'pending'; }).length;
        var failed = onlineTransactions.filter(function(t) { return t.statut === 'failed'; }).length;
        var total = onlineTransactions.length;
        var rate = total > 0 ? Math.round((success / total) * 100) : 0;
        var el;
        if (el = document.getElementById('successCount')) el.textContent = success;
        if (el = document.getElementById('pendingCount')) el.textContent = pending;
        if (el = document.getElementById('failedCount')) el.textContent = failed;
        if (el = document.getElementById('successRate')) el.textContent = rate + '%';
    }

    function renderWebhooks() {
        var container = document.getElementById('webhooksList');
        if (!container) return;
        var html = '';
        webhooks.forEach(function(w) {
            var badgeClass = w.statut === 'success' ? 'badge-success' : w.statut === 'pending' ? 'badge-warning' : 'badge-danger';
            html += '<div class="d-flex justify-content-between align-items-start border-bottom pb-2 mb-2"><div><span class="material-icons me-2" style="font-size: 18px;">call_made</span><strong>Callback #' + w.transaction + '</strong><br><small class="text-muted">' + w.date + ' - ' + w.message + ' - ' + w.montant.toLocaleString() + ' CDF</small></div><span class="' + badgeClass + '">' + w.statut + '</span></div>';
        });
        container.innerHTML = html;
    }

    function renderOnlinePayments() {
        var elSearch = document.getElementById('filterOnlineSearch');
        var elStatut = document.getElementById('filterOnlineStatut');
        var search = (elSearch && elSearch.value ? elSearch.value : '').toLowerCase();
        var statut = elStatut ? elStatut.value : '';
        var filtered = onlineTransactions.filter(function(t) {
            var matchSearch = !search || (t.client && t.client.toLowerCase().includes(search)) || (t.callback && t.callback.toLowerCase().includes(search));
            return matchSearch && (!statut || t.statut === statut);
        });
        var tbody = document.getElementById('onlinePaymentsBody');
        if (!tbody) return;
        var html = '';
        filtered.forEach(function(t) {
            var badgeClass = t.statut === 'success' ? 'badge-success' : t.statut === 'pending' ? 'badge-warning' : 'badge-danger';
            html += '<tr><td>' + t.date + '</td><td>' + t.client + '</td><td>' + t.abonnement + '</td><td>' + (t.devise === 'USD' ? t.montant.toFixed(2) + ' USD' : t.montant.toLocaleString() + ' CDF') + '</td><td>' + t.mode + '</td><td><span class="' + badgeClass + '">' + t.statut + '</span></td><td><span class="badge bg-secondary">' + t.callback + '</span></td><td class="text-end"><button class="btn btn-sm btn-light-brand" onclick="viewTransaction(' + t.id + ', \'online\')" title="Voir"><span class="material-icons" style="font-size: 18px;">visibility</span></button>' + (t.statut === 'pending' ? ' <button class="btn btn-sm btn-warning" onclick="retryCallback()" title="Réessayer"><span class="material-icons" style="font-size: 18px;">refresh</span></button>' : '') + '</td></tr>';
        });
        tbody.innerHTML = html;
    }

    function renderJournal() {
        var elSearch = document.getElementById('filterJournalSearch');
        var elType = document.getElementById('filterJournalType');
        var elStatut = document.getElementById('filterJournalStatut');
        var search = (elSearch && elSearch.value ? elSearch.value : '').toLowerCase();
        var type = elType ? elType.value : '';
        var statut = elStatut ? elStatut.value : '';
        var filtered = journal.filter(function(j) {
            var matchSearch = !search || (j.client && j.client.toLowerCase().includes(search)) || (j.reference && j.reference.toLowerCase().includes(search)) || (j.trans_id && j.trans_id.toLowerCase().includes(search));
            return matchSearch && (!type || j.type === type) && (!statut || j.statut === statut);
        });
        var tbody = document.getElementById('journalBody');
        if (!tbody) return;
        var html = '';
        filtered.forEach(function(j) {
            var badgeClass = j.statut === 'success' ? 'badge-success' : 'badge-warning';
            html += '<tr><td>' + j.date + '</td><td><strong>' + j.trans_id + '</strong></td><td>' + j.client + '</td><td>' + j.type + '</td><td>' + (j.devise === 'USD' ? j.montant.toFixed(2) + ' USD' : j.montant.toLocaleString() + ' CDF') + '</td><td><span class="' + badgeClass + '">' + j.statut + '</span></td><td>' + j.mode + '</td><td><span class="badge bg-secondary">' + j.reference + '</span></td><td class="text-end"><button class="btn btn-sm btn-light-brand" onclick="viewJournalEntry(' + j.id + ')" title="Voir"><span class="material-icons" style="font-size: 18px;">visibility</span></button></td></tr>';
        });
        tbody.innerHTML = html;
    }

    function exportJournal() {
        if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'success', title: 'Export réussi', text: 'Le journal a été exporté au format Excel', timer: 2000 });
        }
    }

    function openPaymentModal() {
        currentStep = 1;
        selectedClient = null;
        selectedAbonnement = null;
        selectedPaymentMethod = null;
        paymentAmountUSD = 0;
        paymentAmountCDF = 0;
        promoReduction = 0;
        var ids = ['clientSearch', 'searchResults', 'clientCard', 'formuleSection', 'paymentMethodSection', 'confirmationSection', 'receiptSection', 'cashDetails'];
        var el;
        if (el = document.getElementById('clientSearch')) el.value = '';
        if (el = document.getElementById('searchResults')) el.style.display = 'none';
        if (el = document.getElementById('clientCard')) el.style.display = 'none';
        if (el = document.getElementById('formuleSection')) el.style.display = 'none';
        if (el = document.getElementById('paymentMethodSection')) el.style.display = 'none';
        if (el = document.getElementById('confirmationSection')) el.style.display = 'none';
        if (el = document.getElementById('receiptSection')) el.style.display = 'none';
        if (el = document.getElementById('cashDetails')) el.style.display = 'none';
        if (el = document.getElementById('formuleSelect')) el.value = '';
        if (el = document.getElementById('promoCodeInput')) el.value = '';
        if (el = document.getElementById('montantRecu')) el.value = '';
        if (el = document.getElementById('monnaieRendre')) el.value = '';
        if (el = document.getElementById('nextBtn')) el.style.display = 'inline-block';
        if (el = document.getElementById('payBtn')) el.style.display = 'none';
        document.querySelectorAll('.payment-method-card').forEach(function(c) { c.classList.remove('selected', 'border-primary'); });
        var modalEl = document.getElementById('paymentModal');
        if (modalEl && typeof bootstrap !== 'undefined') new bootstrap.Modal(modalEl).show();
    }

    function searchClient() {
        var q = (document.getElementById('clientSearch').value || '').trim().toLowerCase();
        var results = document.getElementById('searchResults');
        if (q.length < 2) { results.style.display = 'none'; return; }
        var found = clients.filter(function(c) {
            return c.nom.toLowerCase().includes(q) || (c.phone && c.phone.includes(q)) || (c.code_membre && c.code_membre.toLowerCase().includes(q)) || abonnements.some(function(a) { return a.client_id === c.id && a.num_abonnement && a.num_abonnement.toLowerCase().includes(q); });
        });
        if (found.length === 0) results.innerHTML = '<div class="p-3 text-muted small">Aucun client trouvé</div>';
        else results.innerHTML = found.map(function(c) {
            var abo = abonnements.find(function(a) { return a.client_id === c.id; });
            return '<div class="p-2 border-bottom client-result-item" style="cursor: pointer;" onclick="chooseClient(' + c.id + ')"><strong>' + c.nom + '</strong> - ' + (c.phone || '-') + ' | ' + (c.code_membre || '-') + (abo ? '<br><small class="text-muted">Abonnement: ' + abo.formule + ' (exp. ' + abo.date_expiration + ')</small>' : '') + '</div>';
        }).join('');
        results.style.display = 'block';
    }

    function chooseClient(clientId) {
        selectedClient = clients.find(function(c) { return c.id === clientId; });
        selectedAbonnement = abonnements.find(function(a) { return a.client_id === clientId; });
        document.getElementById('clientSearch').value = selectedClient.nom;
        document.getElementById('searchResults').style.display = 'none';
        document.getElementById('clientName').textContent = selectedClient.nom;
        document.getElementById('clientCode').textContent = selectedClient.code_membre || '-';
        var statusMap = { actif: 'Actif', expire: 'Expiré', suspendu: 'Suspendu' };
        var statusClass = selectedClient.statut === 'actif' ? 'bg-success' : selectedClient.statut === 'expire' ? 'bg-danger' : 'bg-warning';
        var statusEl = document.getElementById('clientStatus');
        statusEl.className = 'badge ' + statusClass;
        statusEl.textContent = statusMap[selectedClient.statut] || 'Actif';
        if (selectedClient.photo) document.getElementById('clientPhoto').src = selectedClient.photo;
        document.getElementById('clientCurrentAbonnement').textContent = selectedAbonnement ? selectedAbonnement.formule : 'Aucun';
        document.getElementById('clientExpiry').textContent = selectedAbonnement ? selectedAbonnement.date_expiration : '-';
        document.getElementById('clientCard').style.display = 'block';
        document.getElementById('formuleSection').style.display = 'block';
    }

    function resetClientSelection() {
        selectedClient = null;
        selectedAbonnement = null;
        document.getElementById('clientSearch').value = '';
        document.getElementById('clientCard').style.display = 'none';
        document.getElementById('formuleSection').style.display = 'none';
        document.getElementById('paymentMethodSection').style.display = 'none';
        document.getElementById('confirmationSection').style.display = 'none';
    }

    function updateCustomAmount() {
        var usd = parseFloat(document.getElementById('customAmountUSD').value) || 0;
        var cdf = parseFloat(document.getElementById('customAmountCDF').value) || 0;
        if (usd > 0 && cdf > 0) { paymentAmountUSD = usd; paymentAmountCDF = cdf; }
        else if (usd > 0) { paymentAmountUSD = usd; paymentAmountCDF = usd * config.exchangeRate; }
        else if (cdf > 0) { paymentAmountUSD = cdf / config.exchangeRate; paymentAmountCDF = cdf; }
        else { paymentAmountUSD = 0; paymentAmountCDF = 0; }
        document.getElementById('displayAmount').textContent = paymentAmountUSD.toFixed(2) + ' USD / ' + Math.round(paymentAmountCDF).toLocaleString() + ' CDF';
    }

    function updateAmount() {
        var sel = document.getElementById('formuleSelect');
        var opt = sel.options[sel.selectedIndex];
        var promoCode = (document.getElementById('promoCodeInput').value || '').trim().toUpperCase();
        document.getElementById('customAmountWrap').style.display = (opt && opt.value === 'personnalise') ? 'block' : 'none';
        if (opt && opt.value === 'personnalise') { updateCustomAmount(); return; }
        if (!opt || !opt.value) {
            document.getElementById('displayAmount').textContent = '-';
            document.getElementById('promoApplied').style.display = 'none';
            return;
        }
        var prixUSD = parseFloat(opt.dataset.prixUsd) || 0;
        var prixCDF = parseFloat(opt.dataset.prixCdf) || 0;
        promoReduction = 0;
        var promo = promotions.find(function(p) { return p.code === promoCode; });
        if (promo) promoReduction = promo.reduction;
        paymentAmountUSD = prixUSD * (1 - promoReduction / 100);
        paymentAmountCDF = prixCDF * (1 - promoReduction / 100);
        document.getElementById('displayAmount').textContent = paymentAmountUSD.toFixed(2) + ' USD / ' + Math.round(paymentAmountCDF).toLocaleString() + ' CDF';
        document.getElementById('promoApplied').style.display = promo ? 'inline' : 'none';
    }

    function selectPaymentMethod(method) {
        if (!selectedClient) return;
        selectedPaymentMethod = method;
        document.querySelectorAll('.payment-method-card').forEach(function(el) { el.classList.remove('selected', 'border-primary'); });
        var card = document.querySelector('[data-method="' + method + '"]');
        if (card) card.classList.add('selected', 'border-primary');
        document.getElementById('cashDetails').style.display = (method === 'cash_usd' || method === 'cash_cdf') ? 'block' : 'none';
        document.getElementById('confirmClient').textContent = selectedClient.nom;
        document.getElementById('confirmAbonnement').textContent = document.getElementById('formuleSelect').options[document.getElementById('formuleSelect').selectedIndex].text;
        var devise = method === 'cash_usd' ? 'USD' : 'CDF';
        document.getElementById('confirmMontant').textContent = devise === 'USD' ? paymentAmountUSD.toFixed(2) + ' USD' : Math.round(paymentAmountCDF).toLocaleString() + ' CDF';
        document.getElementById('confirmMode').textContent = { cash_usd: 'Espèces USD', cash_cdf: 'Espèces CDF', card: 'Carte bancaire' }[method];
        document.getElementById('confirmationSection').style.display = 'block';
        document.getElementById('receiptSection').style.display = 'block';
        document.getElementById('nextBtn').style.display = 'none';
        document.getElementById('payBtn').style.display = 'inline-block';
    }

    function calculMonnaie() {
        var recu = parseFloat(document.getElementById('montantRecu').value) || 0;
        var montant = selectedPaymentMethod === 'cash_usd' ? paymentAmountUSD : paymentAmountCDF;
        document.getElementById('monnaieRendre').value = selectedPaymentMethod === 'cash_usd' ? (Math.max(0, recu - montant)).toFixed(2) : Math.max(0, recu - montant).toLocaleString();
    }

    function nextStepPayment() {
        if (currentStep === 1 && selectedClient) {
            if (!document.getElementById('formuleSelect').value) {
                if (typeof Swal !== 'undefined') Swal.fire({ icon: 'warning', title: 'Formule requise', text: 'Veuillez choisir une formule.' });
                return;
            }
            updateAmount();
            if (paymentAmountUSD <= 0 && paymentAmountCDF <= 0) {
                if (typeof Swal !== 'undefined') Swal.fire({ icon: 'warning', title: 'Montant invalide', text: 'Veuillez choisir une formule valide.' });
                return;
            }
            document.getElementById('paymentMethodSection').style.display = 'block';
        }
    }

    function processPayment() {
        if (!selectedClient) {
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'warning', title: 'Client requis', text: 'Veuillez sélectionner un client.' });
            return;
        }
        if (selectedPaymentMethod === 'cash_usd' || selectedPaymentMethod === 'cash_cdf') {
            var recu = parseFloat(document.getElementById('montantRecu').value) || 0;
            var montant = selectedPaymentMethod === 'cash_usd' ? paymentAmountUSD : paymentAmountCDF;
            if (recu < montant) {
                if (typeof Swal !== 'undefined') Swal.fire({ icon: 'warning', title: 'Montant insuffisant', text: 'Le montant reçu doit être au moins égal au montant à payer.' });
                return;
            }
        }
        var printReceipt = document.getElementById('printReceipt').checked;
        var emailReceipt = document.getElementById('emailReceipt').checked;
        var msg = '<p>Transaction #TR-' + Date.now().toString().slice(-8) + '</p><p>Client: ' + selectedClient.nom + '</p><p>Montant: ' + (selectedPaymentMethod === 'cash_usd' ? paymentAmountUSD.toFixed(2) + ' USD' : Math.round(paymentAmountCDF).toLocaleString() + ' CDF') + '</p><p>Mode: ' + { cash_usd: 'Espèces USD', cash_cdf: 'Espèces CDF', card: 'Carte bancaire' }[selectedPaymentMethod] + '</p>';
        if (printReceipt) msg += '<p><span class="material-icons text-success align-middle">check_circle</span> Reçu imprimé automatiquement (double exemplaire)</p>';
        if (emailReceipt) msg += '<p><span class="material-icons text-success align-middle">check_circle</span> Reçu PDF envoyé à ' + selectedClient.email + '</p>';
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Paiement effectué', html: msg, confirmButtonColor: '#3454d1' });
        cashPayments.push({
            id: cashPayments.length + 1,
            date: new Date().toISOString().slice(0, 16).replace('T', ' '),
            client: selectedClient.nom,
            abonnement: document.getElementById('formuleSelect').options[document.getElementById('formuleSelect').selectedIndex].text.split(' - ')[0],
            montant: selectedPaymentMethod === 'cash_usd' ? paymentAmountUSD : paymentAmountCDF,
            devise: selectedPaymentMethod === 'cash_usd' ? 'USD' : 'CDF',
            mode: selectedPaymentMethod === 'card' ? 'Carte' : 'Espèces',
            statut: 'success',
            reçu: 'REC-' + (cashPayments.length + 100)
        });
        var modalEl = document.getElementById('paymentModal');
        if (modalEl && bootstrap && bootstrap.Modal) bootstrap.Modal.getInstance(modalEl).hide();
        renderCashPayments();
        updateCashStats();
    }

    function viewTransaction(id, type) {
        var transaction = type === 'cash' ? cashPayments.find(function(t) { return t.id === id; }) : onlineTransactions.find(function(t) { return t.id === id; });
        if (!transaction) return;
        var html = '<table class="table table-borderless"><tr><td class="fw-semibold">ID:</td><td>#TR-2024-' + (transaction.id + 155) + '</td></tr><tr><td class="fw-semibold">Date:</td><td>' + transaction.date + '</td></tr><tr><td class="fw-semibold">Client:</td><td>' + transaction.client + '</td></tr><tr><td class="fw-semibold">Abonnement:</td><td>' + transaction.abonnement + '</td></tr><tr><td class="fw-semibold">Montant:</td><td class="fw-bold">' + (transaction.devise === 'USD' ? transaction.montant.toFixed(2) + ' USD' : transaction.montant.toLocaleString() + ' CDF') + '</td></tr><tr><td class="fw-semibold">Mode:</td><td>' + transaction.mode + '</td></tr><tr><td class="fw-semibold">Statut:</td><td><span class="badge-' + (transaction.statut === 'success' ? 'success' : 'warning') + '">' + transaction.statut + '</span></td></tr></table>';
        document.getElementById('transactionDetails').innerHTML = html;
        var hmacEl = document.getElementById('hmacDetails');
        var retryEl = document.getElementById('retryCallback');
        if (type === 'online' && transaction.signature) {
            hmacEl.style.display = 'block';
            document.getElementById('hmacSignature').textContent = transaction.signature;
            if (retryEl) retryEl.style.display = 'inline-block';
        } else {
            hmacEl.style.display = 'none';
            if (retryEl) retryEl.style.display = 'none';
        }
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) new bootstrap.Modal(document.getElementById('transactionModal')).show();
    }

    function viewJournalEntry(id) {
        var entry = journal.find(function(j) { return j.id === id; });
        if (entry && typeof Swal !== 'undefined') Swal.fire({ title: 'Entrée du journal', html: '<p><strong>Transaction:</strong> ' + entry.trans_id + '</p><p><strong>Client:</strong> ' + entry.client + '</p><p><strong>Montant:</strong> ' + (entry.devise === 'USD' ? entry.montant.toFixed(2) + ' USD' : entry.montant.toLocaleString() + ' CDF') + '</p><p><strong>Référence:</strong> ' + entry.reference + '</p><p><strong>Statut:</strong> <span class="badge-' + (entry.statut === 'success' ? 'success' : 'warning') + '">' + entry.statut + '</span></p>', confirmButtonColor: '#3454d1' });
    }

    function printReceipt(ref) {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Impression', text: 'Reçu ' + ref + ' en cours d\'impression...', timer: 1500 });
    }

    function retryCallback() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Callback renvoyé', text: 'Le webhook a été retransmis avec succès', timer: 2000 });
    }

    window.openPaymentModal = openPaymentModal;
    window.searchClient = searchClient;
    window.chooseClient = chooseClient;
    window.resetClientSelection = resetClientSelection;
    window.updateAmount = updateAmount;
    window.updateCustomAmount = updateCustomAmount;
    window.selectPaymentMethod = selectPaymentMethod;
    window.calculMonnaie = calculMonnaie;
    window.nextStepPayment = nextStepPayment;
    window.processPayment = processPayment;
    window.viewTransaction = viewTransaction;
    window.viewJournalEntry = viewJournalEntry;
    window.printReceipt = printReceipt;
    window.retryCallback = retryCallback;
    window.renderCashPayments = renderCashPayments;
    window.renderOnlinePayments = renderOnlinePayments;
    window.renderJournal = renderJournal;
    window.exportJournal = exportJournal;

    document.addEventListener('DOMContentLoaded', function() {
        var urlParams = new URLSearchParams(window.location.search);
        var tabParam = urlParams.get('tab');
        if (tabParam === 'enligne') tabParam = 'online';
        var validTabs = ['caisse', 'online', 'journal'];
        var tab = validTabs.indexOf(tabParam) >= 0 ? tabParam : 'caisse';
        showTab(tab);

        // Forcer ce module en mode clair (désactiver le rendu sombre uniquement sur cette page)
        try {
            document.documentElement.classList.remove('app-skin-dark');
        } catch (e) {}
    });
})();
