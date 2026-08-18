# Dossier de formation - Parametres et journal sensible

> Organisation, employes internes, specialites, journal d'audit.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `core`

| Adresse | Vue | Nom interne |
|---|---|---|
| `dashboard/` | `dashboard_redirect` | `dashboard_redirect` |
| `select-gym/` | `select_gym` | `select_gym` |
| `gym/<int:gym_id>/dashboard/` | `gym_dashboard` | `gym_dashboard` |
| `rapport/` | `reports_dashboard` | `rapport` |
| `rapport/export/` | `accounting_report_export` | `rapport_export` |
| `parametres/` | `settings_dashboard` | `settings` |
| `parametres/journal/export/` | `activity_log_export` | `activity_log_export` |
| `switch-gym/<int:gym_id>/` | `switch_gym` | `switch_gym` |

## Donnees manipulees

Ce module ne definit pas de donnees propres.

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `dashboard_redirect` | `login_required` |
| `select_gym` | `login_required` |
| `switch_gym` | `login_required`<br>`require_POST` |
| `settings_dashboard` | `login_required` |
| `activity_log_export` | `login_required` |
| `gym_dashboard` | `login_required` |
| `reports_dashboard` | `login_required` |
| `accounting_report_export` | `login_required` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Cet employe a deja un acces dans cette salle.
- Le delai doit valoir au moins un jour.
- Seul un proprietaire peut exister par organisation : ce role ne s'attribue pas depuis les parametres.
- Un delai de plus d'un an n'a pas de sens.
- Vous ne pouvez pas attribuer ce role. Votre niveau d'acces permet d'affecter : {valeur}.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Coordonnees de la salle mises a jour.
- Delai de prevenance des maintenances mis a jour.
- Employe cree : {valeur}. Mot de passe temporaire : {valeur}. Changement obligatoire a la premiere connexion.
- Employe {valeur} {valeur}.
- Informations de l'organisation mises a jour.
- Mot de passe reinitialise pour {valeur} : {valeur}. Changement obligatoire a la premiere connexion.
- Profil employe mis a jour : {valeur}.
- Profil employe supprime : {valeur}.
- Specialite coach enregistree : {valeur}
- Specialite {valeur} mise a jour.
- Vous travaillez maintenant sur : <strong>{valeur}</strong>

### Refus et erreurs

- Acces refuse a ce gym.
- Acces refuse a cette salle.
- Ce compte est partage avec un autre acces actif. Utilisez une reinitialisation globale supervisee.
- Ce compte est partage avec un autre profil actif. La modification globale est bloquee.
- Vous n'avez pas le droit de changer de gym.
- Vous ne pouvez pas supprimer votre propre profil d'acces.
- Vous ne pouvez pas vous desactiver vous-meme.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `employee.created`
- `employee.deleted`
- `employee.password_reset`
- `employee.updated`
- `gym.contact_updated`
- `gym.maintenance_alert_updated`
- `organization.updated`
- `settings.action_refused`
- `settings.activity_log_exported`

## Ecrans concernes

- `core\templates\core\dashboard.html`
- `core\templates\core\dashboard_members.html`
- `core\templates\core\rapports.html`
- `core\templates\core\select_gym.html`
- `core\templates\core\settings.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### SeedDemoDataSafetyTests
- seed demo data refuses to run in production without opt in
- seed demo data creates complete module kpi dataset

### AccountingReportExportTests
- dashboard displays peak hour scoped to current gym
- csv export is accounting file scoped to current gym
- xlsx export contains expected sheets and no other tenant data
- report page uses selected gym and shows accounting summary
- report page exposes accounting chart data and visual blocks
- dashboard chart data is scoped and matches existing kpis
- dashboard chart data has valid series for supported periods
- journalier report defaults to today period
- journalier export defaults to today period
- mensuel report defaults to month period
- mensuel export defaults to month period
- custom subscription rows only sum pos payments inside period
- custom transaction rows use real status and keep entry type in description
- custom register rows include opening and theoretical balance
- dashboard excludes future subscriptions from active metrics
- custom report preview uses selected types and columns
- report page displays rh payroll summary with contributions
- custom report preview supports payroll dataset
- custom report preview displays grouping label and period scoped payroll summary
- custom report export is scoped to current gym
- custom report xlsx export contains expected sheet and scoped data
- report exports use period based filename
- settings owner can create internal employee for selected gym
- settings owner can open internal employee edit mode
- settings owner can update internal employee profile
- settings owner can delete internal employee profile
- settings employee delete preserves shared member profile
- settings employee update blocks shared member profile
- settings owner can manage employee across organization gyms
- organization logo upload rejects non image file
- settings dashboard renders v1 sections
- settings can update organization and log activity
- settings create coach specialty and form uses it

### RoleAccessMatrixTests
- cashier home redirects to pos not dashboard
- cashier cannot open dashboard or transaction journal
- reception can control access but cannot open reports
- cashier navigation only exposes cashier scope
- reception navigation exposes access and operational tools only
- manager navigation exposes dashboard reports and settings
- manager settings excludes organization management
- manager cannot create employee for another gym
- manager cannot create another manager
- manager settings hides manager creation and manager rows
- manager settings locks gym choice to active gym
- manager cannot reset password for manager role
- manager cannot reset password for shared user identity
- manager deactivation only disables current role for shared user identity
- manager can update allowed employee profile in current gym
- manager can delete allowed employee profile in current gym
- manager cannot delete manager profile
- non owner cannot open dashboard for other gym than request context

### RoleChoiceCleanupTests
- internal employee form excludes accountant role
- internal employee form can limit roles for manager scope
- internal employee form hides locked gym field
- owner create user form excludes accountant role

### AccountingReportCoverageMatrixTests

> Suite de couverture quasi exhaustive pour les rapports:

- coverage matrix documents supported axes
- report period matrix returns expected windows
- accounting report expected outputs are stable for month
- accounting report invariants hold for every supported period
- custom report type matrix returns expected dataset only
- custom report column matrix preserves requested order
- custom report grouping matrix preserves base row count

### DashboardKpiCoverageMatrixTests
- kpi coverage matrix documents supported axes
- machine kpis expected outputs are stable
- product kpis expected outputs are stable
- rh kpis expected outputs are stable
- coaching kpis expected outputs are stable
- kpi builders preserve scope and invariants for all periods
- dashboard context matches kpi builders for every period

### ReportPeriodBoundsTests

> Aucune periode relative ne doit deborder sur des journees a venir.

- no relative period ends in the future
- the current week stops today
- the current year stops today
- a custom range is left untouched — _Une borne future explicitement saisie reste celle de l'utilisateur._
- period windows stay consistent between each other

### SettingsRefusalAuditTests

> Un refus doit s'expliquer a l'utilisateur et laisser une trace.

- an out of reach role is explained in plain words
- the message lists the roles actually allowed
- touching a higher account is recorded
- editing the organization without the right is recorded
- opening a higher account sheet is recorded
- a legitimate action is not recorded as refused

### ActivityLogConsultationTests

> Le journal doit rester exploitable : filtrable et exportable.

- the default window covers the last thirty days
- an older entry reappears on a wider window
- reversed dates are reordered instead of emptying the page
- an unreadable date falls back on the default window
- filtering by domain
- filtering by actor
- searching a target
- an unknown domain is ignored rather than emptying
- the export mirrors the filters
- the export is named after the period
- the export hides technical metadata — _L'IP et le chemin interne n'ont pas leur place dans un document remis._
- exporting is itself recorded
- a cashier cannot export the log

### DashboardKpiConsistencyTests

> Les indicateurs doivent dire vrai et mener a une action.

- expired members only counts those who had a subscription
- members who never subscribed are counted apart
- the old subtraction would have overcounted — _Le calcul par soustraction comptait aussi ceux qui n'ont jamais souscrit._
- expiry tiers accumulate — _Un membre a echeance dans cinq jours n'apparaissait dans aucun palier._
- each tier matches the list it links to
- the call list starts with the most urgent
- an explicit sort is respected
- an unknown window falls back on seven days
- the coach ratio is no longer frozen at zero
- period comparisons are supplied to the template — _Les badges existaient dans le template sans donnee derriere._

### TemplateCommentSyntaxTests

> Aucun gabarit ne doit afficher ses propres commentaires.

- no template uses a multiline short comment

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

