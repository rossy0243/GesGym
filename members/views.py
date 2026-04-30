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
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.http import require_POST
import qrcode
from access.models import AccessLog
from coaching.models import Coach
from smartclub.access_control import MEMBER_ADMIN_ROLES, MEMBER_ROLES, has_role
from .forms import MemberCreationForm
from .models import Member, MemberPreRegistration, MemberPreRegistrationLink
from notifications.models import Notification
from pos.models import Payment
from subscriptions.models import MemberSubscription, SubscriptionPlan, SubscriptionRequest


#######   MEMBRE  ######


def _cleanup_expired_pre_registrations():
    MemberPreRegistration.delete_expired_pending()


def _member_management_allowed(request):
    return has_role(request, MEMBER_ROLES) and request.gym


def _get_pre_registration_public_url(request, link):
    return request.build_absolute_uri(
        reverse("members:public_pre_registration", args=[link.token])
    )


def _get_current_member(user):
    return getattr(user, "member_profile", None)


def _member_code(member):
    return f"MEM-{member.id:05d}"


def _subscription_progress(subscription):
    if not subscription:
        return 0

    total_days = max((subscription.end_date - subscription.start_date).days, 1)
    elapsed_days = (timezone.localdate() - subscription.start_date).days
    progress = round((elapsed_days / total_days) * 100)
    return min(max(progress, 0), 100)


def _status_label(status):
    return {
        "active": "Actif",
        "expired": "Expire",
        "suspended": "Suspendu",
    }.get(status, "Inconnu")


def _status_class(status):
    return {
        "active": "is-active",
        "expired": "is-expired",
        "suspended": "is-suspended",
    }.get(status, "is-unknown")


def _member_tab_config(unread_notification_count):
    badge = str(unread_notification_count) if unread_notification_count else ""
    return [
        {"key": "home", "label": "Accueil", "icon": "home"},
        {"key": "messages", "label": "Messages", "icon": "mail", "badge": badge},
        {"key": "subscription", "label": "Abonnement", "icon": "subscription"},
        {"key": "plans", "label": "Formules", "icon": "plans"},
    ]


@login_required
def member_portal(request):
    """
    Espace mobile du membre connecte: carte, QR code, abonnement et historique.
    """
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("user", "gym", "gym__organization"),
        id=current_member.id,
        user=request.user,
    )
    subscription = member.active_subscription
    payments = (
        Payment.objects.filter(member=member, gym=member.gym)
        .select_related("subscription", "subscription__plan", "product")
        .order_by("-created_at")[:6]
    )
    access_logs = (
        AccessLog.objects.filter(member=member, gym=member.gym)
        .select_related("scanned_by")
        .order_by("-check_in_time")[:8]
    )
    coaches = Coach.objects.filter(
        gym=member.gym,
        members=member,
        is_active=True,
    ).order_by("name")
    member_notifications = Notification.objects.filter(
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
    ).select_related("sent_by").order_by("-created_at")[:18]
    unread_notification_count = Notification.objects.filter(
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
        read_at__isnull=True,
    ).count()
    available_plans = SubscriptionPlan.objects.filter(
        gym=member.gym,
        is_active=True,
    ).order_by("price", "duration_days", "name")
    pending_requests = SubscriptionRequest.objects.filter(
        gym=member.gym,
        member=member,
        status__in=[
            SubscriptionRequest.STATUS_PENDING,
            SubscriptionRequest.STATUS_AWAITING_PAYMENT,
        ],
    ).select_related("plan").order_by("-created_at")
    pending_plan_ids = list(pending_requests.values_list("plan_id", flat=True))
    status = member.computed_status
    active_tab = request.GET.get("tab", "home")
    payments_list = list(payments)
    recent_payments = payments_list[:4]
    archived_payments = payments_list[4:]
    access_logs_list = list(access_logs)
    recent_access_logs = access_logs_list[:4]
    archived_access_logs = access_logs_list[4:]
    granted_access_count = sum(1 for item in access_logs_list if item.access_granted)
    denied_access_count = len(access_logs_list) - granted_access_count
    member_notifications_list = list(member_notifications)
    unread_notifications = [item for item in member_notifications_list if not item.read_at]
    read_notifications = [item for item in member_notifications_list if item.read_at]
    if active_tab not in {tab["key"] for tab in _member_tab_config(unread_notification_count)}:
        active_tab = "home"

    member_tabs = []
    for tab in _member_tab_config(unread_notification_count):
        member_tabs.append(
            {
                **tab,
                "url": f"{reverse('members:member_portal')}?tab={tab['key']}",
                "is_active": tab["key"] == active_tab,
            }
        )

    context = {
        "member": member,
        "member_code": _member_code(member),
        "organization": member.gym.organization,
        "gym": member.gym,
        "subscription": subscription,
        "subscription_progress": _subscription_progress(subscription),
        "payments": payments_list,
        "recent_payments": recent_payments,
        "archived_payments": archived_payments,
        "access_logs": access_logs_list,
        "recent_access_logs": recent_access_logs,
        "archived_access_logs": archived_access_logs,
        "granted_access_count": granted_access_count,
        "denied_access_count": denied_access_count,
        "coaches": coaches,
        "member_notifications": member_notifications_list,
        "unread_notifications": unread_notifications[:5],
        "recent_notifications": read_notifications[:6],
        "archived_notifications": read_notifications[6:18],
        "unread_notification_count": unread_notification_count,
        "member_tabs": member_tabs,
        "active_tab": active_tab,
        "available_plans": available_plans,
        "pending_requests": pending_requests,
        "pending_plan_ids": pending_plan_ids,
        "current_plan_id": subscription.plan_id if subscription and subscription.plan_id else None,
        "status": status,
        "status_label": _status_label(status),
        "status_class": _status_class(status),
        "days_remaining": member.days_remaining,
        "pwa_manifest_url": reverse("members:member_app_manifest"),
        "pwa_service_worker_url": reverse("members:member_app_service_worker"),
    }
    return render(request, "members/member_portal.html", context)


@login_required
@require_POST
def member_subscription_request(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    plan = get_object_or_404(
        SubscriptionPlan,
        id=request.POST.get("plan_id"),
        gym=member.gym,
        is_active=True,
    )

    SubscriptionRequest.objects.filter(
        gym=member.gym,
        member=member,
        status=SubscriptionRequest.STATUS_PENDING,
    ).exclude(plan=plan).update(
        status=SubscriptionRequest.STATUS_CANCELLED,
        notes="Remplacee par une nouvelle demande depuis l'espace membre.",
    )

    request_obj, created = SubscriptionRequest.objects.get_or_create(
        gym=member.gym,
        member=member,
        plan=plan,
        status=SubscriptionRequest.STATUS_PENDING,
        defaults={
            "requested_by": request.user,
            "price_usd": plan.price,
        },
    )
    if not created and request_obj.price_usd != plan.price:
        request_obj.price_usd = plan.price
        request_obj.requested_by = request.user
        request_obj.save(update_fields=["price_usd", "requested_by", "updated_at"])

    messages.success(
        request,
        "Demande de souscription enregistree. Le paiement sera finalise quand le module de paiement sera branche.",
    )
    return redirect(f"{reverse('members:member_portal')}?tab=plans")


@login_required
@require_POST
def member_notification_read(request, notification_id):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    member = get_object_or_404(
        Member.objects.select_related("gym"),
        id=current_member.id,
        user=request.user,
    )
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        gym=member.gym,
        member=member,
        channel=Notification.CHANNEL_IN_APP,
    )

    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])

    return redirect(f"{reverse('members:member_portal')}?tab=messages")


@login_required
def member_portal_qr(request):
    current_member = _get_current_member(request.user)
    if not current_member:
        raise PermissionDenied

    qr = qrcode.make(current_member.get_qr_data())
    buffer = BytesIO()
    qr.save(buffer)

    return HttpResponse(buffer.getvalue(), content_type="image/png")


def member_app_manifest(request):
    manifest = {
        "name": "SmartClub Membre",
        "short_name": "SmartClub",
        "description": "Carte membre, abonnement et acces SmartClub.",
        "start_url": reverse("members:member_portal"),
        "scope": "/members/",
        "display": "standalone",
        "background_color": "#f6f7f2",
        "theme_color": "#102820",
        "orientation": "portrait",
        "icons": [
            {
                "src": static("icons/1.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": static("avatar/logo_smartclub.png"),
                "sizes": "1536x1024",
                "type": "image/png",
            },
        ],
    }
    return JsonResponse(manifest)


def member_app_service_worker(request):
    content = """
const CACHE_NAME = "smartclub-member-v5";
const STATIC_ASSETS = [
  "/static/css/member-portal.css",
  "/static/js/member-portal.js",
  "/static/icons/1.png",
  "/static/avatar/logo_smartclub.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => null)
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
"""
    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/members/"
    return response

#######   liste  ######
@login_required
def member_list(request):
    """
    Liste des membres avec filtres avancés (SaaS multi-tenant sécurisé)
    """

    # 🔐 sécurité rôles
    if not _member_management_allowed(request):
        raise PermissionDenied

    _cleanup_expired_pre_registrations()
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
    pre_registration_link, _ = MemberPreRegistrationLink.objects.get_or_create(gym=gym)
    pre_registration_url = _get_pre_registration_public_url(request, pre_registration_link)
    pending_pre_registrations_count = MemberPreRegistration.objects.filter(
        gym=gym,
        status=MemberPreRegistration.STATUS_PENDING,
        expires_at__gt=timezone.now(),
    ).count()

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
        "pre_registration_link": pre_registration_link,
        "pre_registration_url": pre_registration_url,
        "pending_pre_registrations_count": pending_pre_registrations_count,
    }

    return render(request, "members/member_list.html", context)


#CREATION MEMBRE
@login_required
def create_member(request):

    if not _member_management_allowed(request):
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
                            Mot de passe temporaire : <strong>12345</strong><br>
                            Espace membre : <strong>{reverse("members:member_portal")}</strong>
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
@login_required
def member_qr(request, uuid):

    if not uuid:
        return HttpResponse(status=404)

    if not _member_management_allowed(request):
        raise PermissionDenied

    get_object_or_404(Member, qr_code=uuid, gym=request.gym)
    
    qr = qrcode.make(uuid)

    buffer = BytesIO()
    qr.save(buffer)

    return HttpResponse(
        buffer.getvalue(),
        content_type="image/png"
    )
    


@login_required
def edit_member(request, member_id):
    if not _member_management_allowed(request):
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
    if not _member_management_allowed(request):
        raise PermissionDenied

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
            "amount": float(p.amount_cdf),
            "original_amount": float(p.amount),
            "original_currency": p.currency,
            "method": p.method,
            "status": p.status
        })
        
    access_logs = AccessLog.objects.filter(
        member=member,
        gym=request.gym,
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
        "member_code": _member_code(member),
        "member_portal_url": request.build_absolute_uri(reverse("members:member_portal")),
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

    if not has_role(request, {"owner"}):
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
    if not has_role(request, MEMBER_ADMIN_ROLES):
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
    if not has_role(request, MEMBER_ADMIN_ROLES):
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
