# Roadmap interim - tenir la salle quand le responsable manque

Cadrage arrete le 27 aout 2026 avec le proprietaire. Rien n'est encore code.

## Le besoin

Le gerant ne vient pas. Seule la caissiere est presente. Un client se
presente, et elle ne peut rien faire de ce qui demande le role gerant.

## Ce que l'analyse a d'abord etabli

**Elle peut deja encaisser.** Ouvrir et fermer la caisse, vendre un produit,
vendre un abonnement, prendre un paiement, scanner un QR, ouvrir la porte. Le
blocage n'est pas dans l'argent.

**Ce qui la bloque, ce sont les fiches.** Creer ou modifier un membre,
confirmer une preinscription, suspendre ou reactiver quelqu'un, corriger un
stock. Le cas qui fait mal : un nouveau client arrive, elle peut prendre son
argent mais pas creer sa fiche - donc pas lui vendre son abonnement.

**Le contournement facile n'existe pas.** `UserGymRole` impose
`unique_together = ("user", "gym")` : un employe ne porte qu'un seul role par
salle. On ne peut pas lui ajouter le role reception a cote de la caisse.

## Ce qui a ete tranche

| Question | Decision |
| --- | --- |
| Mecanisme | Delegation temporaire : elle recoit les droits et travaille normalement |
| Qui accorde | Le proprietaire ou le gerant, a distance |
| Si personne ne repond | Apres cinq minutes, elle peut se l'accorder en se justifiant |
| Etendue | Les gestes du quotidien seulement |
| Duree | Jusqu'a la fin de la journee, extinction automatique |
| Beneficiaire | Tout employe present, sauf proprietaire et gerant |

## Ce que j'ai decide seul, a confirmer

- **Le delai avant auto-octroi est de cinq minutes.** Les notifications de
  l'application visent les membres, pas le personnel : prevenir un gerant
  passe donc par un e-mail, qu'un gerant absent lit rarement dans l'instant.
  Attendre dix minutes devant un client pour une reponse qui viendra
  rarement etait un coût sans contrepartie. C'est une constante, pas un
  reglage : un delai negociable finirait a zero.
- **Un seul interim actif a la fois par salle.** Deux interimaires simultanes
  brouilleraient la question de qui tient la salle, et diluerait la
  responsabilite au moment ou elle compte le plus.
- **L'interim ne se renouvelle pas tout seul.** Il meurt a minuit ; le
  lendemain, il faut le redemander. Une absence qui dure doit se voir.
- **Le gerant qui revient ne le coupe pas automatiquement.** Rien ne prouve
  qu'une connexion soit une prise de poste, et retirer des droits en pleine
  operation ferait echouer un geste en cours. La revocation reste manuelle.

## Modele de donnees

### `RoleInterim`

| Champ | Role |
| --- | --- |
| `gym` | la salle concernee |
| `beneficiary` | l'employe qui recoit les droits |
| `granted_by` | qui l'a accorde ; vide si auto-octroi |
| `reason` | motif, obligatoire en auto-octroi |
| `requested_at` | horodatage de la demande |
| `started_at` | debut effectif des droits |
| `expires_at` | fin de la journee de `started_at` |
| `revoked_at`, `revoked_by` | coupure anticipee |
| `self_granted` | vrai si personne n'a repondu |

Deux etats suffisent a le lire : **demande** (`requested_at` seul) et **actif**
(`started_at` pose, ni revoque ni expire).

## Le point d'accroche technique

Tout passe par une seule fonction, `smartclub/access_control.py` :

```python
def has_role(request, allowed_roles):
    role = current_role(request)
    if not role or role not in allowed_roles:
        return False
    ...
```

Les decorateurs et `permission_flags` l'appellent tous. **C'est le seul endroit
a enseigner**, ce qui rend le changement etroit et verifiable :

```python
    if role not in allowed_roles:
        if not (interim_actif(request) and allowed_roles in GROUPES_OUVERTS):
            return False
```

`GROUPES_OUVERTS` est un ensemble des frozensets eux-memes - ils sont
hachables. Ouvrir un droit de plus consiste a y ajouter une ligne, et la liste
se lit d'un coup d'oeil.

## Etendue exacte

**Ouvert par l'interim :**

| Groupe | Ce que cela permet |
| --- | --- |
| `MEMBER_ROLES`, `MEMBER_WRITE_ROLES` | creer et modifier une fiche membre |
| `MEMBER_STATUS_ROLES` | suspendre, reactiver |
| `PRE_REGISTRATION_ROLES` | confirmer une preinscription |
| `PRODUCT_ROLES` | corriger un stock |

**Ferme, meme sous interim :**

`DASHBOARD_ROLES`, `POS_HISTORY_ROLES`, `REPORT_ROLES`, `SETTINGS_ROLES`,
`RH_EMPLOYEE_ROLES`, `RH_PAYROLL_ROLES`, `ACCESS_DEVICE_ROLES`,
`MACHINE_ROLES`, `COACHING_ROLES`, `SUBSCRIPTION_ROLES`.

Le remplaçant debloque la journee. Il ne voit ni le chiffre d'affaires, ni
l'historique de caisse, ni la paie, et ne touche ni aux reglages ni aux
lecteurs. C'est la difference entre tenir la salle et la diriger.

### Deux groupes ouvrent plus que leur nom ne le dit

Le proprietaire a choisi de les laisser tels quels, la tracabilite servant de
contrepartie. Il faut donc le savoir :

- `MEMBER_STATUS_ROLES` ouvre aussi la **regeneration du QR** d'un membre, ce
  qui invalide sa carte imprimee. Le geste est journalise sous
  `member.qr_regenerated`.
- `PRODUCT_ROLES` ouvre **tout le catalogue** - creer, modifier, supprimer un
  produit - la ou le besoin ne demandait qu'un mouvement de stock.

La suppression d'un membre reste hors de portee en toutes circonstances :
`MEMBER_DELETE_ROLES = {"owner"}`, et meme le gerant ne l'a pas.

## Le parcours

1. La caissiere bute sur un geste ferme. L'ecran lui propose de **demander
   l'interim**, en indiquant pourquoi.
2. Le proprietaire et le gerant sont prevenus. L'un d'eux accorde depuis son
   telephone : l'interim demarre aussitot.
3. **Si personne n'a repondu au bout de cinq minutes**, un bouton lui permet de
   se l'accorder. Le motif devient obligatoire, et l'octroi est marque comme
   auto-accorde.
4. Pendant toute la duree, un **bandeau permanent** rappelle qu'elle agit sous
   interim, et jusqu'a quand.
5. A minuit, les droits tombent seuls. Le proprietaire ou le gerant peuvent y
   couper court a tout instant.

## Tracabilite

C'est la contrepartie de la delegation : elle donne de vrais pouvoirs, donc
tout doit rester attribuable.

- l'octroi et la revocation partent au journal d'activite sensible, avec qui,
  quand et pourquoi ;
- **chaque action faite sous interim y est marquee comme telle** - sans quoi
  une correction de stock du mardi serait indistinguable d'une correction
  ordinaire ;
- **tous les gestes ouverts sont deja journalises** : creation et modification
  de membre, suspension, reactivation, regeneration de QR, confirmation de
  preinscription, mouvements et ajustements de stock, creation, modification et
  suppression de produit. La creation de produit ne l'etait pas ; elle l'est
  desormais, verifiee par un test qui tombe si la trace disparait ;
- un auto-octroi est signale distinctement : c'est l'evenement que le
  proprietaire veut pouvoir relire.

## Risques reconnus

- **L'auto-octroi est un droit qu'on s'accorde a soi-meme.** Le delai, le motif
  obligatoire, la notification immediate et la revocation a distance
  l'encadrent ; ils ne l'empechent pas. C'est un choix assume : une salle
  paralysee coute plus qu'un abus rare et visible.
- **La validation a distance sera l'exception.** Faute de canal vers le
  personnel, l'alerte part par e-mail ; en pratique, c'est l'auto-octroi qui
  portera la fonction. L'e-mail sert alors de trace et d'alerte differee, ce
  qui reste utile - mais autant le savoir avant de construire.
- **Un interim quotidien signale autre chose.** Si la caissiere le demande tous
  les jours, le probleme n'est pas technique : c'est le role de la personne
  qu'il faut revoir. Un compteur mensuel par beneficiaire le rendrait visible.

## Fichiers concernes

| Fichier | Role |
| --- | --- |
| `smartclub/access_control.py` | `has_role`, `GROUPES_OUVERTS`, `interim_actif` |
| `compte/models.py` | `RoleInterim`, a cote de `UserGymRole` |
| `core/views.py` | demande, octroi, auto-octroi, revocation |
| `templates/base.html` | le bandeau permanent |
| `core/audit.py` | marquage des actions faites sous interim |
