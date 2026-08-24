import pytest

from backend.evidence_messaging import format_evidence_support


@pytest.mark.parametrize(
    "raw",
    [
        "65% respaldo de datos",
        "Respaldo de datos: 65%",
        "65%",
    ],
)
def test_python_consumers_normalize_productive_payload_to_one_label(raw):
    assert format_evidence_support(raw) == "Respaldo de datos: 65%"


def test_python_evidence_label_has_a_neutral_missing_value():
    assert format_evidence_support(None) == "Respaldo de datos: No disponible"
