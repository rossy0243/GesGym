# core/utils.py
from django.db.models import Q

def filter_by_gym(queryset, request, field_name='gym'):
    """
    Filtre sécurisé par gym ou organisation selon le rôle de l'utilisateur.
    À utiliser dans toutes les ListView / QuerySet.
    """
    if not request.user.is_authenticated:
        return queryset.none()

    if getattr(request, 'is_owner', False) and request.organization:
        # Owner voit tous les gyms de son organisation
        return queryset.filter(**{f'{field_name}__organization': request.organization})

    elif getattr(request, 'gym', None):
        # Utilisateur normal voit uniquement son gym
        return queryset.filter(**{field_name: request.gym})

    return queryset.none()