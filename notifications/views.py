from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
            notification = Notification.objects.create(
                gym=gym,
                member=form.cleaned_data["member"],
                title=form.cleaned_data["title"],
                message=form.cleaned_data["message"],
                channel=Notification.CHANNEL_IN_APP,
                status=Notification.STATUS_SENT,
                sent_at=timezone.now(),
                sent_by=request.user,
            )
            messages.success(
                request,
                f"Message envoye a {notification.member.first_name} {notification.member.last_name}.",
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
        "nav_active": "notifications",
    }
    return render(request, "notifications/in_app_dashboard.html", context)
