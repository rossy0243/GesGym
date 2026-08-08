import json
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from organizations.models import Gym

from .forms import ContactRequestForm


# TODO Royal Gym : remplacer par le vrai numéro WhatsApp (indicatif + numéro, sans "+" ni espaces).
CONTACT_WHATSAPP_NUMBER = "243000000000"
# TODO Royal Gym : remplacer par l'adresse e-mail réelle de contact.
CONTACT_EMAIL = "contact@royalgym.example"

LANDING_META_DESCRIPTION = (
    "Royal Gym est une salle de sport premium à Kinshasa : musculation, cardio, "
    "cours collectifs et coaching personnalisé dans un cadre haut de gamme."
)
LANDING_OG_IMAGE = "/static/images/royal-gym-logo-512.png"
LANDING_KEYWORDS = (
    "salle de sport Kinshasa, musculation, fitness, cours collectifs, coaching personnel, "
    "Royal Gym"
)


def _build_whatsapp_url(message):
    if message:
        return f"https://wa.me/{CONTACT_WHATSAPP_NUMBER}?text={quote(message)}"
    return f"https://wa.me/{CONTACT_WHATSAPP_NUMBER}"


def _build_contact_whatsapp_message(cleaned_data):
    return (
        "Bonjour Royal Gym, je viens de vous contacter depuis votre site.\n\n"
        f"Nom complet : {cleaned_data['full_name']}\n"
        f"Téléphone : {cleaned_data['phone']}\n"
        f"Email : {cleaned_data['email'] or 'Non renseigné'}\n\n"
        f"Message : {cleaned_data['message'] or 'Aucun message complémentaire.'}"
    )


def _absolute_url(request, path=""):
    if path:
        return request.build_absolute_uri(path)
    return request.build_absolute_uri(request.path)


def _build_landing_seo_context(request):
    canonical_url = _absolute_url(request)
    og_image_url = _absolute_url(request, LANDING_OG_IMAGE)
    title = "Royal Gym | Salle de sport premium à Kinshasa"
    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Quels services propose Royal Gym ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Musculation, cardio-training, cours collectifs et coaching "
                        "personnalisé, dans un espace pensé pour progresser en toute "
                        "sécurité."
                    ),
                },
            },
            {
                "@type": "Question",
                "name": "Quels sont les horaires d'ouverture ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Contactez-nous par WhatsApp ou téléphone pour connaître nos horaires à jour.",
                },
            },
            {
                "@type": "Question",
                "name": "Proposez-vous un coaching personnalisé ?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": (
                        "Oui, nos coachs vous accompagnent avec un suivi personnalisé "
                        "adapté à vos objectifs."
                    ),
                },
            },
        ],
    }
    gym_schema = {
        "@context": "https://schema.org",
        "@type": "ExerciseGym",
        "name": "Royal Gym",
        "description": LANDING_META_DESCRIPTION,
        "url": canonical_url,
        "image": og_image_url,
        "telephone": f"+{CONTACT_WHATSAPP_NUMBER}",
        "email": CONTACT_EMAIL,
        "address": {
            "@type": "PostalAddress",
            # TODO Royal Gym : remplacer par l'adresse réelle.
            "streetAddress": "Adresse à confirmer",
            "addressLocality": "Kinshasa",
            "addressCountry": "CD",
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
        "seo_schema_json": json.dumps([gym_schema, faq_schema], ensure_ascii=False),
    }


def landing(request):
    contact_sent = request.GET.get("contact") == "sent"
    contact_whatsapp_message = ""
    if contact_sent:
        contact_whatsapp_message = request.session.pop("contact_whatsapp_message", "")

    if request.method == "POST":
        form = ContactRequestForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            subject = f"Nouveau message Royal Gym - {cleaned_data['full_name']}"
            message = (
                "Un nouveau message a été envoyé depuis le site Royal Gym.\n\n"
                f"Nom complet : {cleaned_data['full_name']}\n"
                f"Téléphone : {cleaned_data['phone']}\n"
                f"Email : {cleaned_data['email'] or 'Non renseigné'}\n\n"
                "Message :\n"
                f"{cleaned_data['message'] or 'Aucun message complémentaire.'}\n"
            )
            reply_to = [cleaned_data["email"]] if cleaned_data["email"] else []
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[CONTACT_EMAIL],
                reply_to=reply_to,
            )
            email.send(fail_silently=False)
            request.session["contact_whatsapp_message"] = _build_contact_whatsapp_message(
                cleaned_data,
            )
            return redirect(f"{reverse('landing')}?contact=sent#contact-form")
    else:
        form = ContactRequestForm()

    return render(
        request,
        "compte/accueil.html",
        {
            "contact_form": form,
            "contact_sent": contact_sent,
            "contact_whatsapp_link": _build_whatsapp_url(contact_whatsapp_message),
            "whatsapp_contact_url": _build_whatsapp_url(""),
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
