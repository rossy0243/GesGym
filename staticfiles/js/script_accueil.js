
(function() {
    // ============================================
    // FONCTION D'INSCRIPTION - STRUCTURE COMPLÈTE
    // ============================================

    // ---------- 1. BASE DE DONNÉES SIMULÉE ----------
    const clientsDB = {
    '123456': null,  // Clients existants (sans mot de passe)
    '789012': null,
    '345678': null
    };

    // Stockage des mots de passe après inscription
    const passwords = {};

    // ---------- 2. SÉLECTION DES ÉLÉMENTS DOM ----------
    // Overlay et boutons
    const overlay = document.getElementById('modalOverlay');
    const closeBtn = document.getElementById('closeModal');
    
    // Boutons desktop
    const registerBtn = document.getElementById('registerBtn');
    
    // Boutons mobile
    const mobileRegisterBtn = document.getElementById('mobileRegisterBtn');
    
    // Éléments de la modale inscription
    const registerModal = document.getElementById('registerModal');
    const step1 = document.getElementById('registerStep1');
    const step2 = document.getElementById('registerStep2');
    
    // Champs du formulaire inscription
    const clientNumberInput = document.getElementById('clientNumber');
    const password1 = document.getElementById('password1');
    const password2 = document.getElementById('password2');
    
    // Boutons d'action inscription
    const checkClientBtn = document.getElementById('checkClientBtn');
    const createAccountBtn = document.getElementById('createAccountBtn');
    
    // Message d'erreur inscription
    const registerError = document.getElementById('registerError');

    // Éléments connexion (désactivés)
    const loginModal = document.getElementById('loginModal');
    const loginSubmitBtn = document.getElementById('loginSubmitBtn');

    // Variable pour stocker le numéro en cours d'inscription
    let currentRegisterNumber = '';

    // ---------- 3. FONCTION D'OUVERTURE DE LA MODALE D'INSCRIPTION ----------
    function openRegisterModal() {
    // Afficher l'overlay
    overlay.classList.add('active');
    
    // Cacher les erreurs précédentes
    registerError.classList.add('hidden');
    
    // Afficher la modale d'inscription et cacher celle de connexion
    registerModal.style.display = 'block';
    loginModal.style.display = 'none';
    
    // Réinitialiser à l'étape 1
    step1.style.display = 'block';
    step2.style.display = 'none';
    
    // Vider les champs
    clientNumberInput.value = '';
    password1.value = '';
    password2.value = '';
    }

    // ---------- 4. FONCTION D'OUVERTURE DE LA MODALE DE CONNEXION (désactivée) ----------
    function openLoginModal() {
    // Ne rien faire - connexion désactivée
    console.log('Connexion désactivée');
    }

    // ---------- 5. FONCTION DE FERMETURE ----------
    function closeModal() {
    overlay.classList.remove('active');
    registerError.classList.add('hidden');
    }

    // ---------- 6. EVENT LISTENERS : OUVERTURE INSCRIPTION (desktop et mobile) ----------
    if (registerBtn) {
    registerBtn.addEventListener('click', (e) => {
        e.preventDefault();
        openRegisterModal();
    });
    }
    
    if (mobileRegisterBtn) {
    mobileRegisterBtn.addEventListener('click', (e) => {
        e.preventDefault();
        openRegisterModal();
        // Fermer le menu mobile après ouverture
        document.getElementById('mobile-menu').classList.remove('open');
        const icon = document.querySelector('#menu-btn i');
        if (icon) {
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
        }
    });
    }

    // ---------- 7. BOUTONS CONNEXION ----------
    // Les boutons Connexion sont des liens HTML classiques.
    // Ne pas intercepter le clic ici : l'URL Django est deja rendue dans href.

    // ---------- 8. EVENT LISTENER : FERMETURE ----------
    closeBtn.addEventListener('click', closeModal);
    
    // Fermeture en cliquant sur l'overlay
    overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closeModal();
    });

    // ---------- 9. FONCTION ÉTAPE 1 : VÉRIFICATION NUMÉRO ----------
    checkClientBtn.addEventListener('click', () => {
    // Récupérer et nettoyer la valeur
    const num = clientNumberInput.value.trim();
    
    // Validation : champ vide
    if (num === '') {
        registerError.textContent = 'Veuillez saisir un numéro.';
        registerError.classList.remove('hidden');
        return;
    }
    
    // Vérifier si le numéro existe dans la base
    if (clientsDB.hasOwnProperty(num)) {
        // Numéro valide : passer à l'étape 2
        currentRegisterNumber = num;
        step1.style.display = 'none';
        step2.style.display = 'block';
        registerError.classList.add('hidden');
    } else {
        // Numéro inconnu : afficher erreur
        registerError.textContent = 'Numéro client inconnu.';
        registerError.classList.remove('hidden');
    }
    });

    // ---------- 10. FONCTION ÉTAPE 2 : CRÉATION DU COMPTE ----------
    createAccountBtn.addEventListener('click', () => {
    // Récupérer les mots de passe
    const pwd1 = password1.value;
    const pwd2 = password2.value;
    
    // Validation 1 : champs vides
    if (pwd1 === '' || pwd2 === '') {
        registerError.textContent = 'Veuillez remplir les mots de passe.';
        registerError.classList.remove('hidden');
        return;
    }
    
    // Validation 2 : correspondance des mots de passe
    if (pwd1 !== pwd2) {
        registerError.textContent = 'Les mots de passe ne correspondent pas.';
        registerError.classList.remove('hidden');
        return;
    }
    
    // Validation 3 : longueur minimum
    if (pwd1.length < 3) {
        registerError.textContent = 'Le mot de passe doit contenir au moins 3 caractères.';
        registerError.classList.remove('hidden');
        return;
    }

    // ---------- 11. ENREGISTREMENT DU COMPTE ----------
    // Stocker le mot de passe
    passwords[currentRegisterNumber] = pwd1;
    
    // Afficher message de succès (SweetAlert2)
    Swal.fire({
        icon: 'success',
        title: 'Compte créé !',
        text: 'Votre compte a été créé avec succès. Vous pouvez maintenant vous connecter.',
        timer: 2000,
        showConfirmButton: true
    }).then(() => {
        // Fermer la modale après le succès
        closeModal();
    });
    });

    // ---------- 12. BOUTON CONNEXION MODALE DÉSACTIVÉ ----------
    if (loginSubmitBtn) {
    loginSubmitBtn.addEventListener('click', (e) => {
        e.preventDefault();
        // Ne rien faire
    });
    }

    // ---------- Animations au scroll ----------
    const elements = document.querySelectorAll('.animate-on-scroll');
    if (elements.length) {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            observer.unobserve(entry.target);
        }
        });
    }, { threshold: 0.2, rootMargin: '0px 0px -50px 0px' });
    elements.forEach(el => observer.observe(el));
    }

    // ---------- Menu mobile ----------
    const menuBtn = document.getElementById('menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    if (menuBtn && mobileMenu) {
    menuBtn.addEventListener('click', () => {
        mobileMenu.classList.toggle('open');
        const icon = menuBtn.querySelector('i');
        if (mobileMenu.classList.contains('open')) {
        icon.classList.remove('fa-bars');
        icon.classList.add('fa-times');
        } else {
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
        }
    });

    const mobileLinks = mobileMenu.querySelectorAll('a:not(.mobile-auth-buttons a)');
    mobileLinks.forEach(link => {
        link.addEventListener('click', () => {
        mobileMenu.classList.remove('open');
        const icon = menuBtn.querySelector('i');
        icon.classList.remove('fa-times');
        icon.classList.add('fa-bars');
        });
    });
    }

    // ---------- Défilement fluide ----------
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const targetId = this.getAttribute('href');
        if (targetId === '#') return;
        const targetElement = document.querySelector(targetId);
        if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
    });
})();
