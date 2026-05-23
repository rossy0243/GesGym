from django.conf import settings
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render
from django.urls import reverse

from organizations.models import Gym

from .forms import DemoRequestForm


PACK_PRESET_MESSAGES = {
    "club": "Bonjour, je souhaite decouvrir le Pack Club a travers une demonstration, en particulier pour la gestion des membres, des abonnements, des paiements, des acces et des rapports.",
    "premium": "Bonjour, je souhaite decouvrir le Pack Premium a travers une demonstration, notamment pour les modules avances comme le stock, les employes, les equipements et le coaching.",
}

PACK_LABELS = {
    "club": "Pack Club",
    "premium": "Pack Premium",
}


def landing(request):
    demo_sent = request.GET.get("demo") == "sent"
    selected_pack = request.GET.get("pack", "").strip().lower()
    if selected_pack not in PACK_PRESET_MESSAGES:
        selected_pack = ""

    if request.method == "POST":
        form = DemoRequestForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            sites_count = cleaned_data["sites_count"]
            pack_key = cleaned_data.get("selected_pack", "")
            pack_label = PACK_LABELS.get(pack_key, "Non precise")
            subject = f"Nouvelle demande de demo SmartClub Pro - {cleaned_data['club_name']}"
            message = (
                "Une nouvelle demande de demo a ete envoyee depuis la landing page.\n\n"
                f"Pack choisi : {pack_label}\n"
                f"Nom complet : {cleaned_data['full_name']}\n"
                f"Email : {cleaned_data['email']}\n"
                f"Telephone : {cleaned_data['phone']}\n"
                f"Club : {cleaned_data['club_name']}\n"
                f"Nombre de sites actifs : {sites_count}\n\n"
                "Besoin exprime :\n"
                f"{cleaned_data['message'] or 'Aucun message complementaire.'}\n"
            )
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=["contact@smartclubpro.org"],
                reply_to=[cleaned_data["email"]],
            )
            email.send(fail_silently=False)
            return redirect(f"{reverse('landing')}?demo=sent#demo-form")
    else:
        initial = {}
        if selected_pack:
            initial["selected_pack"] = selected_pack
            initial["message"] = PACK_PRESET_MESSAGES[selected_pack]
        form = DemoRequestForm(initial=initial)

    return render(
        request,
        "compte/accueil.html",
        {
            "demo_form": form,
            "demo_sent": demo_sent,
            "selected_pack_label": PACK_LABELS.get(selected_pack, ""),
        },
    )


def gym_home(request):
    """
    Page publique du gym basée sur le sous-domaine
    """

    gym = request.gym

    if not gym:
        return render(request, "website/no_gym.html")

    website = getattr(gym, "website", None)

    return render(request, "website/home.html", {
        "gym": gym,
        "website": website
    })
