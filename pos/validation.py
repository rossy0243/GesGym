"""
Qui doit contre-signer une clôture de caisse, et qui peut le faire.

Le principe : **une clôture ne vaut que si quelqu'un d'autre l'a regardee**.
Mais « quelqu'un d'autre » n'a pas le meme sens selon la place de celui qui a
compte le tiroir, et le client a fini par le formuler ainsi :

* le **proprietaire** ne rend de comptes a personne : sa clôture est close ;
* le **gerant** n'ouvre une caisse qu'en depannage. Lui demander une
  contre-signature bloquerait le poste ; le proprietaire est donc informe, et
  l'alerte ne part que lorsqu'il declare avoir vu ;
* **tous les autres** - caissiers, accueil - restent contre-signes par un
  tiers.

Une exception a la regle du gerant : lorsqu'il clôture le tiroir de quelqu'un
d'autre. Ce cas-la n'est pas son depannage habituel - l'argent a ete compte
par une seule personne sur la caisse d'une autre, et personne n'a verifie ce
comptage. La contre-signature reprend ses droits.
"""

from compte.models import UserGymRole

AUCUN = "aucun"
ACQUITTEMENT = "acquittement"
CONTRESIGNATURE = "contresignature"

LIBELLES = {
    AUCUN: "Aucune verification requise",
    ACQUITTEMENT: "A signaler au proprietaire",
    CONTRESIGNATURE: "A contre-signer par un tiers",
}


def est_proprietaire(utilisateur, gym):
    """
    Proprietaire de cette salle, par l'un ou l'autre chemin.

    Ce projet en connait deux : le compte qui possede l'organisation
    (``owned_organization``, ce que le middleware appelle ``is_owner``), et le
    role "owner" attribue sur une salle. Les deux donnent les memes droits
    partout ailleurs ; n'en reconnaitre qu'un ici aurait reclame une
    contre-signature a quelqu'un qui n'en doit aucune, et prive le
    proprietaire de son bandeau selon la facon dont son compte a ete cree.
    """
    if not utilisateur or not gym:
        return False

    if (
        utilisateur.owned_organization_id
        and utilisateur.owned_organization_id == gym.organization_id
    ):
        return True

    return _a_le_role(utilisateur, gym, "owner")


def _a_le_role(utilisateur, gym, role):
    return UserGymRole.objects.filter(
        user=utilisateur, gym=gym, role=role, is_active=True
    ).exists()


def est_gerant(utilisateur, gym):
    if not utilisateur or not gym:
        return False
    return _a_le_role(utilisateur, gym, "manager")


def regime(registre):
    """
    Ce que cette clôture attend : rien, un acquittement, ou une signature.

    Une caisse encore ouverte n'attend rien : on ne contre-signe pas un
    comptage qui n'a pas eu lieu.
    """
    if not registre.is_closed:
        return AUCUN

    auteur = registre.closed_by
    if auteur is None:
        # Compte efface : personne ne peut plus repondre de ce comptage. Un
        # tiers doit le reprendre a son compte.
        return CONTRESIGNATURE

    gym = registre.gym
    if est_proprietaire(auteur, gym):
        return AUCUN

    if est_gerant(auteur, gym) and registre.opened_by_id == auteur.id:
        return ACQUITTEMENT

    return CONTRESIGNATURE


def en_attente(registre):
    """La clôture attend-elle encore un geste ?"""
    return regime(registre) != AUCUN and not registre.is_validated


def peut_signer(registre, utilisateur):
    """
    Cet utilisateur peut-il clore le dossier de cette clôture ?

    Retourne ``(vrai_ou_faux, raison)`` : la raison sert de message quand le
    geste est refuse, plutot qu'un acces interdit qui n'apprend rien.
    """
    if not registre.is_closed:
        return False, "Cette caisse n'est pas encore clôturee."

    if registre.is_validated:
        return False, "Cette clôture a deja ete signalee comme vue."

    besoin = regime(registre)
    gym = registre.gym

    if besoin == AUCUN:
        return False, "Cette clôture n'attend aucune verification."

    if besoin == ACQUITTEMENT:
        if not est_proprietaire(utilisateur, gym):
            return False, (
                "Cette clôture a ete faite par un gerant : seul le "
                "proprietaire peut declarer l'avoir vue."
            )
        return True, ""

    # Contre-signature : un tiers, et jamais celui qui a compte le tiroir.
    if registre.closed_by_id == utilisateur.id:
        return False, (
            "Vous avez clôture cette caisse : la verification revient a "
            "quelqu'un d'autre."
        )

    if est_proprietaire(utilisateur, gym) or est_gerant(utilisateur, gym):
        return True, ""

    return False, "Seuls un gerant ou le proprietaire peuvent contre-signer."


def motif_requis(registre):
    """
    Un ecart ne se signe jamais sans explication.

    Ni pour un caissier, ni pour un gerant : dans six mois, personne ne saura
    s'il s'agissait d'un rendu de monnaie ou d'autre chose. Une caisse juste,
    elle, se signe d'un clic.
    """
    return bool(registre.difference)


def a_acquitter(gym):
    """
    Les clôtures de gerant que le proprietaire n'a pas encore vues.

    Elles alimentent son bandeau : une clôture qu'il pourrait ne jamais lire
    ne serait pas une information.
    """
    from .models import CashRegister

    candidates = (
        CashRegister.objects.filter(
            gym=gym, is_closed=True, validated_at__isnull=True
        )
        .select_related("closed_by", "opened_by", "gym")
        .order_by("-closed_at")
    )
    return [
        registre for registre in candidates if regime(registre) == ACQUITTEMENT
    ]
