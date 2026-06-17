import json
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from organizations.models import Gym

from .forms import DemoRequestForm


PACK_PRESET_MESSAGES = {
    "club": "Bonjour, je souhaite découvrir le Pack Club à travers une démonstration, en particulier pour la gestion des membres, des abonnements, des paiements, des accès QR code et des rapports.",
    "premium": "Bonjour, je souhaite découvrir le Pack Premium à travers une démonstration, notamment pour les modules avancés comme le stock, les employés, les équipements, le coaching et le pilotage multi-site.",
}

PACK_LABELS = {
    "club": "Pack Club",
    "premium": "Pack Premium",
}
DEMO_WHATSAPP_NUMBER = "243842616570"
LANDING_META_DESCRIPTION = (
    "SmartClub Pro est un logiciel de gestion pour salles de sport : membres, "
    "abonnements, paiements, contrôle d’accès QR code, coaching et rapports "
    "dans une plateforme unique pour réduire les pertes et mieux piloter."
)
LANDING_OG_IMAGE = "/static/images/smartclub-logo-full.png"
LANDING_KEYWORDS = (
    "logiciel salle de sport, logiciel gestion salle de sport, gestion club fitness, "
    "application salle de sport, logiciel abonnement fitness, contrôle accès QR code gym"
)


def _build_whatsapp_url(message):
    if message:
        return f"https://wa.me/{DEMO_WHATSAPP_NUMBER}?text={quote(message)}"
    return f"https://wa.me/{DEMO_WHATSAPP_NUMBER}"


def _build_demo_whatsapp_message(cleaned_data, pack_label):
    return (
        "Bonjour SmartClub Pro, je viens de faire une demande de démo.\n\n"
        f"Pack choisi : {pack_label}\n"
        f"Nom complet : {cleaned_data['full_name']}\n"
        f"Email : {cleaned_data['email']}\n"
        f"Téléphone : {cleaned_data['phone']}\n"
        f"Club : {cleaned_data['club_name']}\n"
        f"Nombre de sites actifs : {cleaned_data['sites_count']}\n\n"
        f"Besoin : {cleaned_data['message'] or 'Aucun message complémentaire.'}"
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
                "name": "Quelle est la différence entre le Pack Club et le Pack Premium ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Le Pack Club couvre l'exploitation essentielle. Le Pack Premium "
                        "ajoute les besoins avancés liés aux produits, aux employés, aux "
                        "équipements et au coaching."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Comment fonctionne la tarification ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Le prix mensuel dépend du pack choisi et du nombre de sites actifs "
                        "équipés. Chaque site actif bénéficie du pack retenu."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Le membre a-t-il un espace mobile ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Oui. Chaque pack inclut un espace membre mobile PWA avec carte, QR code, "
                        "abonnement, coach, accès, paiements et messages de la salle."
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
            "telephone": "+243979710633",
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
    demo_whatsapp_message = ""
    if demo_sent:
        demo_whatsapp_message = request.session.pop("demo_whatsapp_message", "")
    selected_pack = request.GET.get("pack", "").strip().lower()
    if selected_pack not in PACK_PRESET_MESSAGES:
        selected_pack = ""

    if request.method == "POST":
        form = DemoRequestForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            sites_count = cleaned_data["sites_count"]
            pack_key = cleaned_data.get("selected_pack", "")
            pack_label = PACK_LABELS.get(pack_key, "Non précisé")
            subject = f"Nouvelle demande de démo SmartClub Pro - {cleaned_data['club_name']}"
            message = (
                "Une nouvelle demande de démo a été envoyée depuis la landing page.\n\n"
                f"Pack choisi : {pack_label}\n"
                f"Nom complet : {cleaned_data['full_name']}\n"
                f"Email : {cleaned_data['email']}\n"
                f"Téléphone : {cleaned_data['phone']}\n"
                f"Club : {cleaned_data['club_name']}\n"
                f"Nombre de sites actifs : {sites_count}\n\n"
                "Besoin exprimé :\n"
                f"{cleaned_data['message'] or 'Aucun message complémentaire.'}\n"
            )
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=["contact@smartclubpro.org"],
                reply_to=[cleaned_data["email"]],
            )
            email.send(fail_silently=False)
            request.session["demo_whatsapp_message"] = _build_demo_whatsapp_message(
                cleaned_data,
                pack_label,
            )
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
            "demo_whatsapp_link": _build_whatsapp_url(demo_whatsapp_message),
            "whatsapp_contact_url": _build_whatsapp_url(""),
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
