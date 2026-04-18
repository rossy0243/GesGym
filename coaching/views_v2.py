from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from members.models import Member
from smartclub.decorators import module_required

from .forms import CoachForm, CoachMemberForm
from .kpis import build_coaching_kpis, coaches_queryset
from .models import Coach


def _validation_message(exc):
    return exc.messages[0] if getattr(exc, "messages", None) else str(exc)


@login_required
@module_required("COACHING")
def coach_list(request):
    gym = request.gym
    coaches = coaches_queryset(gym).annotate(member_count=Count("members", distinct=True)).order_by("name")

    active_filter = request.GET.get("active")
    if active_filter == "active":
        coaches = coaches.filter(is_active=True)
    elif active_filter == "inactive":
        coaches = coaches.filter(is_active=False)

    search = request.GET.get("search", "").strip()
    if search:
        coaches = coaches.filter(
            Q(name__icontains=search)
            | Q(phone__icontains=search)
            | Q(specialty__icontains=search)
        )

    context = {
        "gym": gym,
        "coaches": coaches,
        "active_filter": active_filter,
        "search": search,
        **build_coaching_kpis(gym),
    }
    return render(request, "coaching/coach_list.html", context)


@login_required
@module_required("COACHING")
def coach_detail(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)
    members = coach.members.filter(gym=request.gym, is_active=True).order_by("first_name", "last_name")
    available_members = (
        Member.objects.filter(gym=request.gym, is_active=True, status="active")
        .exclude(id__in=members.values_list("id", flat=True))
        .order_by("first_name", "last_name")
    )

    context = {
        "gym": request.gym,
        "coach": coach,
        "members": members,
        "available_members": available_members,
        "member_form": CoachMemberForm(coach=coach),
        **build_coaching_kpis(request.gym),
    }
    return render(request, "coaching/coach_detail.html", context)


@login_required
@module_required("COACHING")
def coach_create(request):
    gym = request.gym

    if request.method == "POST":
        form = CoachForm(request.POST)
        if form.is_valid():
            coach = form.save(commit=False)
            coach.gym = gym
            coach.save()
            messages.success(request, f'Coach "{coach.name}" cree avec succes.')
            return redirect("coaching:detail", coach_id=coach.id)
    else:
        form = CoachForm()

    return render(
        request,
        "coaching/coach_form.html",
        {"gym": gym, "form": form, "title": "Ajouter un coach"},
    )


@login_required
@module_required("COACHING")
def coach_update(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        form = CoachForm(request.POST, instance=coach)
        if form.is_valid():
            form.save()
            messages.success(request, f'Coach "{coach.name}" modifie avec succes.')
            return redirect("coaching:detail", coach_id=coach.id)
    else:
        form = CoachForm(instance=coach)

    return render(
        request,
        "coaching/coach_form.html",
        {
            "gym": request.gym,
            "form": form,
            "coach": coach,
            "title": "Modifier le coach",
        },
    )


@login_required
@module_required("COACHING")
def coach_delete(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        coach.is_active = False
        coach.save(update_fields=["is_active"])
        messages.success(request, f'Coach "{coach.name}" desactive avec succes.')
        return redirect("coaching:list")

    return render(
        request,
        "coaching/coach_confirm_delete.html",
        {"gym": request.gym, "coach": coach},
    )


@login_required
@module_required("COACHING")
def assign_member(request, coach_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)

    if request.method == "POST":
        form = CoachMemberForm(request.POST, coach=coach)
        if form.is_valid():
            try:
                coach.assign_member(form.cleaned_data["member"])
                member = form.cleaned_data["member"]
                messages.success(
                    request,
                    f'Membre "{member.first_name} {member.last_name}" assigne a {coach.name}.',
                )
            except ValidationError as exc:
                messages.error(request, _validation_message(exc))
        else:
            messages.error(request, "Membre invalide pour ce coach.")

    return redirect("coaching:detail", coach_id=coach.id)


@login_required
@module_required("COACHING")
def remove_member(request, coach_id, member_id):
    coach = get_object_or_404(Coach, id=coach_id, gym=request.gym)
    member = get_object_or_404(Member, id=member_id, gym=request.gym)

    if request.method == "POST":
        try:
            coach.remove_member(member)
            messages.success(request, f'Membre "{member.first_name}" retire de {coach.name}.')
        except ValidationError as exc:
            messages.error(request, _validation_message(exc))

    return redirect("coaching:detail", coach_id=coach.id)
