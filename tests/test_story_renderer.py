from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageOps

from backend.story_renderer import (
    SAFE_ZONE_BOTTOM,
    STORY_CTA_BOUNDS,
    STORY_FOOTER_BOUNDS,
    render_story_jpeg,
    render_ticket_evidence_jpeg,
)
from backend.result_reporting import build_result_report
from backend.vertical_content import build_final_results_story, build_public_pick_story
from tests.test_result_reporting import rows_with_states
from tests.test_social_poster import batch


def _decode_jpeg(jpeg: bytes) -> Image.Image:
    assert jpeg[:3] == b"\xff\xd8\xff"
    with Image.open(BytesIO(jpeg)) as image:
        assert image.format == "JPEG"
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


def _marked_ticket_jpeg(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, "#202020")
    pixels = image.load()
    marker_size = max(8, min(size) // 30)
    markers = {
        "top_left": (236, 48, 48),
        "top_right": (40, 212, 92),
        "bottom_left": (45, 106, 236),
        "bottom_right": (238, 208, 47),
    }
    for offset_x in range(marker_size):
        for offset_y in range(marker_size):
            pixels[offset_x, offset_y] = markers["top_left"]
            pixels[size[0] - 1 - offset_x, offset_y] = markers["top_right"]
            pixels[offset_x, size[1] - 1 - offset_y] = markers["bottom_left"]
            pixels[size[0] - 1 - offset_x, size[1] - 1 - offset_y] = markers[
                "bottom_right"
            ]
    output = BytesIO()
    image.save(output, format="JPEG", quality=100, subsampling=0)
    return output.getvalue()


def _expected_foreground_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    source = Image.new("RGB", size)
    contained = ImageOps.contain(source, (960, 1580), method=Image.Resampling.LANCZOS)
    left = 60 + (960 - contained.width) // 2
    top = 170 + (1580 - contained.height) // 2
    return left, top, left + contained.width, top + contained.height


def _assert_corner_markers(output: Image.Image, source_size: tuple[int, int]) -> None:
    left, top, right, bottom = _expected_foreground_box(source_size)
    expected = {
        (left, top): (236, 48, 48),
        (right - 1, top): (40, 212, 92),
        (left, bottom - 1): (45, 106, 236),
        (right - 1, bottom - 1): (238, 208, 47),
    }
    for (x, y), (red, green, blue) in expected.items():
        nearby = output.crop((x, y, x + 3, y + 3)).getdata()
        assert any(
            abs(pixel[0] - red) < 55
            and abs(pixel[1] - green) < 55
            and abs(pixel[2] - blue) < 55
            for pixel in nearby
        ), (x, y)


def test_render_story_jpeg_is_rgb_1080x1920_and_deterministic():
    card = build_public_pick_story(batch(), portfolio_date="2026-08-24")

    first = render_story_jpeg(card)
    second = render_story_jpeg(card)

    assert first == second
    image = _decode_jpeg(first)
    assert image.mode == "RGB"
    assert image.size == (1080, 1920)


def test_render_story_jpeg_rejects_non_vertical_cards():
    with pytest.raises(ValueError, match="requires one VerticalCard"):
        render_story_jpeg(object())


def test_result_story_never_draws_internal_pick_ids(monkeypatch: pytest.MonkeyPatch):
    report = build_result_report(rows_with_states(*(6 * ("ganado",))), kind="final")
    card = build_final_results_story(report)
    internal_ids = {str(row.pick_id) for row in card.rows}
    drawn: list[str] = []
    original = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)

    render_story_jpeg(card)

    assert not any(f"PICK {internal_id}" in drawn for internal_id in internal_ids)
    assert drawn.count("GANADO") == 6


def test_render_ticket_evidence_contains_all_source_corners_without_cropping():
    source = _tall_ticket_jpeg()

    output = _decode_jpeg(
        render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")
    )

    assert output.mode == "RGB"
    assert output.size == (1080, 1920)

    _assert_corner_markers(output, (320, 900))

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


@pytest.mark.parametrize("source_size", [(1200, 400), (640, 160)])
def test_render_ticket_evidence_centers_landscape_and_short_sources_without_cropping(
    source_size: tuple[int, int],
):
    output = _decode_jpeg(
        render_ticket_evidence_jpeg(
            _marked_ticket_jpeg(source_size), observed_label="24 AGO · CDMX"
        )
    )

    assert output.size == (1080, 1920)
    _assert_corner_markers(output, source_size)


def test_render_ticket_evidence_is_deterministic_and_rejects_invalid_input():
    source = _tall_ticket_jpeg()

    first = render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")
    second = render_ticket_evidence_jpeg(source, observed_label="24 AGO · CDMX")

    assert first == second
    with pytest.raises(ValueError, match="valid JPEG"):
        render_ticket_evidence_jpeg(b"not an image", observed_label="24 AGO · CDMX")
    with pytest.raises(ValueError, match="JPEG bytes"):
        render_ticket_evidence_jpeg(object(), observed_label="24 AGO · CDMX")


def test_story_cta_and_footer_render_inside_instagram_safe_zone():
    assert SAFE_ZONE_BOTTOM == 1740
    assert STORY_CTA_BOUNDS[1] >= 0
    assert STORY_CTA_BOUNDS[3] <= SAFE_ZONE_BOTTOM
    assert STORY_FOOTER_BOUNDS[1] >= 0
    assert STORY_FOOTER_BOUNDS[3] <= SAFE_ZONE_BOTTOM

    card = build_public_pick_story(batch(), portfolio_date="2026-08-24")
    output = _decode_jpeg(render_story_jpeg(card))
    cta = output.crop(STORY_CTA_BOUNDS)
    footer = output.crop(STORY_FOOTER_BOUNDS)
    below_safe_zone = output.crop((60, SAFE_ZONE_BOTTOM, 1020, 1880))

    assert (
        sum(
            red > 180 and green > 150 and blue < 130
            for red, green, blue in cta.getdata()
        )
        > 40_000
    )
    assert (
        sum(
            red > 120 and green > 130 and blue > 150
            for red, green, blue in footer.getdata()
        )
        > 100
    )
    assert all(max(pixel) < 64 for pixel in below_safe_zone.getdata())
