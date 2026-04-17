#members/views.py
from datetime import date, timedelta
from io import BytesIO
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.db.models import Q, Exists, OuterRef
from django.core.paginator import Paginator
import qrcode
from access.models import AccessLog
from .forms import MemberCreationForm
from .models import Member
from pos.models import Payment
from subscriptions.models import MemberSubscription, SubscriptionPlan


#######   MEMBRE  ######

#######   liste  ######
@login_required
def member_list(request):
    """
    Liste des membres avec filtres avancés (SaaS multi-tenant sécurisé)
    """

    # 🔐 sécurité rôles
    if request.role not in ["owner", "manager"]:
        raise PermissionDenied

    gym = request.gym
    today = timezone.now().date()
    limit = today + timedelta(days=7)
    active_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("pk"),
        is_active=True,
        end_date__gte=today,
        is_paused=False,
    )
    expiring_subscription_exists = MemberSubscription.objects.filter(
        member=OuterRef("pk"),
        is_active=True,
        end_date__range=(today, limit),
        is_paused=False,
    )
    any_access_exists = AccessLog.objects.filter(member=OuterRef("pk"))
    recent_access_exists = AccessLog.objects.filter(
        member=OuterRef("pk"),
        check_in_time__date__gte=today - timedelta(days=30),
    )

    # 🔥 base queryset optimisée
    members = (
        Member.objects
        .filter(gym=gym)
        .select_related("user")
        .annotate(
            has_active_subscription=Exists(active_subscription_exists),
            has_expiring_subscription=Exists(expiring_subscription_exists),
            has_any_access=Exists(any_access_exists),
            has_recent_access=Exists(recent_access_exists),
        )
    )

    # =====================
    # 🔎 FILTRES
    # =====================

    search = request.GET.get("search")
    status = request.GET.get("status")
    plan = request.GET.get("plan")
    access_filter = request.GET.get("access")
    created_from = request.GET.get("created_from")
    created_to = request.GET.get("created_to")
    sort = request.GET.get("sort", "newest")

    # 🔍 Recherche
    if search:
        members = members.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search) |
            Q(user__username__icontains=search)
        )

    # 📊 Statut
    if status == "active":
        members = members.filter(has_active_subscription=True)

    elif status == "expired":
        # Membres dont l'abonnement actif est expiré
        members = members.filter(
            has_active_subscription=False
        ).exclude(status="suspended")

    elif status == "suspended":
        members = members.filter(status="suspended")

    elif status == "expiring":
        members = members.filter(has_expiring_subscription=True)

    # 💳 Plan
    if plan:
        members = members.filter(
            subscriptions__plan_id=plan,
            subscriptions__is_active=True
        ).distinct()

    # 🔽 tri par défaut (important UX)
    if access_filter == "recent":
        members = members.filter(has_recent_access=True)
    elif access_filter == "never":
        members = members.filter(has_any_access=False)

    if created_from:
        try:
            members = members.filter(created_at__date__gte=date.fromisoformat(created_from))
        except ValueError:
            created_from = ""

    if created_to:
        try:
            members = members.filter(created_at__date__lte=date.fromisoformat(created_to))
        except ValueError:
            created_to = ""

    sort_options = {
        "newest": ["-created_at"],
        "oldest": ["created_at"],
        "name_asc": ["first_name", "last_name"],
        "name_desc": ["-first_name", "-last_name"],
        "expiry_asc": ["subscriptions__end_date", "-created_at"],
        "expiry_desc": ["-subscriptions__end_date", "-created_at"],
        "last_access": ["-access_logs__check_in_time", "-created_at"],
    }
    sort = sort if sort in sort_options else "newest"
    members = members.order_by(*sort_options[sort]).distinct()

    # =====================
    # 📄 PAGINATION
    # =====================

    paginator = Paginator(members, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # =====================
    # 📦 DATA TEMPLATE
    # =====================

    plans = SubscriptionPlan.objects.filter(
        gym=gym,
        is_active=True
    )
    # AJOUT IMPORTANT : On passe le formulaire au template
    form = MemberCreationForm()

    context = {
        "page_obj": page_obj,
        "plans": plans,

        # 🔥 conserver filtres dans UI
        "search": search or "",
        "status": status or "",
        "plan_selected": plan or "",
        "access_filter": access_filter or "",
        "created_from": created_from or "",
        "created_to": created_to or "",
        "sort_selected": sort,
        "form" : form,
    }

    return render(request, "members/member_list.html", context)


#CREATION MEMBRE
@login_required
def create_member(request):

    if request.role not in ["owner", "manager"]:
        raise PermissionDenied
    
    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            member.gym = request.gym
            member.save()  # déclenche signal → crée User automatiquement

            messages.success(
                request,
                f"""
                <div class="d-flex align-items-center gap-3">
                    <span class="material-icons text-white" style="font-size:32px;">check_circle</span>
                    <div>
                        <strong style="font-size:1.1rem;">Membre créé avec succès !</strong><br>
                        <span class="opacity-90">
                            {member.first_name} {member.last_name}<br>
                            Identifiant : <strong>{member.user.username}</strong><br>
                            Mot de passe temporaire : <strong>12345</strong>
                        </span>
                    </div>
                </div>
                """,
                extra_tags='safe toast-success'
            )
            return redirect("members:member_list")
            
    else:
        form = MemberCreationForm()

    return redirect("members:member_list")

#Qrcode
def member_qr(request, uuid):

    if not uuid:
        return HttpResponse(status=404)
    
    qr = qrcode.make(uuid)

    buffer = BytesIO()
    qr.save(buffer)

    return HttpResponse(
        buffer.getvalue(),
        content_type="image/png"
    )
    


@login_required
def edit_member(request, member_id):
    if request.role not in ["owner", "manager"]:
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES, instance=member)
        
        if form.is_valid():
            form.save()
            messages.success(request, "Membre modifié avec succès.")
            
            # Réponse JSON pour le modal (au lieu de redirect)
            return JsonResponse({
                'success': True,
                'message': 'Membre modifié avec succès.'
            })

        else:
            # Retourner les erreurs de validation
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

    # GET : Retourner les données pour pré-remplir le formulaire
    data = {
        'id': member.id,
        'first_name': member.first_name,
        'last_name': member.last_name,
        'phone': member.phone,
        'email': member.email,
        'address': member.address,
        'photo_url': member.photo.url if member.photo else None,
    }

    return JsonResponse(data)


#DETAIL D'UN MEMBRE
@login_required
def member_detail(request, member_id):
    member = get_object_or_404(
        Member.objects.select_related("user"),
        id=member_id,
        gym=request.gym
    )
    subscription = member.active_subscription
    organization = request.gym.organization if request.gym else None
    
    payments = Payment.objects.filter(
        member=member, gym = request.gym
    ).order_by("-created_at")[:5]
    
    payments_data = []
    
    for p in payments:
        payments_data.append({
            "date": p.created_at.strftime("%d/%m/%Y"),
            "amount": float(p.amount),
            "method": p.method,
            "status": p.status
        })
        
    access_logs = AccessLog.objects.filter(
        member=member
    ).order_by("-check_in_time")[:5]

    access_data = []

    for log in access_logs:
        access_data.append({
            "date": log.check_in_time.strftime("%d/%m/%Y"),
            "time": log.check_in_time.strftime("%H:%M"),
            "device": log.device_used,
            "status": log.access_granted
        })
    data = {
        "id": member.id,
        "photo_url": member.photo.url if member.photo else None,
        "organization_name": organization.name if organization else "",
        "organization_logo_url": organization.logo.url if organization and organization.logo else "",
        "gym_name": request.gym.name if request.gym else "",
        "username": member.user.username if member.user else "Non défini",
        "first_name": member.first_name,
        "last_name": member.last_name,
        "phone": member.phone,
        "email": member.email,
        "status": member.computed_status,
        "qr_code": str(member.qr_code),
        # abonnement
        "subscription_type": member.subscription_type,
        "start_date": subscription.start_date.strftime("%d/%m/%Y") if subscription else None,
        "expiration_date": member.expiration_date.strftime("%d/%m/%Y") if member.expiration_date else None,
        "price": subscription.plan.price if subscription else 0,

        # paiements
        "paid": member.amount_paid if hasattr(member, "amount_paid") else 0,
        "remaining": member.amount_remaining if hasattr(member, "amount_remaining") else 0,
        
        "payments": payments_data,
        "access_logs": access_data,
    }

    return JsonResponse(data)


@login_required
def delete_member(request, member_id):

    if request.role != "owner":
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.gym
    )

    if request.method == "POST":
        member.delete()
        messages.success(request, "Membre supprimé avec succès.")

    return redirect("members:member_list")


@login_required
def suspend_member(request, member_id):
    if request.role not in ["owner", "manager"]:
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Suspendre le membre
    member.status = "suspended"
    member.save()

    # Mettre en pause l'abonnement actif
    active_sub = member.active_subscription
    if active_sub and not active_sub.is_paused:
        active_sub.is_paused = True
        active_sub.paused_at = timezone.now()
        active_sub.save()

    messages.warning(request, f"{member.first_name} {member.last_name} a été suspendu. Son abonnement est en pause.")
    return redirect("members:member_list")


@login_required
def reactivate_member(request, member_id):
    if request.role not in ["owner", "manager"]:
        raise PermissionDenied

    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    # Réactiver le membre
    member.status = "active"
    member.save()

    # Reprendre l'abonnement en pause
    active_sub = member.active_subscription
    if active_sub and active_sub.is_paused:
        active_sub.resume_subscription()   # utilise la méthode qu'on a ajoutée

    messages.success(request, f"{member.first_name} {member.last_name} a été réactivé avec succès.")
    return redirect("members:member_list")
