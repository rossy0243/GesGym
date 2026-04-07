# context_processors.py (à côté de settings.py)
from organizations.models import GymModule

def user_owner_check(request):
    """
    Ajoute une variable pour savoir si l'utilisateur connecté est Owner
    """
    user_has_owner_role = False
    
    if hasattr(request, 'gym') and request.gym and request.user.is_authenticated:
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
        gyms = request.organization.gyms.filter(is_active=True)
        gym_modules = GymModule.objects.filter(
            gym__in=gyms,
            is_active=True
        ).select_related('module')

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