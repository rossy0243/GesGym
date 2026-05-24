from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.audit import log_sensitive_action
from pos.services import record_subscription_payment
from smartclub.access_control import SUBSCRIPTION_ROLES, has_role
from smartclub.decorators import module_required

from .forms import MemberSubscriptionForm, SubscriptionOfferForm, SubscriptionPlanForm
from .models import MemberSubscription, SubscriptionOffer, SubscriptionPlan


PLAN_MANAGEMENT_ROLES = SUBSCRIPTION_ROLES
SUBSCRIPTION_MANAGEMENT_ROLES = SUBSCRIPTION_ROLES


def _require_gym_role(request, allowed_roles):
    if not getattr(request, "gym", None):
        raise PermissionDenied

    if not has_role(request, allowed_roles):
        raise PermissionDenied


def _wants_json(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _plan_list_context(request, form=None):
    today = timezone.now().date()
    active_subscriptions = MemberSubscription.objects.filter(
        gym=request.gym,
        is_active=True,
        start_date__lte=today,
        end_date__gte=today,
        is_paused=False,
    )
    plans = SubscriptionPlan.objects.filter(gym=request.gym).prefetch_related("offers").annotate(
        active_members_count=Count(
            "subscriptions",
            filter=Q(
                subscriptions__gym=request.gym,
                subscriptions__is_active=True,
                subscriptions__start_date__lte=today,
                subscriptions__end_date__gte=today,
                subscriptions__is_paused=False,
            ),
            distinct=True,
        ),
        total_sales_count=Count(
            "subscriptions",
            filter=Q(subscriptions__gym=request.gym),
            distinct=True,
        ),
    ).order_by("-is_active", "name")
    top_sales_count = max((plan.total_sales_count for plan in plans), default=0)

    return {
        "plans": plans,
        "form": form or SubscriptionPlanForm(gym=request.gym),
        "offer_form": SubscriptionOfferForm(gym=request.gym, prefix="offer"),
        "offers_catalog": SubscriptionOffer.objects.filter(gym=request.gym).order_by("-is_active", "name"),
        "top_sales_count": top_sales_count,
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

    with transaction.atomic():
        MemberSubscription.objects.filter(
            gym=member.gym,
            member=member,
            is_active=True,
        ).update(is_active=False)

        subscription = MemberSubscription.objects.create(
            gym=member.gym,
            member=member,
            plan=plan,
            start_date=start_date,
            end_date=end_date,
            auto_renew=auto_renew,
            is_active=True,
        )

    return subscription


@login_required
@module_required("SUBSCRIPTIONS")
def plan_list(request):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)
    return render(request, "subscriptions/subscription_plan_list.html", _plan_list_context(request))


@login_required
@module_required("SUBSCRIPTIONS")
def create_plan(request):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, gym=request.gym)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.gym = request.gym
            try:
                plan.save()
                form.save_m2m()
                log_sensitive_action(
                    request,
                    "subscription.plan_created",
                    "SubscriptionPlan",
                    plan.name,
                    metadata={"plan_id": plan.id, "price": str(plan.price)},
                )
            except IntegrityError:
                if _wants_json(request):
                    return JsonResponse(
                        {
                            "success": False,
                            "errors": {"name": ["Une formule avec ce nom existe deja dans ce gym."]},
                        },
                        status=400,
                    )
                messages.error(request, "Une formule avec ce nom existe deja dans ce gym.")
                return redirect("subscriptions:subscription_plan_list")

            messages.success(request, "Formule creee avec succes.")
            if _wants_json(request):
                return JsonResponse({"success": True, "message": "Formule creee avec succes."})
            return redirect("subscriptions:subscription_plan_list")

        if _wants_json(request):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    else:
        form = SubscriptionPlanForm(gym=request.gym)

    return render(request, "subscriptions/subscription_plan_list.html", _plan_list_context(request, form=form))


@login_required
@module_required("SUBSCRIPTIONS")
def edit_plan(request, plan_id):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)
    plan = get_object_or_404(SubscriptionPlan, id=plan_id, gym=request.gym)

    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, instance=plan, gym=request.gym)
        if form.is_valid():
            try:
                form.save()
                log_sensitive_action(
                    request,
                    "subscription.plan_updated",
                    "SubscriptionPlan",
                    plan.name,
                    metadata={"plan_id": plan.id},
                )
                return JsonResponse({"success": True, "message": "Formule modifiee avec succes."})
            except IntegrityError:
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {"name": ["Une formule avec ce nom existe deja dans ce gym."]},
                    },
                    status=400,
                )

        return JsonResponse({"success": False, "errors": form.errors}, status=400)

    return JsonResponse(
        {
            "id": plan.id,
            "name": plan.name,
            "duration_days": plan.duration_days,
            "price": float(plan.price),
            "description": plan.description or "",
            "offer_ids": list(plan.offers.values_list("id", flat=True)),
            "coaching_mode": plan.coaching_mode,
            "coaching_level": plan.coaching_level,
            "is_active": plan.is_active,
        }
    )


@login_required
@module_required("SUBSCRIPTIONS")
def delete_plan(request, plan_id):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)
    plan = get_object_or_404(SubscriptionPlan, id=plan_id, gym=request.gym)

    if request.method == "POST":
        has_history = MemberSubscription.objects.filter(gym=request.gym, plan=plan).exists()
        if has_history:
            plan.is_active = False
            plan.save(update_fields=["is_active"])
            log_sensitive_action(
                request,
                "subscription.plan_deactivated",
                "SubscriptionPlan",
                plan.name,
                metadata={"plan_id": plan.id},
            )
            messages.success(request, "Formule desactivee pour conserver l'historique.")
            return redirect("subscriptions:subscription_plan_list")

        plan_name = plan.name
        plan_id_value = plan.id
        plan.delete()
        log_sensitive_action(
            request,
            "subscription.plan_deleted",
            "SubscriptionPlan",
            plan_name,
            metadata={"plan_id": plan_id_value},
        )
        messages.success(request, "Formule supprimee.")
        return redirect("subscriptions:subscription_plan_list")

    return redirect("subscriptions:subscription_plan_list")


@login_required
@module_required("SUBSCRIPTIONS")
def create_offer(request):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    if request.method != "POST":
        return redirect("subscriptions:subscription_plan_list")

    form = SubscriptionOfferForm(request.POST, gym=request.gym, prefix="offer")
    if form.is_valid():
        offer = form.save(commit=False)
        offer.gym = request.gym
        offer.save()
        log_sensitive_action(
            request,
            "subscription.offer_created",
            "SubscriptionOffer",
            offer.name,
            metadata={"offer_id": offer.id, "category": offer.category},
        )
        if _wants_json(request):
            return JsonResponse({"success": True, "message": "Offre creee avec succes."})
        messages.success(request, "Offre creee avec succes.")
        return redirect("subscriptions:subscription_plan_list")

    if _wants_json(request):
        return JsonResponse({"success": False, "errors": form.errors}, status=400)
    return render(request, "subscriptions/subscription_plan_list.html", _plan_list_context(request, form=SubscriptionPlanForm(gym=request.gym)))


@login_required
@module_required("SUBSCRIPTIONS")
def edit_offer(request, offer_id):
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)
    offer = get_object_or_404(SubscriptionOffer, id=offer_id, gym=request.gym)

    if request.method == "POST":
        form = SubscriptionOfferForm(request.POST, instance=offer, gym=request.gym, prefix="offer")
        if form.is_valid():
            form.save()
            log_sensitive_action(
                request,
                "subscription.offer_updated",
                "SubscriptionOffer",
                offer.name,
                metadata={"offer_id": offer.id},
            )
            if _wants_json(request):
                return JsonResponse({"success": True, "message": "Offre modifiee avec succes."})
            messages.success(request, "Offre modifiee avec succes.")
            return redirect("subscriptions:subscription_plan_list")

        if _wants_json(request):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
        return render(request, "subscriptions/subscription_plan_list.html", _plan_list_context(request, form=SubscriptionPlanForm(gym=request.gym)))

    return JsonResponse(
        {
            "id": offer.id,
            "name": offer.name,
            "category": offer.category,
            "description": offer.description or "",
            "grants_individual_coaching": offer.grants_individual_coaching,
            "grants_group_coaching": offer.grants_group_coaching,
            "is_active": offer.is_active,
        }
    )


@login_required
@module_required("SUBSCRIPTIONS")
def create_subscription(request):
    _require_gym_role(request, SUBSCRIPTION_MANAGEMENT_ROLES)

    if request.method == "POST":
        form = MemberSubscriptionForm(request.POST, gym=request.gym)
        if form.is_valid():
            member = form.cleaned_data["member"]
            plan = form.cleaned_data["plan"]
            start_date = form.cleaned_data["start_date"]
            auto_renew = form.cleaned_data["auto_renew"]
            payment_method = form.cleaned_data["payment_method"]
            currency = form.cleaned_data["currency"]

            try:
                subscription, payment = record_subscription_payment(
                    gym=request.gym,
                    member=member,
                    plan=plan,
                    currency=currency,
                    method=payment_method,
                    start_date=start_date,
                    auto_renew=auto_renew,
                    created_by=request.user,
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
            else:
                log_sensitive_action(
                    request,
                    "subscription.created",
                    "MemberSubscription",
                    f"{subscription.member.first_name} {subscription.member.last_name}".strip(),
                    metadata={
                        "subscription_id": subscription.id,
                        "plan_id": subscription.plan_id,
                        "payment_id": payment.id,
                        "currency": payment.currency,
                        "amount": str(payment.amount),
                    },
                )

                messages.success(
                    request,
                    f"Abonnement enregistre avec succes et paiement POS cree: {payment.amount} {payment.currency}.",
                )
                return redirect("members:member_list")
    else:
        form = MemberSubscriptionForm(gym=request.gym)

    return render(request, "subscriptions/create_subscription.html", {"form": form})
