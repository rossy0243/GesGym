# Dossier de formation - Caisse et paiements

> Ouverture et cloture de caisse, encaissements, depenses.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `pos`

| Adresse | Vue | Nom interne |
|---|---|---|
| `` | `views.cashier_dashboard` | `cashier_dashboard` |
| `search-members/` | `views.search_members` | `search_members` |
| `open-register/` | `views.open_register` | `open_register` |
| `close-register/<int:register_id>/` | `views.close_register` | `close_register` |
| `register-history/` | `views.register_history` | `register_history` |
| `register-detail/<int:register_id>/` | `views.register_detail` | `register_detail` |

## Donnees manipulees

### `CashRegister`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `session_code` | CharField |
| `opened_by` | ForeignKey |
| `closed_by` | ForeignKey |
| `opening_amount` | DecimalField |
| `exchange_rate` | DecimalField |
| `closing_amount` | DecimalField |
| `difference` | DecimalField |
| `opened_at` | DateTimeField |
| `closed_at` | DateTimeField |
| `is_closed` | BooleanField |

### `Payment`

| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `cash_register` | ForeignKey |
| `member` | ForeignKey |
| `subscription` | ForeignKey |
| `currency` | CharField |
| `exchange_rate` | DecimalField |
| `amount_cdf` | DecimalField |
| `amount_usd` | DecimalField |
| `amount` | DecimalField |
| `method` | CharField |
| `status` | CharField |
| `type` | CharField |
| `category` | CharField |
| `transaction_id` | CharField |
| `description` | CharField |
| `source_app` | CharField |
| `source_model` | CharField |
| `source_id` | PositiveIntegerField |
| `created_by` | ForeignKey |
| `created_at` | DateTimeField |
| `product` | ForeignKey |

Valeurs possibles `STATUS` :

```python
(('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed'))
```

Valeurs possibles `CATEGORY_CHOICES` :

```python
(('subscription', 'Abonnement'), ('product', 'Vente produit'), ('salary', 'Salaire'), ('maintenance', 'Maintenance'), ('expense', 'Depense'), ('other', 'Autre'))
```

### `ExchangeRate`

> Taux du jour défini manuellement par le gym


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `rate` | DecimalField |
| `date` | DateField |
| `created_at` | DateTimeField |

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `search_members` | `login_required`<br>`role_required(POS_CASHIER_ROLES)`<br>`module_required('POS')` |
| `cashier_dashboard` | `login_required`<br>`role_required(POS_CASHIER_ROLES)`<br>`module_required('POS')` |
| `open_register` | `login_required`<br>`role_required(POS_CASHIER_ROLES)`<br>`module_required('POS')` |
| `close_register` | `login_required`<br>`role_required(POS_CASHIER_ROLES)`<br>`module_required('POS')` |
| `register_history` | `login_required`<br>`role_required(POS_HISTORY_ROLES)`<br>`module_required('POS')` |
| `register_detail` | `login_required`<br>`role_required(POS_HISTORY_ROLES)`<br>`module_required('POS')` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- Aucune caisse ouverte pour cet utilisateur. Ouvrez votre session POS avant tout mouvement financier.
- Aucune caisse ouverte. Ouvrez une session POS avant tout mouvement financier.
- Impossible d'enregistrer un mouvement sur une caisse fermee.
- L'abonnement n'appartient pas à ce gym.
- La caisse n'appartient pas a ce gym.
- La caisse ouverte n'a pas de taux USD-CDF valide.
- La date de debut est invalide.
- La date de debut ne peut pas etre dans le futur pour un abonnement encaisse.
- La formule d'abonnement n'appartient pas a ce gym.
- La quantite vendue doit etre superieure a zero.
- La quantite vendue est invalide.
- Le fonds d'ouverture ne peut pas etre negatif.
- Le membre doit etre actif pour acheter un abonnement.
- Le membre n'appartient pas a ce gym.
- Le membre n'appartient pas à ce gym.
- Le montant doit etre superieur a zero.
- Le montant reel ne peut pas etre negatif.
- Le produit n'appartient pas à ce gym.
- Le taux USD-CDF doit etre superieur a zero.
- Le taux USD-CDF est obligatoire pour ouvrir la caisse.
- Le taux de change doit etre superieur a zero.
- Le taux de change est requis pour USD
- Produit introuvable pour ce gym.
- Une caisse est deja ouverte pour cet utilisateur dans ce gym.
- {valeur} invalide.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Caisse de {valeur} cloturee d'autorite. Difference : {valeur} CDF. L'ecart reste attribue a son titulaire.
- Caisse fermee. Difference : {valeur} CDF
- Caisse ouverte avec succes.
- Decaissement enregistre.
- Paiement abonnement enregistre: {valeur} {valeur}.
- Vente produit enregistree: {valeur} {valeur}.

### Avertissements

- Vous avez deja une caisse ouverte.

### Refus et erreurs

- Aucune caisse ouverte.
- Cette session de caisse n'a pas de taux USD-CDF. Fermez-la puis ouvrez une nouvelle session.
- Devise invalide.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `pos.expense_recorded`
- `pos.product_sale_recorded`
- `pos.register_closed`
- `pos.register_opened`
- `pos.subscription_payment_recorded`

## Ecrans concernes

- `pos\templates\pos\cashier.html`
- `pos\templates\pos\close_register.html`
- `pos\templates\pos\register_detail.html`
- `pos\templates\pos\register_history.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### PosAccountingTests
- cash register requires exchange rate when opening
- exchange rate is saved per gym and day
- usd payment is converted to cdf with register rate
- cdf payment clears any usd reference
- payment requires cash register
- product sale is recorded in pos and updates stock
- subscription payment respects start date and auto renew
- subscription payment rejects inactive member
- cash register totals use cdf accounting amounts
- payment rejects cross gym member
- cashier dashboard requires active module
- open register logs sensitive action
- each user can have their own open register
- cashier dashboard uses only current users register
- pos payment uses current users register
- manager can force close another users register — _Regle revue : une caisse laissee ouverte par quelqu'un qui a quitte son_
- manager can supervise register history
- cashier dashboard labels machine maintenance payments
- register detail labels machine maintenance payments
- cashier dashboard labels salary payments
- register detail labels salary payments

### ForcedRegisterClosureTests

> Une caisse laissee ouverte ne doit pas rester bloquee indefiniment.

- owner can close a register left open
- manager can close a register left open
- the difference stays attached to the original holder
- a forced closure is audited as such
- the page warns before a forced closure
- the holder can open a new register afterwards
- a cashier still cannot close someone else register
- a normal closure is not flagged as forced
- another gym register stays out of reach

### CashDrawerSeparationTests

> Le tiroir ne contient que des especes ; le reste se rapproche ailleurs.

- only cash counts towards the expected drawer
- a bank transfer never touches the drawer
- a card payment never touches the drawer
- cash movements still move the drawer
- non cash movements are tracked apart
- global totals still cover every method — _Les rapports comptables continuent de tout voir._
- a negative cash balance is allowed but flagged
- a healthy balance is not flagged
- non cash exits cannot make the drawer negative — _Un virement important ne doit pas declencher une fausse alerte._
- the close page separates both natures

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

