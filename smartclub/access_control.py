"""
Matrice centrale des permissions par role.

Les vues restent protegees cote serveur; les templates utilisent les memes
flags pour masquer la navigation non autorisee.
"""

DASHBOARD_ROLES = frozenset({"owner", "manager"})
MEMBER_ROLES = frozenset({"owner", "manager", "reception"})
MEMBER_WRITE_ROLES = frozenset({"owner", "manager", "reception"})
MEMBER_STATUS_ROLES = frozenset({"owner", "manager"})
MEMBER_DELETE_ROLES = frozenset({"owner"})
MEMBER_ADMIN_ROLES = MEMBER_STATUS_ROLES
SUBSCRIPTION_ROLES = frozenset({"owner", "manager"})
POS_CASHIER_ROLES = frozenset({"owner", "manager", "reception", "cashier"})
POS_HISTORY_ROLES = frozenset({"owner", "manager"})
ACCESS_ROLES = frozenset({"owner", "manager", "reception"})
ACCESS_DEVICE_ROLES = frozenset({"owner", "manager"})
REPORT_ROLES = frozenset({"owner", "manager"})
COACHING_ROLES = frozenset({"owner", "manager"})
NOTIFICATION_ROLES = frozenset({"owner", "manager", "commercial"})
MACHINE_ROLES = frozenset({"owner", "manager"})
RH_EMPLOYEE_ROLES = frozenset({"owner", "manager"})
RH_ATTENDANCE_ROLES = frozenset({"owner", "manager", "reception"})
RH_PAYROLL_ROLES = frozenset({"owner", "manager"})
PRODUCT_ROLES = frozenset({"owner", "manager"})
SETTINGS_ROLES = frozenset({"owner", "manager"})
SETTINGS_ORGANIZATION_ROLES = frozenset({"owner"})
COACH_PORTAL_ROLES = frozenset({"coach"})

# Le commercial demarche et convertit les prospects. Il tient les messages aux
# membres, les preinscriptions, les coordonnees de la salle et la vitrine
# publique. Il ne touche ni a l'argent, ni aux fiches membres, ni au personnel.
PRE_REGISTRATION_ROLES = frozenset({"owner", "manager", "reception", "commercial"})

# Regenerer le lien public coupe toutes les demandes en cours : plus sensible
# que consulter la liste.
PRE_REGISTRATION_LINK_ROLES = frozenset({"owner", "manager", "commercial"})

# Coordonnees de la salle affichees au membre. Distinctes du reglage de
# maintenance, qui reste au proprietaire et au gerant.
SETTINGS_GYM_CONTACT_ROLES = frozenset({"owner", "manager", "commercial"})

# Vitrine publique : pied de page, accroches, photos, questions frequentes.
# Separee de l'identite de l'organisation, que seul le proprietaire renomme.
SETTINGS_LANDING_ROLES = frozenset({"owner", "commercial"})

# Encarts financiers du tableau de bord. Ces trois roles etaient jusqu'ici
# ecrits en dur dans core/views.py, hors de cette matrice : un nouveau role en
# aurait ete exclu sans que rien ne le signale.
DASHBOARD_SALES_ROLES = frozenset({"owner", "manager", "cashier"})

# Quels comptes chacun peut creer, modifier et voir dans la liste du personnel.
# Regle de fond : on ne delegue pas un droit qu'on n'a pas soi-meme.
#
# Le commercial retouche la vitrine publique, qui vaut pour toute
# l'organisation. Un gerant n'y a pas acces : lui laisser creer un commercial
# reviendrait a lui offrir ce droit par personne interposee. La creation d'un
# commercial reste donc au proprietaire.
EMPLOYEE_ROLES_BY_OWNER = ("manager", "commercial", "coach", "reception", "cashier")
EMPLOYEE_ROLES_BY_MANAGER = ("coach", "reception", "cashier")


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
        "can_member_write": has_role(request, MEMBER_WRITE_ROLES),
        "can_member_status_admin": has_role(request, MEMBER_STATUS_ROLES),
        "can_member_delete": has_role(request, MEMBER_DELETE_ROLES),
        "can_subscriptions": has_role(request, SUBSCRIPTION_ROLES),
        "can_pos_cashier": has_role(request, POS_CASHIER_ROLES),
        "can_pre_registrations": has_role(request, PRE_REGISTRATION_ROLES),
        "can_pre_registration_link": has_role(request, PRE_REGISTRATION_LINK_ROLES),
        "can_settings_landing": has_role(request, SETTINGS_LANDING_ROLES),
        "can_settings_gym_contact": has_role(request, SETTINGS_GYM_CONTACT_ROLES),
        "can_pos_history": has_role(request, POS_HISTORY_ROLES),
        "can_access": has_role(request, ACCESS_ROLES),
        "can_reports": has_role(request, REPORT_ROLES),
        "can_coaching": has_role(request, COACHING_ROLES),
        "can_notifications": has_role(request, NOTIFICATION_ROLES),
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
        ]
    elif role == "reception":
        route_candidates = [
            ("can_access", "ACCESS", "access:acces_dashboard"),
            ("can_members", "MEMBERS", "members:member_list"),
            ("can_pos_cashier", "POS", "pos:cashier_dashboard"),
            ("can_rh_attendance", "RH", "rh:attendance_list"),
        ]
    elif role == "coach":
        route_candidates = [
            (None, "COACHING", "coaching:coach_portal"),
        ]
    else:
        route_candidates = [
            ("can_members", "MEMBERS", "members:member_list"),
            ("can_pos_cashier", "POS", "pos:cashier_dashboard"),
            ("can_access", "ACCESS", "access:acces_dashboard"),
            ("can_rh_attendance", "RH", "rh:attendance_list"),
        ]
    for flag_name, module_code, route_name in route_candidates:
        has_flag = True if flag_name is None else flags.get(flag_name, False)
        if has_flag and module_is_active(request, module_code):
            return route_name

    return "compte:profile"
