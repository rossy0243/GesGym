"""
Organisation dont le site vitrine porte les couleurs.

La page d'accueil est publique : le visiteur n'est pas connecte, donc
`request.organization` n'est pas renseigne par le middleware. Il faut donc
resoudre l'organisation autrement, sans quoi le pied de page ne peut afficher
que des valeurs ecrites en dur.
"""

from organizations.models import Organization


# Valeurs de secours, utilisees seulement tant qu'aucune organisation n'a
# renseigne ses coordonnees. Elles ne doivent jamais paraitre en production :
# c'est le role de la page Parametres de les remplacer.
FALLBACK_WHATSAPP_NUMBER = "243000000000"
FALLBACK_CONTACT_EMAIL = "contact@royalgym.example"
FALLBACK_SERVICES = (
    "Musculation",
    "Cardio-training",
    "Cours collectifs",
    "Coaching personnel",
)


def landing_organization(request=None):
    """
    Organisation a afficher sur le site vitrine.

    L'organisation de la session prime quand elle existe : un proprietaire
    connecte doit voir sa propre vitrine. Sinon on prend la premiere
    organisation active, celle a qui appartient le domaine.
    """
    depuis_session = getattr(request, "organization", None) if request else None
    if depuis_session is not None:
        return depuis_session

    return Organization.objects.filter(is_active=True).order_by("created_at").first()


def landing_contact(request=None):
    """
    Bloc de contact du site, coordonnees de l'organisation d'abord.

    Chaque valeur retombe separement sur son secours : une organisation qui
    n'a renseigne que son telephone ne doit pas perdre le reste du pied de
    page.
    """
    organization = landing_organization(request)

    if organization is None:
        return {
            "organization": None,
            "name": "Royal Gym",
            "address": "",
            "phone": "",
            "email": FALLBACK_CONTACT_EMAIL,
            "hours": "",
            "whatsapp_number": FALLBACK_WHATSAPP_NUMBER,
            "whatsapp_url": f"https://wa.me/{FALLBACK_WHATSAPP_NUMBER}",
            "services": list(FALLBACK_SERVICES),
            "social_links": [],
        }

    numero = "".join(c for c in (organization.whatsapp_number or "") if c.isdigit())
    numero = numero or FALLBACK_WHATSAPP_NUMBER

    return {
        "organization": organization,
        "name": organization.name,
        "address": (organization.address or "").strip(),
        "phone": (organization.phone or "").strip(),
        "email": (organization.email or "").strip() or FALLBACK_CONTACT_EMAIL,
        "hours": (organization.opening_hours or "").strip(),
        "whatsapp_number": numero,
        "whatsapp_url": organization.whatsapp_url or f"https://wa.me/{numero}",
        "services": organization.services_list or list(FALLBACK_SERVICES),
        "social_links": organization.social_links,
    }
