"""Network-free 1080x1920 story rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from backend.vertical_content import VerticalCard


ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "frontend" / "public" / "logo.jpg"
NAVY = "#071021"
PANEL = "#101B31"
GOLD = "#F5CF58"
WHITE = "#F8FAFC"
MUTED = "#AAB6CA"
GREEN = "#32D583"
GREEN_PANEL = "#103A2D"
RED = "#FF6B6B"
RED_PANEL = "#451F2A"

_SIZE = (1080, 1920)
_RESAMPLE = Image.Resampling.LANCZOS
SAFE_ZONE_BOTTOM = 1740
STORY_CTA_BOUNDS = (72, 1570, 1008, 1622)
STORY_FOOTER_BOUNDS = (60, 1648, 1020, 1680)
TICKET_FOREGROUND_BOX = (60, 170, 1020, 1750)
TICKET_FOREGROUND_SIZE = (960, 1580)


def _font(
    size: int, *, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    )
    candidates = [Path(name) for name in names]
    if bold:
        candidates.extend(
            [
                Path("C:/Windows/Fonts/arialbd.ttf"),
                Path("C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
            ]
        )
    else:
        candidates.extend(
            [
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("C:/Windows/Fonts/DejaVuSans.ttf"),
            ]
        )
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no size parameter.
        return ImageFont.load_default()


def _jpeg(image: Image.Image) -> bytes:
    output = BytesIO()
    image.convert("RGB").save(
        output,
        format="JPEG",
        quality=92,
        optimize=True,
        subsampling=0,
    )
    return output.getvalue()


def render_story_jpeg(card: VerticalCard) -> bytes:
    """Render one immutable vertical card as deterministic JPEG bytes."""
    if not isinstance(card, VerticalCard):
        raise ValueError("story renderer requires one VerticalCard")

    image = Image.new("RGB", _SIZE, NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((26, 26, 1054, 1894), radius=32, outline=GOLD, width=3)
    _paste_logo(image, (56, 72), (112, 112))

    draw.text((184, 76), "REY TACO PICKS", fill=GOLD, font=_font(25, bold=True))
    draw.text(
        (184, 112),
        _fit_text(draw, card.headline, _font(48, bold=True), 680),
        fill=WHITE,
        font=_font(48, bold=True),
    )
    draw.text(
        (184, 174),
        _fit_text(draw, card.subtitle, _font(24), 760),
        fill=MUTED,
        font=_font(24),
    )
    date_width = draw.textlength(card.portfolio_date, font=_font(22))
    draw.text((1004 - date_width, 78), card.portfolio_date, fill=MUTED, font=_font(22))

    panel_y = 270
    panel_height = 178
    panel_gap = 18
    event_font = _font(27, bold=True)
    detail_font = _font(23)
    meta_font = _font(20, bold=True)
    if not card.rows:
        draw.rounded_rectangle(
            (58, panel_y, 1022, panel_y + panel_height), radius=18, fill=PANEL
        )
        draw.text(
            (86, panel_y + 64),
            "Contenido disponible en reytacopicks.com",
            fill=MUTED,
            font=detail_font,
        )
    for index, row in enumerate(card.rows):
        y = panel_y + index * (panel_height + panel_gap)
        if y + panel_height > 1650:
            break
        draw.rounded_rectangle((58, y, 1022, y + panel_height), radius=18, fill=PANEL)
        badge_label, badge_fill, badge_text = _row_badge(row.state)
        draw.rounded_rectangle(
            (78, y + 22, 194, y + 156),
            radius=12,
            fill=badge_fill,
            outline=badge_text,
            width=2,
        )
        badge_font = _font(16, bold=True)
        badge_width = draw.textlength(badge_label, font=badge_font)
        draw.text(
            (136 - badge_width / 2, y + 78),
            badge_label,
            fill=badge_text,
            font=badge_font,
        )
        event = _fit_text(draw, row.event, event_font, 770)
        selection = _fit_text(draw, row.selection, detail_font, 770)
        details = " · ".join(value for value in (row.odds, row.score) if value)
        details = _fit_text(draw, details, meta_font, 770)
        draw.text((224, y + 24), event, fill=WHITE, font=event_font)
        draw.text((224, y + 76), selection, fill=MUTED, font=detail_font)
        draw.text((224, y + 122), details, fill=GOLD, font=meta_font)

    cta_font = _font(28, bold=True)
    cta = _fit_text(draw, card.cta, cta_font, 900)
    cta_width = draw.textlength(cta, font=cta_font)
    draw.rounded_rectangle(STORY_CTA_BOUNDS, radius=16, fill=GOLD)
    cta_top = STORY_CTA_BOUNDS[1] + 10
    draw.text((540 - cta_width / 2, cta_top), cta, fill=NAVY, font=cta_font)
    footer = "18+ · Apuesta con responsabilidad"
    footer_font = _font(21, bold=True)
    footer_width = draw.textlength(footer, font=footer_font)
    draw.text(
        (540 - footer_width / 2, STORY_FOOTER_BOUNDS[1]),
        footer,
        fill=MUTED,
        font=footer_font,
    )
    return _jpeg(image)


def _row_badge(state: str) -> tuple[str, str, str]:
    normalized = " ".join(str(state or "").split()).casefold()
    if normalized == "ganado":
        return "GANADO", GREEN_PANEL, GREEN
    if normalized in {"perdido", "fallado"}:
        return "PERDIDO", RED_PANEL, RED
    if normalized in {"void", "nulo"}:
        return "NULO", PANEL, MUTED
    if normalized:
        label = normalized.upper()
        return (label[:9], PANEL, GOLD)
    return "PICK", PANEL, GOLD


def render_ticket_evidence_jpeg(ticket_jpeg: bytes, observed_label: str) -> bytes:
    """Render an original ticket image, contained without cropping, as a story."""
    if not isinstance(ticket_jpeg, bytes):
        raise ValueError("ticket evidence renderer requires JPEG bytes")
    try:
        with Image.open(BytesIO(ticket_jpeg)) as opened:
            opened.load()
            source = opened.convert("RGB")
    except (OSError, ValueError):
        raise ValueError("ticket evidence renderer requires valid JPEG bytes") from None

    background = ImageOps.fit(source, _SIZE, method=_RESAMPLE)
    background = background.filter(ImageFilter.GaussianBlur(radius=28))
    image = Image.blend(background, Image.new("RGB", _SIZE, NAVY), 0.68)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((26, 26, 1054, 1894), radius=32, outline=GOLD, width=3)

    draw.text((70, 74), "EVIDENCIA ORIGINAL", fill=GOLD, font=_font(40, bold=True))
    label = _fit_text(draw, str(observed_label), _font(24), 900)
    draw.text((70, 132), label, fill=WHITE, font=_font(24))

    foreground = ImageOps.contain(source, TICKET_FOREGROUND_SIZE, method=_RESAMPLE)
    x = TICKET_FOREGROUND_BOX[0] + (TICKET_FOREGROUND_SIZE[0] - foreground.width) // 2
    y = TICKET_FOREGROUND_BOX[1] + (TICKET_FOREGROUND_SIZE[1] - foreground.height) // 2
    draw.rounded_rectangle(
        (x - 10, y - 10, x + foreground.width + 10, y + foreground.height + 10),
        radius=20,
        fill=PANEL,
        outline=GOLD,
        width=3,
    )
    image.paste(foreground, (x, y))
    footer = "reytacopicks.com · 18+"
    footer_font = _font(23, bold=True)
    footer_width = draw.textlength(footer, font=footer_font)
    draw.text((540 - footer_width / 2, 1838), footer, fill=WHITE, font=footer_font)
    return _jpeg(image)


def _paste_logo(
    image: Image.Image, position: tuple[int, int], size: tuple[int, int]
) -> None:
    if not LOGO.is_file():
        return
    try:
        with Image.open(LOGO) as source:
            logo = ImageOps.fit(source.convert("RGB"), size, method=_RESAMPLE)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo.width - 1, logo.height - 1), fill=255)
        image.paste(logo, position, mask)
    except (OSError, ValueError):
        return


def _fit_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: float,
) -> str:
    normalized = " ".join(str(value).split())
    if draw.textlength(normalized, font=font) <= width:
        return normalized
    suffix = "…"
    candidate = normalized
    while candidate and draw.textlength(candidate + suffix, font=font) > width:
        candidate = candidate[:-1]
    return candidate.rstrip() + suffix
