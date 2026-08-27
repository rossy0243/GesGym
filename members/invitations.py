"""
Regles du mode invite.

Un membre dont la formule le prevoit remet un carnet a une personne exterieure :
un nom, un numero, et un nombre de seances. L'invite entre avec un QR code et ne
devient jamais membre.

Tout ce qui decide vit ici. Les vues ne font qu'appeler et afficher, pour que la
meme regle s'applique que l'invite se presente au comptoir ou devant le lecteur.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import GuestPass


# Un meme numero ne peut pas etre invite indefiniment : deux invitations par
# mois a la meme personne vaudraient un demi-abonnement gratuit a vie. Passe ce
# seuil, c'est un abonnement qu'il faut lui proposer.
PLAFOND_PAR_PERSONNE = 3
FENETRE_PLAFOND_JOURS = 365

# Un mois d'abonnement est une tranche de trente jours depuis sa date de debut.
# Les durees du projet s'expriment en jours : compter en mois calendaires ferait
# diverger le quota de l'abonnement qui le porte.
JOURS_PAR_TRANCHE = 30


def _numero_normalise(telephone):
    """
    Forme comparable d'un numero.

    Sans cela, « 0821886995 » et « 082 188 69 95 » compteraient pour deux
    personnes differentes, et le plafond ne servirait a rien.
    """
    return "".join(caractere for caractere in str(telephone or "") if caractere.isdigit())


# ---------------------------------------------------------------------------
# Quota du membre
# ---------------------------------------------------------------------------


def tranche_courante(member):
    """
    Premier et dernier jour du mois d'abonnement en cours.

    On raisonne en dates : un abonnement commence un jour, pas a une heure, et
    melanger les deux ferait glisser la frontiere selon le fuseau.

    Renvoie ``(None, None)`` sans abonnement actif : il n'y a alors pas de quota
    a compter.
    """
    abonnement = member.active_subscription
    if abonnement is None:
        return None, None

    ecoule = (timezone.localdate() - abonnement.start_date).days
    rang = max(ecoule // JOURS_PAR_TRANCHE, 0)

    debut = abonnement.start_date + timedelta(days=rang * JOURS_PAR_TRANCHE)
    return debut, debut + timedelta(days=JOURS_PAR_TRANCHE)


def quota(member):
    """
    Etat du droit d'inviter, pour l'ecran comme pour la decision.

    ``accorde`` vient de la formule, ``utilise`` compte les carnets emis dans la
    tranche courante - qu'ils aient servi, expire ou change de nom. Un carnet
    emis est une invitation depensee.
    """
    abonnement = member.active_subscription
    if abonnement is None or abonnement.plan is None:
        return {"accorde": 0, "utilise": 0, "restant": 0, "seances": 0}

    accorde = abonnement.plan.guest_invites_per_month or 0
    debut, fin = tranche_courante(member)

    utilise = 0
    if debut is not None:
        utilise = GuestPass.objects.filter(
            host=member,
            created_at__date__gte=debut,
            created_at__date__lt=fin,
        ).count()

    return {
        "accorde": accorde,
        "utilise": utilise,
        "restant": max(accorde - utilise, 0),
        "seances": abonnement.plan.guest_sessions_per_invite or 1,
    }


def passages_de(gym, telephone, hors=None):
    """Nombre de fois qu'un numero a ete invite dans cette salle, sur un an."""
    numero = _numero_normalise(telephone)
    if not numero:
        return 0

    depuis = timezone.now() - timedelta(days=FENETRE_PLAFOND_JOURS)
    carnets = GuestPass.objects.filter(gym=gym, created_at__gte=depuis)
    if hors is not None:
        carnets = carnets.exclude(pk=hors.pk)

    return sum(
        1 for carnet in carnets.only("guest_phone")
        if _numero_normalise(carnet.guest_phone) == numero
    )


# ---------------------------------------------------------------------------
# Emission et reattribution
# ---------------------------------------------------------------------------


def _verifier_invite(gym, nom, telephone, hors=None):
    nom = (nom or "").strip()
    telephone = (telephone or "").strip()

    if not nom:
        raise ValidationError("Le nom de l'invite est obligatoire.")
    if not _numero_normalise(telephone):
        raise ValidationError("Le telephone de l'invite est obligatoire.")

    if passages_de(gym, telephone, hors=hors) >= PLAFOND_PAR_PERSONNE:
        raise ValidationError(
            f"Cette personne a deja ete invitee {PLAFOND_PAR_PERSONNE} fois "
            "cette annee. Proposez-lui un abonnement."
        )

    return nom, telephone


@transaction.atomic
def emettre(member, nom, telephone, par=None):
    """Remet un carnet a une personne, si le membre y a droit."""
    etat = quota(member)

    if member.active_subscription is None:
        raise ValidationError(
            "Votre abonnement doit etre actif pour inviter quelqu'un."
        )
    if etat["accorde"] == 0:
        raise ValidationError(
            "Votre formule ne comprend pas d'invitations."
        )
    if etat["restant"] == 0:
        raise ValidationError(
            "Vous avez utilise toutes vos invitations pour cette periode."
        )

    nom, telephone = _verifier_invite(member.gym, nom, telephone)

    return GuestPass.objects.create(
        gym=member.gym,
        host=member,
        guest_name=nom,
        guest_phone=telephone,
        sessions_allowed=etat["seances"],
        expires_at=timezone.now() + timedelta(days=GuestPass.DUREE_JOURS),
        created_by=par,
    )


@transaction.atomic
def reattribuer(carnet, nom, telephone):
    """
    Change le destinataire d'un carnet que personne n'a encore utilise.

    La date limite ne bouge pas : elle appartient au carnet, pas a l'invite.
    Sinon un membre la reculerait indefiniment en changeant de nom la veille de
    chaque echeance.
    """
    if carnet.sessions_used:
        raise ValidationError(
            "Ce carnet a deja servi : il ne peut plus changer de destinataire."
        )
    if carnet.is_expired:
        raise ValidationError("Ce carnet est caduc.")

    # Le plafond se reverifie sur le nouveau numero : sans cela, la
    # reattribution deviendrait la porte de sortie pour l'atteindre.
    nom, telephone = _verifier_invite(carnet.gym, nom, telephone, hors=carnet)

    carnet.guest_name = nom
    carnet.guest_phone = telephone
    carnet.reassigned_count += 1
    carnet.save(update_fields=[
        "guest_name", "guest_phone", "reassigned_count",
    ])
    return carnet


# ---------------------------------------------------------------------------
# Entree de l'invite
# ---------------------------------------------------------------------------


def retrouver(gym, code):
    """Le carnet portant ce QR code, ou None."""
    try:
        return GuestPass.objects.select_related("host").get(gym=gym, code=code)
    except (GuestPass.DoesNotExist, ValueError, ValidationError):
        return None


def refus_eventuel(carnet):
    """
    Ce qui empeche cet invite d'entrer maintenant, ou None.

    Chaque refus se nomme : un message muet enverrait l'accueil chercher une
    panne inexistante.
    """
    if carnet.sessions_left == 0:
        return "Ce carnet d'invitation est epuise."
    if carnet.is_expired:
        return "Ce carnet d'invitation est caduc."

    # La validite de l'hote se reverifie ici, et pas seulement a l'emission :
    # un membre dont l'abonnement expire ne doit pas laisser derriere lui des
    # invitations encore vivantes.
    if carnet.host.active_subscription is None:
        return f"L'abonnement de {carnet.host.first_name} a expire."
    if not carnet.host.is_active:
        return f"Le compte de {carnet.host.first_name} est suspendu."

    return None


@transaction.atomic
def consommer(carnet):
    """Decompte une seance. A n'appeler qu'apres ``refus_eventuel``."""
    carnet = GuestPass.objects.select_for_update().get(pk=carnet.pk)
    carnet.sessions_used += 1
    carnet.save(update_fields=["sessions_used"])
    return carnet


def libelle_passage(carnet):
    """Ce que le journal affiche pour ce passage."""
    return (
        f"Invite - {carnet.guest_name} "
        f"({carnet.sessions_used}/{carnet.sessions_allowed}), "
        f"invite par {carnet.host.first_name} {carnet.host.last_name}"
    )


def en_cours(gym):
    """
    Carnets qu'un invite peut encore utiliser, pour l'ecran de l'accueil.

    C'est la liste de verification a l'entree : quelqu'un se presente en disant
    « je viens en invite », et l'accueil retrouve son nom sans avoir besoin du
    QR.
    """
    return (
        GuestPass.objects.filter(gym=gym, expires_at__gt=timezone.now())
        .exclude(sessions_used__gte=F("sessions_allowed"))
        .select_related("host")
        .order_by("-created_at")
    )
