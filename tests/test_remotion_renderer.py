from backend.remotion_renderer import remotion_child_environment, render_with_fallback


class FallbackRenderer:
    def __init__(self):
        self.calls = 0

    def render(self, frames):
        self.calls += 1
        return b"fallback"


def test_disabled_remotion_uses_existing_renderer():
    renderer = FallbackRenderer()
    assert render_with_fallback(
        object(),
        remotion_command=["never-run"],
        fallback_renderer=renderer,
        fallback_frames=[b"frame"],
        enabled=False,
    ) == b"fallback"
    assert renderer.calls == 1


def test_remotion_failure_uses_existing_renderer():
    renderer = FallbackRenderer()
    assert render_with_fallback(
        object(),
        remotion_command=["never-run"],
        fallback_renderer=renderer,
        fallback_frames=[b"frame"],
        enabled=True,
    ) == b"fallback"
    assert renderer.calls == 1


def test_remotion_child_environment_excludes_application_secrets():
    environment = remotion_child_environment({
        "PATH": "path",
        "SystemRoot": "root",
        "NODE_ENV": "test",
        "SUPABASE_SERVICE_ROLE_KEY": "secret",
        "TELEGRAM_BOT_TOKEN": "secret",
    })
    assert environment["PATH"] == "path"
    assert environment["NODE_ENV"] == "test"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in environment
    assert "TELEGRAM_BOT_TOKEN" not in environment
