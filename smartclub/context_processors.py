# context_processors.py (à côté de settings.py)
from django.urls import NoReverseMatch, reverse

from organizations.models import GymModule
from .access_control import current_role, has_role, permission_flags


def _safe_file_url(file_field):
    if not file_field:
        return ""
    try:
        return file_field.url
    except ValueError:
        return ""


def organization_branding_processor(request):
    organization = getattr(request, "organization", None)
    gym = getattr(request, "gym", None)
    if not organization and getattr(request, "user", None) and request.user.is_authenticated:
        member_profile = getattr(request.user, "member_profile", None)
        if member_profile and getattr(member_profile, "gym", None):
            gym = gym or member_profile.gym
            organization = member_profile.gym.organization

    organization_name = getattr(organization, "name", "") or "SmartClub"
    gym_name = getattr(gym, "name", "") or ""
    initials = "".join(
        item[:1].upper()
        for item in (organization_name, gym_name or "Club")
        if item
    )[:2] or "SC"

    return {
        "organization_brand_logo_url": _safe_file_url(getattr(organization, "logo", None)),
        "organization_brand_name": organization_name,
        "organization_brand_gym_name": gym_name,
        "organization_brand_initials": initials,
    }


def _safe_reverse(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return "#"


def _humanize_route_label(value):
    return (value or "Page").replace("_", " ").replace("-", " ").title()


def breadcrumbs_processor(request):
    resolver = getattr(request, "resolver_match", None)
    if not resolver:
        return {}

    namespace = resolver.namespace or ""
    url_name = resolver.url_name or ""
    route_key = f"{namespace}:{url_name}" if namespace else url_name

    section_map = {
        "core": ("Tableau de bord", "core:dashboard_redirect"),
        "members": ("Membres", "members:member_list"),
        "subscriptions": ("Abonnements", "subscriptions:subscription_plan_list"),
        "pos": ("Point de vente", "pos:cashier_dashboard"),
        "access": ("Controle d'acces", "access:acces_dashboard"),
        "machines": ("Machines", "machines:list"),
        "rh": ("Ressources humaines", "rh:list"),
        "products": ("Stock & produits", "products:list"),
        "coaching": ("Coaching", "coaching:list"),
        "notifications": ("Messages membres", "notifications:dashboard"),
        "compte": ("Compte", "compte:profile"),
    }
    leaf_map = {
        "core:dashboard_redirect": "Tableau de bord",
        "core:gym_dashboard": "Tableau de bord",
        "core:select_gym": "Choisir une salle",
        "core:rapport": "Rapports",
        "core:rapport_export": "Export rapport",
        "core:settings": "Parametres",
        "members:member_list": "Liste des membres",
        "members:pre_registration_list": "Preinscriptions",
        "members:public_pre_registration": "Preinscription",
        "subscriptions:subscription_plan_list": "Formules",
        "pos:cashier_dashboard": "Caisse",
        "pos:register_history": "Journal de caisse",
        "access:acces_dashboard": "Controle d'acces",
        "machines:list": "Liste des machines",
        "machines:maintenance_dashboard": "Maintenances",
        "rh:list": "Employes",
        "rh:attendance_list": "Presences",
        "rh:attendance_bulk": "Enregistrement groupe",
        "rh:payroll_dashboard": "Paie",
        "products:list": "Liste des produits",
        "products:stock_dashboard": "Stock",
        "products:movement_list": "Mouvements",
        "coaching:list": "Coachs",
        "notifications:dashboard": "Messages membres",
        "compte:profile": "Mon profil",
    }

    page_title = leaf_map.get(route_key, _humanize_route_label(url_name))
    breadcrumbs = [{"label": "Accueil", "url": _safe_reverse("core:dashboard_redirect")}]

    section = section_map.get(namespace)
    if section and section[0] != page_title:
        breadcrumbs.append({"label": section[0], "url": _safe_reverse(section[1])})

    breadcrumbs.append({"label": page_title, "url": ""})
    return {
        "page_title": page_title,
        "breadcrumbs": breadcrumbs,
    }

def user_owner_check(request):
    """
    Ajoute une variable pour savoir si l'utilisateur connecté est Owner
    """
    user_has_owner_role = False
    
    if request.user.is_authenticated and getattr(request, 'is_owner', False):
        user_has_owner_role = True
    elif hasattr(request, 'gym') and request.gym and request.user.is_authenticated:
        from compte.models import UserGymRole
        role = UserGymRole.objects.filter(
            user=request.user,
            gym=request.gym,
            is_active=True
        ).first()
        
        if role and role.role == 'owner':
            user_has_owner_role = True
    
    return {
        'user_has_owner_role': user_has_owner_role,
    }

def modules_processor(request):
    """
    Injecte les modules activés dans tous les templates.
    Gère correctement Owner et utilisateurs normaux.
    """
    modules = {
        'MEMBERS': False, 'SUBSCRIPTIONS': False, 'POS': False, 'ACCESS': False,
        'NOTIFICATIONS': False, 'PRODUCTS': False, 'MACHINES': False,
        'COACHING': False, 'RH': False, 'WEBSITE': False, 'COMPTE': False, 'CORE': False,
    }

    base_context = permission_flags(request)
    base_context["current_role"] = current_role(request)
    base_context["can_pos"] = base_context["can_pos_cashier"] or base_context["can_pos_history"]
    base_context["can_rh"] = (
        base_context["can_rh_employees"]
        or base_context["can_rh_attendance"]
        or base_context["can_rh_payroll"]
    )

    if not request.user.is_authenticated:
        return {'active_modules': [], **modules, **base_context}

    # Cas Owner
    if getattr(request, 'is_owner', False) and request.organization:
        if getattr(request, 'gym', None):
            gym_modules = GymModule.objects.filter(
                gym=request.gym,
                is_active=True
            ).select_related('module')
        else:
            gym_modules = []

    # Cas utilisateur normal (Manager, Cashier, etc.)
    elif getattr(request, 'gym', None):
        gym_modules = GymModule.objects.filter(
            gym=request.gym,
            is_active=True
        ).select_related('module')

    else:
        gym_modules = []

    # Activation des modules
    for gm in gym_modules:
        code = gm.module.code
        if code in modules:
            modules[code] = True

    context = {
        'active_modules': [code for code, active in modules.items() if active],
        'module_members': modules['MEMBERS'],
        'module_subscriptions': modules['SUBSCRIPTIONS'],
        'module_pos': modules['POS'],
        'module_access': modules['ACCESS'],
        'module_notifications': modules['NOTIFICATIONS'],
        'module_products': modules['PRODUCTS'],
        'module_machines': modules['MACHINES'],
        'module_coaching': modules['COACHING'],
        'module_rh': modules['RH'],
        'module_website': modules['WEBSITE'],
        'module_compte': modules['COMPTE'],
        'module_core': modules['CORE'],
        **base_context,
    }

    return context


def maintenance_alert_processor(request):
    """
    Signale au gerant et au proprietaire les maintenances qui approchent.

    L'alerte doit suivre l'utilisateur : une maintenance qui n'apparait que sur
    la page des machines n'est vue que par celui qui y va deja, c'est-a-dire
    trop tard. Elle est donc calculee ici pour etre affichee dans le bandeau
    commun a toutes les pages.
    """
    from machines.alerts import maintenance_alert_summary
    from smartclub.access_control import MACHINE_ROLES

    gym = getattr(request, "gym", None)
    if not request.user.is_authenticated or gym is None:
        return {"maintenance_banner": None}

    if not has_role(request, MACHINE_ROLES):
        return {"maintenance_banner": None}

    return {"maintenance_banner": maintenance_alert_summary(gym)}


def access_device_health_processor(request):
    """
    Signale un lecteur qui ne donne plus signe de vie.

    Meme raison que pour les maintenances : une alerte qui n'apparait que sur
    la page des lecteurs n'est vue que par celui qui y va deja. Or personne n'y
    va tant que la porte fonctionne, et elle fonctionne justement toute seule.
    """
    from access.health import resume_hors_ligne
    from smartclub.access_control import ACCESS_DEVICE_ROLES

    gym = getattr(request, "gym", None)
    if not request.user.is_authenticated or gym is None:
        return {"device_offline_banner": None}

    if not has_role(request, ACCESS_DEVICE_ROLES):
        return {"device_offline_banner": None}

    return {"device_offline_banner": resume_hors_ligne(gym)}


def subscription_corrections_processor(request):
    """
    Impose au proprietaire les corrections de periode qu'il n'a pas encore vues.

    Un gerant peut corriger une periode vendue, et cela prend effet aussitot.
    La contrepartie est que le proprietaire en soit informe - non par une ligne
    de journal qu'il pourrait ne jamais lire, mais par un bandeau qui ne
    disparait que lorsqu'il declare l'avoir vue.
    """
    from smartclub.access_control import SETTINGS_ORGANIZATION_ROLES
    from subscriptions import corrections

    gym = getattr(request, "gym", None)
    if not request.user.is_authenticated or gym is None:
        return {"subscription_corrections_banner": None}

    if not has_role(request, SETTINGS_ORGANIZATION_ROLES):
        return {"subscription_corrections_banner": None}

    attente = list(corrections.en_attente(gym)[:5])
    if not attente:
        return {"subscription_corrections_banner": None}

    return {
        "subscription_corrections_banner": {
            "total": corrections.en_attente(gym).count(),
            "corrections": attente,
        }
    }
