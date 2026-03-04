(function() {
    var currentUserId = null;
    var currentRoleId = null;
    var users = [
        { id: 1, name: 'Jean Dupont', login: 'j.dupont', email: 'j.dupont@smartclub.cd', phone: '+243 97 97 10 633', role: 'Administrateur', center: 'Tous les centres', status: 'Actif', twoFA: true, lastLogin: '26/05/2024 09:30' },
        { id: 2, name: 'Marie Mbokani', login: 'm.mbokani', email: 'm.mbokani@smartclub.cd', phone: '+243 98 765 4321', role: 'Manager', center: 'Centre Ville', status: 'Actif', twoFA: true, lastLogin: '26/05/2024 08:15' },
        { id: 3, name: 'Pierre Kabeya', login: 'p.kabeya', email: 'p.kabeya@smartclub.cd', phone: '+243 97 123 4567', role: 'Caissier', center: 'Ngaliema', status: 'Actif', twoFA: false, lastLogin: '25/05/2024 18:45' },
        { id: 4, name: 'Sophie Luntala', login: 's.luntala', email: 's.luntala@smartclub.cd', phone: '+243 99 876 5432', role: "Agent d'accueil", center: 'Gombe', status: 'Actif', twoFA: false, lastLogin: '26/05/2024 07:30' },
        { id: 5, name: 'Christian Tshibangu', login: 'c.tshibangu', email: 'c.tshibangu@smartclub.cd', phone: '+243 81 234 5678', role: 'Caissier', center: 'Matete', status: 'Suspendu', twoFA: false, lastLogin: '20/05/2024 14:20' }
    ];
    var roles = [
        { id: 1, nom: 'Administrateur', description: 'Accès complet à tous les modules, paramètres et journalisation.', users: 2 },
        { id: 2, nom: 'Manager', description: "Gestion des abonnements, rapports, vue d'ensemble.", users: 3 },
        { id: 3, nom: 'Caissier', description: 'Point de vente, encaissements, recherche clients (lecture seule).', users: 8 },
        { id: 4, nom: "Agent d'accueil", description: "Contrôle d'accès manuel, consultation statut client, scan.", users: 12 }
    ];
    var currenciesData = { 1: { name: 'Dollar Américain', code: 'USD', symbol: '$', rate: 1, status: 'Principale' }, 2: { name: 'Franc Congolais', code: 'CDF', symbol: 'FC', rate: 2850, status: 'Actif' }, 3: { name: 'Euro', code: 'EUR', symbol: '€', rate: 0.92, status: 'Inactif' } };

    function getInitials(name) { return (name || '').split(' ').map(function(n){ return n[0]; }).join('').toUpperCase().slice(0,2); }
    function badgeActif(t) { return '<span class="badge bg-success">' + (t || 'Actif') + '</span>'; }
    function badgeInactif(t) { return '<span class="badge bg-secondary">' + (t || 'Inactif') + '</span>'; }
    function badgeSuspendu(t) { return '<span class="badge bg-danger">' + (t || 'Suspendu') + '</span>'; }

    function renderUsersTable() {
        var tbody = document.getElementById('users-table-body');
        if (!tbody) return;
        tbody.innerHTML = users.map(function(u) {
            var roleBadge = u.status === 'Actif' ? badgeActif(u.role) : badgeInactif(u.role + ' (Suspendu)');
            var statusBadge = u.status === 'Actif' ? badgeActif() : badgeSuspendu();
            var twoFABadge = u.twoFA ? badgeActif('Activé') : badgeInactif('Désactivé');
            var actions = '<div class="dropdown"><button type="button" class="btn btn-sm btn-light" data-bs-toggle="dropdown"><span class="material-icons" style="font-size:18px;">more_vert</span></button><div class="dropdown-menu dropdown-menu-end">' +
                '<a class="dropdown-item" href="javascript:void(0)" onclick="window.settingsViewUser(' + u.id + ')"><span class="material-icons me-2" style="font-size:16px;">visibility</span>Voir</a>' +
                '<a class="dropdown-item" href="javascript:void(0)" onclick="window.settingsEditUser(' + u.id + ')"><span class="material-icons me-2" style="font-size:16px;">edit</span>Modifier</a>' +
                '<a class="dropdown-item" href="javascript:void(0)" onclick="window.settingsResetPassword(' + u.id + ')"><span class="material-icons me-2" style="font-size:16px;">key</span>Réinitialiser mot de passe</a>';
            if (u.status === 'Actif') actions += '<div class="dropdown-divider"></div><a class="dropdown-item text-danger" href="javascript:void(0)" onclick="window.settingsSuspendUser(' + u.id + ')"><span class="material-icons me-2" style="font-size:16px;">pause_circle</span>Suspendre</a>';
            else actions += '<a class="dropdown-item text-success" href="javascript:void(0)" onclick="window.settingsReactivateUser(' + u.id + ')"><span class="material-icons me-2" style="font-size:16px;">play_circle</span>Réactiver</a>';
            actions += '</div></div>';
            return '<tr id="user-row-' + u.id + '" data-user-id="' + u.id + '"><td><div class="d-flex align-items-center gap-2"><div class="rounded-circle d-inline-flex align-items-center justify-content-center text-white" style="width:36px;height:36px;font-size:12px;font-weight:bold;background:#3454d1;" id="user-initials-' + u.id + '">' + getInitials(u.name) + '</div><div><span class="fw-semibold d-block">' + (u.name || '') + '</span><small class="text-muted">' + (u.login || '') + '</small></div></div></td><td>' + (u.email || '') + '</td><td id="user-role-' + u.id + '">' + roleBadge + '</td><td>' + (u.center || '') + '</td><td id="user-status-' + u.id + '">' + statusBadge + '</td><td>' + (u.lastLogin || '-') + '</td><td>' + twoFABadge + '</td><td class="text-end">' + actions + '</td></tr>';
        }).join('');
    }
    function renderRolesTable() {
        var tbody = document.getElementById('roles-table-body');
        if (!tbody) return;
        tbody.innerHTML = roles.map(function(r) {
            return '<tr id="role-row-' + r.id + '"><td><span class="fw-semibold" id="role-name-' + r.id + '">' + (r.nom || '') + '</span></td><td id="role-desc-' + r.id + '">' + (r.description || '') + '</td><td id="role-users-' + r.id + '">' + (r.users != null ? r.users : '-') + '</td><td class="text-end"><button type="button" class="btn btn-sm btn-light" onclick="window.settingsViewRole(' + r.id + ')"><span class="material-icons" style="font-size:18px;">visibility</span></button> <button type="button" class="btn btn-sm btn-light" onclick="window.settingsEditRole(' + r.id + ')"><span class="material-icons" style="font-size:18px;">edit</span></button></td></tr>';
        }).join('');
    }

    window.settingsSaveAll = function() {
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Paramètres enregistrés', text: 'Les modifications ont été sauvegardées.', confirmButtonColor: '#3454d1' });
        else alert('Paramètres enregistrés.');
    };
    window.settingsShowSubTab = function(tab) {
        var usersDiv = document.getElementById('subtab-users');
        var rolesDiv = document.getElementById('subtab-roles');
        var usersBtn = document.getElementById('subtab-users-btn');
        var rolesBtn = document.getElementById('subtab-roles-btn');
        if (tab === 'users') {
            if (usersDiv) usersDiv.style.display = 'block';
            if (rolesDiv) rolesDiv.style.display = 'none';
            if (usersBtn) { usersBtn.classList.add('active'); usersBtn.classList.remove('btn-outline-primary'); usersBtn.classList.add('btn-primary'); }
            if (rolesBtn) { rolesBtn.classList.remove('active'); rolesBtn.classList.remove('btn-primary'); rolesBtn.classList.add('btn-outline-primary'); }
        } else {
            if (usersDiv) usersDiv.style.display = 'none';
            if (rolesDiv) rolesDiv.style.display = 'block';
            if (usersBtn) { usersBtn.classList.remove('active'); usersBtn.classList.remove('btn-primary'); usersBtn.classList.add('btn-outline-primary'); }
            if (rolesBtn) { rolesBtn.classList.add('active'); rolesBtn.classList.add('btn-primary'); rolesBtn.classList.remove('btn-outline-primary'); }
        }
    };
    window.settingsFilterUsers = function() {
        var search = (document.getElementById('searchUser') && document.getElementById('searchUser').value || '').toLowerCase();
        var roleFilter = (document.getElementById('filterRole') && document.getElementById('filterRole').value) || '';
        var statusFilter = (document.getElementById('filterStatus') && document.getElementById('filterStatus').value) || '';
        var rows = document.querySelectorAll('#users-table-body tr');
        var visible = 0;
        rows.forEach(function(row) {
            var id = row.getAttribute('data-user-id');
            var u = users.find(function(x){ return x.id == id; });
            if (!u) { row.style.display = 'none'; return; }
            var matchSearch = !search || (u.name + ' ' + u.login + ' ' + u.email + ' ' + u.role).toLowerCase().indexOf(search) >= 0;
            var matchRole = !roleFilter || u.role === roleFilter;
            var matchStatus = !statusFilter || u.status === statusFilter;
            var show = matchSearch && matchRole && matchStatus;
            row.style.display = show ? '' : 'none';
            if (show) visible++;
        });
        var lbl = document.getElementById('usersCountLabel');
        if (lbl) lbl.textContent = visible + ' utilisateur(s) sur ' + users.length;
    };
    window.settingsFilterRoles = function() {
        var search = (document.getElementById('searchRole') && document.getElementById('searchRole').value || '').toLowerCase();
        document.querySelectorAll('#roles-table-body tr').forEach(function(row) {
            var id = row.id.replace('role-row-','');
            var r = roles.find(function(x){ return x.id == id; });
            if (!r) { row.style.display = 'none'; return; }
            var show = !search || (r.nom + ' ' + (r.description || '')).toLowerCase().indexOf(search) >= 0;
            row.style.display = show ? '' : 'none';
        });
    };
    function getUserById(id) { return users.find(function(u){ return u.id == id; }); }
    function getRoleById(id) { return roles.find(function(r){ return r.id == id; }); }

    window.settingsOpenAddUser = function() {
        document.getElementById('userModalTitle').textContent = 'Ajouter un utilisateur';
        document.getElementById('userId').value = '';
        document.getElementById('userName').value = '';
        document.getElementById('userLogin').value = '';
        document.getElementById('userEmail').value = '';
        document.getElementById('userPhone').value = '';
        document.getElementById('userRole').value = '';
        document.getElementById('userCenter').value = 'Tous les centres';
        document.getElementById('userPassword').value = '';
        document.getElementById('userConfirmPassword').value = '';
        document.getElementById('user2FA').checked = true;
        document.getElementById('userActive').checked = true;
        var pf = document.getElementById('passwordFields');
        if (pf) pf.style.display = 'flex';
        var modal = new bootstrap.Modal(document.getElementById('userModal'));
        modal.show();
    };
    window.settingsEditUser = function(id) {
        var u = getUserById(id);
        if (!u) return;
        currentUserId = id;
        document.getElementById('userModalTitle').textContent = 'Modifier l\'utilisateur';
        document.getElementById('userId').value = u.id;
        document.getElementById('userName').value = u.name;
        document.getElementById('userLogin').value = u.login;
        document.getElementById('userEmail').value = u.email;
        document.getElementById('userPhone').value = u.phone || '';
        document.getElementById('userRole').value = u.role;
        document.getElementById('userCenter').value = u.center;
        document.getElementById('user2FA').checked = u.twoFA;
        document.getElementById('userActive').checked = u.status === 'Actif';
        var pf = document.getElementById('passwordFields');
        if (pf) pf.style.display = 'none';
        new bootstrap.Modal(document.getElementById('userModal')).show();
    };
    window.settingsViewUser = function(id) {
        var u = getUserById(id);
        if (!u) return;
        currentUserId = id;
        document.getElementById('viewUserInitials').textContent = getInitials(u.name);
        document.getElementById('viewUserName').textContent = u.name;
        document.getElementById('viewUserLogin').textContent = u.login;
        document.getElementById('viewUserEmail').textContent = u.email;
        document.getElementById('viewUserRole').textContent = u.role;
        document.getElementById('viewUserCenter').textContent = u.center;
        document.getElementById('viewUserStatus').innerHTML = u.status === 'Actif' ? badgeActif() : badgeSuspendu();
        document.getElementById('viewUserLastLogin').textContent = u.lastLogin || '-';
        var editBtn = document.getElementById('viewUserEditBtn');
        if (editBtn) editBtn.onclick = function() { bootstrap.Modal.getInstance(document.getElementById('viewUserModal')).hide(); window.settingsEditUser(id); };
        new bootstrap.Modal(document.getElementById('viewUserModal')).show();
    };
    window.settingsSaveUser = function() {
        var id = document.getElementById('userId').value;
        var name = (document.getElementById('userName') && document.getElementById('userName').value || '').trim();
        var login = (document.getElementById('userLogin') && document.getElementById('userLogin').value || '').trim();
        var email = (document.getElementById('userEmail') && document.getElementById('userEmail').value || '').trim();
        var role = document.getElementById('userRole') && document.getElementById('userRole').value;
        var center = document.getElementById('userCenter') && document.getElementById('userCenter').value;
        var twoFA = document.getElementById('user2FA') && document.getElementById('user2FA').checked;
        var active = document.getElementById('userActive') && document.getElementById('userActive').checked;
        if (!name || !login || !email || !role) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'error', title: 'Erreur', text: 'Remplissez tous les champs obligatoires.' }) : alert('Champs obligatoires manquants.')); return; }
        if (!id) {
            var pwd = document.getElementById('userPassword') && document.getElementById('userPassword').value;
            var cpwd = document.getElementById('userConfirmPassword') && document.getElementById('userConfirmPassword').value;
            if (!pwd || pwd.length < 8) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'error', title: 'Erreur', text: 'Mot de passe min. 8 caractères.' }) : alert('Mot de passe min. 8 caractères.')); return; }
            if (pwd !== cpwd) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'error', title: 'Erreur', text: 'Mots de passe différents.' }) : alert('Mots de passe différents.')); return; }
            var newId = Math.max.apply(null, users.map(function(u){ return u.id; })) + 1;
            users.push({ id: newId, name: name, login: login, email: email, phone: document.getElementById('userPhone').value, role: role, center: center, status: active ? 'Actif' : 'Suspendu', twoFA: twoFA, lastLogin: '-' });
            renderUsersTable();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Utilisateur ajouté', confirmButtonColor: '#3454d1' });
        } else {
            var user = getUserById(parseInt(id, 10));
            if (user) {
                user.name = name; user.login = login; user.email = email; user.phone = document.getElementById('userPhone').value; user.role = role; user.center = center; user.status = active ? 'Actif' : 'Suspendu'; user.twoFA = twoFA;
                renderUsersTable();
                if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Utilisateur modifié', confirmButtonColor: '#3454d1' });
            }
        }
        bootstrap.Modal.getInstance(document.getElementById('userModal')).hide();
    };
    window.settingsResetPassword = function(id) {
        if (typeof Swal !== 'undefined') Swal.fire({ title: 'Réinitialiser le mot de passe', text: 'Un email de réinitialisation sera envoyé.', icon: 'info', showCancelButton: true, confirmButtonColor: '#3454d1', confirmButtonText: 'Envoyer' }).then(function(r){ if (r.isConfirmed) Swal.fire({ icon: 'success', title: 'Email envoyé' }); });
        else if (confirm('Envoyer un email de réinitialisation ?')) alert('Email envoyé.');
    };
    window.settingsSuspendUser = function(id) {
        var u = getUserById(id);
        if (!u) return;
        if (typeof Swal !== 'undefined') Swal.fire({ title: 'Suspendre', text: 'Suspendre ' + u.name + ' ?', icon: 'warning', showCancelButton: true, confirmButtonColor: '#d33', confirmButtonText: 'Oui' }).then(function(r){ if (r.isConfirmed) { u.status = 'Suspendu'; renderUsersTable(); Swal.fire({ icon: 'success', title: 'Utilisateur suspendu' }); } });
        else if (confirm('Suspendre ' + u.name + ' ?')) { u.status = 'Suspendu'; renderUsersTable(); }
    };
    window.settingsReactivateUser = function(id) {
        var u = getUserById(id);
        if (!u) return;
        if (typeof Swal !== 'undefined') Swal.fire({ title: 'Réactiver', text: 'Réactiver ' + u.name + ' ?', icon: 'info', showCancelButton: true, confirmButtonColor: '#10b981', confirmButtonText: 'Oui' }).then(function(r){ if (r.isConfirmed) { u.status = 'Actif'; renderUsersTable(); Swal.fire({ icon: 'success', title: 'Utilisateur réactivé' }); } });
        else if (confirm('Réactiver ' + u.name + ' ?')) { u.status = 'Actif'; renderUsersTable(); }
    };

    window.settingsViewRole = function(id) {
        var r = getRoleById(id);
        if (!r) return;
        currentRoleId = id;
        document.getElementById('viewRoleName').textContent = r.nom;
        document.getElementById('viewRoleDescription').textContent = r.description || '-';
        document.getElementById('viewRoleUsers').textContent = r.users != null ? r.users : '-';
        var editBtn = document.getElementById('viewRoleEditBtn');
        if (editBtn) editBtn.onclick = function() { bootstrap.Modal.getInstance(document.getElementById('viewRoleModal')).hide(); window.settingsEditRole(id); };
        new bootstrap.Modal(document.getElementById('viewRoleModal')).show();
    };
    window.settingsEditRole = function(id) {
        var r = getRoleById(id);
        if (!r) return;
        currentRoleId = id;
        document.getElementById('editRoleId').value = r.id;
        document.getElementById('editRoleNameInput').value = r.nom;
        document.getElementById('editRoleDescriptionInput').value = r.description || '';
        new bootstrap.Modal(document.getElementById('editRoleModal')).show();
    };
    window.settingsSaveRole = function() {
        var id = parseInt(document.getElementById('editRoleId').value, 10);
        var r = getRoleById(id);
        if (!r) return;
        var name = (document.getElementById('editRoleNameInput') && document.getElementById('editRoleNameInput').value || '').trim();
        if (!name) { alert('Nom du rôle obligatoire.'); return; }
        r.nom = name;
        r.description = (document.getElementById('editRoleDescriptionInput') && document.getElementById('editRoleDescriptionInput').value || '').trim();
        renderRolesTable();
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Rôle mis à jour', confirmButtonColor: '#3454d1' });
        bootstrap.Modal.getInstance(document.getElementById('editRoleModal')).hide();
    };

    window.settingsOpenEditCurrency = function(id, name, code, symbol, rate, status) {
        document.getElementById('editCurrencyId').value = id;
        document.getElementById('editCurrencyName').value = name;
        document.getElementById('editCurrencyCode').value = code;
        document.getElementById('editCurrencySymbol').value = symbol;
        document.getElementById('editCurrencyRate').value = rate;
        new bootstrap.Modal(document.getElementById('editCurrencyModal')).show();
    };
    window.settingsOpenEditRate = function(id, name, rate) {
        var code = (currenciesData[id] && currenciesData[id].code) || 'USD';
        document.getElementById('editRateCurrencyId').value = id;
        document.getElementById('editRateCurrencyLabel').textContent = name + ' (' + code + ')';
        document.getElementById('editRateValue').value = rate;
        new bootstrap.Modal(document.getElementById('editRateModal')).show();
    };
    window.settingsActivateCurrency = function(id) {
        var row = document.getElementById('currency-row-' + id);
        if (row && row.cells[4]) row.cells[4].innerHTML = '<span class="badge bg-success">Actif</span>';
        if (currenciesData[id]) currenciesData[id].status = 'Actif';
        if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Devise activée', confirmButtonColor: '#3454d1' });
    };
    window.settingsConfirmRestore = function() {
        if (typeof Swal !== 'undefined') Swal.fire({ title: 'Attention', text: 'La restauration remplacera toutes les données. Irréversible.', icon: 'warning', showCancelButton: true, confirmButtonColor: '#d33', confirmButtonText: 'Oui, restaurer' }).then(function(r){ if (r.isConfirmed) Swal.fire('Restauration démarrée', 'Le processus a été lancé.', 'info'); });
        else if (confirm('Restauration : toutes les données seront remplacées. Continuer ?')) alert('Restauration démarrée.');
    };

    /* ---------- API Paiements : Configurer + Tester (simulation) ---------- */
    window.settingsApiOpenConfig = function(provider) {
        var modal = document.getElementById('apiConfigModal');
        if (!modal) return;
        var tabCinetpay = document.getElementById('api-tab-cinetpay');
        var tabMobile = document.getElementById('api-tab-mobile');
        if (provider === 'cinetpay') {
            if (tabCinetpay) { tabCinetpay.classList.add('active'); tabCinetpay.setAttribute('aria-selected', 'true'); }
            if (tabMobile) { tabMobile.classList.remove('active'); tabMobile.setAttribute('aria-selected', 'false'); }
            var paneCinetpay = document.getElementById('api-pane-cinetpay');
            var paneMobile = document.getElementById('api-pane-mobile');
            if (paneCinetpay) { paneCinetpay.classList.add('show', 'active'); }
            if (paneMobile) { paneMobile.classList.remove('show', 'active'); }
        } else {
            if (tabMobile) { tabMobile.classList.add('active'); tabMobile.setAttribute('aria-selected', 'true'); }
            if (tabCinetpay) { tabCinetpay.classList.remove('active'); tabCinetpay.setAttribute('aria-selected', 'false'); }
            var paneCinetpay = document.getElementById('api-pane-cinetpay');
            var paneMobile = document.getElementById('api-pane-mobile');
            if (paneMobile) { paneMobile.classList.add('show', 'active'); }
            if (paneCinetpay) { paneCinetpay.classList.remove('show', 'active'); }
            window.settingsApiSwitchMobileProvider(document.getElementById('apiMobileProvider') && document.getElementById('apiMobileProvider').value || 'mpesa');
        }
        new bootstrap.Modal(modal).show();
    };
    window.settingsApiSwitchMobileProvider = function(value) {
        var mpesa = document.getElementById('apiMobileMpesaFields');
        var orange = document.getElementById('apiMobileOrangeFields');
        var airtel = document.getElementById('apiMobileAirtelFields');
        if (mpesa) mpesa.style.display = value === 'mpesa' ? 'block' : 'none';
        if (orange) orange.style.display = value === 'orange' ? 'block' : 'none';
        if (airtel) airtel.style.display = value === 'airtel' ? 'block' : 'none';
    };
    window.settingsApiTestCinetPay = function() {
        if (typeof Swal === 'undefined') { alert('Test connexion CinetPay (simulation) : OK'); return; }
        Swal.fire({
            title: 'Test de connexion en cours',
            html: 'Vérification des identifiants CinetPay...',
            allowOutsideClick: false,
            didOpen: function() { Swal.showLoading(); }
        });
        setTimeout(function() {
            Swal.fire({
                icon: 'success',
                title: 'Connexion réussie',
                text: 'Les identifiants CinetPay sont valides. (Simulation)',
                confirmButtonColor: '#3454d1'
            });
        }, 1800);
    };
    window.settingsApiSaveConfig = function() {
        var modal = document.getElementById('apiConfigModal');
        var keyInput = document.getElementById('apiCinetpayKey');
        var siteInput = document.getElementById('apiCinetpaySiteId');
        var keyDisplay = document.getElementById('apiCinetpayKeyDisplay');
        var siteDisplay = document.getElementById('apiCinetpaySiteDisplay');
        if (siteInput && siteInput.value && siteDisplay) siteDisplay.textContent = siteInput.value;
        if (keyInput && keyInput.value) {
            if (keyDisplay) keyDisplay.textContent = '••••••••••••' + (keyInput.value.slice(-4) || '');
            if (keyInput) keyInput.value = '';
        }
        if (modal && bootstrap.Modal.getInstance(modal)) bootstrap.Modal.getInstance(modal).hide();
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                icon: 'success',
                title: 'Configuration enregistrée',
                text: 'Les paramètres API Paiements ont été sauvegardés. (Simulation)',
                confirmButtonColor: '#3454d1'
            });
        } else {
            alert('Configuration enregistrée (simulation).');
        }
    };

    window.settingsShowTab = function(tab) {
        var valid = ['general', 'finance', 'api', 'users', 'notifications', 'backup'];
        if (valid.indexOf(tab) < 0) tab = 'general';
        valid.forEach(function(id) {
            var pane = document.getElementById(id);
            if (pane) { pane.classList.remove('show', 'active'); }
        });
        var active = document.getElementById(tab);
        if (active) { active.classList.add('show', 'active'); }
        ['general', 'finance', 'api', 'users', 'notifications', 'backup'].forEach(function(t) {
            var el = document.getElementById('nav-settings-' + t);
            if (el) el.classList.toggle('active', t === tab);
        });
        var url = new URL(window.location.href);
        url.searchParams.set('tab', tab);
        window.history.replaceState({}, '', url);
    };

    document.addEventListener('DOMContentLoaded', function() {
        renderUsersTable();
        renderRolesTable();
        window.settingsFilterUsers();

        var urlParams = new URLSearchParams(window.location.search);
        var tabParam = urlParams.get('tab');
        var initialTab = ['general', 'finance', 'api', 'users', 'notifications', 'backup'].indexOf(tabParam) >= 0 ? tabParam : 'users';
        window.settingsShowTab(initialTab);
        window.settingsShowSubTab('users');

        ['general', 'finance', 'api', 'users', 'notifications', 'backup'].forEach(function(t) {
            var el = document.getElementById('nav-settings-' + t);
            if (el) {
                var a = el.querySelector('a');
                if (a) a.addEventListener('click', function(e) { e.preventDefault(); window.settingsShowTab(t); });
            }
        });

        document.getElementById('btnAddCurrency') && document.getElementById('btnAddCurrency').addEventListener('click', function() {
            var name = (document.getElementById('newCurrencyName') && document.getElementById('newCurrencyName').value || '').trim();
            var code = (document.getElementById('newCurrencyCode') && document.getElementById('newCurrencyCode').value || '').trim();
            if (!name || !code) { (typeof Swal !== 'undefined' ? Swal.fire({ icon: 'warning', title: 'Nom et code requis' }) : alert('Nom et code requis')); return; }
            bootstrap.Modal.getInstance(document.getElementById('addCurrencyModal')).hide();
            document.getElementById('addCurrencyForm').reset();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Devise ajoutée', confirmButtonColor: '#3454d1' });
        });
        document.getElementById('btnSaveCurrency') && document.getElementById('btnSaveCurrency').addEventListener('click', function() {
            var id = document.getElementById('editCurrencyId').value;
            var name = document.getElementById('editCurrencyName').value;
            var code = document.getElementById('editCurrencyCode').value;
            var symbol = document.getElementById('editCurrencySymbol').value;
            var rate = document.getElementById('editCurrencyRate').value;
            var row = document.getElementById('currency-row-' + id);
            if (row) {
                row.cells[0].textContent = name;
                row.cells[1].textContent = code;
                row.cells[2].textContent = symbol;
                row.cells[3].textContent = parseFloat(rate).toLocaleString('fr-FR', { minimumFractionDigits: 2 });
            }
            if (currenciesData[id]) { currenciesData[id].name = name; currenciesData[id].code = code; currenciesData[id].symbol = symbol; currenciesData[id].rate = parseFloat(rate); }
            bootstrap.Modal.getInstance(document.getElementById('editCurrencyModal')).hide();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Devise mise à jour', confirmButtonColor: '#3454d1' });
        });
        document.getElementById('btnSaveRate') && document.getElementById('btnSaveRate').addEventListener('click', function() {
            var id = document.getElementById('editRateCurrencyId').value;
            var rate = document.getElementById('editRateValue').value;
            var row = document.getElementById('currency-row-' + id);
            if (row) row.cells[3].textContent = parseFloat(rate).toLocaleString('fr-FR', { minimumFractionDigits: 2 });
            if (currenciesData[id]) currenciesData[id].rate = parseFloat(rate);
            bootstrap.Modal.getInstance(document.getElementById('editRateModal')).hide();
            if (typeof Swal !== 'undefined') Swal.fire({ icon: 'success', title: 'Taux mis à jour', confirmButtonColor: '#3454d1' });
        });
    });
})();
