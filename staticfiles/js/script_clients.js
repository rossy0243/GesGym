
// ================================================
// DONNÉES EXEMPLES AVEC PHOTOS RÉELLES
// ================================================

let members = [
    {
        id: 1,
        first_name: "Jean",
        last_name: "Dupont",
        full_name: "Jean Dupont",
        phone: "+243 81 234 5678",
        email: "jean.d@email.com",
        address: "Av. de la Libération",
        city: "Kinshasa",
        photo: "https://randomuser.me/api/portraits/men/1.jpg",
        subscription: {
            type: "12mois",
            type_label: "12 mois",
            start_date: "2024-01-01",
            expiry_date: "2024-12-31",
            price: 420,
            paid: 420,
            status: "actif"
        },
        payments: [
            { date: "01/01/2024", amount: 420, method: "cash", status: "paye" }
        ],
        access_logs: [
            { date: "17/06/2024", time: "08:30", method: "QR code" },
            { date: "16/06/2024", time: "17:45", method: "QR code" },
            { date: "15/06/2024", time: "09:15", method: "Manuel" }
        ],
        documents: [],
        created_at: "01/01/2024",
        status: "actif"
    },
    {
        id: 2,
        first_name: "Marie",
        last_name: "Lukusa",
        full_name: "Marie Lukusa",
        phone: "+243 82 345 6789",
        email: "marie.l@email.com",
        address: "Av. du Commerce",
        city: "Kinshasa",
        photo: "https://randomuser.me/api/portraits/women/2.jpg",
        subscription: {
            type: "6mois",
            type_label: "6 mois",
            start_date: "2024-03-15",
            expiry_date: "2024-09-15",
            price: 240,
            paid: 240,
            status: "actif"
        },
        payments: [
            { date: "15/03/2024", amount: 240, method: "card", status: "paye" }
        ],
        access_logs: [
            { date: "17/06/2024", time: "10:00", method: "QR code" }
        ],
        documents: [],
        created_at: "15/03/2024",
        status: "actif"
    },
    {
        id: 3,
        first_name: "Paul",
        last_name: "Mbuyi",
        full_name: "Paul Mbuyi",
        phone: "+243 83 456 7890",
        email: "paul.m@email.com",
        address: "Av. de l'Université",
        city: "Kinshasa",
        photo: "https://randomuser.me/api/portraits/men/3.jpg",
        subscription: {
            type: "3mois",
            type_label: "3 mois",
            start_date: "2024-02-01",
            expiry_date: "2024-05-01",
            price: 135,
            paid: 135,
            status: "expire"
        },
        payments: [
            { date: "01/02/2024", amount: 135, method: "mobile", status: "paye" }
        ],
        access_logs: [
            { date: "30/04/2024", time: "18:30", method: "QR code" }
        ],
        documents: [],
        created_at: "01/02/2024",
        status: "expire"
    },
    {
        id: 4,
        first_name: "Alice",
        last_name: "Mbuyi",
        full_name: "Alice Mbuyi",
        phone: "+243 84 567 8901",
        email: "alice.m@email.com",
        address: "Av. des Aviateurs",
        city: "Kinshasa",
        photo: "https://randomuser.me/api/portraits/women/4.jpg",
        subscription: {
            type: "1mois",
            type_label: "1 mois",
            start_date: "2024-06-01",
            expiry_date: "2024-07-01",
            price: 50,
            paid: 50,
            status: "actif"
        },
        payments: [
            { date: "01/06/2024", amount: 50, method: "cash", status: "paye" }
        ],
        access_logs: [
            { date: "17/06/2024", time: "07:45", method: "QR code" },
            { date: "16/06/2024", time: "18:00", method: "QR code" }
        ],
        documents: [],
        created_at: "01/06/2024",
        status: "actif"
    },
    {
        id: 5,
        first_name: "Pierre",
        last_name: "Kalala",
        full_name: "Pierre Kalala",
        phone: "+243 85 678 9012",
        email: "pierre.k@email.com",
        address: "Route de Matadi",
        city: "Kinshasa",
        photo: "https://randomuser.me/api/portraits/men/5.jpg",
        subscription: {
            type: "12mois",
            type_label: "12 mois",
            start_date: "2024-01-15",
            expiry_date: "2025-01-15",
            price: 420,
            paid: 420,
            status: "actif"
        },
        payments: [
            { date: "15/01/2024", amount: 420, method: "bank", status: "paye" }
        ],
        access_logs: [
            { date: "17/06/2024", time: "11:30", method: "QR code" },
            { date: "16/06/2024", time: "09:45", method: "QR code" }
        ],
        documents: [],
        created_at: "15/01/2024",
        status: "actif"
    }
];

// Variables globales
let filteredMembers = [...members];
let currentPage = 1;
let itemsPerPage = 10;
let currentMemberId = null;
let editingMemberId = null; // ID du membre en cours de modification (null = ajout)
let html5QrCode = null;

// ================================================
// FONCTIONS DE NAVIGATION
// ================================================
// La navigation laterale est geree globalement par static/js/nav-toggle.js.

function showCheckInView() {
    document.getElementById('membersListView').style.display = 'none';
    document.getElementById('checkInView').style.display = 'block';
    document.getElementById('pageTitle').textContent = 'Pointage Accueil';
}

function showMembersList() {
    document.getElementById('membersListView').style.display = 'block';
    document.getElementById('checkInView').style.display = 'none';
    document.getElementById('pageTitle').textContent = 'Gestion des Membres';
}

// ================================================
// FONCTIONS DE RECHERCHE ET FILTRES
// ================================================

function searchMembers() {
    const searchTerm = document.getElementById('searchMember').value.toLowerCase();
    
    filteredMembers = members.filter(m => 
        m.full_name.toLowerCase().includes(searchTerm) ||
        m.phone.toLowerCase().includes(searchTerm) ||
        m.email.toLowerCase().includes(searchTerm)
    );
    
    filterMembers(); // Appliquer les filtres supplémentaires
}

function filterMembers() {
    const statusFilter = document.getElementById('statusFilter').value;
    const subscriptionFilter = document.getElementById('subscriptionFilter').value;
    
    // Appliquer le filtre de recherche d'abord
    let filtered = [...filteredMembers];
    
    // Filtre par statut
    if (statusFilter !== 'all') {
        if (statusFilter === 'proche') {
            const today = new Date();
            const sevenDaysFromNow = new Date();
            sevenDaysFromNow.setDate(today.getDate() + 7);
            
            filtered = filtered.filter(m => {
                if (m.subscription.status !== 'actif') return false;
                const expiryDate = new Date(m.subscription.expiry_date);
                return expiryDate <= sevenDaysFromNow && expiryDate >= today;
            });
        } else {
            filtered = filtered.filter(m => m.subscription.status === statusFilter);
        }
    }
    
    // Filtre par type d'abonnement
    if (subscriptionFilter !== 'all') {
        filtered = filtered.filter(m => m.subscription.type === subscriptionFilter);
    }
    
    filteredMembers = filtered;
    currentPage = 1;
    updateStats();
    renderMembersTable();
}

function resetFilters() {
    document.getElementById('searchMember').value = '';
    document.getElementById('statusFilter').value = 'all';
    document.getElementById('subscriptionFilter').value = 'all';
    filteredMembers = [...members];
    currentPage = 1;
    updateStats();
    renderMembersTable();
}

// ================================================
// FONCTIONS D'AFFICHAGE
// ================================================

function updateStats() {
    document.getElementById('totalMembers').textContent = members.length;
    
    const actifs = members.filter(m => m.subscription.status === 'actif').length;
    const expires = members.filter(m => m.subscription.status === 'expire').length;
    document.getElementById('membersStats').textContent = `${actifs} / ${expires}`;
    
    const today = new Date();
    const sevenDaysFromNow = new Date();
    sevenDaysFromNow.setDate(today.getDate() + 7);
    
    const expiringSoon = members.filter(m => {
        if (m.subscription.status !== 'actif') return false;
        const expiryDate = new Date(m.subscription.expiry_date);
        return expiryDate <= sevenDaysFromNow && expiryDate >= today;
    }).length;
    document.getElementById('expiringSoon').textContent = expiringSoon;
    
    // Revenu du mois
    const monthRevenue = members.reduce((sum, m) => {
        const paymentMonth = new Date(m.payments[0]?.date.split('/').reverse().join('-')).getMonth();
        const currentMonth = new Date().getMonth();
        if (paymentMonth === currentMonth) {
            return sum + m.subscription.paid;
        }
        return sum;
    }, 0);
    document.getElementById('monthlyRevenue').textContent = monthRevenue + ' $';
    
    // Entrées aujourd'hui
    const todayStr = new Date().toLocaleDateString('fr-FR');
    const todayCheckins = members.reduce((sum, m) => {
        return sum + m.access_logs.filter(log => log.date === todayStr).length;
    }, 0);
    document.getElementById('todayCheckins').textContent = todayCheckins;
}

function renderMembersTable() {
    const tbody = document.getElementById('membersTableBody');
    const start = (currentPage - 1) * itemsPerPage;
    const end = start + itemsPerPage;
    const paginatedMembers = filteredMembers.slice(start, end);
    
    if (paginatedMembers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center p-4">Aucun membre trouvé</td></tr>';
    } else {
        let html = '';
        paginatedMembers.forEach(member => {
            const memberIdDisplay = 'SG-' + String(member.id).padStart(5, '0');
            const today = new Date();
            const expiryDate = new Date(member.subscription.expiry_date);
            const sevenDaysFromNow = new Date();
            sevenDaysFromNow.setDate(today.getDate() + 7);
            
            let statusClass = '';
            let statusText = '';
            
            if (member.subscription.status === 'actif') {
                if (expiryDate <= sevenDaysFromNow) {
                    statusClass = 'badge-proche-expiration';
                    statusText = 'Expire bientôt';
                } else {
                    statusClass = 'badge-actif';
                    statusText = 'Actif';
                }
            } else if (member.subscription.status === 'expire') {
                statusClass = 'badge-expire';
                statusText = 'Expiré';
            } else if (member.subscription.status === 'suspendu') {
                statusClass = 'badge-suspendu';
                statusText = 'Suspendu';
            }
            
            const lastAccess = member.access_logs[0] ? 
                `${member.access_logs[0].date} ${member.access_logs[0].time}` : 'Jamais';
            
            html += `
                <tr>
                    <td><span class="fw-medium text-muted">${memberIdDisplay}</span></td>
                    <td>
                        <div>
                            <a href="javascript:void(0);" class="fw-semibold" onclick="viewMember(${member.id})">${member.full_name}</a>
                            <span class="fs-11 text-muted d-block">${member.phone}</span>
                        </div>
                    </td>
                    <td>${member.email}</td>
                    <td>${member.subscription.type_label}</td>
                    <td>${new Date(member.subscription.expiry_date).toLocaleDateString('fr-FR')}</td>
                    <td><span class="${statusClass}">${statusText}</span></td>
                    <td>${lastAccess}</td>
                    <td class="text-end">
                        <div class="dropdown">
                            <a href="javascript:void(0);" class="btn btn-sm btn-light d-inline-flex align-items-center justify-content-center" data-bs-toggle="dropdown" title="Actions" style="width:36px;height:36px;">
                                <span class="material-icons" style="font-size:20px;">more_vert</span>
                            </a>
                            <div class="dropdown-menu dropdown-menu-end">
                                <a href="javascript:void(0);" class="dropdown-item d-flex align-items-center gap-2" onclick="viewMember(${member.id})">
                                    <span class="material-icons" style="font-size:18px;">visibility</span> Voir (${memberIdDisplay})
                                </a>
                                <a href="javascript:void(0);" class="dropdown-item d-flex align-items-center gap-2" onclick="editMember(${member.id})">
                                    <span class="material-icons" style="font-size:18px;">edit</span> Modifier
                                </a>
                            </div>
                        </div>
                    </td>
                </tr>
            `;
        });
        tbody.innerHTML = html;
    }
    
    updatePagination();
}

function updatePagination() {
    const totalItems = filteredMembers.length;
    const totalPages = Math.ceil(totalItems / itemsPerPage);
    const startItem = totalItems > 0 ? (currentPage - 1) * itemsPerPage + 1 : 0;
    const endItem = Math.min(currentPage * itemsPerPage, totalItems);
    
    document.getElementById('paginationInfo').textContent = 
        totalItems > 0 ? `Affichage ${startItem}-${endItem} sur ${totalItems} membres` : 'Aucun membre trouvé';
    
    let paginationHtml = '';
    
    if (totalPages > 0) {
        // Bouton précédent
        paginationHtml += `
            <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link d-flex align-items-center justify-content-center" href="javascript:void(0);" onclick="changePage(${currentPage - 1})" style="min-width:36px;">
                    <span class="material-icons" style="font-size:20px;">chevron_left</span>
                </a>
            </li>
        `;
        
        // Numéros de page
        for (let i = 1; i <= totalPages; i++) {
            if (i === 1 || i === totalPages || (i >= currentPage - 1 && i <= currentPage + 1)) {
                paginationHtml += `
                    <li class="page-item ${i === currentPage ? 'active' : ''}">
                        <a class="page-link" href="javascript:void(0);" onclick="changePage(${i})">${i}</a>
                    </li>
                `;
            } else if (i === currentPage - 2 || i === currentPage + 2) {
                paginationHtml += `
                    <li class="page-item disabled">
                        <a class="page-link" href="javascript:void(0);">...</a>
                    </li>
                `;
            }
        }
        
        // Bouton suivant
        paginationHtml += `
            <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link d-flex align-items-center justify-content-center" href="javascript:void(0);" onclick="changePage(${currentPage + 1})" style="min-width:36px;">
                    <span class="material-icons" style="font-size:20px;">chevron_right</span>
                </a>
            </li>
        `;
    }
    
    document.getElementById('paginationControls').innerHTML = paginationHtml;
}

function changePage(page) {
    const totalPages = Math.ceil(filteredMembers.length / itemsPerPage);
    if (page >= 1 && page <= totalPages) {
        currentPage = page;
        renderMembersTable();
    }
}

// ================================================
// FONCTIONS CRUD
// ================================================

function previewPhoto(input) {
    if (input.files && input.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            document.getElementById('photoPreview').innerHTML = `<img src="${e.target.result}" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;">`;
        }
        reader.readAsDataURL(input.files[0]);
    }
}

function resetMemberModalToAdd() {
    editingMemberId = null;
    document.getElementById('addMemberForm').reset();
    document.getElementById('photoPreview').innerHTML = '<span class="material-icons" style="font-size:32px;">camera_alt</span>';
    const modalEl = document.getElementById('addMemberModal');
    modalEl.querySelector('.modal-title').innerHTML = '<span class="material-icons me-2" style="font-size:24px;">person_add</span>Nouveau membre';
    modalEl.querySelector('.modal-footer .btn-primary').innerHTML = '<span class="material-icons me-2" style="font-size:18px;">save</span>Enregistrer le membre';
}

function saveMember() {
    const lastName = document.getElementById('memberLastName').value;
    if (!lastName) {
        Swal.fire('Erreur', 'Veuillez entrer le nom du membre', 'error');
        return;
    }
    
    const firstName = document.getElementById('memberFirstName').value;
    const fullName = firstName ? `${firstName} ${lastName}` : lastName;
    
    const subscriptionType = document.getElementById('memberSubscription').value;
    const subscriptionPrices = {
        '1mois': 50,
        '3mois': 135,
        '6mois': 240,
        '12mois': 420
    };
    
    const startDate = document.getElementById('memberStartDate').value;
    const expiryDate = new Date(startDate);
    if (subscriptionType === '1mois') expiryDate.setMonth(expiryDate.getMonth() + 1);
    else if (subscriptionType === '3mois') expiryDate.setMonth(expiryDate.getMonth() + 3);
    else if (subscriptionType === '6mois') expiryDate.setMonth(expiryDate.getMonth() + 6);
    else if (subscriptionType === '12mois') expiryDate.setFullYear(expiryDate.getFullYear() + 1);
    
    const amountPaid = parseFloat(document.getElementById('memberAmountPaid').value) || 0;
    const typeLabelEl = document.getElementById('memberSubscription').options[document.getElementById('memberSubscription').selectedIndex];
    const typeLabel = typeLabelEl ? typeLabelEl.text.split(' - ')[0] : subscriptionType;
    
    if (editingMemberId) {
        const member = members.find(m => m.id === editingMemberId);
        if (!member) {
            Swal.fire('Erreur', 'Membre introuvable', 'error');
            return;
        }
        const newPhoto = document.getElementById('memberPhoto').files && document.getElementById('memberPhoto').files[0];
        function applyMemberUpdate(photoDataUrl) {
            if (photoDataUrl) member.photo = photoDataUrl;
            member.first_name = firstName;
            member.last_name = lastName;
            member.full_name = fullName;
            member.phone = document.getElementById('memberPhone').value;
            member.email = document.getElementById('memberEmail').value;
            member.address = document.getElementById('memberAddress').value;
            member.city = document.getElementById('memberCity').value;
            member.zip = document.getElementById('memberZip').value || undefined;
            member.subscription.type = subscriptionType;
            member.subscription.type_label = typeLabel;
            member.subscription.start_date = startDate;
            member.subscription.expiry_date = expiryDate.toISOString().split('T')[0];
            member.subscription.price = subscriptionPrices[subscriptionType] || member.subscription.price;
            member.subscription.paid = amountPaid;
            member.subscription.status = amountPaid >= (subscriptionPrices[subscriptionType] || member.subscription.price) ? 'actif' : 'suspendu';
            member.status = member.subscription.status;
            resetFilters();
            const modal = bootstrap.Modal.getInstance(document.getElementById('addMemberModal'));
            modal.hide();
            resetMemberModalToAdd();
            Swal.fire('Succès', 'Membre modifié avec succès', 'success');
        }
        if (newPhoto) {
            const reader = new FileReader();
            reader.onload = function(e) { applyMemberUpdate(e.target.result); };
            reader.readAsDataURL(newPhoto);
        } else {
            applyMemberUpdate(null);
        }
        return;
    }
    
    const gender = Math.random() > 0.5 ? 'men' : 'women';
    const randomId = Math.floor(Math.random() * 50) + 1;
    const photo = `https://randomuser.me/api/portraits/${gender}/${randomId}.jpg`;
    
    const newMember = {
        id: members.length + 1,
        first_name: firstName,
        last_name: lastName,
        full_name: fullName,
        phone: document.getElementById('memberPhone').value,
        email: document.getElementById('memberEmail').value,
        address: document.getElementById('memberAddress').value,
        city: document.getElementById('memberCity').value,
        photo: photo,
        subscription: {
            type: subscriptionType,
            type_label: typeLabel,
            start_date: startDate,
            expiry_date: expiryDate.toISOString().split('T')[0],
            price: subscriptionPrices[subscriptionType],
            paid: amountPaid,
            status: amountPaid >= subscriptionPrices[subscriptionType] ? 'actif' : 'suspendu'
        },
        payments: [
            {
                date: new Date().toLocaleDateString('fr-FR'),
                amount: amountPaid,
                method: document.getElementById('memberPaymentMethod').value,
                status: 'paye'
            }
        ],
        access_logs: [],
        documents: [],
        created_at: new Date().toLocaleDateString('fr-FR'),
        status: amountPaid >= subscriptionPrices[subscriptionType] ? 'actif' : 'suspendu'
    };
    
    members.push(newMember);
    resetFilters();
    
    const modal = bootstrap.Modal.getInstance(document.getElementById('addMemberModal'));
    modal.hide();
    resetMemberModalToAdd();
    
    Swal.fire('Succès', 'Membre ajouté avec succès', 'success');
    
    if (document.getElementById('memberSendWelcome').checked) {
        setTimeout(() => {
            Swal.fire('Email envoyé', 'Un email de bienvenue avec QR code a été envoyé', 'info');
        }, 1000);
    }
}

function viewMember(id) {
    currentMemberId = id;
    const member = members.find(m => m.id === id);
    
    if (member) {
        // Informations de base
        const memberIdDisplay = 'SG-' + String(member.id).padStart(5, '0');
        document.getElementById('viewMemberId').textContent = memberIdDisplay;
        document.getElementById('viewMemberName').textContent = member.full_name;
        document.getElementById('viewMemberPhone').textContent = member.phone;
        document.getElementById('viewMemberEmail').textContent = member.email;
        
        if (member.photo) {
            document.getElementById('viewMemberPhoto').innerHTML = 
                `<img src="${member.photo}" class="member-avatar-lg">`;
        } else {
            const initials = member.full_name.split(' ').map(n => n[0]).join('');
            document.getElementById('viewMemberPhoto').innerHTML = initials;
        }
        
        // Statut
        const statusSpan = document.getElementById('viewMemberStatus');
        if (member.subscription.status === 'actif') {
            const today = new Date();
            const expiryDate = new Date(member.subscription.expiry_date);
            const sevenDaysFromNow = new Date();
            sevenDaysFromNow.setDate(today.getDate() + 7);
            
            if (expiryDate <= sevenDaysFromNow) {
                statusSpan.className = 'badge-proche-expiration mb-2';
                statusSpan.textContent = 'Expire bientôt';
            } else {
                statusSpan.className = 'badge-actif mb-2';
                statusSpan.textContent = 'Actif';
            }
        } else if (member.subscription.status === 'expire') {
            statusSpan.className = 'badge-expire mb-2';
            statusSpan.textContent = 'Expiré';
        } else {
            statusSpan.className = 'badge-suspendu mb-2';
            statusSpan.textContent = 'Suspendu';
        }
        
        // Bouton suspendre/activer
        const suspendBtn = document.getElementById('suspendBtn');
        if (member.subscription.status === 'suspendu') {
            suspendBtn.innerHTML = '<span class="material-icons me-2" style="font-size:18px;">play_circle</span>Activer';
        } else {
            suspendBtn.innerHTML = '<span class="material-icons me-2" style="font-size:18px;">pause_circle</span>Suspendre';
        }
        
        // Abonnement
        document.getElementById('viewSubscriptionType').textContent = member.subscription.type_label;
        document.getElementById('viewStartDate').textContent = new Date(member.subscription.start_date).toLocaleDateString('fr-FR');
        document.getElementById('viewExpiryDate').textContent = new Date(member.subscription.expiry_date).toLocaleDateString('fr-FR');
        document.getElementById('viewPrice').textContent = member.subscription.price + ' $';
        document.getElementById('viewPaid').textContent = member.subscription.paid + ' $';
        document.getElementById('viewRemaining').textContent = (member.subscription.price - member.subscription.paid) + ' $';
        
        // Historique des abonnements
        const historyHtml = `
            <div class="timeline-item">
                <div class="fw-semibold">${member.subscription.type_label}</div>
                <div class="text-muted small">Du ${new Date(member.subscription.start_date).toLocaleDateString('fr-FR')} au ${new Date(member.subscription.expiry_date).toLocaleDateString('fr-FR')}</div>
            </div>
        `;
        document.getElementById('subscriptionHistory').innerHTML = historyHtml;
        
        // Paiements
        let paymentsHtml = '';
        member.payments.forEach(p => {
            paymentsHtml += `
                <tr>
                    <td>${p.date}</td>
                    <td>${p.amount} $</td>
                    <td>${p.method === 'cash' ? 'Cash' : p.method === 'card' ? 'Carte' : 'Mobile Money'}</td>
                    <td><span class="badge-actif">Payé</span></td>
                </tr>
            `;
        });
        document.getElementById('paymentHistory').innerHTML = paymentsHtml || '<tr><td colspan="4" class="text-center">Aucun paiement</td></tr>';
        
        // Accès
        let accessHtml = '';
        member.access_logs.slice(0, 5).forEach(log => {
            accessHtml += `
                <tr>
                    <td>${log.date}</td>
                    <td>${log.time}</td>
                    <td>${log.method}</td>
                </tr>
            `;
        });
        document.getElementById('accessHistory').innerHTML = accessHtml || '<tr><td colspan="3" class="text-center">Aucun accès</td></tr>';
        
        // QR Code avec librairie externe
        const qrContainer = document.getElementById('memberQRCode');
        qrContainer.innerHTML = ''; // Vider le conteneur
        
        // Générer un vrai QR code
        const qrData = `SG-${member.id.toString().padStart(5, '0')}`;
        QRCode.toCanvas(qrData, { width: 150 }, function(error, canvas) {
            if (error) {
                console.error(error);
                qrContainer.innerHTML = '<p>Erreur de génération QR code</p>';
            } else {
                qrContainer.appendChild(canvas);
            }
        });
        
        const modal = new bootstrap.Modal(document.getElementById('viewMemberModal'));
        modal.show();
        
        // Graphique des accès
        setTimeout(() => {
            createAccessChart(member);
        }, 300);
    }
}

function createAccessChart(member) {
    const ctx = document.getElementById('accessChart').getContext('2d');
    
    // Compter les accès par jour
    const last7Days = [];
    const counts = [];
    
    for (let i = 6; i >= 0; i--) {
        const date = new Date();
        date.setDate(date.getDate() - i);
        const dateStr = date.toLocaleDateString('fr-FR');
        last7Days.push(dateStr.split('/')[0]); // Juste le jour
        
        const count = member.access_logs.filter(log => log.date === dateStr).length;
        counts.push(count);
    }
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: last7Days,
            datasets: [{
                label: 'Nombre d\'accès',
                data: counts,
                borderColor: '#3454d1',
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    });
}

function suspendMember() {
    const member = members.find(m => m.id === currentMemberId);
    if (member) {
        const newStatus = member.subscription.status === 'suspendu' ? 'actif' : 'suspendu';
        const action = newStatus === 'suspendu' ? 'suspendre' : 'activer';
        
        Swal.fire({
            title: `Confirmation`,
            text: `Êtes-vous sûr de vouloir ${action} ce membre ?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Oui',
            cancelButtonText: 'Non'
        }).then((result) => {
            if (result.isConfirmed) {
                member.subscription.status = newStatus;
                member.status = newStatus;
                
                const modal = bootstrap.Modal.getInstance(document.getElementById('viewMemberModal'));
                modal.hide();
                
                resetFilters();
                
                Swal.fire('Succès', `Membre ${action} avec succès`, 'success');
            }
        });
    }
}

function editMemberFromView() {
    const modal = bootstrap.Modal.getInstance(document.getElementById('viewMemberModal'));
    modal.hide();
    setTimeout(() => editMember(currentMemberId), 500);
}

function editMember(id) {
    const member = members.find(m => m.id === id);
    if (!member) {
        Swal.fire('Erreur', 'Membre introuvable', 'error');
        return;
    }
    editingMemberId = id;
    const modalEl = document.getElementById('addMemberModal');
    const modalTitle = modalEl.querySelector('.modal-title');
    const saveBtn = modalEl.querySelector('.modal-footer .btn-primary');
    modalTitle.innerHTML = '<span class="material-icons me-2" style="font-size:24px;">edit</span>Modifier le membre';
    saveBtn.innerHTML = '<span class="material-icons me-2" style="font-size:18px;">save</span>Enregistrer les modifications';
    document.getElementById('memberLastName').value = member.last_name || '';
    document.getElementById('memberFirstName').value = member.first_name || '';
    document.getElementById('memberPhone').value = member.phone || '';
    document.getElementById('memberEmail').value = member.email || '';
    document.getElementById('memberAddress').value = member.address || '';
    document.getElementById('memberCity').value = member.city || '';
    document.getElementById('memberZip').value = member.zip || '';
    document.getElementById('memberSubscription').value = member.subscription.type || '';
    document.getElementById('memberStartDate').value = member.subscription.start_date || '';
    const lastPayment = member.payments && member.payments.length ? member.payments[member.payments.length - 1] : null;
    document.getElementById('memberPaymentMethod').value = (lastPayment && lastPayment.method) ? lastPayment.method : 'cash';
    document.getElementById('memberAmountPaid').value = member.subscription.paid != null ? member.subscription.paid : '';
    document.getElementById('memberSendWelcome').checked = false;
    if (member.photo) {
        document.getElementById('photoPreview').innerHTML = `<img src="${member.photo}" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;">`;
    } else {
        document.getElementById('photoPreview').innerHTML = '<span class="material-icons" style="font-size:32px;">camera_alt</span>';
    }
    document.getElementById('memberPhoto').value = '';
    new bootstrap.Modal(modalEl).show();
}

// ================================================
// FONCTIONS ACCUEIL (CHECK-IN)
// ================================================

function searchCheckin() {
    const searchTerm = document.getElementById('checkinSearch').value.toLowerCase();
    
    if (searchTerm.length < 2) {
        document.getElementById('compactMemberView').innerHTML = `
            <div class="text-center text-muted py-5">
                <span class="material-icons" style="font-size:48px;">person</span>
                <p class="mt-2">Recherchez un membre pour afficher sa fiche compacte</p>
            </div>
        `;
        return;
    }
    
    const member = members.find(m => 
        m.full_name.toLowerCase().includes(searchTerm) ||
        m.phone.includes(searchTerm)
    );
    
    if (member) {
        const today = new Date();
        const expiryDate = new Date(member.subscription.expiry_date);
        const status = member.subscription.status === 'actif' && expiryDate >= today ? 'Actif' : 'Non actif';
        const statusClass = member.subscription.status === 'actif' && expiryDate >= today ? 'badge-actif' : 'badge-expire';
        
        const memberPhoto = member.photo ? 
            `<img src="${member.photo}" class="member-photo">` : 
            `<div class="member-photo-placeholder">${member.full_name.split(' ').map(n => n[0]).join('')}</div>`;
        
        document.getElementById('compactMemberView').innerHTML = `
            <div class="member-compact-card">
                <div class="d-flex align-items-center gap-3 mb-3">
                    ${memberPhoto}
                    <div>
                        <h4 class="text-white mb-1">${member.full_name}</h4>
                        <p class="text-white-50 mb-0">${member.phone}</p>
                    </div>
                </div>
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="${statusClass}">${status}</span>
                        <p class="text-white-50 small mt-2">Expire le: ${new Date(member.subscription.expiry_date).toLocaleDateString('fr-FR')}</p>
                    </div>
                    <button class="btn btn-light" onclick="recordAccess(${member.id})">
                        <span class="material-icons me-2" style="font-size:18px;">check_circle</span>Enregistrer entrée
                    </button>
                </div>
            </div>
        `;
    } else {
        document.getElementById('compactMemberView').innerHTML = `
            <div class="alert alert-warning">
                Aucun membre trouvé
            </div>
        `;
    }
}

function startQRScanner() {
    document.getElementById('qr-reader').style.display = 'block';
    
    if (!html5QrCode) {
        html5QrCode = new Html5Qrcode("qr-reader");
        
        html5QrCode.start(
            { facingMode: "environment" },
            {
                fps: 10,
                qrbox: 250
            },
            (decodedText) => {
                // Quand un QR code est scanné
                html5QrCode.stop();
                document.getElementById('qr-reader').style.display = 'none';
                
                // Chercher le membre par son ID (format SG-XXXXX)
                const match = decodedText.match(/SG-(\d+)/);
                if (match) {
                    const memberId = parseInt(match[1]);
                    const member = members.find(m => m.id === memberId);
                    
                    if (member) {
                        document.getElementById('checkinSearch').value = member.full_name;
                        searchCheckin();
                    } else {
                        Swal.fire('Erreur', 'QR code non reconnu', 'error');
                    }
                } else {
                    Swal.fire('Erreur', 'Format de QR code invalide', 'error');
                }
            },
            (error) => {
                // Ignorer les erreurs de scan
            }
        ).catch((err) => {
            Swal.fire('Erreur', 'Impossible d\'accéder à la caméra', 'error');
        });
    }
}

function recordAccess(memberId) {
    const member = members.find(m => m.id === memberId);
    
    if (member) {
        const today = new Date();
        const expiryDate = new Date(member.subscription.expiry_date);
        
        if (member.subscription.status !== 'actif' || expiryDate < today) {
            Swal.fire('Accès refusé', 'L\'abonnement de ce membre n\'est pas actif', 'error');
            return;
        }
        
        const now = new Date();
        const timeStr = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const dateStr = now.toLocaleDateString('fr-FR');
        
        member.access_logs.unshift({
            date: dateStr,
            time: timeStr,
            method: 'Manuel'
        });
        
        Swal.fire({
            icon: 'success',
            title: 'Accès autorisé',
            text: `Bienvenue ${member.full_name}`,
            timer: 2000
        });
        
        updateStats();
    }
}

// ================================================
// FONCTIONS DIVERSES
// ================================================

function exportMembers() {
    Swal.fire('Export', 'Export des membres en cours...', 'info');
}

function printMembers() {
    Swal.fire('Impression', 'Préparation de l\'impression...', 'info');
}



// ================================================
// INITIALISATION
// ================================================

document.addEventListener('DOMContentLoaded', function() {
    document.querySelector('.b-brand .logo-sm').style.display = 'none';
    var urlParams = new URLSearchParams(window.location.search);
    var filterParam = urlParams.get('filter');
    var isExpire = filterParam === 'expire';
    var elTous = document.getElementById('nav-clients-tous');
    var elExpire = document.getElementById('nav-clients-expire');
    if (elTous) elTous.classList.toggle('active', !isExpire);
    if (elExpire) elExpire.classList.toggle('active', isExpire);
    showMembersList();
    resetFilters();
    // Réinitialiser le modal membre à la fermeture (Annuler ou après enregistrement)
    var addMemberModalEl = document.getElementById('addMemberModal');
    if (addMemberModalEl) {
        addMemberModalEl.addEventListener('hidden.bs.modal', function() {
            resetMemberModalToAdd();
        });
    }
    // Ouvrir le modal "Nouveau membre" si arrivée via lien "Nouveau client" (hash #add ou ?action=add)
    if (window.location.hash === '#add' || urlParams.get('action') === 'add') {
        window.history.replaceState(null, '', window.location.pathname + (window.location.search || ''));
        setTimeout(function() {
            var modalEl = document.getElementById('addMemberModal');
            if (modalEl) new bootstrap.Modal(modalEl).show();
        }, 300);
    }
});
