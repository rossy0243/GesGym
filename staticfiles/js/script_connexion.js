    (function() {
      // --- Éléments DOM ---
      const loginForm = document.getElementById('login-form');
      const twoFAForm = document.getElementById('2fa-form');
      const forgotForm = document.getElementById('forgot-form');
      const resetForm = document.getElementById('reset-form');

      // Champs de saisie
      const loginIdentifier = document.getElementById('login-identifier');
      const loginPassword = document.getElementById('login-password');
      const code2fa = document.getElementById('2fa-code');
      const forgotIdentifier = document.getElementById('forgot-identifier');
      const resetCode = document.getElementById('reset-code');
      const newPassword = document.getElementById('new-password');
      const confirmPassword = document.getElementById('confirm-password');

      // Boutons et liens
      const loginBtn = document.getElementById('login-btn');
      const forgotLink = document.getElementById('forgot-password-link');
      const backToLoginFrom2FA = document.getElementById('back-to-login-from-2fa');
      const backToLoginFromForgot = document.getElementById('back-to-login-from-forgot');
      const backToLoginFromReset = document.getElementById('back-to-login-from-reset');
      const sendResetCodeBtn = document.getElementById('send-reset-code-btn');
      const verify2faBtn = document.getElementById('verify-2fa-btn');
      const resetPasswordBtn = document.getElementById('reset-password-btn');

      // Zones de message
      const forgotMessage = document.getElementById('forgot-message');
      const resetMessage = document.getElementById('reset-message');

      // --- Données de démo (exactement comme dans l'original) ---
      const DEMO_USER = {
        email: 'test@demo.com',
        password: 'password',
        expected2FACode: '123456'
      };

      // Variable pour stocker l'email lors de la réinitialisation
      let resetEmail = '';

      // --- Fonction d'affichage des formulaires ---
      function showForm(formToShow) {
        [loginForm, twoFAForm, forgotForm, resetForm].forEach(f => f.classList.add('hidden'));
        formToShow.classList.remove('hidden');
        // Effacer les messages
        if (forgotMessage) forgotMessage.innerHTML = '';
        if (resetMessage) resetMessage.innerHTML = '';
      }

      // --- Connexion ---
      loginBtn.addEventListener('click', function(e) {
        e.preventDefault();
        const identifier = loginIdentifier.value.trim();
        const password = loginPassword.value;

        if (identifier === DEMO_USER.email && password === DEMO_USER.password) {
          // Succès : afficher le formulaire 2FA
          showForm(twoFAForm);
          code2fa.value = '';
        } else {
          Swal.fire({
            icon: 'error',
            title: 'Échec de connexion',
            text: 'Email ou mot de passe incorrect (utilisez test@demo.com / password)',
            confirmButtonColor: '#004e92'
          });
        }
      });

      // --- Vérification 2FA ---
      verify2faBtn.addEventListener('click', function() {
        const code = code2fa.value.trim();
        if (code === DEMO_USER.expected2FACode) {
          Swal.fire({
            icon: 'success',
            title: 'Connexion réussie !',
            text: 'Redirection vers le tableau de bord...',
            timer: 2000,
            showConfirmButton: true,
            confirmButtonColor: '#004e92'
          }).then(() => {
            // Ici vous pourrez rediriger vers index.html
            // window.location.href = 'index.html';
          });
        } else {
          Swal.fire({
            icon: 'error',
            title: 'Code invalide',
            text: 'Le code attendu est 123456',
            confirmButtonColor: '#004e92'
          });
        }
      });

      // --- Lien "Mot de passe oublié" ---
      forgotLink.addEventListener('click', function(e) {
        e.preventDefault();
        showForm(forgotForm);
        forgotIdentifier.value = DEMO_USER.email; // préremplir
      });

      // --- Retours vers la connexion ---
      backToLoginFrom2FA.addEventListener('click', function(e) { e.preventDefault(); showForm(loginForm); });
      backToLoginFromForgot.addEventListener('click', function(e) { e.preventDefault(); showForm(loginForm); });
      backToLoginFromReset.addEventListener('click', function(e) { e.preventDefault(); showForm(loginForm); });

      // --- Envoi du code de réinitialisation ---
      sendResetCodeBtn.addEventListener('click', function() {
        const email = forgotIdentifier.value.trim();
        if (!email) {
          forgotMessage.innerHTML = '<span class="text-red-500">Veuillez saisir votre email.</span>';
          return;
        }
        // Simuler l'envoi d'un code (dans une vraie app, on enverrait un email)
        if (email !== DEMO_USER.email) {
          forgotMessage.innerHTML = '<span class="text-red-500">Email inconnu.</span>';
          return;
        }
        resetEmail = email;
        forgotMessage.innerHTML = '<span class="text-green-600">Un code de réinitialisation a été envoyé à ' + email + ' (code démo : 654321).</span>';
        // Passer au formulaire de réinitialisation
        showForm(resetForm);
        resetCode.value = '';
        newPassword.value = '';
        confirmPassword.value = '';
        resetMessage.innerHTML = '';
      });

      // --- Réinitialisation du mot de passe ---
      resetPasswordBtn.addEventListener('click', function() {
        const code = resetCode.value.trim();
        const newPass = newPassword.value;
        const confirmPass = confirmPassword.value;

        if (!code || !newPass || !confirmPass) {
          resetMessage.innerHTML = '<span class="text-red-500">Tous les champs sont requis.</span>';
          return;
        }
        if (newPass !== confirmPass) {
          resetMessage.innerHTML = '<span class="text-red-500">Les mots de passe ne correspondent pas.</span>';
          return;
        }
        // Vérifier le code (simulé avec "654321")
        if (code !== '654321') {
          resetMessage.innerHTML = '<span class="text-red-500">Code invalide. Veuillez réessayer.</span>';
          return;
        }
        // Succès : changer le mot de passe (pour la démo)
        DEMO_USER.password = newPass; // mise à jour en mémoire
        resetMessage.innerHTML = '<span class="text-green-600">Mot de passe réinitialisé avec succès !</span>';
        setTimeout(() => {
          showForm(loginForm);
          // Remettre les champs de login à jour (optionnel)
          loginPassword.value = newPass; // pour que l'utilisateur puisse se connecter directement avec le nouveau mdp
        }, 1500);
      });

      // --- Petite touche : soumission avec Entrée ---
      code2fa.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') verify2faBtn.click();
      });
      resetCode.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') resetPasswordBtn.click();
      });

      // Empêcher la soumission par défaut de tout formulaire
      document.querySelectorAll('form').forEach(f => f.addEventListener('submit', e => e.preventDefault()));
    })();

