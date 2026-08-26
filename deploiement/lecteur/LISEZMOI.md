# Rendre un lecteur pilotable depuis l'application en ligne

L'application est hebergee sur internet ; le lecteur vit dans le reseau de la
salle, derriere une connexion sans adresse publique. Le lecteur sait sortir
vers internet — c'est ainsi qu'il remonte les passages — mais rien ne peut
entrer. Le tunnel ouvre ce chemin retour, et lui seul.

Ce qu'il rend possible : enroler un visage, pousser une date de validite apres
un paiement, ouvrir la porte a distance. **Les passages, eux, remontent deja
sans lui** : ne coupez jamais un lecteur du reseau en croyant que le tunnel en
est responsable.

## Ce dont vous avez besoin

- une machine de la salle qui reste allumee, sur le meme reseau que le lecteur ;
- l'adresse du lecteur, lisible sur sa fiche dans l'application ;
- pour l'installation definitive seulement : un domaine technique gere par
  Cloudflare. **Pas le domaine du site.** Prenez-en un separement : il n'est
  jamais vu par les membres, et le site de production n'est jamais touche.

## Etape 1 — La demonstration, sur place, en cinq minutes

A faire une fois par salle, pour verifier que tout repond avant d'engager quoi
que ce soit.

```powershell
.\tunnel-demo.ps1
```

Si le lecteur n'est pas en `192.168.1.188` :

```powershell
.\tunnel-demo.ps1 -Lecteur 192.168.1.50
```

Le script telecharge `cloudflared` s'il manque, verifie que le lecteur repond,
puis affiche une adresse en `trycloudflare.com`.

Dans l'application, sur la fiche du lecteur, cliquez **Modifier** :

| Champ | Valeur |
| --- | --- |
| Adresse ou nom d'hote | l'adresse affichee, sans `https://` |
| Port | `443` |
| Lecteur joint par un tunnel (HTTPS) | coche |
| Mot de passe | laisser vide |

Enregistrez, puis cliquez **Ouvrir**. Si la porte s'ouvre, la salle est prete
pour l'etape 2.

**Fermez la fenetre des que le test est fait.** Tant qu'elle est ouverte,
l'administration du lecteur est joignable par qui connait l'adresse. Cette
adresse est jetable : elle change a chaque demarrage, ce qui interdit d'en
faire une installation.

## Etape 2 — L'installation definitive

Dans un PowerShell **administrateur** :

```powershell
.\tunnel-permanent.ps1 -Salle royal -Domaine exemple-technique.com
```

Le nom obtenu sera `royal.exemple-technique.com`, fixe pour toujours. Le script
ouvre votre navigateur pour l'autorisation Cloudflare, cree le tunnel,
l'associe au nom, puis l'installe en **service Windows** : il repart seul apres
une coupure de courant, sans que personne ait a y penser.

Reportez ensuite ce nom dans la fiche du lecteur, comme a l'etape 1.

## Etape 3 — Fermer la porte a tout le monde sauf nous

A ce stade, le nom est public. Un jeton le referme.

1. Dans Cloudflare, ouvrez **Zero Trust → Access → Applications**, puis
   *Add an application* → *Self-hosted*.
2. Domaine de l'application : le nom de la salle, par exemple
   `royal.exemple-technique.com`.
3. Ajoutez une regle **Service Auth** et creez un **jeton de service**.
4. Copiez l'identifiant et le secret : le secret ne sera plus jamais affiche.
5. Dans l'application, fiche du lecteur → **Modifier**, cochez la case tunnel
   et collez les deux valeurs.

Sans cette etape, l'adresse du lecteur suffit a atteindre son administration.
Avec elle, seule l'application peut le joindre.

## Verifier que tout tient

Sur la fiche du lecteur, deux voyants disent deux choses differentes :

- **Remonte les passages** — le lecteur ecrit a l'application. Il ne depend
  pas du tunnel.
- **Pilotable** — l'application peut appeler le lecteur. C'est celui-ci que le
  tunnel allume.

Les deux au vert : l'installation est complete.

## En cas de panne

**Le service tourne-t-il ?**

```powershell
Get-Service cloudflared
Restart-Service cloudflared
```

**Le lecteur repond-il encore sur le reseau local ?**

```powershell
Test-NetConnection 192.168.1.188 -Port 80
```

Si le lecteur ne repond pas localement, le tunnel n'y peut rien : le probleme
est dans la salle.

**Le lecteur a change d'adresse ?** Modifiez `ingress` dans
`%USERPROFILE%\.cloudflared\config.yml`, puis `Restart-Service cloudflared`.
Le mieux reste de fixer son adresse sur le routeur.
