from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden
from django.db.models import Q, Count, Sum
from django.db.models.functions import ExtractMonth, TruncDate
from django.utils.timezone import now
from datetime import timedelta
import calendar
from access.models import AccessLog
from compte.models import UserGymRole
from members.models import Member
from organizations.models import Gym, GymModule, Organization
from pos.models import Payment
from subscriptions.models import MemberSubscription


@login_required
def dashboard_redirect(request):
    """Redirige vers le bon dashboard après connexion"""
    
    if not request.user.is_authenticated:
        return redirect('login')

    # === CAS OWNER ===
    if hasattr(request, 'is_owner') and request.is_owner:
        # Si l'Owner a plusieurs gyms → on le redirige vers la sélection
        if len(getattr(request, 'owned_gyms', [])) > 1:
            return redirect('core:select_gym')
        
        # Si l'Owner n'a qu'un seul gym → on va directement sur son dashboard
        elif len(getattr(request, 'owned_gyms', [])) == 1:
            gym = request.owned_gyms[0]
            request.session['current_gym_id'] = gym.id
            return redirect('core:gym_dashboard', gym_id=gym.id)
        
        # Fallback
        else:
            return redirect('core:select_gym')

    # === CAS UTILISATEUR NORMAL (Manager, Coach, etc.) ===
    if hasattr(request, 'gym') and request.gym:
        return redirect('core:gym_dashboard', gym_id=request.gym.id)

    # Fallback général
    return redirect('core:select_gym')

@login_required
def select_gym(request):
    """Page pour sélectionner un gym (Owner avec plusieurs gyms)"""
    
    # Récupérer tous les gyms accessibles
    if hasattr(request, 'is_owner') and request.is_owner:
        gyms = request.owned_gyms if hasattr(request, 'owned_gyms') else []
    else:
        gyms = Gym.objects.filter(
            user_roles__user=request.user,
            user_roles__is_active=True
        )
    
    if request.method == 'POST':
        gym_id = request.POST.get('gym_id')
        gym = get_object_or_404(Gym, id=gym_id)
        
        # Vérifier l'accès
        if gym in gyms or (request.user.is_superuser):
            request.session['current_gym_id'] = gym_id
            return redirect('core:gym_dashboard', gym_id=gym_id)
    
    context = {
        'gyms': gyms,
    }
    return render(request, 'core/select_gym.html', context)

@login_required
def switch_gym(request, gym_id):
    """
    Permet à un Owner de changer de gym actif.
    Version robuste avec vérifications de sécurité.
    """
    user = request.user

    # Vérification 1 : L'utilisateur doit être Owner
    if not getattr(user, 'is_owner', False) or not user.owned_organization:
        messages.error(request, "Vous n'avez pas le droit de changer de gym.")
        return redirect('core:dashboard_redirect')

    # Vérification 2 : Le gym doit appartenir à son organisation
    gym = get_object_or_404(
        Gym,
        id=gym_id,
        organization=user.owned_organization,
        is_active=True
    )

    # Vérification 3 : Optionnel - Vérifier que l'utilisateur a bien accès à ce gym
    if gym not in request.owned_gyms:   # si tu as la propriété owned_gyms dans le middleware
        messages.error(request, "Accès refusé à ce gym.")
        return redirect('core:select_gym')

    # Tout est OK → on change le gym actif en session
    request.session['current_gym_id'] = gym.id
    request.session.modified = True  # Force la sauvegarde de la session

    messages.success(
        request, 
        f"Vous travaillez maintenant sur : <strong>{gym.name}</strong>",
        extra_tags='safe'
    )

    # Redirection vers le dashboard du gym
    return redirect('core:gym_dashboard', gym_id=gym.id)

@login_required
def gym_dashboard(request, gym_id):
    """Dashboard pour une salle spécifique - Vérifie les accès par rôle"""
    
    # Récupérer le gym avec son organisation
    gym = get_object_or_404(Gym.objects.select_related('organization'), id=gym_id)
    
    # ======================
    # VÉRIFICATION DES ACCÈS
    # ======================
    
    user_role = None
    is_owner = hasattr(request, 'is_owner') and request.is_owner
    
    # Owner : vérifier que le gym appartient à son organisation
    if is_owner and request.user.owned_organization:
        if gym.organization_id != request.user.owned_organization_id:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = 'owner'
    
    # Non-Owner : utiliser request.role du middleware
    elif hasattr(request, 'role') and request.role:
        # Vérifier que l'utilisateur a bien un rôle dans ce gym
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = request.role
    
    else:
        # Fallback : vérifier dans la base de données
        user_role_obj = UserGymRole.objects.filter(
            user=request.user, 
            gym=gym, 
            is_active=True
        ).first()
        if not user_role_obj:
            return HttpResponseForbidden("Accès non autorisé")
        user_role = user_role_obj.role
    
    today = now().date()
    view = request.GET.get("view", "dashboard")
    
    # Récupérer les modules actifs
    active_modules = GymModule.objects.filter(
        gym=gym,
        is_active=True
    ).values_list('module__code', flat=True)

    # ======================
    # MEMBRES
    # ======================

    total_members = Member.objects.filter(gym=gym).count()

    active_members = Member.objects.filter(
        gym=gym,
        subscriptions__is_active=True
    ).distinct().count()

    expired_members = Member.objects.filter(
        gym=gym
    ).filter(
        Q(subscriptions__is_active=False) | Q(subscriptions__isnull=True)
    ).distinct().count()

    # nouveaux ce mois
    current_month = today.month
    current_year = today.year

    new_members_month = Member.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).count()

    # ======================
    # REVENUS (selon rôle)
    # ======================
    
    daily_revenue = 0
    monthly_revenue = 0
    
    # Seuls owner, manager et accountant voient les revenus
    if user_role in ['owner', 'manager', 'accountant']:
        payments_today = Payment.objects.filter(
            gym=gym,
            created_at__date=today
        )
        daily_revenue = payments_today.aggregate(total=Sum("amount"))["total"] or 0

        monthly_revenue = Payment.objects.filter(
            gym=gym,
            created_at__year=current_year,
            created_at__month=current_month
        ).aggregate(total=Sum("amount"))["total"] or 0

    # ... le reste de votre code reste identique ...
    # (je garde la suite identique à votre code existant)
    
    # ======================
    # ACCES (selon rôle)
    # ======================
    
    today_checkins = 0
    if user_role in ['owner', 'manager', 'reception']:
        today_checkins = AccessLog.objects.filter(
            member__gym=gym,
            check_in_time__date=today,
            access_granted=True
        ).count()

    # ======================
    # EXPIRATIONS
    # ======================

    expiry_soon = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date__gte=today,
        end_date__lte=today + timedelta(days=15)
    ).count()
    
    # ======================
    # REPARTITION FORMULES
    # ======================

    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True
    ).values(
        "plan__name"
    ).annotate(
        total=Count("id")
    ).order_by("-total")

    total_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        is_active=True
    ).count()

    # ======================
    # FREQUENTATION SEMAINE
    # ======================

    start_week = today - timedelta(days=today.weekday())

    days = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]

    attendance_qs = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__gte=start_week,
        access_granted=True
    ).annotate(
        day=TruncDate("check_in_time")
    ).values("day").annotate(
        count=Count("id")
    )

    attendance_map = {a["day"]: a["count"] for a in attendance_qs}

    attendance_week = []

    for i in range(7):
        day = start_week + timedelta(days=i)
        attendance_week.append({
            "day": days[i],
            "count": attendance_map.get(day, 0)
        })

    # ======================
    # DERNIERS PAIEMENTS (selon rôle)
    # ======================

    recent_payments = []
    if user_role in ['owner', 'manager', 'accountant', 'cashier']:
        recent_payments = Payment.objects.filter(
            gym=gym
        ).select_related(
            "member"
        ).order_by("-created_at")[:5]
    
    # ======================
    # ALERTES EXPIRATION
    # ======================

    expiry_7_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=7),
        is_active=True
    ).count()

    expiry_3_days = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=3),
        is_active=True
    ).count()

    expiry_1_day = MemberSubscription.objects.filter(
        member__gym=gym,
        end_date=today + timedelta(days=1),
        is_active=True
    ).count()

    # ======================
    # PAIEMENTS EN ATTENTE (selon rôle)
    # ======================

    pending_count = 0
    pending_total = 0
    
    if user_role in ['owner', 'manager', 'accountant', 'cashier']:
        pending_payments = Payment.objects.filter(
            gym=gym,
            status="pending"
        )
        pending_count = pending_payments.count()
        pending_total = pending_payments.aggregate(total=Sum("amount"))["total"] or 0

    # ======================
    # DERNIERS ACCES (selon rôle)
    # ======================

    recent_access = []
    if user_role in ['owner', 'manager', 'reception']:
        recent_access = AccessLog.objects.filter(
            member__gym=gym
        ).select_related(
            "member"
        ).order_by("-check_in_time")[:5]
    
    # ======================
    # FREQUENTATION SEMAINE (graph)
    # ======================

    week_labels = []
    week_values = []

    for day in attendance_week:
        week_labels.append(day["day"])
        week_values.append(day["count"])

    # ======================
    # REVENUS PAR MOIS (graph)
    # ======================

    sales_labels = []
    sales_values = []
    
    if user_role in ['owner', 'manager', 'accountant']:
        monthly_sales = Payment.objects.filter(
            gym=gym,
            created_at__year=current_year
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount")
        ).order_by("month")

        for m in monthly_sales:
            sales_labels.append(calendar.month_abbr[m["month"]])
            sales_values.append(float(m["total"]))

    # ======================
    # REPARTITION ABONNEMENTS (graph)
    # ======================

    plan_labels = []
    plan_values = []

    for p in plans_stats:
        plan_labels.append(p["plan__name"])
        plan_values.append(p["total"])

    # ======================
    # DONNÉES SPÉCIFIQUES PAR RÔLE
    # ======================
    
    # Pour Coach : récupérer ses membres
    my_members = []
    coach_name = None
    if user_role == 'coach':
        from coaching.models import Coach
        coach = Coach.objects.filter(
            gym=gym, 
            is_active=True
        ).filter(
            Q(name__icontains=request.user.first_name) | 
            Q(user=request.user)
        ).first()
        
        if coach:
            my_members = coach.members.filter(is_active=True)
            coach_name = coach.name
        else:
            coach_name = request.user.first_name
    
    # Pour Reception : récupérer les checkins du jour
    checkins_today = today_checkins if user_role == 'reception' else 0
    
    # Pour Cashier : récupérer les ventes du jour
    sales_today = daily_revenue if user_role == 'cashier' else 0
    
    # Pour Accountant : récupérer les totaux
    total_maintenance_cost = 0
    total_revenue = monthly_revenue
    if user_role == 'accountant' and 'MACHINES' in active_modules:
        from machines.models import MaintenanceLog
        total_maintenance_cost = MaintenanceLog.objects.filter(
            machine__gym=gym
        ).aggregate(total=Sum('cost'))['total'] or 0

    context = {
        # Modules et infos générales
        "active_modules": active_modules,
        "gym": gym,
        "organization": gym.organization,
        "context_view": view,
        "user_role": user_role,
        "is_owner": is_owner,
        
        # Données spécifiques par rôle
        "my_members": my_members,
        "coach_name": coach_name,
        "checkins_today": checkins_today,
        "sales_today": sales_today,
        "total_maintenance_cost": total_maintenance_cost,
        "total_revenue": total_revenue,
        
        # Membres
        "total_members": total_members,
        "active_members": active_members,
        "expired_members": expired_members,
        "new_members_month": new_members_month,

        # Revenus
        "daily_revenue": daily_revenue,
        "monthly_revenue": monthly_revenue,

        # Accès
        "today_checkins": today_checkins,

        # Expirations
        "expiry_soon": expiry_soon,
        "expiry_7_days": expiry_7_days,
        "expiry_3_days": expiry_3_days,
        "expiry_1_day": expiry_1_day,

        # Abonnements
        "plans_stats": plans_stats,
        "total_subscriptions": total_subscriptions,
        "plan_labels": plan_labels,
        "plan_values": plan_values,

        # Fréquentation
        "attendance_week": attendance_week,
        "week_labels": week_labels,
        "week_values": week_values,

        # Paiements
        "recent_payments": recent_payments,
        "pending_count": pending_count,
        "pending_total": pending_total,

        # Accès récents
        "recent_access": recent_access,
        
        # Graphiques
        "sales_labels": sales_labels,
        "sales_values": sales_values,
    }

    return render(request, "core/dashboard.html", context)

@login_required
def reports_dashboard(request):
    gym = request.gym
    today = now().date()
    section = request.GET.get("section", "journalier")
    # =========================
    # CA du jour
    # =========================
    payments_today = Payment.objects.filter(
        gym=gym,
        created_at__date=today
    )

    daily_revenue = payments_today.aggregate(
        total=Sum("amount")
    )["total"] or 0

    daily_transactions = payments_today.count()

    # =========================
    # Nouveaux membres
    # =========================
    daily_new_clients = Member.objects.filter(
        gym=gym,
        created_at__date=today
    ).count()
    
    # =========================
    # Fréquentation
    # =========================
    daily_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=True
    ).count()

    denied_access = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__date=today,
        access_granted=False
    ).count()

    # =========================
    # Transactions détaillées
    # =========================
    transactions = payments_today.select_related(
        "member"
    ).order_by("-created_at")[:50]

    # =========================
    # KPI MENSUELS
    # =========================

    today = now().date()
    current_year = today.year
    current_month = today.month

    payments_month = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    )

    monthly_revenue = payments_month.aggregate(
        total=Sum("amount")
    )["total"] or 0

    monthly_transactions = payments_month.count()


    # nouveaux membres ce mois
    monthly_new_members = Member.objects.filter(
        gym=gym,
        created_at__year=current_year,
        created_at__month=current_month
    ).count()


    # renouvellements abonnement
    monthly_renewals = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
    ).count()


    # visites
    monthly_visits = AccessLog.objects.filter(
        member__gym=gym,
        check_in_time__year=current_year,
        check_in_time__month=current_month,
        access_granted=True
    ).count()
    
    plans_stats = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__year=current_year,
        start_date__month=current_month
        ).values(
            "plan__name"
        ).annotate(
            subscriptions=Count("id"),
            revenue=Sum("payments__amount")
        ).order_by("-revenue")
    
    monthly_sales = Payment.objects.filter(
        gym=gym,
        created_at__year=current_year
        ).annotate(
            month=ExtractMonth("created_at")
        ).values("month").annotate(
            total=Sum("amount")
        ).order_by("month")
    
    sales_labels = []
    sales_values = []

    for m in monthly_sales:
        sales_labels.append(m["month"])
        sales_values.append(float(m["total"]))
    context = {
        "section": section,
            # journalier
        "daily_revenue": daily_revenue,
        "daily_transactions": daily_transactions,
        "daily_new_clients": daily_new_clients,
        "daily_visits": daily_visits,
        "denied_access": denied_access,
        "transactions": transactions,

        # mensuel
        "monthly_revenue": monthly_revenue,
        "monthly_new_members": monthly_new_members,
        "monthly_renewals": monthly_renewals,
        "monthly_visits": monthly_visits,
        "plans_stats": plans_stats,
        "sales_labels": sales_labels,
        "sales_values": sales_values,
        "monthly_transactions": monthly_transactions
        }

    return render(request, "core/rapports.html", context)


@login_required
def organization_dashboard(request, org_id):
    """Dashboard pour le role Owner - Vue consolidée avec grille des gyms"""
    
    # Vérifier que l'utilisateur est bien Owner de cette organisation
    if not hasattr(request, 'is_owner') or not request.is_owner:
        return HttpResponseForbidden("Seul un Owner peut accéder à ce dashboard")
    
    if request.user.owned_organization_id != org_id:
        return HttpResponseForbidden("Vous n'êtes pas propriétaire de cette organisation")
    
    from datetime import timedelta
    from django.utils.timezone import now
    from members.models import Member
    from machines.models import Machine
    from coaching.models import Coach
    from subscriptions.models import MemberSubscription
    
    organization = get_object_or_404(Organization, id=org_id)
    gyms = organization.gyms.filter(is_active=True)
    
    today = now().date()
    
    # Récupérer les données pour chaque gym
    gyms_data = []
    total_members = 0
    total_machines = 0
    total_maintenance_cost = 0
    
    for gym in gyms:
        # Machines
        machines = Machine.objects.filter(gym=gym)
        machines_ok = machines.filter(status='ok').count()
        machines_maintenance = machines.filter(status='maintenance').count()
        machines_broken = machines.filter(status='broken').count()
        machines_total = machines.count()
        
        # Pourcentage
        machines_ok_percent = (machines_ok / machines_total * 100) if machines_total > 0 else 0
        machines_maintenance_percent = (machines_maintenance / machines_total * 100) if machines_total > 0 else 0
        machines_broken_percent = (machines_broken / machines_total * 100) if machines_total > 0 else 0
        
        # Membres
        members_count = Member.objects.filter(gym=gym, is_active=True).count()
        
        # Coachs
        coaches_count = Coach.objects.filter(gym=gym, is_active=True).count()
        
        # Abonnements expirant bientôt
        expiry_soon = MemberSubscription.objects.filter(
            member__gym=gym,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=15),
            is_active=True
        ).count()
        
        # Coût maintenance
        from machines.models import MaintenanceLog
        gym_maintenance_cost = MaintenanceLog.objects.filter(
            machine__gym=gym
        ).aggregate(total=Sum('cost'))['total'] or 0
        
        gyms_data.append({
            'id': gym.id,
            'name': gym.name,
            'machines': machines_total,
            'machines_ok': machines_ok,
            'machines_maintenance': machines_maintenance,
            'machines_broken': machines_broken,
            'machines_ok_percent': round(machines_ok_percent, 1),
            'machines_maintenance_percent': round(machines_maintenance_percent, 1),
            'machines_broken_percent': round(machines_broken_percent, 1),
            'members': members_count,
            'coaches': coaches_count,
            'expiry_soon': expiry_soon,
            'maintenance_cost': gym_maintenance_cost,
        })
        
        total_members += members_count
        total_machines += machines_total
        total_maintenance_cost += gym_maintenance_cost
    
    context = {
        'organization': organization,
        'gyms': gyms,
        'gyms_data': gyms_data,
        'total_gyms': gyms.count(),
        'members_total': total_members,
        'machines_total': total_machines,
        'maintenance_cost_total': total_maintenance_cost,
        'user_role': 'owner',
        'nav_active': 'dashboard',
    }
    return render(request, 'core/organization_dashboard.html', context)