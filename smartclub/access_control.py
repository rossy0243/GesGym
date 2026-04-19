"""
Matrice centrale des permissions par role.

Les vues restent protegees cote serveur; les templates utilisent les memes
flags pour masquer la navigation non autorisee.
"""

DASHBOARD_ROLES = frozenset({"owner", "manager"})
MEMBER_ROLES = frozenset({"owner", "manager", "reception", "cashier"})
MEMBER_ADMIN_ROLES = frozenset({"owner", "manager"})
SUBSCRIPTION_ROLES = frozenset({"owner", "manager"})
POS_CASHIER_ROLES = frozenset({"owner", "manager", "reception", "cashier"})
POS_HISTORY_ROLES = frozenset({"owner", "manager"})
ACCESS_ROLES = frozenset({"owner", "manager", "reception"})
REPORT_ROLES = frozenset({"owner", "manager"})
COACHING_ROLES = frozenset({"owner", "manager"})
MACHINE_ROLES = frozenset({"owner", "manager"})
RH_EMPLOYEE_ROLES = frozenset({"owner", "manager"})
RH_ATTENDANCE_ROLES = frozenset({"owner", "manager", "reception"})
RH_PAYROLL_ROLES = frozenset({"owner", "manager"})
PRODUCT_ROLES = frozenset({"owner", "manager"})
SETTINGS_ROLES = frozenset({"owner", "manager"})
SETTINGS_ORGANIZATION_ROLES = frozenset({"owner"})


def current_role(request):
    """Retourne le role courant deja resolu par le middleware multi-tenant."""
    if getattr(request, "is_owner", False):
        return "owner"
    return getattr(request, "role", None)


def has_role(request, allowed_roles):
    """Verifie le role courant et la presence d'un contexte gym si necessaire."""
    role = current_role(request)
    if not role or role not in allowed_roles:
        return False

    if role != "owner" and not getattr(request, "gym", None):
        return False

    return True


def permission_flags(request):
    """Flags utilises par la navigation et certains templates."""
    return {
        "can_dashboard": has_role(request, DASHBOARD_ROLES),
        "can_members": has_role(request, MEMBER_ROLES),
        "can_subscriptions": has_role(request, SUBSCRIPTION_ROLES),
        "can_pos_cashier": has_role(request, POS_CASHIER_ROLES),
        "can_pos_history": has_role(request, POS_HISTORY_ROLES),
        "can_access": has_role(request, ACCESS_ROLES),
        "can_reports": has_role(request, REPORT_ROLES),
        "can_coaching": has_role(request, COACHING_ROLES),
        "can_machines": has_role(request, MACHINE_ROLES),
        "can_rh_employees": has_role(request, RH_EMPLOYEE_ROLES),
        "can_rh_attendance": has_role(request, RH_ATTENDANCE_ROLES),
        "can_rh_payroll": has_role(request, RH_PAYROLL_ROLES),
        "can_products": has_role(request, PRODUCT_ROLES),
        "can_settings": has_role(request, SETTINGS_ROLES),
        "can_settings_organization": has_role(request, SETTINGS_ORGANIZATION_ROLES),
    }


def module_is_active(request, module_code):
    gym = getattr(request, "gym", None)
    if not gym:
        return False

    from organizations.models import GymModule

    return GymModule.objects.filter(
        gym=gym,
        module__code=module_code,
        is_active=True,
    ).exists()


def role_home_route(request):
    """
    Premiere page utile pour les roles sans acces au dashboard global.
    Les routes tiennent compte des modules actifs pour eviter un faux depart.
    """
    flags = permission_flags(request)

    if flags["can_dashboard"]:
        return "dashboard"

    role = current_role(request)
    if role == "cashier":
        route_candidates = [
            ("can_pos_cashier", "POS", "pos:cashier_dashboard"),
            ("can_members", "MEMBERS", "members:member_list"),
        ]
    elif role == "reception":
        route_candidates = [
            ("can_access", "ACCESS", "access:acces_dashboard"),
            ("can_members", "MEMBERS", "members:member_list"),
            ("can_pos_cashier", "POS", "pos:cashier_dashboard"),
            ("can_rh_attendance", "RH", "rh:attendance_bulk"),
        ]
    else:
        route_candidates = [
            ("can_members", "MEMBERS", "members:member_list"),
            ("can_pos_cashier", "POS", "pos:cashier_dashboard"),
            ("can_access", "ACCESS", "access:acces_dashboard"),
            ("can_rh_attendance", "RH", "rh:attendance_bulk"),
        ]
    for flag_name, module_code, route_name in route_candidates:
        if flags[flag_name] and module_is_active(request, module_code):
            return route_name

    return "compte:profile"
