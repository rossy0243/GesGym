"""
Effacement des donnees d'exploitation d'une salle.

Le geste est irreversible et detruit le travail de plusieurs mois. Il n'existe
que parce qu'une salle doit pouvoir repartir de zero apres une periode d'essai,
une reprise ou une erreur de saisie massive.

Ce qui disparait : la vie de la salle. Ce qui reste : sa configuration, pour
qu'elle soit utilisable a la seconde suivante sans tout reparametrer.
"""

import json

from django.apps import apps
from django.core import serializers
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from compte.models import User


# Efface. L'ordre n'a pas d'importance pour le comptage, qui precede toujours
# la suppression ; il en a pour la lecture, alors on suit le parcours d'un
# membre : sa fiche, ses abonnements, son argent, ses passages.
DONNEES_EFFACEES = (
    ("Membres", "members.Member"),
    ("Preinscriptions", "members.MemberPreRegistration"),
    ("Objectifs de membres", "members.MemberGoal"),
    ("Mesures de poids", "members.MemberWeightMeasurement"),
    ("Abonnements souscrits", "subscriptions.MemberSubscription"),
    ("Demandes d'abonnement", "subscriptions.SubscriptionRequest"),
    ("Paiements", "pos.Payment"),
    ("Sessions de caisse", "pos.CashRegister"),
    ("Passages", "access.AccessLog"),
    ("Presences employes", "rh.Attendance"),
    ("Conges", "rh.LeaveRequest"),
    ("Heures supplementaires", "rh.OvertimeEntry"),
    ("Versements de paie", "rh.PaymentRecord"),
    ("Ajustements de paie", "rh.PayrollAdjustment"),
    ("Bulletins de paie", "rh.PayrollSlip"),
    ("Suivis de coaching", "coaching.CoachingFollowUp"),
    ("Avis sur le coaching", "coaching.CoachingFeedback"),
    ("Affectations de coach", "coaching.CoachAssignment"),
    ("Mouvements de stock", "products.StockMovement"),
    ("Notifications", "notifications.Notification"),
)

# Conserve. Enumere pour que l'ecran puisse le montrer : dire ce qui survit
# rassure autant que dire ce qui meurt.
DONNEES_CONSERVEES = (
    ("Formules d'abonnement", "subscriptions.SubscriptionPlan"),
    ("Offres", "subscriptions.SubscriptionOffer"),
    ("Catalogue produits", "products.Product"),
    ("Machines", "machines.Machine"),
    ("Employes", "rh.Employee"),
    ("Regles de cotisation", "rh.PayrollContributionRule"),
    ("Coachs", "coaching.Coach"),
    ("Specialites", "coaching.CoachSpecialty"),
    ("Programmes collectifs", "coaching.GroupCoachingProgram"),
    ("Lecteurs", "access.AccessDevice"),
    ("Acces du personnel", "compte.UserGymRole"),
)


def _modele(chemin):
    application, nom = chemin.split(".")
    return apps.get_model(application, nom)


def _lignes(gym, chemin):
    return _modele(chemin).objects.filter(gym=gym)


def _comptes_des_membres(gym):
    """
    Comptes de connexion appartenant aux membres de cette salle.

    Supprimer une fiche membre ne supprime pas son compte : le lien part du
    membre vers le compte, pas l'inverse. Sans ce nettoyage, la salle se vide
    mais ses identifiants de connexion survivent.

    Un compte portant un role dans une salle est celui d'un employe : on n'y
    touche jamais, meme s'il est aussi membre.
    """
    return (
        User.objects.filter(member_profile__gym=gym)
        .exclude(gym_roles__isnull=False)
        .exclude(is_staff=True)
        .exclude(is_superuser=True)
        .distinct()
    )


def inventaire(gym):
    """
    Ce que l'effacement detruirait, chiffre, avant toute action.

    Sert l'ecran de confirmation : personne ne doit valider sans savoir
    combien de membres et de paiements il s'apprete a perdre.
    """
    efface = [
        {"libelle": libelle, "nombre": _lignes(gym, chemin).count()}
        for libelle, chemin in DONNEES_EFFACEES
    ]
    efface.append(
        {"libelle": "Comptes de connexion des membres",
         "nombre": _comptes_des_membres(gym).count()}
    )

    conserve = [
        {"libelle": libelle, "nombre": _lignes(gym, chemin).count()}
        for libelle, chemin in DONNEES_CONSERVEES
    ]

    return {
        "efface": [ligne for ligne in efface if ligne["nombre"]],
        "conserve": [ligne for ligne in conserve if ligne["nombre"]],
        "total": sum(ligne["nombre"] for ligne in efface),
    }


def exporter(gym):
    """
    Copie complete des donnees sur le point de disparaitre, en JSON.

    Remise au proprietaire avant l'effacement : il doit repartir avec ce
    qu'il detruit, faute de quoi une erreur de manipulation serait sans
    recours.
    """
    donnees = {}
    for _, chemin in DONNEES_EFFACEES:
        lignes = _lignes(gym, chemin)
        if lignes.exists():
            donnees[chemin] = serializers.serialize("python", lignes)

    return json.dumps(
        {
            "salle": {"id": gym.id, "nom": gym.name, "slug": gym.slug},
            "genere_le": timezone.now().isoformat(),
            "avertissement": (
                "Sauvegarde produite avant effacement des donnees "
                "d'exploitation. Aucune reimportation automatique n'existe : "
                "ce fichier est une archive, pas un bouton de retour."
            ),
            "donnees": donnees,
        },
        cls=DjangoJSONEncoder,
        ensure_ascii=False,
        indent=2,
    )


@transaction.atomic
def purger(gym):
    """
    Efface les donnees d'exploitation de la salle. Tout ou rien.

    Renvoie le detail de ce qui a ete supprime, pour la trace et pour l'ecran.
    """
    supprime = {}

    comptes = list(_comptes_des_membres(gym).values_list("id", flat=True))

    for libelle, chemin in DONNEES_EFFACEES:
        nombre = _lignes(gym, chemin).count()
        if nombre:
            _lignes(gym, chemin).delete()
            supprime[libelle] = nombre

    # Apres la suppression des fiches, ces comptes n'ont plus de profil : on
    # les retrouve par les identifiants releves avant.
    if comptes:
        nombre, _ = User.objects.filter(id__in=comptes).delete()
        supprime["Comptes de connexion des membres"] = len(comptes)

    # Le catalogue survit, mais son stock ne veut plus rien dire : les
    # mouvements qui l'avaient constitue viennent de disparaitre.
    produits = _modele("products.Product").objects.filter(gym=gym)
    remis_a_zero = produits.exclude(quantity=0).count()
    if remis_a_zero:
        produits.update(quantity=0)
        supprime["Stocks remis a zero"] = remis_a_zero

    return supprime
