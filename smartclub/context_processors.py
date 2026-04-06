# context_processors.py (à côté de settings.py)
from organizations.models import GymModule

def modules_processor(request):
    """
    Ajoute les modules activés dans TOUS les templates
    """
    modules = {
        'MEMBERS': False,
        'SUBSCRIPTIONS': False,
        'POS': False,
        'ACCESS': False,
        'NOTIFICATIONS': False,
        'PRODUCTS': False,
        'MACHINES': False,
        'COACHING': False,
        'RH': False,
        'WEBSITE': False,
        'COMPTE': False,
        'CORE': False,
    }
    
    if hasattr(request, 'gym') and request.gym:
        gym_modules = GymModule.objects.filter(
            gym=request.gym,
            is_active=True
        ).select_related('module')
        
        for gm in gym_modules:
            modules[gm.module.code] = True
    
    # Variables simples à utiliser dans les templates
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