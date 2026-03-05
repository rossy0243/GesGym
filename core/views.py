#core/views.py
from datetime import timedelta
from django.utils import timezone
from django.contrib import messages
from core.decorators import role_required
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import MemberCreationForm, SubscriptionForm, SubscriptionPlanForm
from .models import Member, Subscription, SubscriptionPlan
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

@login_required
def superadmin_dashboard(request):
    return render(request, 'core/superadmin.html')


@login_required
@role_required(["admin"])
def admin_dashboard(request):
    gym = request.gym
    return render(request, 'core/admin.html', {'gym': gym})

@login_required
@role_required(["manager"])
def manager_dashboard(request):
    gym = request.gym
    return render(request, 'core/manager.html', {'gym': gym})

@login_required
@role_required(["cashier"])
def cashier_dashboard(request):
    gym = request.gym
    return render(request, 'core/cashier.html', {'gym': gym})

@login_required
@role_required(["reception"])
def reception_dashboard(request):
    gym = request.gym
    return render(request, 'core/reception.html', {'gym': gym})

@login_required
@role_required(["member"])
def member_dashboard(request):
    member = request.user.member_profile
    return render(request, 'core/member.html', {
        'member': member,
        'gym': member.gym
    })


@login_required
@role_required(["admin", "reception", "manager"])
def member_detail(request, member_id):

    member = get_object_or_404(
        Member.objects.select_related("user")
        .prefetch_related("subscription_set"),
        id=member_id,
        gym=request.user.gym
    )

    return render(request, "core/member_list.html", {
        "members": Member.objects.filter(gym=request.user.gym),
        "selected_member": member
    })


@login_required
@role_required(["admin", "reception"])
def create_member(request):

    allowed_roles = ["admin", "reception"]
    
    if not request.user.is_authenticated or request.user.role not in allowed_roles:
        raise PermissionDenied("Accès refusé – rôle non autorisé.")
    
    
    if request.method == "POST":
        form = MemberCreationForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save(commit=False)
            member.gym = request.user.gym
            member.save()  # déclenche signal → crée User automatiquement

            messages.success(
                request,
                f"Membre créé avec succès | Mot de passe par défaut : 12345"
            )

            
            return redirect("core:member_list")
            
    else:
        form = MemberCreationForm()

    return render(request, "core/create_member.html", {"form": form})

@login_required
@role_required(["admin", "reception", "manager"])
def member_list(request):

    if request.user.role not in ["admin", "reception", "manager"]:
        raise PermissionDenied

    members = Member.objects.filter(gym=request.user.gym).select_related("user").prefetch_related("subscription_set")

    form = MemberCreationForm()
    
    return render(request, "core/member_list.html", {"members": members, "form": form})


@login_required
@role_required(["admin", "reception"])
def edit_member(request, member_id):

    if request.user.role not in ["admin", "reception"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    form = MemberCreationForm(request.POST or None, request.FILES or None, instance=member)

    if form.is_valid():
        form.save()
        messages.success(request, "Membre modifié avec succès.")
        return redirect("core:member_list")

    return render(request, "core/edit_member.html", {"form": form})


@login_required
@role_required(["admin"])
def delete_member(request, member_id):

    if request.user.role not in ["admin"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    if request.method == "POST":
        member.delete()
        messages.success(request, "Membre supprimé avec succès.")
        return redirect("core:member_list")

    return render(request, "core/delete_member.html", {"member": member})

@login_required
@role_required(["admin", "reception"])
def toggle_member_status(request, member_id):

    if request.user.role not in ["admin", "reception"]:
        raise PermissionDenied

    member = get_object_or_404(
        Member,
        id=member_id,
        gym=request.user.gym
    )

    if member.status == "suspended":
        member.status = "active"
    else:
        member.status = "suspended"

    member.save()

    return redirect("member_list")



def create_subscription(member, plan):

    start_date = timezone.now().date()

    end_date = start_date + timedelta(days=plan.duration_days)

    # désactiver anciennes subscriptions
    Subscription.objects.filter(
        member=member,
        is_active=True
    ).update(is_active=False)

    subscription = Subscription.objects.create(
        member=member,
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        is_active=True
    )

    return subscription


@login_required
@role_required(["admin","manager"])
def plan_list(request):

    plans = SubscriptionPlan.objects.filter(gym=request.user.gym)
    form = SubscriptionPlanForm()
    return render(
        request,
        "core/subscription_plan_list.html",
        {"plans": plans, "form": form}
    )

@login_required
@role_required(["admin","manager"])
def create_plan(request):

    if request.method == "POST":

        form = SubscriptionPlanForm(request.POST)

        if form.is_valid():

            plan = form.save(commit=False)
            plan.gym = request.user.gym
            plan.save()

            messages.success(request,"Plan créé avec succès")

            return redirect("core:subscription_plan_list")

    else:
        form = SubscriptionPlanForm()

    return render(request,"core/create_plan.html",{"form":form})


@login_required
@role_required(["admin","manager"])
def edit_plan(request, plan_id):

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.user.gym
    )

    form = SubscriptionPlanForm(
        request.POST or None,
        instance=plan
    )

    if form.is_valid():
        form.save()
        messages.success(request,"Plan modifié")
        return redirect("core:subscription_plan_list")

    return render(request,"core/edit_plan.html",{"form":form})

@login_required
@role_required(["admin","manager"])
def delete_plan(request, plan_id):

    plan = get_object_or_404(
        SubscriptionPlan,
        id=plan_id,
        gym=request.user.gym
    )

    if request.method == "POST":
        plan.delete()
        messages.success(request,"Plan supprimé")
        return redirect("core:subscription_plan_list")

    return render(request,"core/delete_plan.html",{"plan":plan})


@login_required
@role_required(["admin","manager","reception"])
def create_subscription(request):

    if request.method == "POST":

        form = SubscriptionForm(request.POST)

        if form.is_valid():

            subscription = form.save(commit=False)

            plan = subscription.plan

            subscription.end_date = (
                subscription.start_date
                + timedelta(days=plan.duration_days)
            )

            # désactiver abonnement actif
            Subscription.objects.filter(
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
        form = SubscriptionForm()

    return render(
        request,
        "core/create_subscription.html",
        {"form": form}
    )