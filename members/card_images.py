from io import BytesIO
import math

import qrcode
from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 1004
CARD_HEIGHT = 650


def _font(size, bold=False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(draw, text, max_width, max_size, min_size, bold=False):
    for size in range(max_size, min_size - 1, -1):
        font = _font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return _font(min_size, bold=bold)


def _open_image(field_file):
    if not field_file:
        return None
    try:
        field_file.open("rb")
        image = Image.open(field_file)
        image.load()
        return image.convert("RGBA")
    except (OSError, SyntaxError, ValueError):
        return None
    finally:
        try:
            field_file.close()
        except Exception:
            pass


def _paste_contained(base, image, box):
    x, y, width, height = box
    if not image:
        return
    image = image.copy()
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    px = x + (width - image.width) // 2
    py = y + (height - image.height) // 2
    base.alpha_composite(image, (px, py))


def _paste_cover(base, image, box):
    x, y, width, height = box
    if not image:
        return
    image = image.copy()
    ratio = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    base.alpha_composite(cropped, (x, y))


def _draw_photo_placeholder(draw, x, y, size):
    draw.rectangle((x, y, x + size, y + size), fill="#f4f4f2")
    draw.ellipse(
        (
            x + size * 0.34,
            y + size * 0.24,
            x + size * 0.66,
            y + size * 0.56,
        ),
        fill="#c9c9c5",
    )
    draw.pieslice(
        (
            x + size * 0.18,
            y + size * 0.48,
            x + size * 0.82,
            y + size * 1.08,
        ),
        180,
        360,
        fill="#c9c9c5",
    )


def _draw_hex_texture(draw):
    radius = 34
    horizontal_step = radius * 1.75
    vertical_step = radius * 1.52
    rows = int(CARD_HEIGHT / vertical_step) + 3
    cols = int(CARD_WIDTH / horizontal_step) + 3
    for row in range(-1, rows):
        for col in range(-1, cols):
            x = col * horizontal_step + (horizontal_step / 2 if row % 2 else 0)
            y = row * vertical_step
            points = []
            for i in range(6):
                angle = 0.5235987756 + i * 1.0471975512
                points.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
            alpha = max(8, int(46 - (y / CARD_HEIGHT) * 31))
            draw.line(points + [points[0]], fill=(255, 255, 255, alpha), width=2)


def _qr_image(value, size):
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(value or "-")
    qr.make(fit=True)
    return qr.make_image(fill_color="#111827", back_color="#ffffff").convert("RGBA").resize(
        (size, size),
        Image.Resampling.NEAREST,
    )


def render_member_card_png(member):
    organization = member.gym.organization if member.gym_id else None
    logo = _open_image(getattr(organization, "logo", None))
    photo = _open_image(member.photo)
    full_name = f"{member.first_name or ''} {member.last_name or ''}".strip() or "Membre"
    member_number = f"MEM-{member.id:05d}" if member.id else "-"
    username = member.user.username if getattr(member, "user", None) else "Non defini"
    organization_name = (organization.name if organization else "Organisation").upper()

    image = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), "#111111")
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(CARD_HEIGHT):
        shade = int(20 - (y / CARD_HEIGHT) * 9)
        draw.line((0, y, CARD_WIDTH, y), fill=(shade, shade, shade + 2, 255))
    _draw_hex_texture(draw)
    draw.ellipse((80, 20, 780, 520), fill=(255, 255, 255, 20))
    draw.ellipse((730, 430, 1070, 760), fill=(255, 255, 255, 28))
    draw.rounded_rectangle((1, 1, CARD_WIDTH - 2, CARD_HEIGHT - 2), radius=26, outline=(255, 255, 255, 26), width=2)

    logo_box = ((CARD_WIDTH - 390) // 2, 24, 390, 112)
    if logo:
        _paste_contained(image, logo, logo_box)
    else:
        logo_font = _fit_font(draw, organization_name, 350, 38, 18, bold=True)
        text_bbox = draw.textbbox((0, 0), organization_name, font=logo_font)
        draw.text(((CARD_WIDTH - (text_bbox[2] - text_bbox[0])) // 2, 48), organization_name, fill="#ffffff", font=logo_font)
        gym_font = _font(16, bold=True)
        gym_bbox = draw.textbbox((0, 0), "GYM", font=gym_font)
        draw.text(((CARD_WIDTH - (gym_bbox[2] - gym_bbox[0])) // 2, 92), "GYM", fill="#ef4444", font=gym_font)

    photo_box = (60, 205, 200, 200)
    if photo:
        _paste_cover(image, photo, photo_box)
    else:
        _draw_photo_placeholder(draw, *photo_box[:2], photo_box[2])
    draw.rectangle((60, 205, 260, 405), outline=(255, 255, 255, 42), width=2)

    info_x = 300
    name_font = _fit_font(draw, full_name, 335, 33, 21, bold=True)
    draw.text((info_x, 226), full_name, fill="#ffffff", font=name_font)
    draw.text((info_x, 282), f"@{username}", fill="#f4f4f5", font=_font(20))
    draw.text((info_x, 329), "N\u00b0 membre:", fill="#ffffff", font=_font(22))
    draw.text((info_x + 150, 329), member_number, fill="#ffffff", font=_font(22, bold=True))

    qr_size = 200
    qr_x = 690
    qr_y = 245
    qr_padding = 24
    draw.rectangle(
        (qr_x - qr_padding, qr_y - qr_padding, qr_x + qr_size + qr_padding, qr_y + qr_size + qr_padding),
        fill="#ffffff",
    )
    image.alpha_composite(_qr_image(member.get_qr_data(), qr_size), (qr_x, qr_y))

    draw.rectangle((60, 548, 620, 549), fill=(255, 255, 255, 40))
    draw.text((60, 568), "Carte personnelle - acces reserve au membre identifie.", fill=(255, 255, 255, 140), font=_font(12))
    gym_name = member.gym.name if member.gym_id else ""
    gym_font = _font(12)
    gym_bbox = draw.textbbox((0, 0), gym_name, font=gym_font)
    draw.text((944 - (gym_bbox[2] - gym_bbox[0]), 582), gym_name, fill=(255, 255, 255, 122), font=gym_font)

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_organization_pwa_icon_png(organization, size=512):
    size = max(128, min(int(size or 512), 1024))
    logo = _open_image(getattr(organization, "logo", None))
    organization_name = (getattr(organization, "name", "") or "SmartClub").upper()

    image = Image.new("RGBA", (size, size), (16, 40, 32, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(size):
        shade = int(18 + (y / size) * 14)
        draw.line((0, y, size, y), fill=(shade, shade + 22, shade + 15, 255))

    draw.ellipse((-size * 0.25, -size * 0.2, size * 0.7, size * 0.65), fill=(255, 255, 255, 18))
    draw.ellipse((size * 0.45, size * 0.52, size * 1.25, size * 1.22), fill=(255, 255, 255, 14))

    if logo:
        margin = round(size * 0.12)
        _paste_contained(image, logo, (margin, margin, size - margin * 2, size - margin * 2))
    else:
        words = [part[:1] for part in organization_name.split() if part]
        initials = "".join(words[:2]) or "SC"
        font = _fit_font(draw, initials, round(size * 0.72), round(size * 0.36), round(size * 0.16), bold=True)
        bbox = draw.textbbox((0, 0), initials, font=font)
        draw.text(
            ((size - (bbox[2] - bbox[0])) / 2, (size - (bbox[3] - bbox[1])) / 2 - bbox[1]),
            initials,
            fill="#ffffff",
            font=font,
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
