
// Sous-modules Abonnements : synchronisation avec ?tab=
function showAbonnementsTab(tab) {
    const validTabs = ['formules', 'promos', 'renouvellements'];
    const t = validTabs.includes(tab) ? tab : 'formules';
    const pane = document.getElementById(t);
    if (pane) {
        document.querySelectorAll('#subscriptionTabsContent .tab-pane').forEach(el => {
            el.classList.remove('show', 'active');
        });
        pane.classList.add('show', 'active');
    }
    
    // Activer le bouton d'onglet correspondant
    document.querySelectorAll('#subscriptionTabs .nav-link').forEach(el => {
        el.classList.remove('active');
    });
    document.getElementById(t + '-tab')?.classList.add('active');
    
    ['formules', 'promos', 'renouvellements'].forEach(id => {
        const el = document.getElementById('nav-abonnements-' + id);
        if (el) el.classList.toggle('active', id === t);
    });
    
    const url = new URL(window.location);
    url.searchParams.set('tab', t);
    window.history.replaceState({}, '', url);
    
    const titles = {
        formules: 'Gestion des Abonnements - Formules',
        promos: 'Gestion des Abonnements - Promotions',
        renouvellements: 'Gestion des Abonnements - Renouvellements'
    };
    const titleEl = document.getElementById('pageAbonnementsTitle');
    if (titleEl) titleEl.textContent = titles[t] || titles.formules;
}

const formulesData = {
    1: { nom: '1 mois', duree: 30, prixUsd: 45, prixCdf: 0, description: 'Accès illimité, Cours collectifs', badge: 'primary', populaire: false },
    2: { nom: '3 mois', duree: 90, prixUsd: 120, prixCdf: 0, description: 'Accès illimité, Cours collectifs, 1 séance coaching/mois', badge: 'success', populaire: true },
    3: { nom: '12 mois', duree: 365, prixUsd: 399, prixCdf: 0, description: 'Accès illimité, Tous les cours, Coaching hebdomadaire, Accès VIP, Invitations événements', badge: 'warning', populaire: false },
    4: { nom: '6 mois', duree: 180, prixUsd: 210, prixCdf: 0, description: 'Accès illimité, Tous les cours, 2 séances coaching/mois, Accès prioritaire', badge: 'info', populaire: false },
    5: { nom: 'Journalier', duree: 1, prixUsd: 10, prixCdf: 0, description: 'Accès journée, Cours collectifs', badge: 'secondary', populaire: false },
    6: { nom: 'Entreprise', duree: 30, prixUsd: 0, prixCdf: 0, description: 'Forfait groupe, Facturation mensuelle, Suivi personnalisé', badge: 'purple', populaire: false }
};

function ouvrirModalNouvelleFormule() {
    document.getElementById('formuleId').value = '';
    document.getElementById('newFormuleForm').reset();
    document.getElementById('formuleDuree').value = '30';
    document.getElementById('formuleBadge').value = 'primary';
    document.getElementById('formulePopulaire').checked = false;
    document.getElementById('addFormuleModalTitle').textContent = 'Créer une nouvelle formule';
    document.getElementById('addFormuleBtn').textContent = 'Créer la formule';
    const modalEl = document.getElementById('addFormuleModal');
    if (modalEl) new bootstrap.Modal(modalEl).show();
}

function editerFormule(id) {
    const f = formulesData[id];
    if (!f) {
        Swal.fire({ icon: 'warning', title: 'Formule inconnue', text: 'Données de la formule #' + id, confirmButtonColor: '#3454d1' });
        return;
    }
    document.getElementById('formuleId').value = id;
    document.getElementById('formuleNom').value = f.nom;
    document.getElementById('formuleDuree').value = f.duree;
    document.getElementById('formulePrixUsd').value = f.prixUsd;
    document.getElementById('formulePrixCdf').value = f.prixCdf;
    document.getElementById('formuleDesc').value = f.description;
    document.getElementById('formuleBadge').value = f.badge || 'primary';
    document.getElementById('formulePopulaire').checked = f.populaire || false;
    document.getElementById('addFormuleModalTitle').textContent = 'Modifier la formule';
    document.getElementById('addFormuleBtn').textContent = 'Enregistrer les modifications';
    const modalEl = document.getElementById('addFormuleModal');
    if (modalEl) new bootstrap.Modal(modalEl).show();
}

function exporterFormules() {
    Swal.fire({
        icon: 'success',
        title: 'Export réussi',
        text: 'Les formules ont été exportées au format Excel',
        timer: 2000,
        showConfirmButton: false
    });
}

function exporterRenouvellements() {
    Swal.fire({
        icon: 'success',
        title: 'Export réussi',
        text: 'La liste des renouvellements a été exportée',
        timer: 2000,
        showConfirmButton: false
    });
}

function voirRenouvellement(el) {
    const row = el.closest('tr');
    if (!row) return;
    const cells = row.querySelectorAll('td');
    const client = cells[0] ? cells[0].textContent.trim() : '-';
    const formule = cells[1] ? cells[1].textContent.trim() : '-';
    const echeance = cells[2] ? cells[2].textContent.trim() : '-';
    const montant = cells[3] ? cells[3].textContent.trim() : '-';
    const mode = cells[4] ? cells[4].textContent.trim() : '-';
    const statut = cells[5] ? cells[5].textContent.trim() : '-';

    Swal.fire({
        title: 'Détail du renouvellement',
        html: `
            <div class="text-start">
                <p><strong>Client :</strong> ${client}</p>
                <p><strong>Formule actuelle :</strong> ${formule}</p>
                <p><strong>Date d'échéance :</strong> ${echeance}</p>
                <p><strong>Montant :</strong> ${montant}</p>
                <p><strong>Mode :</strong> ${mode}</p>
                <p><strong>Statut :</strong> ${statut}</p>
            </div>
        `,
        icon: 'info',
        confirmButtonColor: '#3454d1'
    });
}

function dupliquerFormule() {
    Swal.fire({
        title: 'Dupliquer une formule',
        input: 'select',
        inputOptions: { 
            1: '1 mois', 
            2: '3 mois', 
            3: '12 mois',
            4: '6 mois',
            5: 'Journalier',
            6: 'Entreprise'
        },
        inputPlaceholder: 'Choisir une formule',
        confirmButtonColor: '#3454d1'
    });
}

const promotionsData = {
    1: { code: 'FETE25', reduction: 25, formules: ['1 mois', '3 mois'], dateDebut: '2026-03-01', dateFin: '2026-03-31', maxUtil: 100, statut: 'actif', desc: 'Promotion Fête du travail' },
    2: { code: 'WELCOME', reduction: 15, formules: ['Toutes'], permanent: true, maxUtil: null, statut: 'actif', desc: 'Bienvenue nouveaux clients' },
    3: { code: 'COUPLE', reduction: 20, formules: ['6 mois', '12 mois'], dateDebut: '2026-02-01', dateFin: '2026-02-28', maxUtil: 50, statut: 'expire', desc: 'Offre couple Février' },
    4: { code: 'ETUDIANT', reduction: 30, formules: ['6 mois', '12 mois'], dateDebut: '2026-01-01', dateFin: '2026-12-31', maxUtil: 200, statut: 'actif', desc: 'Tarif étudiant' },
    5: { code: 'FAMILLE', reduction: 25, formules: ['Toutes'], dateDebut: '2026-06-01', dateFin: '2026-08-31', maxUtil: 100, statut: 'actif', desc: 'Offre été famille' }
};

function togglePromoToutes() {
    const toutes = document.getElementById('promoToutes').checked;
    ['promoFormule1','promoFormule3','promoFormule6','promoFormule12'].forEach(id => {
        const el = document.getElementById(id);
        el.disabled = toutes;
        if (toutes) el.checked = false;
    });
}

function togglePromoDates() {
    const permanent = document.getElementById('promoPermanent').checked;
    const wrap = document.getElementById('promoDatesWrap');
    wrap.style.opacity = permanent ? '0.5' : '1';
    wrap.style.pointerEvents = permanent ? 'none' : 'auto';
    document.getElementById('promoDateDebut').disabled = permanent;
    document.getElementById('promoDateFin').disabled = permanent;
    if (permanent) {
        document.getElementById('promoDateDebut').value = '';
        document.getElementById('promoDateFin').value = '';
    }
}

function resetPromoForm() {
    document.getElementById('promoForm').reset();
    document.getElementById('promoId').value = '';
    ['promoFormule1','promoFormule3','promoFormule6','promoFormule12'].forEach(id => {
        document.getElementById(id).disabled = false;
    });
    document.getElementById('promoDatesWrap').style.opacity = '1';
    document.getElementById('promoDatesWrap').style.pointerEvents = 'auto';
    document.getElementById('promoDateDebut').disabled = false;
    document.getElementById('promoDateFin').disabled = false;
    document.getElementById('promoPermanent').checked = false;
}

function creerPromo() {
    resetPromoForm();
    document.getElementById('promoModalTitle').textContent = 'Créer une promotion';
    document.getElementById('promoSaveBtn').textContent = 'Créer la promotion';
    const modal = new bootstrap.Modal(document.getElementById('promoModal'));
    modal.show();
}

function editerPromo(id) {
    resetPromoForm();
    const p = promotionsData[id];
    if (!p) {
        Swal.fire({ icon: 'warning', title: 'Promotion introuvable', text: `La promotion #${id} n'existe pas` });
        return;
    }
    document.getElementById('promoModalTitle').textContent = 'Modifier la promotion';
    document.getElementById('promoSaveBtn').textContent = 'Enregistrer les modifications';
    document.getElementById('promoId').value = id;
    document.getElementById('promoCode').value = p.code;
    document.getElementById('promoReduction').value = p.reduction;
    document.getElementById('promoStatut').value = p.statut === 'expire' ? 'inactif' : p.statut;
    document.getElementById('promoDesc').value = p.desc || '';
    document.getElementById('promoMaxUtil').value = p.maxUtil || '';
    document.getElementById('promoPermanent').checked = !!p.permanent;
    document.getElementById('promoDateDebut').value = p.dateDebut || '';
    document.getElementById('promoDateFin').value = p.dateFin || '';
    document.getElementById('promoFormule1').checked = (p.formules || []).includes('1 mois');
    document.getElementById('promoFormule3').checked = (p.formules || []).includes('3 mois');
    document.getElementById('promoFormule6').checked = (p.formules || []).includes('6 mois');
    document.getElementById('promoFormule12').checked = (p.formules || []).includes('12 mois');
    document.getElementById('promoToutes').checked = (p.formules || []).includes('Toutes') || (p.formules || []).length >= 4;
    togglePromoToutes();
    togglePromoDates();
    const modal = new bootstrap.Modal(document.getElementById('promoModal'));
    modal.show();
}

function sauvegarderPromo() {
    const code = document.getElementById('promoCode').value.trim();
    const reduction = document.getElementById('promoReduction').value;
    if (!code) {
        Swal.fire({ icon: 'warning', title: 'Champ requis', text: 'Veuillez saisir le code promo' });
        return;
    }
    if (!reduction || reduction < 1 || reduction > 100) {
        Swal.fire({ icon: 'warning', title: 'Réduction invalide', text: 'La réduction doit être entre 1 et 100%' });
        return;
    }
    const formules = [];
    if (document.getElementById('promoToutes').checked) {
        formules.push('Toutes');
    } else {
        if (document.getElementById('promoFormule1').checked) formules.push('1 mois');
        if (document.getElementById('promoFormule3').checked) formules.push('3 mois');
        if (document.getElementById('promoFormule6').checked) formules.push('6 mois');
        if (document.getElementById('promoFormule12').checked) formules.push('12 mois');
    }
    if (formules.length === 0 && !document.getElementById('promoToutes').checked) {
        Swal.fire({ icon: 'warning', title: 'Champ requis', text: 'Sélectionnez au moins une formule' });
        return;
    }
    bootstrap.Modal.getInstance(document.getElementById('promoModal')).hide();
    Swal.fire({
        icon: 'success',
        title: document.getElementById('promoId').value ? 'Promotion modifiée' : 'Promotion créée',
        text: `Code: ${code} - ${reduction}% - Formules: ${formules.join(', ') || 'Toutes'}`,
        timer: 2000,
        showConfirmButton: false
    });
}

function sauvegarderFormule() {
    const id = document.getElementById('formuleId').value;
    const isEdit = id !== '';
    const nom = document.getElementById('formuleNom').value.trim();
    if (!nom) {
        Swal.fire({ icon: 'warning', title: 'Champ requis', text: 'Le nom de la formule est obligatoire.', confirmButtonColor: '#3454d1' });
        return;
    }
    const modalEl = document.getElementById('addFormuleModal');
    if (modalEl) {
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();
    }
    document.getElementById('formuleId').value = '';
    document.getElementById('newFormuleForm').reset();
    document.getElementById('formuleDuree').value = '30';
    document.getElementById('addFormuleModalTitle').textContent = 'Créer une nouvelle formule';
    document.getElementById('addFormuleBtn').textContent = 'Créer la formule';
    Swal.fire({
        icon: 'success',
        title: isEdit ? 'Formule modifiée' : 'Formule créée',
        text: isEdit ? 'Les modifications ont été enregistrées.' : 'La nouvelle formule a été ajoutée avec succès.',
        timer: 2000,
        showConfirmButton: false
    });
}

function supprimerPromo(id) {
    Swal.fire({
        title: 'Confirmer la suppression',
        text: 'Cette action est irréversible',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        confirmButtonText: 'Supprimer',
        cancelButtonText: 'Annuler'
    });
}

function showAide() {
    Swal.fire({
        title: 'Aide - Module Abonnements',
        html: `
            <div class="text-start">
                <p><span class="material-icons text-success me-2" style="font-size: 16px;">check_circle</span> Gérez vos formules d'abonnement</p>
                <p><span class="material-icons text-success me-2" style="font-size: 16px;">check_circle</span> Créez des promotions personnalisées</p>
                <p><span class="material-icons text-success me-2" style="font-size: 16px;">check_circle</span> Suivez les renouvellements automatiques</p>
                <p><span class="material-icons text-success me-2" style="font-size: 16px;">check_circle</span> Tarifs multi-devises (USD/CDF)</p>
            </div>
        `,
        icon: 'info',
        confirmButtonColor: '#3454d1'
    });
}

document.addEventListener('DOMContentLoaded', function() {
    if (document.querySelector('.b-brand .logo-sm')) {
        document.querySelector('.b-brand .logo-sm').style.display = 'none';
    }
    const urlParams = new URLSearchParams(window.location.search);
    const tabParam = urlParams.get('tab');
    showAbonnementsTab(tabParam || 'formules');
    
    const addFormuleModalEl = document.getElementById('addFormuleModal');
    if (addFormuleModalEl) {
        addFormuleModalEl.addEventListener('show.bs.modal', function() {
            if (!document.getElementById('formuleId').value) {
                document.getElementById('newFormuleForm').reset();
                document.getElementById('formuleDuree').value = '30';
                document.getElementById('addFormuleModalTitle').textContent = 'Créer une nouvelle formule';
                document.getElementById('addFormuleBtn').textContent = 'Créer la formule';
            }
        });
    }
});
