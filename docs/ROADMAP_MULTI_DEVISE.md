# Roadmap multi-devise Afrique

## Contexte

GesGym est deja structure pour le multi-tenant: organisations, gyms, roles, modules et donnees scoppes par salle. Cette base est saine pour une extension multi-pays.

En revanche, la couche financiere reste encore orientee RDC:

- POS limite a `USD` / `CDF`.
- Paiements convertis vers `amount_cdf`.
- Caisse ouverte avec un taux `1 USD = X CDF`.
- Produits affiches et prices en `USD`.
- RH, salaires et rapports majoritairement en `CDF`.
- Rapports comptables agreges autour de `amount_cdf`.

Cette logique est coherente pour la RDC, mais elle doit etre generalisee avant une extension propre sur plusieurs pays africains.

## Objectif

Permettre a chaque gym de fonctionner dans sa devise locale, tout en gardant la possibilite d'accepter une devise secondaire et de produire des rapports fiables.

Exemples:

- RDC: base `CDF`, devise secondaire possible `USD`.
- Senegal / Cote d'Ivoire: base `XOF`.
- Cameroun: base `XAF`.
- Rwanda: base `RWF`.
- Kenya: base `KES`.

## Principes cibles

### 1. Devise principale par gym

Chaque gym devra porter une configuration monetaire:

```text
country
base_currency
secondary_currency optional
```

La devise principale devient la devise comptable du gym.

### 2. Paiements en devise generique

Remplacer progressivement la logique specifique `amount_cdf` / `amount_usd` par:

```text
amount_original
currency_original
amount_base
base_currency
exchange_rate
```

`amount_base` represente toujours le montant comptable dans la devise principale du gym.

### 3. Taux fige par transaction

Le taux utilise au moment d'un paiement doit rester stocke sur la transaction.

On ne doit jamais recalculer un ancien paiement avec le taux du jour.

### 4. Prix par devise

Les produits, abonnements et services ne doivent plus supposer une devise fixe.

Modele cible:

```text
price_amount
price_currency
```

### 5. Caisse par devise locale

La caisse doit s'ouvrir dans la devise principale du gym.

Elle peut accepter une devise secondaire si le gym l'a configuree.

### 6. Rapports

Les rapports doivent afficher:

- les montants dans la devise principale du gym;
- les montants originaux quand ils sont utiles;
- le taux historique utilise;
- une consolidation optionnelle dans une devise choisie pour les owners multi-pays.

## Impacts fonctionnels

Modules a adapter:

- POS et caisse.
- Paiements.
- Produits et valeur de stock.
- Abonnements et ventes.
- RH et salaires.
- Rapports comptables.
- Dashboards KPI.
- Exports CSV/XLSX.
- Templates avec `CDF` ou `USD` en dur.

## Strategie recommandee

### Phase 1: configuration devise

- Ajouter `country`, `base_currency`, `secondary_currency` sur `Gym`.
- Ajouter une liste de devises supportees.
- Exposer cette configuration dans les parametres.

### Phase 2: couche monetaire

- Introduire des helpers de formatage montant/devise.
- Introduire une fonction de conversion vers devise base.
- Centraliser les libelles de devise.

### Phase 3: migration POS

- Ajouter les champs generiques sur les paiements.
- Garder temporairement `amount_cdf` pour compatibilite.
- Adapter les services POS pour ecrire les deux formats pendant la transition.

### Phase 4: migration affichage

- Remplacer les `CDF` / `USD` hardcodes dans les templates.
- Adapter les tableaux, cards, rapports et exports.

### Phase 5: nettoyage

- Deprecier progressivement les champs specifiques `amount_cdf` / `amount_usd`.
- Mettre a jour les tests de reporting.
- Ajouter une couverture multi-pays.

## Decision produit

Cette evolution doit etre traitee comme une fondation produit avant l'ouverture multi-pays. Ce n'est pas un simple changement d'affichage.

La plateforme est prete a evoluer vers ce modele, mais elle ne doit pas etre ouverte a plusieurs pays avant que la couche monetaire soit generalisee.
