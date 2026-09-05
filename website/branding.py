"""
Contenu du site vitrine, tel que l'organisation l'a declare.

La page d'accueil est publique : le visiteur n'est pas connecte, donc
`request.organization` n'est pas renseigne par le middleware. Il faut donc
resoudre l'organisation autrement, sans quoi la page ne peut afficher que des
valeurs ecrites en dur.

Chaque valeur retombe **separement** sur son secours. Une organisation qui n'a
rempli que son telephone ne doit pas perdre le reste de sa page.
"""

from organizations.models import LandingFaq, Organization


# Valeurs de secours : le contenu d'origine de la page. Elles servent tant que
# l'organisation n'a rien declare, pour qu'une page vide ne remplace jamais une
# page complete.
FALLBACK_WHATSAPP_NUMBER = "243000000000"
FALLBACK_CONTACT_EMAIL = "contact@royalgym.example"
FALLBACK_NAME = "Royal Gym"
FALLBACK_CITY = "Kinshasa"
FALLBACK_KICKER = "Salle de sport premium à Kinshasa"
FALLBACK_TITLE = "Entraînez-vous comme un roi"
FALLBACK_INTRO = (
    "Musculation, cardio-training, cours collectifs et coaching personnalisé "
    "dans un espace pensé pour vous aider à progresser, en toute sécurité et "
    "dans une ambiance motivante."
)
FALLBACK_SEO_DESCRIPTION = (
    "{name} est une salle de sport premium à {city} : musculation, cardio, "
    "cours collectifs et coaching personnalisé dans un cadre haut de gamme."
)
FALLBACK_SEO_KEYWORDS = (
    "salle de sport {city}, musculation, fitness, cours collectifs, "
    "coaching personnel, {name}"
)
FALLBACK_SERVICES = (
    "Musculation",
    "Cardio-training",
    "Cours collectifs",
    "Coaching personnel",
)
FALLBACK_FAQ = (
    (
        "Quels services proposez-vous ?",
        "Musculation, cardio-training, cours collectifs et coaching personnalisé, "
        "dans un espace pensé pour progresser en toute sécurité.",
    ),
    (
        "Quels sont les horaires d'ouverture ?",
        "Contactez-nous par WhatsApp ou téléphone pour connaître nos horaires à jour.",
    ),
    (
        "Proposez-vous un coaching personnalisé ?",
        "Oui, nos coachs vous accompagnent avec un suivi personnalisé adapté à vos objectifs.",
    ),
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


def _image_url(champ):
    """URL d'une image televersee, ou chaine vide si aucune."""
    if not champ:
        return ""
    try:
        return champ.url
    except ValueError:
        return ""


def _faq_entries(organization):
    """Questions declarees, ou celles d'origine tant que rien n'est saisi."""
    if organization is not None:
        declarees = [
            {"question": item.question, "answer": item.answer}
            for item in LandingFaq.objects.filter(
                organization=organization, is_active=True
            )
        ]
        if declarees:
            return declarees

    return [{"question": q, "answer": r} for q, r in FALLBACK_FAQ]


def landing_contact(request=None):
    """Tout ce que la page d'accueil affiche de l'organisation."""
    organization = landing_organization(request)

    def valeur(champ, secours):
        if organization is None:
            return secours
        return (getattr(organization, champ, "") or "").strip() or secours

    nom = valeur("name", FALLBACK_NAME)
    ville = valeur("city", FALLBACK_CITY)

    numero = ""
    if organization is not None:
        numero = "".join(
            c for c in (organization.whatsapp_number or "") if c.isdigit()
        )
    numero = numero or FALLBACK_WHATSAPP_NUMBER

    return {
        "organization": organization,
        "name": nom,
        "city": ville,
        "address": valeur("address", ""),
        "phone": valeur("phone", ""),
        "email": valeur("email", FALLBACK_CONTACT_EMAIL),
        "hours": valeur("opening_hours", ""),
        "whatsapp_number": numero,
        "whatsapp_url": f"https://wa.me/{numero}",
        "services": (
            organization.services_list
            if organization is not None and organization.services_list
            else list(FALLBACK_SERVICES)
        ),
        "social_links": organization.social_links if organization is not None else [],
        # Accroches
        "kicker": valeur("landing_kicker", FALLBACK_KICKER),
        "title": valeur("landing_title", FALLBACK_TITLE),
        "intro": valeur("landing_intro", FALLBACK_INTRO),
        "seo_description": valeur(
            "seo_description", FALLBACK_SEO_DESCRIPTION.format(name=nom, city=ville)
        ),
        "seo_keywords": valeur(
            "seo_keywords", FALLBACK_SEO_KEYWORDS.format(name=nom, city=ville)
        ),
        # Photos
        "logo_url": _image_url(getattr(organization, "logo", None)),
        "hero_image_url": _image_url(getattr(organization, "landing_hero_image", None)),
        "image_1_url": _image_url(getattr(organization, "landing_image_1", None)),
        "image_2_url": _image_url(getattr(organization, "landing_image_2", None)),
        "image_3_url": _image_url(getattr(organization, "landing_image_3", None)),
        "faq": _faq_entries(organization),
        # Formules reellement proposees, et si leur prix est public.
        "plans": landing_plans(organization),
        "show_prices": bool(
            organization is not None and organization.show_public_prices
        ),
    }


# ---------------------------------------------------------------------------
# Formules affichees sur le site vitrine
# ---------------------------------------------------------------------------
#
# Les cartes de la page etaient ecrites en dur : le site annoncait quatre
# formules la ou la salle n'en proposait qu'une. On lit desormais celles que
# l'application connait.

# Contenu affiche tant qu'aucune formule n'est enregistree. Mieux vaut la page
# livree qu'une section vide.
FALLBACK_PLANS = (
    {
        "name": "Journalier",
        "description": "Pour decouvrir la salle",
        "duration_label": "1 jour",
        "price": None,
        "offers": ["Acces a la salle 1 jour", "Musculation & cardio", "Sans engagement"],
        "featured": False,
    },
    {
        "name": "Mensuel",
        "description": "La formule la plus flexible",
        "duration_label": "1 mois",
        "price": None,
        "offers": ["Acces illimite 1 mois", "Cours collectifs inclus", "Carte membre & QR code"],
        "featured": False,
    },
    {
        "name": "Trimestriel",
        "description": "Le meilleur rapport engagement / prix",
        "duration_label": "3 mois",
        "price": None,
        "offers": ["Tout le mensuel, inclus", "Suivi coaching renforce", "Tarif preferentiel"],
        "featured": True,
    },
    {
        "name": "Annuel",
        "description": "Pour s'engager sur la duree",
        "duration_label": "1 an",
        "price": None,
        "offers": ["Tout le trimestriel, inclus", "Meilleur tarif a l'annee", "Coaching personnalise"],
        "featured": False,
    },
)


def duree_lisible(jours):
    """
    Duree telle qu'un prospect la lit, plutot qu'un nombre de jours.

    "30 jours" est exact mais froid ; "1 mois" est ce que la personne cherche.
    On ne convertit que les durees rondes, pour ne jamais arrondir un tarif.
    """
    exactes = {1: "1 jour", 7: "1 semaine", 30: "1 mois", 90: "3 mois",
               180: "6 mois", 365: "1 an"}
    if jours in exactes:
        return exactes[jours]
    return f"{jours} jours"


def landing_plans(organization):
    """
    Formules a montrer au public, une par nom.

    Une organisation a souvent les memes formules dans chacune de ses salles :
    les afficher toutes donnerait la meme carte repetee. On regroupe donc par
    nom, en gardant la premiere rencontree.
    """
    if organization is None:
        return [dict(p) for p in FALLBACK_PLANS]

    from django.db.models import Count

    from subscriptions.models import SubscriptionPlan

    formules = (
        SubscriptionPlan.objects.filter(
            gym__organization=organization,
            gym__is_active=True,
            is_active=True,
        )
        .prefetch_related("offers")
        # Le nombre de ventes n'est pas un champ du modele : il se compte ici,
        # comme ailleurs dans l'application.
        .annotate(ventes=Count("subscriptions", distinct=True))
        .order_by("duration_days", "price", "id")
    )

    # La plus vendue porte la mention "Populaire". L'application le sait deja :
    # inutile de designer une formule a la main dans le gabarit.
    ventes = {formule.id: formule.ventes for formule in formules}
    meilleure = None
    if ventes and max(ventes.values()) > 0:
        meilleure = max(ventes, key=ventes.get)

    vues = {}
    for formule in formules:
        cle = formule.name.strip().lower()
        if cle in vues:
            continue
        vues[cle] = {
            "name": formule.name,
            "description": (formule.description or "").strip(),
            "duration_label": duree_lisible(formule.duration_days),
            "price": formule.price,
            "offers": formule.advantage_labels,
            "featured": formule.id == meilleure,
        }

    return list(vues.values()) or [dict(p) for p in FALLBACK_PLANS]
