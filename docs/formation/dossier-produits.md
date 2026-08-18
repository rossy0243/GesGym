# Dossier de formation - Produits et stock

> Catalogue, mouvements de stock, ventes au comptoir.

Ce dossier rassemble la matiere brute du module. Il sert a rediger la
formation : il n'en est pas une. Les intitules proviennent du code, donc
de ce que le logiciel fait reellement, pas de ce qu'on croit qu'il fait.

## Parcours accessibles

### Application `products`

| Adresse | Vue | Nom interne |
|---|---|---|
| `products/` | `views.product_list` | `list` |
| `products/create/` | `views.product_create` | `create` |
| `products/<int:product_id>/` | `views.product_detail` | `detail` |
| `products/<int:product_id>/update/` | `views.product_update` | `update` |
| `products/<int:product_id>/delete/` | `views.product_delete` | `delete` |
| `products/<int:product_id>/movement/add/` | `views.stock_movement_create` | `add_movement` |
| `movements/` | `views.stock_movement_list` | `movement_list` |
| `stock/dashboard/` | `views.stock_dashboard` | `stock_dashboard` |

## Donnees manipulees

### `Product`

> Produit vendu dans le gym (boisson, complément, etc.)


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `name` | CharField |
| `price` | DecimalField |
| `currency` | CharField |
| `quantity` | IntegerField |
| `is_active` | BooleanField |
| `created_at` | DateTimeField |

Valeurs possibles `CURRENCY_CHOICES` :

```python
((CURRENCY_USD, 'USD (Dollar americain)'), (CURRENCY_CDF, 'CDF (Franc congolais)'))
```

### `StockMovement`

> Historique des mouvements de stock


| Champ | Type |
|---|---|
| `gym` | ForeignKey |
| `product` | ForeignKey |
| `quantity` | IntegerField |
| `movement_type` | CharField |
| `reason` | CharField |
| `created_at` | DateTimeField |

## Qui a le droit de faire quoi

Garde-fous poses sur chaque vue. A traduire en langage metier dans la
formation : « la reception peut pointer mais pas consulter les salaires ».

| Action | Protections |
|---|---|
| `product_list` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `product_detail` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `product_create` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `product_update` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `product_delete` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `stock_movement_create` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `stock_movement_list` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |
| `stock_dashboard` | `login_required`<br>`module_required('PRODUCTS')`<br>`role_required(PRODUCT_ROLES)` |

## Regles metier appliquees

Refus opposes par le logiciel. Chacun merite une explication dans la
formation : pourquoi la regle existe, et que faire quand on la rencontre.

- La quantite doit etre superieure a zero.
- La quantite ne peut pas etre negative.
- Le prix ne peut pas etre negatif.

## Ce que l'utilisateur lit a l'ecran

Messages affiches apres une action. Ils donnent le vocabulaire exact a
employer dans la formation : l'apprenant doit reconnaitre ce qu'il verra.

### Confirmations

- Entree de stock enregistree : {valeur} - {valeur}.
- Produit "{valeur}" cree avec succes.
- Produit "{valeur}" desactive avec succes.
- Produit "{valeur}" modifie avec succes.

## Traces laissees dans le journal sensible

Actions consignees. Utile pour expliquer aux equipes ce qui est trace,
et rassurer sur ce qui ne l'est pas.

- `products.product_deactivated`
- `products.stock_adjusted`
- `products.stock_movement`

## Ecrans concernes

- `products\templates\products\product_confirm_delete.html`
- `products\templates\products\product_detail.html`
- `products\templates\products\product_form.html`
- `products\templates\products\product_list.html`
- `products\templates\products\stock_dashboard.html`
- `products\templates\products\stock_movement_form.html`
- `products\templates\products\stock_movement_list.html`

## Comportements garantis par les tests

Chaque intitule decrit une promesse verifiee automatiquement. C'est la
meilleure source pour les cas limites a montrer en formation.

### ProductsTenantTests
- product list is scoped to current gym
- other gym product detail is not accessible
- stock movement list is scoped to current gym
- stock dashboard kpis are scoped to current gym
- general dashboard includes scoped product kpis
- movement cannot target other gym product
- stock movement rejects cross gym product
- manual movement is always an entry
- form pages render without gym id urls

### ProductCurrencyTests

> Un produit peut etre price en francs ou en dollars.

- a product keeps its own price in its own currency
- a cdf product is converted to usd at the session rate
- a usd product is converted to cdf at the session rate
- converting without a rate is refused
- selling a cdf product in cdf charges the shelf price
- selling a cdf product in usd converts at the session rate
- selling a usd product is unchanged
- stock value converts cdf products to usd
- stock value ignores cdf products when no rate is known
- the open register rate is used for stock indicators
- products without rate are counted rather than hidden

## A completer par un humain

Le code ne dit pas tout. Avant de rediger, il faut trancher :

- Qui suit cette formation : reception, caisse, gerant, proprietaire ?
- Quelles taches quotidiennes reelles doit-on savoir faire a la fin ?
- Quels incidents arrivent souvent et doivent etre traites en exercice ?
- Quelles habitudes de la salle different de ce que propose le logiciel ?

