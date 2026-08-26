# Rendre un lecteur pilotable depuis l'application en ligne

L'application est hébergée sur internet ; le lecteur vit dans le réseau de la
salle, derrière une connexion sans adresse publique. Le lecteur sait sortir
vers internet — c'est ainsi qu'il remonte les passages — mais rien ne peut
entrer. Le tunnel ouvre ce chemin retour, et lui seul.

Ce qu'il rend possible : enrôler un visage, pousser une date de validité après
un paiement, ouvrir la porte à distance. **Les passages, eux, remontent déjà
sans lui** : ne coupez jamais un lecteur du réseau en croyant que le tunnel en
est responsable.

## Deux fichiers à double-cliquer

| Fichier | Quand |
| --- | --- |
| `DEMONSTRATION.cmd` | Pour vérifier en cinq minutes, sans rien installer |
| `INSTALLER.cmd` | Pour l'installation définitive, une fois par salle |

**Ne lancez jamais les fichiers `.ps1` directement.** Un double-clic dessus les
ouvre dans l'éditeur au lieu de les exécuter, et Windows refuse par défaut les
scripts venus d'une clé USB. Les deux `.cmd` existent pour supprimer ces
pièges : ils demandent les droits nécessaires, contournent le blocage et
gardent la fenêtre ouverte pour que vous puissiez lire ce qui s'est passé.

## Ce dont vous avez besoin

- une machine de la salle qui reste allumée, sur le même réseau que le lecteur ;
- l'adresse du lecteur, lisible sur sa fiche dans l'application ;
- pour l'installation définitive : le domaine **royalgym.site**, géré par
  Cloudflare. Ce n'est pas le domaine du site des membres, qui n'est jamais
  touché.

## Étape 1 — La démonstration

Double-cliquez **`DEMONSTRATION.cmd`**. Si le lecteur n'est pas à l'adresse
habituelle :

```
DEMONSTRATION.cmd -Lecteur 192.168.1.50
```

Le script télécharge ce qu'il faut, vérifie que le lecteur répond, puis affiche
une adresse en `trycloudflare.com`.

Dans l'application, sur la fiche du lecteur, cliquez **Modifier** :

| Champ | Valeur |
| --- | --- |
| Adresse ou nom d'hôte | l'adresse affichée, sans `https://` |
| Port | `443` |
| Lecteur joint par un tunnel (HTTPS) | cochée |
| Mot de passe | laisser vide |

Enregistrez, puis cliquez **Ouvrir**. Si la porte s'ouvre, passez à l'étape 2.

**Fermez la fenêtre dès que le test est fait.** Tant qu'elle tourne,
l'administration du lecteur est joignable par qui connaît l'adresse. Cette
adresse est jetable : elle change à chaque démarrage, ce qui interdit d'en
faire une installation.

## Étape 2 — L'installation définitive

Double-cliquez **`INSTALLER.cmd`** et acceptez la demande d'autorisation.

Le script avance en six étapes numérotées et dit à chacune ce qu'il fait. Au
milieu, votre navigateur s'ouvre : choisissez **royalgym.site** dans la liste,
puis revenez à la fenêtre.

À la fin, le lecteur porte le nom fixe **`royal.royalgym.site`**, et le tunnel
tourne en **service Windows** : il repart seul après une coupure de courant,
sans que personne ait à y penser.

Reportez ce nom dans la fiche du lecteur, comme à l'étape 1.

Pour une autre salle plus tard :

```
INSTALLER.cmd -Salle bandal -Lecteur 192.168.1.50
```

## Étape 3 — Fermer la porte à tout le monde sauf nous

À ce stade, le nom est public. Un jeton le referme.

1. Dans Cloudflare, ouvrez **Zero Trust → Access → Applications**, puis
   *Add an application* → *Self-hosted*.
2. Domaine de l'application : `royal.royalgym.site`.
3. Ajoutez une règle **Service Auth** et créez un **jeton de service**.
4. Copiez l'identifiant et le secret : le secret ne sera plus jamais affiché.
5. Dans l'application, fiche du lecteur → **Modifier**, cochez la case tunnel
   et collez les deux valeurs.

Sans cette étape, l'adresse du lecteur suffit à atteindre son administration.
Avec elle, seule l'application peut le joindre.

## Vérifier que tout tient

Sur la fiche du lecteur, deux voyants disent deux choses différentes :

- **Remonte les passages** — le lecteur écrit à l'application. Ne dépend pas du
  tunnel.
- **Pilotable** — l'application peut appeler le lecteur. C'est celui-ci que le
  tunnel allume.

Les deux au vert : l'installation est complète.

## En cas de panne

**Rien ne s'affiche au lancement ?** Vous avez sans doute double-cliqué un
fichier `.ps1`. Utilisez les `.cmd`.

**Le service tourne-t-il ?**

```powershell
Get-Service cloudflared
Restart-Service cloudflared
```

**Le lecteur répond-il encore sur le réseau local ?**

```powershell
Test-NetConnection 192.168.1.188 -Port 80
```

Si le lecteur ne répond pas localement, le tunnel n'y peut rien : le problème
est dans la salle.

**Le lecteur a changé d'adresse ?** Relancez `INSTALLER.cmd` avec la nouvelle,
puis corrigez la fiche dans l'application. Le mieux reste de fixer son adresse
sur le routeur.

**Autre chose ?** Le détail complet de la dernière installation est conservé
dans `%LOCALAPPDATA%\RoyalGym\installation-tunnel.log`.
