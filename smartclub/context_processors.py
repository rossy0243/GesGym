# context_processors.py (à côté de settings.py)
from django.urls import NoReverseMatch, reverse

from organizations.models import GymModule


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
        "rh:attendance_bulk": "Presences",
        "rh:payroll_dashboard": "Paie",
        "products:list": "Liste des produits",
        "products:stock_dashboard": "Stock",
        "products:movement_list": "Mouvements",
        "coaching:list": "Coachs",
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

    if not request.user.is_authenticated:
        return {'active_modules': [], **modules}

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
    }

    return context
