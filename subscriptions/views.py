from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .forms import MemberSubscriptionForm, SubscriptionPlanForm
from .models import MemberSubscription, SubscriptionPlan
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse



def create_subscription(member, plan):
    start_date = timezone.now().date()

    end_date = start_date + timedelta(days=plan.duration_days)

    # désactiver anciennes subscriptions
    MemberSubscription.objects.filter(
        member=member,
        is_active=True
    ).update(is_active=False)

    subscription = MemberSubscription.objects.create(
        member=member,
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        is_active=True
    )

    return subscription


@login_required
def plan_list(request):
    plans = SubscriptionPlan.objects.filter(gym=request.gym)
    form = SubscriptionPlanForm()
    return render(
        request,
        "subscriptions/subscription_plan_list.html",
        {"plans": plans, "form": form}
    )

@login_required
def create_plan(request):
    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.gym = request.gym
            plan.save()
            messages.success(request,"Plan créé avec succès")

            return redirect("subscriptions:subscription_plan_list")

    else:
        form = SubscriptionPlanForm()

    return render(request,"core/create_plan.html",{"form":form})


@login_required
def edit_plan(request, plan_id):
    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.gym
    )

    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, instance=plan)

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

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.gym
    )

    if request.method == "POST":
        plan.delete()
        messages.success(request,"Plan supprimé")
        return redirect("subscriptions:subscription_plan_list")

    return render(request,"subscriptions/delete_plan.html",{"plan":plan})


@login_required
def create_subscription(request):
    if request.method == "POST":
        form = MemberSubscriptionForm(request.POST)
        if form.is_valid():
            subscription = form.save(commit=False)
            plan = subscription.plan
            subscription.end_date = (
                subscription.start_date
                + timedelta(days=plan.duration_days)
            )
            # désactiver abonnement actif
            MemberSubscription.objects.filter(
                member=subscription.member,
                is_active=True
            ).update(is_active=False)

            subscription.save()

            messages.success(
                request,
                "Abonnement enregistré avec succès"
            )

            return redirect("core:member_list")

    else:
        form = MemberSubscriptionForm()

    return render(
        request,
        "core/create_subscription.html",
        {"form": form}
    )