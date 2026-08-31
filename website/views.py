import json
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from organizations.models import Gym

from .branding import landing_contact
from .forms import ContactRequestForm


# Valeurs de secours conservees pour compatibilite. Les coordonnees reelles
# viennent desormais de l'organisation, reglees dans Parametres.
CONTACT_WHATSAPP_NUMBER = "243000000000"
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


def _build_whatsapp_url(message, numero=None):
    numero = numero or CONTACT_WHATSAPP_NUMBER
    if message:
        return f"https://wa.me/{numero}?text={quote(message)}"
    return f"https://wa.me/{numero}"


def _build_contact_whatsapp_message(cleaned_data, nom_organisation="Royal Gym"):
    return (
        f"Bonjour {nom_organisation}, je viens de vous contacter depuis votre site.\n\n"
        f"Nom complet : {cleaned_data['full_name']}\n"
        f"Téléphone : {cleaned_data['phone']}\n"
        f"Email : {cleaned_data['email'] or 'Non renseigné'}\n\n"
        f"Message : {cleaned_data['message'] or 'Aucun message complémentaire.'}"
    )


def _absolute_url(request, path=""):
    if path:
        return request.build_absolute_uri(path)
    return request.build_absolute_uri(request.path)


def _build_landing_seo_context(request, contact=None):
    """
    Balises et donnees structurees de la page d'accueil.

    Tout vient de l'organisation : le titre, la description, les mots-cles et
    les questions frequentes. Le bloc lu par les moteurs de recherche doit
    decrire l'etablissement reel, pas un exemple.
    """
    contact = contact or landing_contact(request)
    canonical_url = _absolute_url(request)
    og_image_url = contact["logo_url"] or _absolute_url(request, LANDING_OG_IMAGE)
    if og_image_url.startswith("/"):
        og_image_url = _absolute_url(request, og_image_url)

    title = f"{contact['name']} | {contact['kicker']}"

    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": entree["question"],
                "acceptedAnswer": {"@type": "Answer", "text": entree["answer"]},
            }
            for entree in contact["faq"]
        ],
    }
    gym_schema = {
        "@context": "https://schema.org",
        "@type": "ExerciseGym",
        "name": contact["name"],
        "description": contact["seo_description"],
        "url": canonical_url,
        "image": og_image_url,
        "telephone": contact["phone"] or f"+{contact['whatsapp_number']}",
        "email": contact["email"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": contact["address"] or "Adresse a confirmer",
            "addressLocality": contact["city"],
            "addressCountry": "CD",
        },
    }
    if contact["hours"]:
        gym_schema["openingHours"] = contact["hours"]

    return {
        "seo_title": title,
        "seo_description": contact["seo_description"],
        "seo_keywords": contact["seo_keywords"],
        "seo_robots": "index, follow",
        "seo_canonical_url": canonical_url,
        "seo_og_type": "website",
        "seo_og_image": og_image_url,
        "seo_twitter_card": "summary_large_image",
        "seo_schema_json": json.dumps([gym_schema, faq_schema], ensure_ascii=False),
    }


def landing(request):
    contact = landing_contact(request)
    contact_sent = request.GET.get("contact") == "sent"
    contact_whatsapp_message = ""
    if contact_sent:
        contact_whatsapp_message = request.session.pop("contact_whatsapp_message", "")

    if request.method == "POST":
        form = ContactRequestForm(request.POST)
        if form.is_valid():
            cleaned_data = form.cleaned_data
            subject = f"Nouveau message {contact['name']} - {cleaned_data['full_name']}"
            message = (
                f"Un nouveau message a été envoyé depuis le site {contact['name']}.\n\n"
                f"Nom complet : {cleaned_data['full_name']}\n"
                f"Téléphone : {cleaned_data['phone']}\n"
                f"Email : {cleaned_data['email'] or 'Non renseigné'}\n\n"
                "Message :\n"
                f"{cleaned_data['message'] or 'Aucun message complémentaire.'}\n"
            )
            reply_to = [cleaned_data["email"]] if cleaned_data["email"] else []
            # Destinataire pris sur l'organisation : les demandes partaient
            # jusqu'ici vers une adresse d'exemple, donc nulle part.
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[contact["email"]],
                reply_to=reply_to,
            )
            email.send(fail_silently=False)
            request.session["contact_whatsapp_message"] = _build_contact_whatsapp_message(
                cleaned_data,
                contact["name"],
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
            "contact_whatsapp_link": _build_whatsapp_url(
                contact_whatsapp_message, contact["whatsapp_number"]
            ),
            "whatsapp_contact_url": _build_whatsapp_url("", contact["whatsapp_number"]),
            "landing_contact": contact,
            # Priorite a un vrai lien d'agenda si un jour configure (Google Calendar
            # ou autre), sinon on propose de demander le planning directement sur
            # WhatsApp : plus utile qu'un lien externe qui n'existe pas encore.
            "hero_agenda_url": getattr(settings, "LANDING_AGENDA_URL", "") or _build_whatsapp_url(
                "Bonjour, je voudrais connaître le planning des cours et les horaires.",
                contact["whatsapp_number"],
            ),
            **_build_landing_seo_context(request, contact),
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
