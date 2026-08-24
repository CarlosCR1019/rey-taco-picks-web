from __future__ import annotations

from io import BytesIO

from PIL import Image

from backend.result_banner import render_result_jpeg
from backend.result_reporting import build_result_report
from tests.test_result_reporting import rows_with_states


def test_final_report_renders_a_deterministic_1080_square_jpeg():
    report = build_result_report(
        rows_with_states(*(["ganado"] * 6)),
        kind="final",
    )

    first = render_result_jpeg(report)
    second = render_result_jpeg(report)

    assert first == second
    assert first.startswith(b"\xff\xd8")
    with Image.open(BytesIO(first)) as image:
        assert image.format == "JPEG"
        assert image.size == (1080, 1080)
        assert image.mode == "RGB"


def test_partial_report_cannot_be_rendered_as_a_final_card():
    report = build_result_report(
        rows_with_states(
            "ganado",
            "pendiente",
            "pendiente",
            "pendiente",
            "pendiente",
            "pendiente",
        ),
        kind="evening",
    )

    try:
        render_result_jpeg(report)
    except ValueError as error:
        assert "final" in str(error)
    else:
        raise AssertionError("a partial report must not render a final card")
