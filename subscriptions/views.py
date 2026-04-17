from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import MemberSubscriptionForm, SubscriptionPlanForm
from .models import MemberSubscription, SubscriptionPlan


PLAN_MANAGEMENT_ROLES = {"owner", "manager"}
SUBSCRIPTION_MANAGEMENT_ROLES = {"owner", "manager", "reception", "cashier"}


def _require_gym_role(request, allowed_roles):
    if not getattr(request, "gym", None):
        raise PermissionDenied

    if getattr(request, "role", None) not in allowed_roles:
        raise PermissionDenied


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _plan_list_context(request, form=None):
    today = timezone.now().date()
    active_subscriptions = MemberSubscription.objects.filter(
        gym=request.gym,
        is_active=True,
        end_date__gte=today,
        is_paused=False,
    )
    plans = SubscriptionPlan.objects.filter(gym=request.gym).annotate(
        active_members_count=Count(
            "subscriptions",
            filter=Q(
                subscriptions__gym=request.gym,
                subscriptions__is_active=True,
                subscriptions__end_date__gte=today,
                subscriptions__is_paused=False,
            ),
            distinct=True,
        )
    ).order_by("-is_active", "name")

    return {
        "plans": plans,
        "form": form or SubscriptionPlanForm(gym=request.gym),
        "active_plans_count": plans.filter(is_active=True).count(),
        "active_subscriptions_count": active_subscriptions.count(),
        "auto_renew_count": active_subscriptions.filter(auto_renew=True).count(),
        "expiring_7_count": active_subscriptions.filter(end_date__lte=today + timedelta(days=7)).count(),
        "expiring_30_count": active_subscriptions.filter(end_date__lte=today + timedelta(days=30)).count(),
        "expired_active_count": MemberSubscription.objects.filter(
            gym=request.gym,
            is_active=True,
            end_date__lt=today,
        ).count(),
        "upcoming_renewals": active_subscriptions.select_related("member", "plan").order_by("end_date")[:10],
    }



def create_member_subscription(member, plan, start_date=None, auto_renew=False):
    if member.gym_id != plan.gym_id:
        raise PermissionDenied("Le membre et la formule doivent appartenir au meme gym.")

    start_date = start_date or timezone.now().date()

    end_date = start_date + timedelta(days=plan.duration_days)

    # désactiver anciennes subscriptions
    with transaction.atomic():
        MemberSubscription.objects.filter(
            gym=member.gym,
            member=member,
            is_active=True
        ).update(is_active=False)

        subscription = MemberSubscription.objects.create(
            gym=member.gym,
            member=member,
            plan=plan,
            start_date=start_date,
            end_date=end_date,
            auto_renew=auto_renew,
            is_active=True
        )

    return subscription


@login_required
def plan_list(request):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    return render(
        request,
        "subscriptions/subscription_plan_list.html",
        _plan_list_context(request)
    )

@login_required
def create_plan(request):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, gym=request.gym)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.gym = request.gym
            try:
                plan.save()
            except IntegrityError:
                if _wants_json(request):
                    return JsonResponse({
                        "success": False,
                        "errors": {"name": ["Une formule avec ce nom existe deja dans ce gym."]},
                    }, status=400)
                messages.error(request, "Une formule avec ce nom existe deja dans ce gym.")
                return redirect("subscriptions:subscription_plan_list")
            messages.success(request,"Plan créé avec succès")

            if _wants_json(request):
                return JsonResponse({
                    "success": True,
                    "message": "Formule creee avec succes.",
                })

            return redirect("subscriptions:subscription_plan_list")

        if _wants_json(request):
            return JsonResponse({
                "success": False,
                "errors": form.errors,
            }, status=400)

    else:
        form = SubscriptionPlanForm(gym=request.gym)

    return render(request,"subscriptions/subscription_plan_list.html",_plan_list_context(request, form=form))


@login_required
def edit_plan(request, plan_id):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.gym
    )

    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, instance=plan, gym=request.gym)

        if form.is_valid():
            try:
                form.save()
                return JsonResponse({
                    'success': True,
                    'message': 'Formule modifiée avec succès.'
                })
            except IntegrityError:
                return JsonResponse({
                    'success': False,
                    'errors': {'name': ['Une formule avec ce nom existe déjà dans ce gym.']}
                }, status=400)

        # Erreurs de validation classiques
        return JsonResponse({
            'success': False,
            'errors': form.errors
        }, status=400)

    # GET : données pour pré-remplir le modal
    data = {
        'id': plan.id,
        'name': plan.name,
        'duration_days': plan.duration_days,
        'price': float(plan.price),
        'description': plan.description or "",
        'is_active': plan.is_active,
    }

    return JsonResponse(data)

@login_required
def delete_plan(request, plan_id):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.gym
    )

    if request.method == "POST":
        has_history = MemberSubscription.objects.filter(
            gym=request.gym,
            plan=plan,
        ).exists()

        if has_history:
            plan.is_active = False
            plan.save(update_fields=["is_active"])
            messages.success(request,"Plan desactive pour conserver l'historique.")
            return redirect("subscriptions:subscription_plan_list")
        else:
            plan.delete()
            messages.success(request,"Plan supprime")
            return redirect("subscriptions:subscription_plan_list")
        messages.success(request,"Plan supprimé")
        return redirect("subscriptions:subscription_plan_list")

    return redirect("subscriptions:subscription_plan_list")


@login_required
def create_subscription(request):
    _require_gym_role(request, SUBSCRIPTION_MANAGEMENT_ROLES)

    if request.method == "POST":
        form = MemberSubscriptionForm(request.POST, gym=request.gym)
        if form.is_valid():
            subscription = form.save(commit=False)
            plan = subscription.plan
            subscription.gym = request.gym
            subscription.end_date = (
                subscription.start_date
                + timedelta(days=plan.duration_days)
            )
            # désactiver abonnement actif
            with transaction.atomic():
                MemberSubscription.objects.filter(
                    gym=request.gym,
                    member=subscription.member,
                    is_active=True
                ).update(is_active=False)

                subscription.save()

            messages.success(
                request,
                "Abonnement enregistré avec succès"
            )

            return redirect("members:member_list")

    else:
        form = MemberSubscriptionForm(gym=request.gym)

    return render(
        request,
        "subscriptions/create_subscription.html",
        {"form": form}
    )
