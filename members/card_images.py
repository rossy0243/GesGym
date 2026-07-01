from io import BytesIO
import math

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont


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


def _contained_image(image, width, height):
    if not image:
        return None
    image = image.copy()
    image.thumbnail((width, height), Image.Resampling.LANCZOS)
    return image


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
    p0 = (x + size * 0.20, y + size * 0.78)
    p1 = (x + size * 0.28, y + size * 0.58)
    p2 = (x + size * 0.72, y + size * 0.58)
    p3 = (x + size * 0.80, y + size * 0.78)
    curve = []
    for step in range(25):
        t = step / 24
        mt = 1 - t
        curve.append(
            (
                mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
                mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    draw.polygon(curve + [p0], fill="#c9c9c5")


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


def _draw_linear_background(image):
    c0 = (20, 20, 20)
    c1 = (27, 27, 29)
    c2 = (11, 12, 14)
    sample_width = 251
    sample_height = 163
    denominator = max(sample_width + sample_height - 2, 1)
    pixels = []
    for y in range(sample_height):
        for x in range(sample_width):
            t = (x + y) / denominator
            if t <= 0.45:
                local = t / 0.45
                color = tuple(round(c0[i] + (c1[i] - c0[i]) * local) for i in range(3))
            else:
                local = (t - 0.45) / 0.55
                color = tuple(round(c1[i] + (c2[i] - c1[i]) * local) for i in range(3))
            pixels.append((*color, 255))
    sample = Image.new("RGBA", (sample_width, sample_height))
    sample.putdata(pixels)
    image.alpha_composite(sample.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.BICUBIC))


def _overlay_radial(image, center, inner_radius, outer_radius, stops):
    scale = 4
    sample_width = math.ceil(CARD_WIDTH / scale)
    sample_height = math.ceil(CARD_HEIGHT / scale)
    overlay_pixels = []
    cx, cy = center
    outer_radius = max(outer_radius, inner_radius + 1)
    for y in range(sample_height):
        source_y = y * scale
        for x in range(sample_width):
            source_x = x * scale
            distance = math.hypot(source_x - cx, source_y - cy)
            if distance > outer_radius:
                overlay_pixels.append((0, 0, 0, 0))
                continue
            position = 0 if distance <= inner_radius else (distance - inner_radius) / (outer_radius - inner_radius)
            rgba = stops[-1][1]
            for index, (stop_pos, stop_rgba) in enumerate(stops):
                if position <= stop_pos:
                    if index == 0:
                        rgba = stop_rgba
                    else:
                        prev_pos, prev_rgba = stops[index - 1]
                        local = 0 if stop_pos == prev_pos else (position - prev_pos) / (stop_pos - prev_pos)
                        rgba = tuple(prev_rgba[i] + (stop_rgba[i] - prev_rgba[i]) * local for i in range(4))
                    break
            alpha = max(0, min(255, round(rgba[3])))
            if not alpha:
                overlay_pixels.append((0, 0, 0, 0))
                continue
            source = tuple(max(0, min(255, round(value))) for value in rgba[:3])
            overlay_pixels.append((*source, alpha))
    overlay = Image.new("RGBA", (sample_width, sample_height))
    overlay.putdata(overlay_pixels)
    image.alpha_composite(overlay.resize((CARD_WIDTH, CARD_HEIGHT), Image.Resampling.BICUBIC))


def _rounded_mask():
    mask = Image.new("L", (CARD_WIDTH, CARD_HEIGHT), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, CARD_WIDTH, CARD_HEIGHT), radius=26, fill=255)
    return mask


def _open_default_logo():
    try:
        from django.contrib.staticfiles import finders

        path = finders.find("avatar/logo_smartclub.png")
    except Exception:
        path = None
    if not path:
        return None
    try:
        image = Image.open(path)
        image.load()
        return image.convert("RGBA")
    except (OSError, SyntaxError, ValueError):
        return None


def _paste_logo_with_shadow(base, logo, box):
    contained = _contained_image(logo, box[2], box[3])
    if not contained:
        return
    x = box[0] + (box[2] - contained.width) // 2
    y = box[1] + (box[3] - contained.height) // 2
    alpha = contained.getchannel("A")
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 140), (x, y + 6), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    base.alpha_composite(shadow)
    base.alpha_composite(contained, (x, y))


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
    logo = _open_image(getattr(organization, "logo", None)) or _open_default_logo()
    photo = _open_image(member.photo)
    full_name = f"{member.first_name or ''} {member.last_name or ''}".strip() or "Membre"
    member_number = f"MEM-{member.id:05d}" if member.id else "-"
    username = member.user.username if getattr(member, "user", None) else "Non defini"
    organization_name = (organization.name if organization else "Organisation").upper()

    card = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    background = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 255))
    _draw_linear_background(background)
    draw = ImageDraw.Draw(background, "RGBA")
    _draw_hex_texture(draw)
    _overlay_radial(
        background,
        (330, 205),
        20,
        340,
        [
            (0, (255, 255, 255, 46)),
            (0.45, (255, 255, 255, 18)),
            (1, (255, 255, 255, 0)),
        ],
    )
    _overlay_radial(
        background,
        (900, 555),
        20,
        250,
        [
            (0, (255, 255, 255, 36)),
            (1, (255, 255, 255, 0)),
        ],
    )
    _overlay_radial(
        background,
        (CARD_WIDTH / 2, CARD_HEIGHT / 2),
        60,
        CARD_WIDTH * 0.62,
        [
            (0, (0, 0, 0, 0)),
            (1, (0, 0, 0, 138)),
        ],
    )

    card.alpha_composite(background, (0, 0))
    mask = _rounded_mask()
    image = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    image.paste(card, (0, 0), mask)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((1, 1, CARD_WIDTH - 2, CARD_HEIGHT - 2), radius=26, outline=(255, 255, 255, 26), width=2)

    logo_box = ((CARD_WIDTH - 390) // 2, 24, 390, 112)
    if logo:
        _paste_logo_with_shadow(image, logo, logo_box)
    else:
        logo_font = _fit_font(draw, organization_name, 350, 38, 18, bold=True)
        draw.text((CARD_WIDTH / 2, 60), organization_name, fill="#111827", font=logo_font, anchor="mm")
        gym_font = _font(16, bold=True)
        draw.text((CARD_WIDTH / 2, 92), "GYM", fill="#ef4444", font=gym_font, anchor="mm")

    photo_box = (60, 205, 200, 200)
    if photo:
        _paste_cover(image, photo, photo_box)
    else:
        _draw_photo_placeholder(draw, *photo_box[:2], photo_box[2])
    draw.rectangle((60, 205, 260, 405), outline=(255, 255, 255, 42), width=2)

    info_x = 300
    name_font = _fit_font(draw, full_name, 335, 33, 21, bold=True)
    draw.text((info_x, 258), full_name, fill="#ffffff", font=name_font, anchor="ls")
    draw.text((info_x, 305), f"@{username}", fill="#f4f4f5", font=_font(20, bold=True), anchor="ls")
    draw.text((info_x, 354), "N\u00b0 membre:", fill="#ffffff", font=_font(22), anchor="ls")
    draw.text((info_x + 150, 354), member_number, fill="#ffffff", font=_font(22, bold=True), anchor="ls")

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
    draw.text(
        (60, 582),
        "Carte personnelle - acces reserve au membre identifie.",
        fill=(255, 255, 255, 140),
        font=_font(12, bold=True),
        anchor="ls",
    )
    gym_name = member.gym.name if member.gym_id else ""
    gym_font = _font(12, bold=True)
    draw.text((944, 596), gym_name, fill=(255, 255, 255, 122), font=gym_font, anchor="rs")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
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
