from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from backend.story_renderer import render_story_jpeg, render_ticket_evidence_jpeg
from backend.vertical_content import build_public_pick_story
from tests.test_social_poster import batch


def _decode(jpeg: bytes) -> Image.Image:
    with Image.open(BytesIO(jpeg)) as image:
        return image.copy()


def _tall_ticket_jpeg() -> bytes:
    image = Image.new("RGB", (320, 900), "#202020")
    pixels = image.load()
    for x in range(320):
        for y in range(900):
            if x < 42 and y < 42:
                pixels[x, y] = (236, 48, 48)
            elif x >= 278 and y < 42:
                pixels[x, y] = (40, 212, 92)
            elif x < 42 and y >= 858:
                pixels[x, y] = (45, 106, 236)
            elif x >= 278 and y >= 858:
                pixels[x, y] = (238, 208, 47)
    draw = ImageDraw.Draw(image)
    draw.text((70, 430), "TICKET-ID-4242", fill="#F8FAFC")
    output = BytesIO()
    image.save(output, format="JPEG", quality=98, subsampling=0)
    return output.getvalue()


def test_render_story_jpeg_is_rgb_1080x1920_and_deterministic():
    card = build_public_pick_story(batch(), portfolio_date="2026-08-24")

    first = render_story_jpeg(card)
    second = render_story_jpeg(card)

    assert first == second
    image = _decode(first)
    assert image.mode == "RGB"
    assert image.size == (1080, 1920)


def test_render_story_jpeg_rejects_non_vertical_cards():
    with pytest.raises(ValueError, match="requires one VerticalCard"):
        render_story_jpeg(object())


def test_render_ticket_evidence_contains_all_source_corners_without_cropping():
    source = _tall_ticket_jpeg()

    output = _decode(
        render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")
    )

    assert output.mode == "RGB"
    assert output.size == (1080, 1920)

    # The 320x900 source is contained in a 960x1580 foreground box, yielding
    # roughly 561x1580 centered at x=259 and y=220. Search each source corner
    # in its corresponding foreground quadrant, not merely anywhere in output.
    regions = {
        "red": (
            (280, 255, 480, 420),
            lambda r, g, b: r > 170 and r > g * 1.8 and r > b * 1.5,
        ),
        "green": (
            (600, 255, 800, 420),
            lambda r, g, b: g > 150 and g > r * 1.5 and g > b * 1.2,
        ),
        "blue": (
            (280, 1570, 480, 1760),
            lambda r, g, b: b > 150 and b > r * 1.4 and b > g * 1.2,
        ),
        "yellow": (
            (600, 1570, 800, 1760),
            lambda r, g, b: r > 150 and g > 130 and b < 130,
        ),
    }
    for name, (box, predicate) in regions.items():
        pixels = output.crop(box).getdata()
        assert any(predicate(*pixel) for pixel in pixels), name

    # The source ticket identifier remains visible in the foreground content;
    # this guards against a renderer that reconstructs or masks the ticket.
    foreground = output.crop((250, 250, 830, 1765))
    identifier_region = output.crop((350, 900, 730, 1060))
    assert (
        sum(
            all(channel > 210 for channel in pixel)
            for pixel in identifier_region.getdata()
        )
        > 5
    )
    assert max(channel for pixel in foreground.getdata() for channel in pixel) > 240


def test_render_ticket_evidence_is_deterministic_and_rejects_invalid_input():
    source = _tall_ticket_jpeg()

    first = render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")
    second = render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")

    assert first == second
    with pytest.raises(ValueError, match="valid JPEG"):
        render_ticket_evidence_jpeg(b"not an image", observed_label="24 AGO · CDMX")
    with pytest.raises(ValueError, match="JPEG bytes"):
        render_ticket_evidence_jpeg(object(), observed_label="24 AGO · CDMX")
