from datetime import timedelta

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.audit import log_sensitive_action
from pos.services import record_subscription_payment
from smartclub.access_control import (
    SETTINGS_ORGANIZATION_ROLES,
    SUBSCRIPTION_ROLES,
    has_role,
)
from smartclub.decorators import module_required

from . import corrections
from .forms import MemberSubscriptionForm, SubscriptionOfferForm, SubscriptionPlanForm
from .models import MemberSubscription, SubscriptionCorrection, SubscriptionOffer, SubscriptionPlan

logger = logging.getLogger("subscriptions")


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

    # Meme raison qu'en caisse : le lecteur doit connaitre la nouvelle
    # echeance sans attendre une resynchronisation.
    from access import enrollment

    enrollment.propager(member)

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
            except IntegrityError as exc:
                logger.warning(
                    "Creation de formule refusee par la base | salle=%s | "
                    "nom=%r | cause=%s",
                    getattr(request.gym, "id", None),
                    form.cleaned_data.get("name"),
                    exc,
                )
                if _wants_json(request):
                    return JsonResponse(
                        {
                            "success": False,
                            "errors": {"name": [
                                "La base a refuse ce nom : une formule "
                                "l'utilise deja dans cette salle. Rechargez la "
                                "page, elle a peut-etre ete creee entre-temps."
                            ]},
                        },
                        status=400,
                    )
                # Formulation distincte de celle du formulaire : les deux
                # chemins ne disaient pas un mot de difference, et rien ne
                # permettait de savoir lequel avait refuse.
                messages.error(
                    request,
                    "La base a refuse ce nom : une formule l'utilise deja dans "
                    "cette salle. Rechargez la page, elle a peut-etre ete creee "
                    "entre-temps.",
                )
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
            except IntegrityError as exc:
                logger.warning(
                    "Modification de formule refusee par la base | formule=%s "
                    "| cause=%s", plan.id, exc,
                )
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {"name": [
                            "La base a refuse ce nom : une autre formule "
                            "l'utilise deja dans cette salle."
                        ]},
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
            "guest_invites_per_month": plan.guest_invites_per_month,
            "guest_sessions_per_invite": plan.guest_sessions_per_invite,
            "offer_ids": list(plan.offers.values_list("id", flat=True)),
            "coaching_mode": plan.coaching_mode,
            "coaching_level": plan.coaching_level,
            "is_active": plan.is_active,
        }
    )


@login_required
@require_POST
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

    # La case de confirmation n'apparait qu'une fois le refus tombe : la
    # proposer d'emblee inviterait a la cocher sans lire.
    periode_close = False

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
                    confirm_closed_period=form.cleaned_data.get(
                        "confirm_closed_period", False
                    ),
                    created_by=request.user,
                )
            except ValidationError as exc:
                periode_close = getattr(exc, "code", None) == "periode_close"
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

                # Les jours restants de l'abonnement precedent ont ete reportes :
                # l'agent doit pouvoir l'expliquer au membre qui voit une
                # echeance plus lointaine que la duree de la formule.
                carried_over = (
                    subscription.end_date - subscription.start_date
                ).days - plan.duration_days
                if carried_over > 0:
                    messages.info(
                        request,
                        f"{carried_over} jour(s) restant(s) de l'abonnement precedent "
                        f"ont ete reportes. Echeance au "
                        f"{subscription.end_date:%d/%m/%Y}.",
                    )

                # Encaisser ne leve pas la suspension : sans ce rappel, le
                # membre repartirait en pensant pouvoir entrer.
                if member.status == "suspended":
                    messages.warning(
                        request,
                        f"{member.first_name} {member.last_name} est toujours "
                        "suspendu et n'aura pas acces a la salle. Reactivez son "
                        "compte depuis sa fiche membre.",
                    )

                return redirect("members:member_list")
    else:
        form = MemberSubscriptionForm(gym=request.gym)

    return render(
        request,
        "subscriptions/create_subscription.html",
        {"form": form, "periode_close": periode_close},
    )


# ---------------------------------------------------------------------------
# Correction de la periode d'un abonnement
# ---------------------------------------------------------------------------


@login_required
@module_required("SUBSCRIPTIONS")
@require_POST
def correct_subscription(request, subscription_id):
    """
    Repose la periode d'un abonnement mal date.

    Le membre a paye : l'argent ne bouge pas, seule la periode se deplace. La
    correction prend effet aussitot - le membre retrouve son acces sans
    attendre que quiconque valide.
    """
    _require_gym_role(request, PLAN_MANAGEMENT_ROLES)

    abonnement = get_object_or_404(
        MemberSubscription, id=subscription_id, gym=request.gym
    )

    debut = parse_date((request.POST.get("start_date") or "").strip())
    motif = request.POST.get("reason") or ""

    # Le proprietaire n'a pas a s'accuser reception a lui-meme.
    est_proprietaire = has_role(request, SETTINGS_ORGANIZATION_ROLES)

    try:
        trace = corrections.corriger(
            abonnement, debut, motif, request.user, acquitte=est_proprietaire
        )
    except ValidationError as exc:
        message = exc.messages[0]
        if _wants_json(request):
            return JsonResponse({"success": False, "error": message}, status=400)
        messages.error(request, message)
        return redirect(request.META.get("HTTP_REFERER", "members:member_list"))

    log_sensitive_action(
        request,
        "subscription.period_corrected",
        "MemberSubscription",
        f"{abonnement.member.first_name} {abonnement.member.last_name}",
        metadata={
            "subscription_id": abonnement.id,
            "avant": f"{trace.previous_start} -> {trace.previous_end}",
            "apres": f"{trace.new_start} -> {trace.new_end}",
            "motif": trace.reason,
        },
    )

    reussite = (
        f"Periode corrigee : du {trace.new_start:%d/%m/%Y} au "
        f"{trace.new_end:%d/%m/%Y}."
    )
    if _wants_json(request):
        return JsonResponse({"success": True, "message": reussite})

    messages.success(request, reussite)
    return redirect(request.META.get("HTTP_REFERER", "members:member_list"))


@login_required
@module_required("SUBSCRIPTIONS")
@require_POST
def acknowledge_correction(request, correction_id):
    """
    Le proprietaire declare avoir vu une correction.

    Elle quitte alors son bandeau. Rien d'autre ne change : la correction avait
    deja pris effet, cet accuse informe, il n'autorise pas.
    """
    if not has_role(request, SETTINGS_ORGANIZATION_ROLES):
        return HttpResponseForbidden("Acces reserve au proprietaire")

    correction = get_object_or_404(
        SubscriptionCorrection, id=correction_id, gym=request.gym
    )
    corrections.accuser_reception(correction, request.user)

    log_sensitive_action(
        request,
        "subscription.correction_acknowledged",
        "SubscriptionCorrection",
        str(correction.subscription.member),
        metadata={"correction_id": correction.id},
    )

    if _wants_json(request):
        return JsonResponse({"success": True})
    return redirect(request.META.get("HTTP_REFERER", "core:dashboard_redirect"))
