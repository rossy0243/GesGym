import json

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
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
LANDING_META_DESCRIPTION = (
    "SmartClub Pro est un logiciel de gestion pour salles de sport: membres, "
    "abonnements, paiements, controle d'acces, coaching et rapports dans une "
    "plateforme unique."
)
LANDING_OG_IMAGE = "/static/images/smartclub-logo-full.png"
LANDING_KEYWORDS = (
    "logiciel salle de sport, logiciel gestion salle de sport, gestion club fitness, "
    "application salle de sport, logiciel abonnement fitness, controle acces gym"
)


def _absolute_url(request, path=""):
    if path:
        return request.build_absolute_uri(path)
    return request.build_absolute_uri(request.path)


def _build_landing_seo_context(request):
    canonical_url = _absolute_url(request)
    og_image_url = _absolute_url(request, LANDING_OG_IMAGE)
    title = "SmartClub Pro | Logiciel de gestion pour salles de sport"
    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Quelle est la difference entre le Pack Club et le Pack Premium ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Le Pack Club couvre l'exploitation essentielle. Le Pack Premium "
                        "ajoute les besoins avances lies aux produits, aux employes, aux "
                        "equipements et au coaching."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Comment fonctionne la tarification ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Le prix mensuel depend du pack choisi et du nombre de sites actifs "
                        "equipes. Chaque site actif beneficie du pack retenu."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Le membre a-t-il un espace mobile ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Oui. Tout pack inclut un espace membre mobile PWA avec carte, QR code, "
                        "abonnement, coach, acces, paiements et messages de la salle."
                    ),
                },
            },
        ],
    }
    software_schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "SmartClub Pro",
        "applicationCategory": "BusinessApplication",
        "operatingSystem": "Web",
        "description": LANDING_META_DESCRIPTION,
        "url": canonical_url,
        "image": og_image_url,
        "offers": [
            {
                "@type": "Offer",
                "name": "Pack Club",
                "price": "45",
                "priceCurrency": "USD",
            },
            {
                "@type": "Offer",
                "name": "Pack Premium",
                "price": "55",
                "priceCurrency": "USD",
            },
        ],
        "publisher": {
            "@type": "Organization",
            "name": "SmartClub Pro",
            "email": "contact@smartclubpro.org",
            "telephone": "+243821886995",
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "01 bis, route de Matadi, Ngaliema",
                "addressLocality": "Kinshasa",
                "addressCountry": "CD",
            },
        },
    }
    return {
        "seo_title": title,
        "seo_description": LANDING_META_DESCRIPTION,
        "seo_keywords": LANDING_KEYWORDS,
        "seo_robots": "index, follow",
        "seo_canonical_url": canonical_url,
        "seo_og_type": "website",
        "seo_og_image": og_image_url,
        "seo_twitter_card": "summary_large_image",
        "seo_schema_json": json.dumps([software_schema, faq_schema], ensure_ascii=False),
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
            **_build_landing_seo_context(request),
        },
    )


def robots_txt(request):
    sitemap_url = _absolute_url(request, reverse("sitemap_xml"))
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            "Disallow: /compte/",
            "Disallow: /members/me/",
            "Disallow: /members/preinscription/",
            f"Sitemap: {sitemap_url}",
        ]
    )
    return HttpResponse(content, content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    landing_url = _absolute_url(request, reverse("landing"))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{landing_url}</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")


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
