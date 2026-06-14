from pathlib import Path

from django.core.exceptions import ValidationError


ALLOWED_IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
MAX_IMAGE_UPLOAD_SIZE = 3 * 1024 * 1024


def validate_safe_image_upload(uploaded_file):
    if not uploaded_file:
        return

    if uploaded_file.size and uploaded_file.size > MAX_IMAGE_UPLOAD_SIZE:
        raise ValidationError("L'image ne doit pas depasser 3 Mo.")

    extension = Path(uploaded_file.name or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError("Format image non autorise. Utilisez JPG, PNG, WEBP ou GIF.")

    content_type = getattr(uploaded_file, "content_type", "")
    if content_type and not content_type.startswith("image/"):
        raise ValidationError("Le fichier envoye doit etre une image.")
