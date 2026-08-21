from unittest.mock import patch

from backend import social_banner


class _Image:
    def save(self, *_args, **_kwargs):
        return None


class _Draw:
    def __init__(self):
        self.labels = []

    def rectangle(self, *_args, **_kwargs):
        return None

    def rounded_rectangle(self, *_args, **_kwargs):
        return None

    def text(self, _position, label, **_kwargs):
        self.labels.append(label)


def test_social_banner_normalizes_productive_evidence_payload_without_network():
    draw = _Draw()
    pick = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "pick": "América",
        "cuota": 1.80,
        "horario": "20:00",
        "confianza": "65% respaldo de datos",
        "tiene_valor": False,
    }

    with (
        patch.object(social_banner.Image, "new", return_value=_Image()),
        patch.object(social_banner.ImageDraw, "Draw", return_value=draw),
        patch.object(social_banner.ImageFont, "truetype", return_value=object()),
        patch.object(
            social_banner.urllib.request,
            "urlopen",
            side_effect=AssertionError("network forbidden"),
        ),
    ):
        social_banner.generar_banner_redes(
            [pick], output_path="unused.png", usar_ia=False
        )

    assert draw.labels.count("Respaldo de datos: 65%") == 1
    assert "Respaldo de datos: 65% respaldo de datos" not in draw.labels
    assert not any("Señal de valor" in label for label in draw.labels)
