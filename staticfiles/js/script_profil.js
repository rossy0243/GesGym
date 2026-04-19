(function() {
    window.profilEdit = function() {
        var nameEl = document.getElementById('profileName');
        var infoNom = document.getElementById('infoNom');
        var infoEmail = document.getElementById('infoEmail');
        var infoPhone = document.getElementById('infoPhone');
        var infoAdresse = document.getElementById('infoAdresse');
        var infoNotes = document.getElementById('infoNotes');
        document.getElementById('editNom').value = (nameEl && nameEl.textContent) || 'Julien Dubois';
        document.getElementById('editEmail').value = (infoEmail && infoEmail.textContent) || 'j.dubois@smartclub.cd';
        document.getElementById('editPhone').value = (infoPhone && infoPhone.textContent) || '';
        document.getElementById('editAdresse').value = (infoAdresse && infoAdresse.textContent) || '';
        document.getElementById('editNotes').value = (infoNotes && infoNotes.textContent) || '';
        new bootstrap.Modal(document.getElementById('editProfileModal')).show();
    };
    window.profilChangePassword = function() {
        document.getElementById('changePasswordForm').reset();
        new bootstrap.Modal(document.getElementById('changePasswordModal')).show();
    };
    window.profilMarquerPresence = function() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Pointage enregistré', text: 'Présence marquée à ' + new Date().toLocaleTimeString('fr-FR'), timer: 2000, showConfirmButton: false });
        else alert('Pointage enregistré.');
    };
    window.profilVoirAudit = function() {
        new bootstrap.Modal(document.getElementById('auditModal')).show();
    };
    window.profilActiver2FA = function() {
        new bootstrap.Modal(document.getElementById('activate2FAModal')).show();
    };
    window.profilModifierPreferences = function() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'info', title: 'Modifier les préférences', text: 'Configurer les notifications (rappels caisse, modèles SMS).', confirmButtonColor: '#3454d1' });
        else alert('Modifier les préférences : page à venir.');
    };
    window.profilRevoquerAppareils = function() {
        if (typeof Swal !== 'undefined') Swal.fire({ title: 'Révoquer les appareils ?', text: 'Toutes les sessions seront déconnectées. Vous devrez vous reconnecter.', icon: 'warning', showCancelButton: true, confirmButtonColor: '#d33', cancelButtonColor: '#3085d6', confirmButtonText: 'Oui, révoquer' }).then(function(r) { if (r.isConfirmed) Swal.fire({ icon: 'success', title: 'Appareils révoqués', text: 'Sessions terminées.' }); });
        else if (confirm('Révoquer toutes les sessions ?')) alert('Appareils révoqués.');
    };

    document.addEventListener('DOMContentLoaded', function() {
        document.getElementById('btnSaveProfile') && document.getElementById('btnSaveProfile').addEventListener('click', function() {
            var nom = document.getElementById('editNom').value.trim();
            var email = document.getElementById('editEmail').value.trim();
            var phone = document.getElementById('editPhone').value;
            var adresse = document.getElementById('editAdresse').value;
            var notes = document.getElementById('editNotes').value;
            if (!nom || !email) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'warning', title: 'Champs requis', text: 'Nom et email sont obligatoires.' }) : alert('Nom et email obligatoires.')); return; }
            var nameEl = document.getElementById('profileName');
            if (nameEl) nameEl.textContent = nom;
            if (document.getElementById('infoNom')) document.getElementById('infoNom').textContent = nom;
            if (document.getElementById('infoEmail')) document.getElementById('infoEmail').textContent = email;
            if (document.getElementById('infoPhone')) document.getElementById('infoPhone').textContent = phone;
            if (document.getElementById('infoAdresse')) document.getElementById('infoAdresse').textContent = adresse;
            if (document.getElementById('infoNotes')) document.getElementById('infoNotes').textContent = notes;
            bootstrap.Modal.getInstance(document.getElementById('editProfileModal')).hide();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Profil mis à jour', text: 'Les modifications ont été enregistrées.', confirmButtonColor: '#3454d1' });
        });
        document.getElementById('btnChangePassword') && document.getElementById('btnChangePassword').addEventListener('click', function() {
            var cur = document.getElementById('currentPassword').value;
            var pwd = document.getElementById('newPassword').value;
            var conf = document.getElementById('confirmPassword').value;
            if (!cur || !pwd || !conf) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'warning', title: 'Champs requis', text: 'Remplissez tous les champs.' }) : alert('Remplissez tous les champs.')); return; }
            if (pwd !== conf) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'error', title: 'Erreur', text: 'Les mots de passe ne correspondent pas.' }) : alert('Mots de passe différents.')); return; }
            bootstrap.Modal.getInstance(document.getElementById('changePasswordModal')).hide();
            document.getElementById('changePasswordForm').reset();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Mot de passe modifié', text: 'Votre mot de passe a été mis à jour.', confirmButtonColor: '#3454d1' });
        });
        document.getElementById('btnActivate2FA') && document.getElementById('btnActivate2FA').addEventListener('click', function() {
            var mode = (document.querySelector('input[name="mode2FA"]:checked') && document.querySelector('input[name="mode2FA"]:checked').value) || 'email';
            bootstrap.Modal.getInstance(document.getElementById('activate2FAModal')).hide();
            var badgeEl = document.getElementById('badge2FA');
            var linkEl = document.getElementById('link2FA');
            if (badgeEl) { badgeEl.className = 'badge bg-success'; badgeEl.textContent = 'Activé'; badgeEl.id = 'badge2FA'; }
            if (linkEl) { linkEl.outerHTML = '<span class="text-success ms-3"><span class="material-icons align-middle" style="font-size:18px;">check_circle</span> Activé</span>'; }
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: '2FA activé', text: 'Authentification à deux facteurs par ' + (mode === 'email' ? 'email' : 'application') + ' activée.', confirmButtonColor: '#3454d1' });
        });
    });
})();