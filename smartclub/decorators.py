from functools import wraps

from django.shortcuts import render

from .access_control import has_role

def module_required(module_code):
    """
    Vérifie que le module est activé pour le gym courant.
    Usage: @module_required('MACHINES')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Vérifier si request.gym existe (middleware)
            if not hasattr(request, 'gym') or not request.gym:
                return render(request, 'errors/module_inactive.html', {
                    'error': 'Aucun gym trouvé'
                }, status=403)
            
            # Vérifier si le module est actif
            from organizations.models import GymModule
            is_active = GymModule.objects.filter(
                gym=request.gym,
                module__code=module_code,
                is_active=True
            ).exists()
            
            if not is_active:
                return render(request, 'errors/module_inactive.html', {
                    'module_code': module_code,
                    'module_name': module_code,
                    'gym': request.gym
                }, status=403)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def role_required(allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_role(request, allowed_roles) or not getattr(request, "gym", None):
                return render(
                    request,
                    "errors/module_inactive.html",
                    {"error": "Acces non autorise pour votre role."},
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
