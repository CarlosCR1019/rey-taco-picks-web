"""Deterministic square result card rendered without network dependencies."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from backend.result_reporting import ResultReport


_ROOT = Path(__file__).resolve().parents[1]
_LOGO = _ROOT / "frontend" / "public" / "logo.jpg"
_NAVY = "#071021"
_PANEL = "#101B31"
_GOLD = "#F5CF58"
_WHITE = "#F8FAFC"
_MUTED = "#AAB6CA"
_STATE_COLOR = {
    "ganado": "#2ECC71",
    "perdido": "#EF5350",
    "void": "#90A4AE",
    "revision_pendiente": "#F2C94C",
}
_STATE_LABEL = {
    "ganado": "GANADO",
    "perdido": "PERDIDO",
    "void": "VOID",
    "revision_pendiente": "REVISIÓN",
}


def render_result_jpeg(report: ResultReport) -> bytes:
    """Return one branded 1080-square JPEG for a settled six-pick report."""
    if not isinstance(report, ResultReport):
        raise ValueError("result banner requires a ResultReport")
    if report.kind != "final" or not report.terminal or len(report.rows) != 6:
        raise ValueError("result banner requires one final settled six-pick report")

    image = Image.new("RGB", (1080, 1080), _NAVY)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((26, 26, 1054, 1054), radius=32, outline=_GOLD, width=3)
    _paste_logo(image)

    brand = _font(24, bold=True)
    title = _font(52, bold=True)
    record_font = _font(32, bold=True)
    event_font = _font(24, bold=True)
    detail_font = _font(20)
    status_font = _font(17, bold=True)
    footer_font = _font(19, bold=True)

    draw.text((184, 70), "REY TACO PICKS", fill=_GOLD, font=brand)
    draw.text((184, 105), "CIERRE VERIFICADO", fill=_WHITE, font=title)
    draw.text(
        (184, 170),
        f"RÉCORD DE LA JORNADA: {report.record}",
        fill=_GOLD,
        font=record_font,
    )
    draw.text(
        (824, 78),
        report.portfolio_date,
        fill=_MUTED,
        font=detail_font,
    )

    y = 250
    for row in report.rows:
        state = str(row["estado"])
        color = _STATE_COLOR[state]
        draw.rounded_rectangle((58, y, 1022, y + 108), radius=16, fill=_PANEL)
        draw.rounded_rectangle((76, y + 19, 184, y + 89), radius=12, fill=color)
        label = _STATE_LABEL[state]
        label_width = draw.textlength(label, font=status_font)
        draw.text(
            (130 - label_width / 2, y + 45),
            label,
            fill=_NAVY,
            font=status_font,
        )
        event = _fit_text(draw, str(row["partido"]), event_font, 690)
        selection = _fit_text(
            draw,
            f"{row['pick']}  @ {row['cuota']}",
            detail_font,
            690,
        )
        draw.text((212, y + 22), event, fill=_WHITE, font=event_font)
        draw.text((212, y + 65), selection, fill=_MUTED, font=detail_font)
        y += 122

    draw.line((70, 998, 1010, 998), fill="#273753", width=2)
    draw.text(
        (72, 1015),
        "reytacopicks.com",
        fill=_GOLD,
        font=footer_font,
    )
    footer = "18+ · Juega responsablemente"
    footer_width = draw.textlength(footer, font=footer_font)
    draw.text((1008 - footer_width, 1015), footer, fill=_MUTED, font=footer_font)

    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True, subsampling=0)
    return output.getvalue()


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _paste_logo(image: Image.Image) -> None:
    if not _LOGO.is_file():
        return
    try:
        with Image.open(_LOGO) as source:
            logo = ImageOps.fit(source.convert("RGB"), (112, 112), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 111, 111), fill=255)
        image.paste(logo, (56, 67), mask)
    except (OSError, ValueError):
        return


def _fit_text(
    draw: ImageDraw.ImageDraw,
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: float,
) -> str:
    normalized = " ".join(value.split())
    if draw.textlength(normalized, font=font) <= width:
        return normalized
    suffix = "…"
    candidate = normalized
    while candidate and draw.textlength(candidate + suffix, font=font) > width:
        candidate = candidate[:-1]
    return candidate.rstrip() + suffix
