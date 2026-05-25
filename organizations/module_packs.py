from .models import GymModule, Module


MODULE_DEFINITIONS = [
    {"code": "MEMBERS", "name": "Membres", "description": "Gestion des adherents et abonnes"},
    {"code": "SUBSCRIPTIONS", "name": "Abonnements", "description": "Gestion des abonnements"},
    {"code": "POS", "name": "Point de vente", "description": "Gestion des ventes"},
    {"code": "ACCESS", "name": "Acces", "description": "Controle d'acces et badges"},
    {"code": "NOTIFICATIONS", "name": "Notifications", "description": "Systeme de notifications"},
    {"code": "PRODUCTS", "name": "Produits", "description": "Gestion des produits et stocks"},
    {"code": "MACHINES", "name": "Machines", "description": "Gestion des equipements"},
    {"code": "COACHING", "name": "Coaching", "description": "Gestion des coachs"},
    {"code": "RH", "name": "RH", "description": "Ressources humaines"},
    {"code": "WEBSITE", "name": "Site web", "description": "Gestion du site public"},
    {"code": "COMPTE", "name": "Compte", "description": "Gestion des comptes utilisateurs"},
    {"code": "CORE", "name": "Core", "description": "Fonctionnalites centrales"},
]

MODULE_DEFINITIONS_BY_CODE = {definition["code"]: definition for definition in MODULE_DEFINITIONS}
DEFAULT_MODULE_CODES = [definition["code"] for definition in MODULE_DEFINITIONS]

PACK_CLUB = "club"
PACK_PREMIUM = "premium"

PACK_DEFINITIONS = {
    PACK_CLUB: {
        "label": "Pack Club",
        "module_codes": ["MEMBERS", "SUBSCRIPTIONS", "POS", "ACCESS", "NOTIFICATIONS", "CORE"],
    },
    PACK_PREMIUM: {
        "label": "Pack Premium",
        "module_codes": [
            "MEMBERS",
            "SUBSCRIPTIONS",
            "POS",
            "ACCESS",
            "NOTIFICATIONS",
            "CORE",
            "PRODUCTS",
            "RH",
            "MACHINES",
            "COACHING",
        ],
    },
}

PACK_CHOICES = tuple((code, definition["label"]) for code, definition in PACK_DEFINITIONS.items())


def get_pack_module_codes(pack_code):
    definition = PACK_DEFINITIONS.get(pack_code) or PACK_DEFINITIONS[PACK_PREMIUM]
    return list(definition["module_codes"])


def get_pack_label(pack_code):
    return (PACK_DEFINITIONS.get(pack_code) or PACK_DEFINITIONS[PACK_PREMIUM])["label"]


def ensure_modules_exist():
    for definition in MODULE_DEFINITIONS:
        Module.objects.get_or_create(
            code=definition["code"],
            defaults={
                "name": definition["name"],
                "description": definition["description"],
            },
        )


def sync_gym_modules(gym, active_codes):
    ensure_modules_exist()
    active_codes = set(active_codes)
    modules_by_code = {
        module.code: module
        for module in Module.objects.filter(code__in=DEFAULT_MODULE_CODES)
    }

    for code in DEFAULT_MODULE_CODES:
        gym_module, created = GymModule.objects.get_or_create(
            gym=gym,
            module=modules_by_code[code],
            defaults={"is_active": code in active_codes},
        )
        if not created and gym_module.is_active != (code in active_codes):
            gym_module.is_active = code in active_codes
            gym_module.save(update_fields=["is_active"])


def ensure_default_gym_modules(gym):
    sync_gym_modules(gym, DEFAULT_MODULE_CODES)


def ensure_gym_modules_for_pack(gym, pack_code=None):
    selected_pack = pack_code or getattr(gym.organization, "subscription_pack", PACK_PREMIUM)
    sync_gym_modules(gym, get_pack_module_codes(selected_pack))
