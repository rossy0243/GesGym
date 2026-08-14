# Dossier de formation - Comptes et connexion

> Connexion, profil, changement de mot de passe, roles.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `compte`

| Adresse | Vue | Nom interne |
|---|---|---|
| `login/` | `CustomLoginView.as_view()` | `login` |
| `welcome/` | `welcome` | `welcome` |
| `profile/` | `profile` | `profile` |
| `logout/` | `logout_view` | `logout` |
| `password-reset/` | `auth_views.PasswordResetView.as_view(template_name='compte/password_reset_form.html', email_template_name='compte/emails/password_reset_email.txt', html_email_template_name='compte/emails/password_reset_email.html', subject_template_name='compte/emails/password_reset_subject.txt', form_class=StyledPasswordResetForm, success_url=reverse_lazy('compte:password_reset_done'))` | `password_reset` |
| `password-reset/done/` | `auth_views.PasswordResetDoneView.as_view(template_name='compte/password_reset_done.html')` | `password_reset_done` |
| `reset/<uidb64>/<token>/` | `auth_views.PasswordResetConfirmView.as_view(template_name='compte/password_reset_confirm.html', form_class=StyledSetPasswordForm, success_url=reverse_lazy('compte:password_reset_complete'))` | `password_reset_confirm` |
| `reset/done/` | `auth_views.PasswordResetCompleteView.as_view(template_name='compte/password_reset_complete.html')` | `password_reset_complete` |
| `admin/get-gyms/` | `get_gyms_by_organization` | `get_gyms_by_organization` |
| `users/` | `user_list` | `user_list` |
| `users/create/` | `create_user_by_owner` | `create_user` |
| `users/<int:user_id>/reset-password/` | `reset_password` | `reset_password` |
| `users/<int:user_id>/deactivate/` | `deactivate_user` | `deactivate_user` |
| `users/<int:user_id>/activate/` | `activate_user` | `activate_user` |

## Donnees manipulees

### `User`

> Utilisateur du système SMARTCLUB.
> Le rôle et le gym sont gérés dans le modèle UserGymRole
> afin de permettre plusieurs rôles par utilisateur.


| Champ | Type |
|---|---|
| `is_saas_admin` | BooleanField |
| `owned_organization` | ForeignKey |
| `force_password_change` | BooleanField |

### `UserGymRole`

> Assigne un rôle à un utilisateur dans un gym


| Champ | Type |
|---|---|
| `user` | ForeignKey |
| `gym` | ForeignKey |
| `role` | CharField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

Valeurs possibles `ROLE_CHOICES` :

```python
(('owner', 'Owner'), ('manager', 'Manager'), ('coach', 'Coach'), ('reception', 'Receptionist'), ('cashier', 'Cashier'))
```

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `welcome` | `login_required` |
| `profile` | `login_required` |
| `create_user_by_owner` | `login_required` |
| `user_list` | `login_required` |
| `reset_password` | `login_required`<br>`require_POST` |
| `deactivate_user` | `login_required`<br>`require_POST` |
| `activate_user` | `login_required`<br>`require_POST` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Cette organisation n'a aucun gym actif. Ajoutez au moins un gym.
- Choisissez une organisation existante ou creez-en une nouvelle, mais pas les deux.
- Choisissez une organisation existante ou renseignez une nouvelle organisation.
- Creez au moins un gym pour une nouvelle organisation.
- Le gym '{valeur}' est saisi plusieurs fois.
- Le gym ligne {valeur} est trop court.
- Les champs de creation d'organisation doivent rester vides si vous selectionnez une organisation existante.
- Un meme compte coach ne peut pas etre rattache a plusieurs gyms. Creez des identifiants separes pour chaque gym.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Mot de passe reinitialise pour {valeur}. Un nouveau mot de passe temporaire fort a ete genere et devra etre change a la prochaine connexion.
- Profil mis à jour avec succès.
- Utilisateur '{valeur}' cree avec succes. Un mot de passe temporaire fort a ete genere et devra etre change a la premiere connexion.
- Utilisateur {valeur} desactive
- Utilisateur {valeur} reactive

### Avertissements

- Votre mot de passe temporaire doit être remplacé avant d’accéder à l’application.

### Refus et erreurs

- Aucun acces actif n'est associe a ces identifiants.
- Ce compte est partage avec un autre acces actif. Utilisez une reinitialisation globale supervisee.
- Impossible de mettre à jour le profil. Vérifiez les champs.
- Le recapitulatif a expire. Recommencez la creation du client.
- Mot de passe non modifié. Vérifiez les informations saisies.
- Permission non accordee
- Seul un superuser peut consulter ce recapitulatif.
- Seul un superuser peut creer ou modifier un Owner.
- Seul un superuser peut creer un Owner.
- Utilisateur non trouve dans ce gym
- Vous n'avez pas les permissions necessaires
- Vous ne pouvez pas vous desactiver vous-meme

### Informations

- Aucun recapitulatif recent a afficher.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

_Aucune action de ce module n'est journalisee._

## Ecrans concernes

- `compte\templates\admin\compte\user\change_list.html`
- `compte\templates\admin\create_owner.html`
- `compte\templates\admin\create_owner_confirm.html`
- `compte\templates\admin\create_owner_success.html`
- `compte\templates\compte\accueil.html`
- `compte\templates\compte\auth_base.html`
- `compte\templates\compte\create_user.html`
- `compte\templates\compte\emails\password_reset_email.html`
- `compte\templates\compte\login.html`
- `compte\templates\compte\password_reset_complete.html`
- `compte\templates\compte\password_reset_confirm.html`
- `compte\templates\compte\password_reset_done.html`
- `compte\templates\compte\password_reset_form.html`
- `compte\templates\compte\profile.html`
- `compte\templates\compte\user_list.html`
- `compte\templates\compte\welcome.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### OwnerLoginAndGymSwitchTests
- owner without gym role can login and single gym redirects to dashboard
- owner with multiple gyms must choose then session keeps selected gym
- owner cannot switch to gym from another organization
- switch gym requires post to change session
- select gym renders cleanly when owner has no active gym

### OwnerScopedUserManagementTests
- owner cannot reset password for shared user identity
- user management actions require post
- owner deactivation only disables current gym role

### SharedStaffMultiGymContextTests
- session current gym id drives staff context and role
- staff can switch context between roles using session gym

### LoginConfigurationTests
- login without remember me expires at browser close
- login with remember me uses persistent session
- welcome screen uses org and gym context for staff
- login page displays configured social links
- login page displays password toggle and help text
- owner create user form requires email for password reset autonomy
- member login prioritizes member portal even with staff role
- coach login sets welcome target to coach portal
- login redirects to profile when password change is forced

### PasswordResetFlowTests
- password reset request sends email
- password reset request uses organization brand for staff user
- password reset confirm updates password

### UserProfileTests
- profile page renders context and breadcrumbs
- profile update persists and shows success toast
- password change updates password and keeps user logged in
- forced password change uses dedicated form and clears flag

### SuperAdminOwnerCreationTests
- superadmin can open owner creation view
- superadmin can create owner organization gyms and modules
- owner creation blocks duplicate gym names in same submission
- non superuser cannot access owner creation view

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

