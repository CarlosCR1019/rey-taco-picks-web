from backend.playdoit_health import (
    PlaydoitSourceBlocked,
    PlaydoitSourceInvalid,
    assert_playdoit_source_healthy,
)


def test_block_page_is_recoverable_and_does_not_echo_ip_or_ray_id():
    title = "Acceso bloqueado"
    body = "Nuestro sistema detuvo la solicitud. RAY ID abc123 TU IP 203.0.113.4"

    try:
        assert_playdoit_source_healthy(title=title, body=body, source="<html></html>")
    except PlaydoitSourceBlocked as error:
        assert error.code == "source_blocked"
        assert "203.0.113.4" not in str(error)
        assert "abc123" not in str(error)
    else:
        raise AssertionError("blocked source was accepted")


def test_rendered_altenar_page_is_valid_even_before_event_filtering():
    assert_playdoit_source_healthy(
        title="Playdoit.mx",
        body="Deportes Liga MX",
        source='<div id="altenar"><div></div></div>',
    )


def test_unrendered_page_is_recoverable_source_invalid():
    try:
        assert_playdoit_source_healthy(
            title="Playdoit.mx", body="Menú", source="<html><body>Menú</body></html>"
        )
    except PlaydoitSourceInvalid as error:
        assert error.code == "source_invalid"
    else:
        raise AssertionError("invalid source was accepted")
