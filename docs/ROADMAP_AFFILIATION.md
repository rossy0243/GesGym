# Roadmap affiliation SmartClub Pro

## Contexte

L'affiliation peut devenir un levier marketing important pour SmartClub Pro, surtout dans les marches ou la recommandation terrain compte beaucoup.

Le principe est simple: une personne recommande SmartClub Pro a une salle de sport. Si cette salle devient cliente payante, l'affilie touche une commission.

Exemple:

```text
Lien affilie: https://smartclubpro.org/?ref=JEANFIT
Client recommande: Salle Alpha
Client converti: oui
Commission: generee puis validee manuellement
```

## Objectif

Mettre en place un systeme d'affiliation controle, simple a administrer, et evolutif.

La premiere version ne doit pas automatiser trop vite les paiements. Elle doit surtout permettre de:

- identifier l'affilie;
- rattacher une organisation cliente a un code;
- suivre les conversions;
- generer une commission;
- valider ou payer manuellement.

## Fonctionnement cible

### 1. Creation d'un affilie

Un administrateur SaaS cree un affilie avec:

```text
name
phone
email
referral_code
is_active
```

Exemple de code:

```text
JEANFIT
COACHMIRA
FITKIN01
```

### 2. Lien de tracking

Chaque affilie partage un lien:

```text
https://smartclubpro.org/?ref=JEANFIT
```

Quand un prospect arrive via ce lien, le code est stocke temporairement en session ou cookie.

### 3. Rattachement du client

Lorsqu'une organisation cliente est creee, le systeme peut enregistrer:

```text
referred_by
referral_code_used
referral_attached_at
```

Le rattachement doit rester visible et modifiable par un administrateur SaaS en cas d'erreur.

### 4. Generation de commission

Quand l'organisation devient cliente payante, une commission est creee.

Modele cible:

```text
affiliate
organization
amount
currency
status
trigger
created_at
validated_at
paid_at
```

Statuts:

```text
pending
validated
paid
cancelled
```

## Modeles de commission possibles

### Commission unique

L'affilie touche une seule commission quand le client devient payant.

Exemple:

```text
Pack Club: 20 USD
Pack Premium: 40 USD
```

Avantage: simple a comprendre et simple a gerer.

### Commission recurrente

L'affilie touche un pourcentage sur chaque paiement client pendant une periode donnee.

Exemple:

```text
10% pendant 12 mois
```

Avantage: tres attractif.

Risque: plus complexe a suivre, surtout tant que la facturation SaaS n'est pas completement automatisee.

### Commission hybride

Bonus a l'activation plus pourcentage limite dans le temps.

Exemple:

```text
10 USD a l'inscription
+ 5% pendant 6 mois
```

Bon compromis pour une version plus avancee.

## MVP recommande

Pour SmartClub Pro, commencer avec:

```text
Code affilie + commission unique + validation manuelle
```

Regles:

- un affilie doit etre actif;
- une organisation ne peut avoir qu'un affilie principal;
- une commission est creee une seule fois par organisation payante;
- l'administrateur SaaS valide la commission;
- le paiement reste manuel au debut.

Cette approche reduit les risques de:

- fausses inscriptions;
- doublons;
- attribution abusive;
- commission sur prospect non converti;
- litige entre affiliés.

## Interface V1

### Admin SaaS

Vues utiles:

- liste des affilies;
- creation/modification d'un affilie;
- organisations rattachees;
- commissions en attente;
- commissions validees;
- commissions payees.

### Portail affilie

Pas necessaire en V1.

Peut etre ajoute plus tard avec:

- lien personnel;
- nombre de prospects;
- clients convertis;
- commissions en attente;
- commissions payees.

## Points de vigilance

- Ne pas donner a l'affilie un acces aux donnees des gyms.
- Ne pas exposer les donnees sensibles des clients recommandes.
- Prevoir une validation manuelle au debut.
- Garder une trace de l'origine du rattachement.
- Eviter les commissions automatiques avant une facturation SaaS fiable.

## Strategie recommandee

### Phase 1: suivi interne

- Ajouter les modeles `Affiliate` et `AffiliateCommission`.
- Ajouter le rattachement optionnel sur `Organization`.
- Gerer les commissions dans l'admin SaaS.

### Phase 2: tracking public

- Lire `?ref=CODE`.
- Stocker le code en session/cookie.
- Rattacher automatiquement lors d'une demande demo ou creation client.

### Phase 3: dashboard SaaS

- Ajouter des KPI affiliation:
  - affilies actifs;
  - clients rattaches;
  - commissions en attente;
  - commissions payees.

### Phase 4: portail affilie

- Ajouter une authentification affilie separee.
- Afficher les conversions et commissions.
- Ne pas exposer les donnees operationnelles des gyms.

### Phase 5: commissions recurrentes

- Lier les commissions aux paiements SaaS.
- Calculer un pourcentage par periode.
- Geler les regles de commission au moment de l'inscription client.

## Decision produit

L'affiliation est pertinente pour SmartClub Pro, mais la premiere version doit rester controlee.

Le MVP recommande est une commission unique, rattachee a un code affilie, validee manuellement par l'admin SaaS.
