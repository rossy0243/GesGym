
(function() {
    var SU = window.STATIC_URLS || {};
    var LOGO_SMARTCLUB_URL = SU.logo || '/static/avatar/logo_smartclub.png';
    var AVATAR_1 = SU.avatar1 || '/static/avatar/1.png';
    var AVATAR_2 = SU.avatar2 || '/static/avatar/2.png';
    // ============================
    // Données de simulation
    // ============================
    let clients = [
        { id: 1, nom: "Jean Dupont", email: "jean.dupont@email.com", phone: "+243812345678", code_membre: "GYM-001", photo: AVATAR_1, statut: "actif", abonnement: "12 mois", date_expiration: "2026-03-15" },
        { id: 2, nom: "Marie Kabeya", email: "marie.k@email.com", phone: "+243822345679", code_membre: "GYM-002", photo: AVATAR_2, statut: "actif", abonnement: "6 mois", date_expiration: "2025-06-20" },
        { id: 3, nom: "Pierre Kasongo", email: "pierre.k@email.com", phone: "+243832345680", code_membre: "GYM-003", photo: AVATAR_1, statut: "expire", abonnement: "3 mois", date_expiration: "2025-01-15" },
        { id: 4, nom: "Sophie Lukusa", email: "sophie.l@email.com", phone: "+243842345681", code_membre: "GYM-004", photo: AVATAR_2, statut: "suspendu", abonnement: "1 mois", date_expiration: "2025-02-01" },
        { id: 5, nom: "Paul Mbuyi", email: "paul.m@email.com", phone: "+243852345682", code_membre: "GYM-005", photo: AVATAR_1, statut: "actif", abonnement: "12 mois", date_expiration: "2026-01-10" },
        { id: 6, nom: "Claire Mbombo", email: "claire.m@email.com", phone: "+243862345683", code_membre: "GYM-006", photo: AVATAR_2, statut: "actif", abonnement: "3 mois", date_expiration: "2025-04-30" }
    ];

    let accessHistory = [
        { id: 1, date: "2025-02-21 08:32:45", client_id: 1, client_nom: "Jean Dupont", code_membre: "GYM-001", statut: "success", methode: "QR code", agent: "Karim" },
        { id: 2, date: "2025-02-21 08:35:22", client_id: 2, client_nom: "Marie Kabeya", code_membre: "GYM-002", statut: "success", methode: "QR code", agent: "Karim" },
        { id: 3, date: "2025-02-21 08:42:10", client_id: 5, client_nom: "Paul Mbuyi", code_membre: "GYM-005", statut: "success", methode: "QR code", agent: "Sophie" },
        { id: 4, date: "2025-02-21 08:55:33", client_id: 3, client_nom: "Pierre Kasongo", code_membre: "GYM-003", statut: "denied", methode: "QR code", agent: "Karim", motif: "Abonnement expiré" },
        { id: 5, date: "2025-02-21 09:12:05", client_id: 6, client_nom: "Claire Mbombo", code_membre: "GYM-006", statut: "success", methode: "QR code", agent: "Sophie" },
        { id: 6, date: "2025-02-21 09:25:47", client_id: 4, client_nom: "Sophie Lukusa", code_membre: "GYM-004", statut: "denied", methode: "Manuel", agent: "Karim", motif: "Compte suspendu" },
        { id: 7, date: "2025-02-21 09:38:19", client_id: 1, client_nom: "Jean Dupont", code_membre: "GYM-001", statut: "success", methode: "QR code", agent: "Karim" },
        { id: 8, date: "2025-02-21 09:45:52", client_id: 2, client_nom: "Marie Kabeya", code_membre: "GYM-002", statut: "success", methode: "QR code", agent: "Sophie" },
        { id: 9, date: "2025-02-21 10:02:14", client_id: 5, client_nom: "Paul Mbuyi", code_membre: "GYM-005", statut: "success", methode: "QR code", agent: "Karim" },
        { id: 10, date: "2025-02-21 10:15:36", client_id: 6, client_nom: "Claire Mbombo", code_membre: "GYM-006", statut: "success", methode: "Manuel", agent: "Sophie" }
    ];

    let currentTab = 'scan';
    let currentPage = 1;
    let itemsPerPage = 10;
    let selectedClientForEntry = null;
    let selectedClientForQR = null;
    let currentThemeQR = 'theme1';

    // ============================
    // Navigation & onglets
    // ============================
    function showTab(tab) {
        let contentTab = tab;
        if (tab === 'auto') contentTab = 'manuel';
        currentTab = contentTab;

        document.getElementById('scanSection').style.display = contentTab === 'scan' ? 'block' : 'none';
        document.getElementById('manuelSection').style.display = contentTab === 'manuel' ? 'block' : 'none';
        document.getElementById('historiqueSection').style.display = contentTab === 'historique' ? 'block' : 'none';
        document.getElementById('qrcodeSection').style.display = contentTab === 'qrcode' ? 'block' : 'none';

        ['manuel', 'auto', 'historique', 'qrcode'].forEach(function(id) {
            const el = document.getElementById('nav-acces-' + id);
            if (el) el.classList.toggle('active', id === tab);
        });

        const url = new URL(window.location);
        url.searchParams.set('tab', tab);
        window.history.replaceState({}, '', url);

        if (contentTab === 'scan') {
            updateScanStats();
            renderRealtimeScans();
        } else if (contentTab === 'historique') {
            renderHistorique();
        }
    }

    // ============================
    // Scan & temps réel
    // ============================
    function openScannerModal() {
        const result = document.getElementById('scanResult');
        if (result) result.style.display = 'none';
        const modalEl = document.getElementById('scannerModal');
        if (modalEl && window.bootstrap) new bootstrap.Modal(modalEl).show();
    }

    function simulateScan() {
        const randomClient = clients[Math.floor(Math.random() * clients.length)];
        processScanResult(randomClient);
    }

    function processScanResult(client) {
        const resultDiv = document.getElementById('scanResult');
        if (!resultDiv) return;

        const isExpired = new Date(client.date_expiration) < new Date();
        const finalStatut =
            client.statut === 'actif' && !isExpired ? 'success' :
            'denied';

        const newEntry = {
            id: accessHistory.length + 1,
            date: new Date().toISOString().replace('T', ' ').substring(0, 19),
            client_id: client.id,
            client_nom: client.nom,
            code_membre: client.code_membre,
            statut: finalStatut,
            methode: 'QR code',
            agent: 'Karim',
            motif: finalStatut === 'denied'
                ? (client.statut === 'expire' ? 'Abonnement expiré' : 'Compte suspendu')
                : null
        };
        accessHistory.unshift(newEntry);

        let html = '';
        if (finalStatut === 'success') {
            html = `
                <div class="scan-result success">
                    <div class="d-flex align-items-center gap-3">
                        <span class="material-icons text-success" style="font-size: 48px;">check_circle</span>
                        <div>
                            <h4 class="text-success mb-1">ACCÈS AUTORISÉ</h4>
                            <p class="mb-0">Bienvenue ${client.nom} !</p>
                        </div>
                    </div>
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <img src="${client.photo}" class="client-photo" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%233454d1%22/%3E%3C/text%3E%3C/svg%3E';">
                        </div>
                        <div class="col-md-6">
                            <p><strong>Code membre:</strong> ${client.code_membre}</p>
                            <p><strong>Abonnement:</strong> ${client.abonnement}</p>
                            <p><strong>Expire le:</strong> ${client.date_expiration}</p>
                        </div>
                    </div>
                </div>
            `;
        } else {
            html = `
                <div class="scan-result danger">
                    <div class="d-flex align-items-center gap-3">
                        <span class="material-icons text-danger" style="font-size: 48px;">cancel</span>
                        <div>
                            <h4 class="text-danger mb-1">ACCÈS REFUSÉ</h4>
                            <p class="mb-0">${newEntry.motif}</p>
                        </div>
                    </div>
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <img src="${client.photo}" class="client-photo" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%23c62828%22/%3E%3C/text%3E%3C/svg%3E';">
                        </div>
                        <div class="col-md-6">
                            <p><strong>Code membre:</strong> ${client.code_membre}</p>
                            <p><strong>Statut:</strong> ${client.statut}</p>
                        </div>
                    </div>
                    <div class="mt-3">
                        <button class="btn btn-sm btn-light" onclick="window.location.href='{{ url_paiements }}'">
                            <span class="material-icons me-2" style="font-size: 18px;">payments</span>Renouveler
                        </button>
                    </div>
                </div>
            `;
        }

        resultDiv.innerHTML = html;
        resultDiv.style.display = 'block';

        updateScanStats();
        renderRealtimeScans();

        if (window.Swal) {
            Swal.fire({
                icon: finalStatut === 'success' ? 'success' : 'error',
                title: finalStatut === 'success' ? 'Accès autorisé' : 'Accès refusé',
                text: finalStatut === 'success' ? `Bienvenue ${client.nom}` : newEntry.motif,
                timer: 2000,
                showConfirmButton: false
            });
        }
    }

    function updateScanStats() {
        const today = new Date().toISOString().slice(0, 10);
        const authorized = accessHistory.filter(h => h.date.startsWith(today) && h.statut === 'success').length;
        const denied = accessHistory.filter(h => h.date.startsWith(today) && h.statut === 'denied').length;
        const entriesEl = document.getElementById('todayEntries');
        const deniedEl = document.getElementById('todayDenied');
        if (entriesEl) entriesEl.textContent = authorized;
        if (deniedEl) deniedEl.textContent = denied;
    }

    function renderRealtimeScans() {
        const container = document.getElementById('realtimeScans');
        if (!container) return;
        const recent = accessHistory.slice(0, 8);
        let html = '';
        recent.forEach(entry => {
            const success = entry.statut === 'success';
            html += `
                <div class="timeline-item ${success ? 'success' : 'danger'} mb-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="material-icons me-2 ${success ? 'text-success' : 'text-danger'}" style="font-size: 18px;">
                                ${success ? 'check_circle' : 'cancel'}
                            </span>
                            <strong>${entry.client_nom}</strong>
                            <span class="text-muted ms-2">(${entry.code_membre})</span>
                        </div>
                        <span class="${success ? 'badge-actif' : 'badge-expire'}">
                            ${success ? 'Autorisé' : 'Refusé'}
                        </span>
                    </div>
                    <div class="d-flex justify-content-between mt-1">
                        <span class="text-muted small">
                            <span class="material-icons me-1" style="font-size: 14px;">schedule</span>${entry.date}
                        </span>
                        <span class="text-muted small">Méthode: ${entry.methode} | Agent: ${entry.agent}</span>
                    </div>
                    ${entry.motif ? `<div class="mt-1 text-danger small"><span class="material-icons me-1" style="font-size: 14px;">warning</span>${entry.motif}</div>` : ''}
                </div>
            `;
        });
        container.innerHTML = html;
    }

    // ============================
    // Pointage manuel
    // ============================
    function searchClientManuel() {
        const search = (document.getElementById('manuelSearch').value || '').toLowerCase();
        const resultsDiv = document.getElementById('manuelResults');
        if (!resultsDiv) return;
        if (search.length < 2) {
            resultsDiv.innerHTML = '';
            return;
        }
        const found = clients.filter(c =>
            c.nom.toLowerCase().includes(search) ||
            c.phone.includes(search) ||
            c.code_membre.toLowerCase().includes(search)
        );
        if (!found.length) {
            resultsDiv.innerHTML = '<p class="text-muted text-center p-3">Aucun client trouvé</p>';
            return;
        }
        resultsDiv.innerHTML = found.map(c => `
            <div class="client-card mb-2" onclick="showClientForManualEntry(${c.id})">
                <div class="d-flex align-items-center gap-3">
                    <img src="${c.photo}" class="rounded-circle" style="width: 48px; height: 48px; object-fit: cover;"
                        onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%233454d1%22/%3E%3C/text%3E%3C/svg%3E';">
                    <div class="flex-grow-1">
                        <h6 class="mb-1">${c.nom}</h6>
                        <span class="${c.statut === 'actif' ? 'badge-actif' : c.statut === 'expire' ? 'badge-expire' : 'badge-suspendu'}">${c.statut}</span>
                        <span class="text-muted ms-2 small">${c.code_membre}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    function showClientForManualEntry(clientId) {
        const client = clients.find(c => c.id === clientId);
        if (!client) return;
        selectedClientForEntry = client;
        const details = document.getElementById('manuelClientDetails');
        const isExpired = new Date(client.date_expiration) < new Date();
        const statusDisplay =
            client.statut === 'actif' && !isExpired ? 'Actif' :
            client.statut === 'expire' || isExpired ? 'Expiré' : 'Suspendu';
        const statusClass =
            client.statut === 'actif' && !isExpired ? 'badge-actif' :
            client.statut === 'expire' || isExpired ? 'badge-expire' : 'badge-suspendu';

        details.innerHTML = `
            <div class="text-center mb-3">
                <img src="${client.photo}" class="client-photo mb-2"
                    onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%233454d1%22/%3E%3C/text%3E%3C/svg%3E';">
                <h5>${client.nom}</h5>
            </div>
            <table class="table table-borderless">
                <tr><td class="text-muted">Code membre:</td><td><strong>${client.code_membre}</strong></td></tr>
                <tr><td class="text-muted">Statut:</td><td><span class="${statusClass}">${statusDisplay}</span></td></tr>
                <tr><td class="text-muted">Abonnement:</td><td>${client.abonnement}</td></tr>
                <tr><td class="text-muted">Expire le:</td><td>${client.date_expiration}</td></tr>
                <tr><td class="text-muted">Téléphone:</td><td>${client.phone}</td></tr>
                <tr><td class="text-muted">Email:</td><td>${client.email}</td></tr>
            </table>
            <div class="d-flex gap-2 mt-3">
                <button class="btn btn-success flex-grow-1" onclick="openConfirmEntryModal()" ${client.statut !== 'actif' || isExpired ? 'disabled' : ''}>
                    <span class="material-icons me-2">check_circle</span>Valider entrée
                </button>
                <button class="btn btn-outline-primary" onclick="window.location.href='{{ url_clients }}?id=${client.id}'">
                    <span class="material-icons">visibility</span>
                </button>
            </div>
            ${client.statut !== 'actif' || isExpired ? '<div class="alert alert-warning mt-3 mb-0 small"><span class="material-icons me-2" style="font-size: 16px;">warning</span>Ce client ne peut pas entrer. Veuillez renouveler son abonnement.</div>' : ''}
        `;
    }

    function openConfirmEntryModal() {
        if (!selectedClientForEntry) return;
        const client = selectedClientForEntry;
        const body = document.getElementById('confirmEntryBody');
        body.innerHTML = `
            <div class="text-center mb-3">
                <img src="${client.photo}" class="client-photo mb-2" style="width: 80px; height: 80px;"
                    onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%233454d1%22/%3E%3C/text%3E%3C/svg%3E';">
                <h5>${client.nom}</h5>
            </div>
            <p>Vous êtes sur le point d'enregistrer l'entrée de ce client.</p>
            <p><strong>Code membre:</strong> ${client.code_membre}</p>
            <p><strong>Abonnement:</strong> ${client.abonnement} (expire le ${client.date_expiration})</p>
        `;
        const modalEl = document.getElementById('confirmEntryModal');
        if (modalEl && window.bootstrap) new bootstrap.Modal(modalEl).show();
    }

    function confirmManualEntry() {
        if (!selectedClientForEntry) return;
        const client = selectedClientForEntry;
        const newEntry = {
            id: accessHistory.length + 1,
            date: new Date().toISOString().replace('T', ' ').substring(0, 19),
            client_id: client.id,
            client_nom: client.nom,
            code_membre: client.code_membre,
            statut: 'success',
            methode: 'Manuel',
            agent: 'Karim'
        };
        accessHistory.unshift(newEntry);
        const modalEl = document.getElementById('confirmEntryModal');
        if (modalEl && window.bootstrap) bootstrap.Modal.getInstance(modalEl).hide();
        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: 'Entrée enregistrée',
                text: `L'entrée de ${client.nom} a été validée`,
                timer: 2000
            });
        }
        updateScanStats();
        renderRealtimeScans();
        searchClientManuel();
    }

    // ============================
    // Historique
    // ============================
    function renderHistorique() {
        const search = (document.getElementById('filterHistoriqueSearch')?.value || '').toLowerCase();
        const statut = document.getElementById('filterHistoriqueStatut')?.value || '';
        const methode = document.getElementById('filterHistoriqueMethode')?.value || '';

        let filtered = accessHistory.slice();
        if (search) {
            filtered = filtered.filter(h =>
                h.client_nom.toLowerCase().includes(search) ||
                h.code_membre.toLowerCase().includes(search)
            );
        }
        if (statut) filtered = filtered.filter(h => h.statut === statut);
        if (methode) filtered = filtered.filter(h => h.methode === methode);

        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const pageItems = filtered.slice(start, end);

        const tbody = document.getElementById('historiqueBody');
        let html = '';
        pageItems.forEach(h => {
            const success = h.statut === 'success';
            const statusClass = success ? 'badge-actif' : 'badge-expire';
            const statusText = success ? 'Autorisé' : 'Refusé';
            html += `
                <tr>
                    <td>${h.date}</td>
                    <td>${h.client_nom}</td>
                    <td>${h.code_membre}</td>
                    <td><span class="${statusClass}">${statusText}</span></td>
                    <td>${h.methode}</td>
                    <td>${h.agent}</td>
                    <td>
                        <button class="btn btn-sm btn-light-brand" onclick="viewAccessDetails(${h.id})">
                            <span class="material-icons" style="font-size: 18px;">visibility</span>
                        </button>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;

        const info = document.getElementById('paginationInfo');
        if (info) {
            info.textContent = `${filtered.length ? start + 1 : 0}-${Math.min(end, filtered.length)} sur ${filtered.length} entrées`;
        }
    }

    function viewAccessDetails(id) {
        const entry = accessHistory.find(h => h.id === id);
        if (!entry || !window.Swal) return;
        const success = entry.statut === 'success';
        const statusClass = success ? 'badge-actif' : 'badge-expire';
        const statusText = success ? 'Autorisé' : 'Refusé';
        Swal.fire({
            title: "Détails de l'entrée",
            html: `
                <p><strong>Date:</strong> ${entry.date}</p>
                <p><strong>Client:</strong> ${entry.client_nom}</p>
                <p><strong>Code membre:</strong> ${entry.code_membre}</p>
                <p><strong>Statut:</strong> <span class="${statusClass}">${statusText}</span></p>
                <p><strong>Méthode:</strong> ${entry.methode}</p>
                <p><strong>Agent:</strong> ${entry.agent}</p>
                ${entry.motif ? `<p><strong>Motif:</strong> ${entry.motif}</p>` : ''}
            `,
            confirmButtonColor: '#3454d1'
        });
    }

    function prevPage() {
        if (currentPage > 1) {
            currentPage--;
            renderHistorique();
        }
    }

    function nextPage() {
        if (currentPage * itemsPerPage < accessHistory.length) {
            currentPage++;
            renderHistorique();
        }
    }

    function exportHistorique() {
        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: 'Export réussi',
                text: "L'historique a été exporté au format Excel",
                timer: 2000
            });
        }
    }

    // ============================
    // Génération QR code
    // ============================
    function searchClientForQR() {
        const search = (document.getElementById('qrcodeSearch').value || '').toLowerCase();
        const resultsDiv = document.getElementById('qrcodeResults');
        if (!resultsDiv) return;
        if (search.length < 2) {
            resultsDiv.innerHTML = '';
            return;
        }
        const found = clients.filter(c =>
            c.nom.toLowerCase().includes(search) ||
            c.phone.includes(search) ||
            c.code_membre.toLowerCase().includes(search)
        );
        if (!found.length) {
            resultsDiv.innerHTML = '<p class="text-muted text-center p-3">Aucun client trouvé</p>';
            return;
        }
        resultsDiv.innerHTML = found.map(c => `
            <div class="client-card mb-2" onclick="generateQRCodeForClient(${c.id})">
                <div class="d-flex align-items-center gap-3">
                    <img src="${c.photo}" class="rounded-circle" style="width: 48px; height: 48px; object-fit: cover;"
                        onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%233454d1%22/%3E%3C/text%3E%3C/svg%3E';">
                    <div class="flex-grow-1">
                        <h6 class="mb-1">${c.nom}</h6>
                        <span class="text-muted small">${c.code_membre}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    function generateQRCodeForClient(clientId) {
        const client = clients.find(c => c.id === clientId);
        if (!client) return;
        selectedClientForQR = client;
        const display = document.getElementById('qrcodeDisplay');
        display.innerHTML = `
            <div class="text-center">
                <h6 class="mb-3">QR code de ${client.nom}</h6>
                <div class="qrcode-preview mb-3" id="qrcodePreview"></div>
                <p class="mb-2"><strong>Code membre:</strong> ${client.code_membre}</p>
                <p class="mb-3"><strong>Statut:</strong> <span class="${client.statut === 'actif' ? 'badge-actif' : 'badge-expire'}">${client.statut}</span></p>
                <div class="d-flex gap-2 justify-content-center flex-wrap">
                    <button class="btn btn-sm btn-primary" onclick="downloadQRCode()">
                        <span class="material-icons me-2" style="font-size: 18px;">download</span>Télécharger
                    </button>
                    <button class="btn btn-sm btn-light" onclick="printQRCode()">
                        <span class="material-icons me-2" style="font-size: 18px;">print</span>Imprimer QR
                    </button>
                    <button class="btn btn-sm btn-success" onclick="openCardPreviewModal()">
                        <span class="material-icons me-2" style="font-size: 18px;">print</span>Imprimer carte
                    </button>
                </div>
            </div>
        `;
        const qrDiv = document.getElementById('qrcodePreview');
        qrDiv.innerHTML = '';
        new QRCode(qrDiv, {
            text: client.code_membre,
            width: 200,
            height: 200,
            colorDark: "#000000",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.H
        });
    }

    function downloadQRCode() {
        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: 'QR code téléchargé',
                text: 'Le fichier a été sauvegardé',
                timer: 2000
            });
        }
    }

    function printQRCode() {
        if (window.Swal) {
            Swal.fire({
                icon: 'success',
                title: 'Impression',
                text: "QR code envoyé à l'imprimante",
                timer: 2000
            });
        }
    }

    function updateCardThemeQR() {
        currentThemeQR = document.getElementById('cardThemeQR').value;
        const container = document.getElementById('cardPreviewContainer');
        container.className = 'cards-row ' + (currentThemeQR === 'theme1' ? '' : currentThemeQR);
    }

    function openCardPreviewModal() {
        if (!selectedClientForQR) {
            if (window.Swal) Swal.fire({ icon: 'warning', title: 'Aucun membre', text: "Veuillez d'abord sélectionner un membre." });
            return;
        }
        generateMemberCardRectoVerso();
        const modalEl = document.getElementById('cardPreviewModal');
        if (modalEl && window.bootstrap) new bootstrap.Modal(modalEl).show();
    }

    function generateMemberCardRectoVerso() {
        const client = selectedClientForQR;
        if (!client) return;
        const container = document.getElementById('cardPreviewContainer');
        container.className = 'cards-row ' + (currentThemeQR === 'theme1' ? '' : currentThemeQR);

        const dateAdhesion = client.date_adhesion
            ? new Date(client.date_adhesion).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
            : '-';
        const dateExpiration = client.date_expiration
            ? new Date(client.date_expiration).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
            : '-';
        const photoUrl = client.photo || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%230A4D9B%22/%3E%3C/text%3E%3C/svg%3E';

        const rectoHTML = `
            <div class="card-membre-sc card-front-sc">
                <div class="header-sc">
                    <h1 class="card-header-title-sc"><span class="title-smartclub-sc">smartclub</span> <span class="title-pro-sc">pro</span></h1>
                </div>
                <div class="main-content-sc">
                    <img src="${photoUrl}" alt="Membre" class="member-photo-sc"
                        onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 64 64%22%3E%3Ccircle cx=%2232%22 cy=%2232%22 r=%2232%22 fill=%22%23e0e0e0%22/%3E%3C/svg%3E';">
                    <div class="member-info-sc">
                        <h2>${client.nom.toUpperCase()}</h2>
                        <div class="status-label-sc">● MEMBRE ${(client.statut === 'actif' ? 'PREMIUM' : client.statut).toUpperCase()} ●</div>
                        <div class="details-sc">
                            <p><b>ID:</b> ${client.code_membre}</p>
                            <p><b>ADHÉSION:</b> ${dateAdhesion}</p>
                            <p><b>EXPIRATION:</b> ${dateExpiration}</p>
                        </div>
                    </div>
                </div>
                <div class="chip-sc"></div>
                <div class="badge-valide-sc">✓ VALIDE</div>
            </div>
        `;

        const versoHTML = `
            <div class="card-membre-sc card-back-sc">
                <div class="mag-stripe-sc"></div>
                <div class="back-content-sc">
                    <div style="text-align:center;">
                        <div class="qr-code-sc" id="qrcode-back"></div>
                        <p style="font-size:6px;font-weight:bold;margin-top:5px;color:#666;">ACCÈS MEMBRE</p>
                    </div>
                    <div style="flex:1;">
                        <div class="signature-box-sc">Signature du titulaire</div>
                        <div style="font-size:10px;">
                            <b style="color:#0A4D9B;font-size:10px;">TITULAIRE : ${client.nom.toUpperCase()}</b>
                            <div class="contact-info-sc">
                                <div class="contact-item-sc">📞 ${client.phone || '+243 979 710 633'}</div>
                                <div class="contact-item-sc">📧 ${client.email || 'contact@smartitsolution.cd'}</div>
                                <div class="contact-item-sc">📍 01 bis, route de Matadi, Ngaliema</div>
                            </div>
                        </div>
                        <p style="margin-top:8px;font-size:6px;color:#aaa;line-height:1.1;">
                            Propriété exclusive du SMART CLUB. En cas de perte, merci de rapporter à l'adresse ci-dessus.
                        </p>
                    </div>
                </div>
            </div>
        `;

        container.innerHTML = rectoHTML + versoHTML;

        setTimeout(function() {
            const qrElement = document.getElementById('qrcode-back');
            if (qrElement) {
                qrElement.innerHTML = '';
                new QRCode(qrElement, {
                    text: client.code_membre + '-' + client.nom.replace(/\s/g, '-'),
                    width: 80,
                    height: 80,
                    colorDark: "#000000",
                    colorLight: "#ffffff",
                    correctLevel: QRCode.CorrectLevel.H
                });
            }
        }, 100);
    }

    function printMemberCard() {
        if (window.Swal) {
            Swal.fire({
                icon: 'info',
                title: 'Impression simulée',
                text: "L'impression réelle sera gérée côté backend.",
                confirmButtonColor: '#3454d1'
            });
        }
    }

    // ============================
    // Initialisation
    // ============================
    document.addEventListener('DOMContentLoaded', function() {
        const params = new URLSearchParams(window.location.search);
        let tabParam = params.get('tab') || 'manuel';
        if (['scan', 'manuel', 'auto', 'historique', 'qrcode'].indexOf(tabParam) === -1) {
            tabParam = 'manuel';
        }
        showTab(tabParam);
        updateScanStats();
        renderRealtimeScans();

        // Simulation de scans réguliers
        setInterval(function() {
            if (Math.random() > 0.7) {
                const randomClient = clients[Math.floor(Math.random() * clients.length)];
                const isExpired = new Date(randomClient.date_expiration) < new Date();
                const statut = randomClient.statut === 'actif' && !isExpired ? 'success' : 'denied';
                const newEntry = {
                    id: accessHistory.length + 1,
                    date: new Date().toISOString().replace('T', ' ').substring(0, 19),
                    client_id: randomClient.id,
                    client_nom: randomClient.nom,
                    code_membre: randomClient.code_membre,
                    statut: statut,
                    methode: 'QR code',
                    agent: 'Système auto',
                    motif: statut === 'denied'
                        ? (randomClient.statut === 'expire' ? 'Abonnement expiré' : 'Compte suspendu')
                        : null
                };
                accessHistory.unshift(newEntry);
                if (accessHistory.length > 200) accessHistory.pop();
                updateScanStats();
                renderRealtimeScans();
            }
        }, 10000);
    });

    // Exposer les fonctions nécessaires au HTML
    window.openScannerModal = openScannerModal;
    window.simulateScan = simulateScan;
    window.showTab = showTab;
    window.searchClientManuel = searchClientManuel;
    window.showClientForManualEntry = showClientForManualEntry;
    window.openConfirmEntryModal = openConfirmEntryModal;
    window.confirmManualEntry = confirmManualEntry;
    window.renderHistorique = renderHistorique;
    window.viewAccessDetails = viewAccessDetails;
    window.prevPage = prevPage;
    window.nextPage = nextPage;
    window.exportHistorique = exportHistorique;
    window.searchClientForQR = searchClientForQR;
    window.generateQRCodeForClient = generateQRCodeForClient;
    window.downloadQRCode = downloadQRCode;
    window.printQRCode = printQRCode;
    window.updateCardThemeQR = updateCardThemeQR;
    window.openCardPreviewModal = openCardPreviewModal;
    window.printMemberCard = printMemberCard;
})();
