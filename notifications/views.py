from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from smartclub.access_control import NOTIFICATION_ROLES
from smartclub.decorators import module_required, role_required

from .forms import InAppMessageForm
from .models import Notification


@login_required
@role_required(NOTIFICATION_ROLES)
@module_required("NOTIFICATIONS")
def notification_dashboard(request):
    gym = request.gym

    if request.method == "POST":
        form = InAppMessageForm(request.POST, gym=gym)
        if form.is_valid():
            recipients = list(form.get_recipients().only("id", "first_name", "last_name"))

            if not recipients:
                messages.warning(request, "Aucun membre ne correspond a cette audience.")
                return redirect("notifications:dashboard")

            sent_at = timezone.now()
            payload = [
                Notification(
                    gym=gym,
                    member=member,
                    title=form.cleaned_data["title"],
                    message=form.cleaned_data["message"],
                    channel=Notification.CHANNEL_IN_APP,
                    status=Notification.STATUS_SENT,
                    sent_at=sent_at,
                    sent_by=request.user,
                )
                for member in recipients
            ]
            with transaction.atomic():
                Notification.objects.bulk_create(payload, batch_size=200)

            target = form.cleaned_data["target"]
            target_label = InAppMessageForm.target_label(target).lower()
            messages.success(
                request,
                f"Message envoye a {len(recipients)} membre(s) - {target_label}.",
            )
            return redirect("notifications:dashboard")
    else:
        form = InAppMessageForm(gym=gym)

    notifications = (
        Notification.objects.filter(gym=gym, channel=Notification.CHANNEL_IN_APP)
        .select_related("member", "sent_by")
        .order_by("-created_at")[:40]
    )

    context = {
        "form": form,
        "notifications": notifications,
        "sent_count": Notification.objects.filter(
            gym=gym,
            channel=Notification.CHANNEL_IN_APP,
        ).count(),
        "unread_count": Notification.objects.filter(
            gym=gym,
            channel=Notification.CHANNEL_IN_APP,
            read_at__isnull=True,
        ).count(),
        "audience_cards": _audience_cards(gym),
        "nav_active": "notifications",
    }
    return render(request, "notifications/in_app_dashboard.html", context)


def _audience_cards(gym):
    form = InAppMessageForm(gym=gym)
    cards = []
    for target, label in InAppMessageForm.TARGET_CHOICES:
        if target == InAppMessageForm.TARGET_INDIVIDUAL:
            continue
        cards.append(
            {
                "target": target,
                "label": label,
                "count": form.get_recipients_for_target(target).count(),
            }
        )
    return cards
