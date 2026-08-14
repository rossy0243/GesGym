# Dossier de formation - Ressources humaines

> Employes, pointage, paie et circuit de validation.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `rh`

| Adresse | Vue | Nom interne |
|---|---|---|
| `employees/` | `views.employee_list` | `list` |
| `employees/create/` | `views.employee_create` | `create` |
| `employees/<int:employee_id>/` | `views.employee_detail` | `detail` |
| `employees/<int:employee_id>/update/` | `views.employee_update` | `update` |
| `employees/<int:employee_id>/delete/` | `views.employee_delete` | `delete` |
| `attendances/` | `views.attendance_list` | `attendance_list` |
| `attendances/create/` | `views.attendance_create` | `attendance_create` |
| `attendances/bulk/` | `views.attendance_bulk` | `attendance_bulk` |
| `payroll/` | `views.payroll_dashboard` | `payroll_dashboard` |
| `payroll/contribution-rules/add/` | `views.add_contribution_rule` | `add_contribution_rule` |
| `payroll/contribution-rules/<int:rule_id>/toggle/` | `views.toggle_contribution_rule` | `toggle_contribution_rule` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/adjustments/add/` | `views.add_adjustment` | `add_adjustment` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/leaves/add/` | `views.add_leave_request` | `add_leave_request` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/overtime/add/` | `views.add_overtime_entry` | `add_overtime_entry` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/review/` | `views.review_payroll_slip` | `review_payroll_slip` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/approve/` | `views.approve_payroll_slip` | `approve_payroll_slip` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/pay/` | `views.process_payment` | `process_payment` |
| `payroll/<int:employee_id>/<int:year>/<int:month>/pdf/` | `views.download_payslip_pdf` | `download_payslip_pdf` |

## Donnees manipulees

### `Employee`

> Employe RH rattache a un gym.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `role` | CharField |
| `phone` | CharField |
| `email` | EmailField |
| `compensation_type` | CharField |
| `daily_salary` | DecimalField |
| `monthly_salary` | DecimalField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

Valeurs possibles `ROLE_CHOICES` :

```python
(('manager', 'Manager'), ('coach', 'Coach'), ('reception', 'Accueil'), ('cashier', 'Caissier'), ('cleaner', "Agent d'entretien"))
```

Valeurs possibles `COMPENSATION_TYPE_CHOICES` :

```python
((COMPENSATION_DAILY, 'Salaire journalier'), (COMPENSATION_MONTHLY, 'Salaire mensuel fixe'))
```

### `Attendance`

> Presence journaliere des employes.


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `employee` | ForeignKey |
| `date` | DateField |
| `status` | CharField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `STATUS` :

```python
(('present', 'Present'), ('absent', 'Absent'))
```

### `PaymentRecord`

> Paiement effectif d'un salaire.


| Champ | Type |
|---|---|
| `employee` | ForeignKey |
| `gym` | ForeignKey |
| `year` | IntegerField |
| `month` | IntegerField |
| `amount` | DecimalField |
| `present_days` | IntegerField |
| `payment_date` | DateField |
| `payment_method` | CharField |
| `reference` | CharField |
| `notes` | TextField |
| `is_paid` | BooleanField |
| `pos_payment` | OneToOneField |
| `created_at` | DateTimeField |

### `LeaveRequest`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `employee` | ForeignKey |
| `leave_type` | CharField |
| `start_date` | DateField |
| `end_date` | DateField |
| `reason` | CharField |
| `status` | CharField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `LEAVE_TYPE_CHOICES` :

```python
((TYPE_PAID, 'Conge paye'), (TYPE_UNPAID, 'Conge sans solde'), (TYPE_SICK, 'Conge maladie'))
```

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_PENDING, 'En attente'), (STATUS_APPROVED, 'Approuve'), (STATUS_REJECTED, 'Refuse'))
```

### `OvertimeEntry`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `employee` | ForeignKey |
| `work_date` | DateField |
| `hours` | DecimalField |
| `rate_multiplier` | DecimalField |
| `amount` | DecimalField |
| `reason` | CharField |
| `status` | CharField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_PENDING, 'En attente'), (STATUS_APPROVED, 'Approuve'), (STATUS_REJECTED, 'Refuse'))
```

### `PayrollAdjustment`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `employee` | ForeignKey |
| `year` | IntegerField |
| `month` | IntegerField |
| `adjustment_type` | CharField |
| `label` | CharField |
| `amount` | DecimalField |
| `notes` | TextField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `TYPE_CHOICES` :

```python
((TYPE_BONUS, 'Prime'), (TYPE_ADVANCE, 'Avance'), (TYPE_DEDUCTION, 'Retenue'))
```

### `PayrollContributionRule`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `party` | CharField |
| `calculation_type` | CharField |
| `rate_percent` | DecimalField |
| `fixed_amount` | DecimalField |
| `is_active` | BooleanField |
| `display_order` | PositiveIntegerField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `PARTY_CHOICES` :

```python
((PARTY_EMPLOYEE_TAX, 'Taxe employee'), (PARTY_EMPLOYEE_CONTRIBUTION, 'Cotisation employee'), (PARTY_EMPLOYER_CONTRIBUTION, 'Cotisation employeur'))
```

Valeurs possibles `CALCULATION_CHOICES` :

```python
((CALC_PERCENTAGE, 'Pourcentage du brut'), (CALC_FIXED, 'Montant fixe'))
```

### `PayrollSlip`

| Champ | Type |
|---|---|
| `employee` | ForeignKey |
| `gym` | ForeignKey |
| `year` | IntegerField |
| `month` | IntegerField |
| `status` | CharField |
| `compensation_type` | CharField |
| `base_salary` | DecimalField |
| `present_days` | IntegerField |
| `paid_leave_days` | IntegerField |
| `unpaid_leave_days` | IntegerField |
| `bonus_total` | DecimalField |
| `overtime_total` | DecimalField |
| `deduction_total` | DecimalField |
| `advance_total` | DecimalField |
| `leave_deduction_total` | DecimalField |
| `employee_tax_total` | DecimalField |
| `employee_contribution_total` | DecimalField |
| `employer_contribution_total` | DecimalField |
| `gross_salary` | DecimalField |
| `net_salary` | DecimalField |
| `notes` | TextField |
| `reviewed_at` | DateTimeField |
| `reviewed_by` | ForeignKey |
| `approved_at` | DateTimeField |
| `approved_by` | ForeignKey |
| `paid_at` | DateTimeField |
| `payment_record` | OneToOneField |
| `created_at` | DateTimeField |
| `updated_at` | DateTimeField |

Valeurs possibles `STATUS_CHOICES` :

```python
((STATUS_DRAFT, 'Brouillon'), (STATUS_REVIEWED, 'Verifie'), (STATUS_APPROVED, 'Approuve'), (STATUS_PAID, 'Paye'))
```

### `PayrollWorkflowLog`

| Champ | Type |
|---|---|
| `slip` | ForeignKey |
| `actor` | ForeignKey |
| `action` | CharField |
| `note` | CharField |
| `created_at` | DateTimeField |

Valeurs possibles `ACTION_CHOICES` :

```python
((ACTION_REVIEW, 'Verification'), (ACTION_APPROVE, 'Approbation'), (ACTION_PAY, 'Paiement'))
```

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `employee_list` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_EMPLOYEE_ROLES)` |
| `employee_detail` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_EMPLOYEE_ROLES)` |
| `employee_create` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_EMPLOYEE_ROLES)` |
| `employee_update` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_EMPLOYEE_ROLES)` |
| `employee_delete` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_EMPLOYEE_ROLES)` |
| `attendance_create` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_ATTENDANCE_ROLES)` |
| `attendance_bulk` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_ATTENDANCE_ROLES)` |
| `attendance_list` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_ATTENDANCE_ROLES)` |
| `payroll_dashboard` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `add_contribution_rule` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `toggle_contribution_rule` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `add_adjustment` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `add_leave_request` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `add_overtime_entry` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `review_payroll_slip` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `approve_payroll_slip` | `login_required`<br>`require_POST`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `process_payment` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |
| `download_payslip_pdf` | `login_required`<br>`module_required('RH')`<br>`role_required(RH_PAYROLL_ROLES)` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Le bulletin doit d'abord etre verifie.
- Le bulletin est deja paye.
- Le salaire journalier ne peut pas etre negatif.
- Le salaire mensuel ne peut pas etre negatif.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Ajustement de paie ajoute.
- Bulletin de {valeur} approuve.
- Bulletin de {valeur} verifie.
- Conge enregistre.
- Employe "{valeur}" cree avec succes. {valeur}
- Employe "{valeur}" desactive avec succes.
- Employe "{valeur}" modifie avec succes.
- Heures supplementaires ajoutees.
- Paiement de {valeur} CDF enregistre via POS pour {valeur}.
- Presence enregistree pour {valeur}.
- Regle de cotisation ajoutee.
- Regle de cotisation mise a jour.
- {valeur} presences enregistrees pour le {valeur}.

### Avertissements

- Ce bulletin est deja paye via POS. Les ajustements de paie sont desormais bloques pour preserver la coherence comptable.
- Le bulletin doit etre approuve avant paiement.
- Le salaire de {valeur} est deja paye.

### Refus et erreurs

- Impossible d'ajouter l'ajustement de paie.
- Impossible d'ajouter la regle de cotisation.
- Impossible d'ajouter les heures supplementaires.
- Impossible d'enregistrer le conge.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `rh.employee_created`
- `rh.employee_deactivated`
- `rh.employee_updated`

## Ecrans concernes

- `rh\templates\rh\attendance_bulk.html`
- `rh\templates\rh\attendance_form.html`
- `rh\templates\rh\attendance_list.html`
- `rh\templates\rh\employee_confirm_delete.html`
- `rh\templates\rh\employee_detail.html`
- `rh\templates\rh\employee_form.html`
- `rh\templates\rh\employee_list.html`
- `rh\templates\rh\payment_form.html`
- `rh\templates\rh\payroll_dashboard.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### RhTenantTests
- employee list is scoped to current gym
- other gym employee detail is not accessible
- attendance list is scoped to current gym
- payroll dashboard is scoped to current gym
- general dashboard includes scoped rh kpis — _La carte intitulee « KPI RH » a ete remplacee par « Expirations_
- payment cannot target other gym employee
- payroll action endpoints require post
- salary payment creates pos expense
- paid slip blocks new adjustments
- paid slip blocks leave and overtime changes
- paid slip hides adjustment forms in employee detail
- form pages render without gym id urls
- employee create sends coordinates email
- payroll slip starts as draft then can be approved
- pdf download returns pdf response
- adjustment bonus changes net salary
- unpaid leave creates leave deduction
- overtime entry increases net salary
- attendance rejects cross gym employee
- leave rejects cross gym employee
- adjustment rejects cross gym employee
- monthly salary employee uses fixed base
- employee tax rule reduces net salary
- employer contribution does not reduce net salary
- fixed employee contribution rule reduces net salary
- contribution rule can be added from dashboard

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

