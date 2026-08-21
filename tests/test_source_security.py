from pathlib import Path
import json
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "010319" + "NyC",
    "TACOVIP" + "2026",
    "8684914807:" + "AA",
    "EAGMJ4Qmn" + "NEI",
)


class SourceSecurityTests(unittest.TestCase):
    def test_tracked_source_has_no_known_live_secrets(self):
        files = subprocess.check_output(
            ["git", "ls-files"], cwd=ROOT, text=True
        ).splitlines()
        searchable = [path for path in files if not path.startswith("docs/")]
        hits: list[str] = []

        for relative in searchable:
            path = ROOT / relative
            try:
                contents = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            for marker in FORBIDDEN:
                if marker in contents:
                    hits.append(f"{relative}: {marker[:12]}…")

        self.assertEqual(hits, [])

    def test_privileged_jobs_use_the_service_role_variable(self):
        for relative in (
            "backend/scraper.py", "backend/ticket_listener.py", "backend/verificar_resultados.py",
            "backend/live_tracker.py",
        ):
            contents = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("SUPABASE_SERVICE_ROLE_KEY", contents, relative)
            self.assertNotIn('os.getenv("SUPABASE_KEY")', contents, relative)

    def test_ticket_listener_uses_audited_review_and_one_time_link_flows(self):
        contents = (ROOT / "backend/ticket_listener.py").read_text(encoding="utf-8")
        self.assertIn('rpc("consume_telegram_link_token"', contents)
        self.assertIn('rpc("approve_spei_review"', contents)
        self.assertIn('rpc("reject_spei_review"', contents)
        self.assertIn("SUPABASE_ADMIN_USER_ID", contents)
        self.assertIn("supabase.auth.admin.list_users", contents)
        self.assertNotIn('.eq("email", target_email)', contents)
        verification = contents[contents.index("def verificar_usuario_vip"):contents.index("def procesar_solicitud_union")]
        self.assertNotIn('.eq("telegram_username"', verification)

    def test_results_recap_does_not_claim_an_unconditional_positive_day(self):
        contents = (ROOT / "backend/verificar_resultados.py").read_text(encoding="utf-8")
        self.assertNotIn("Jornada Positiva +EV", contents)

    def test_live_tracker_cannot_grade_or_finalize_picks(self):
        contents = (ROOT / "backend/live_tracker.py").read_text(encoding="utf-8")
        self.assertNotIn("resultado_apuesta", contents)
        self.assertNotIn("finalizado", contents)
        self.assertIn("allowed_ids", contents)

    def test_manual_join_approval_still_requires_an_active_membership(self):
        contents = (ROOT / "backend/ticket_listener.py").read_text(encoding="utf-8")
        command = contents[contents.index("elif texto.startswith('/aprobar '"):contents.index("elif texto.startswith('/expulsar '")]
        self.assertIn("verificar_usuario_vip", command)

    def test_stale_manual_dispatch_is_retired(self):
        contents = (ROOT / "backend/dispatch_picks_now.py").read_text(encoding="utf-8")
        self.assertIn("retirado", contents.lower())
        self.assertNotIn("picks_oficiales", contents)

    def test_scraper_refuses_to_publish_without_persisting_first(self):
        contents = (ROOT / "backend/scraper.py").read_text(encoding="utf-8")
        self.assertIn("require_publish_backend", contents)
        self.assertIn("Publicación cancelada", contents)

    def test_result_updates_use_a_pending_compare_and_set_without_legacy_fallback(self):
        contents = (ROOT / "backend/verificar_resultados.py").read_text(encoding="utf-8")
        update_block = contents[contents.index("for pick in picks_pendientes"):contents.index("print(f\"\\n{'='*60}\")")]
        self.assertIn('.eq("estado", "pendiente")', update_block)
        self.assertNotIn("legacy", update_block)

    def test_build_normalizes_deploy_artifact_line_endings(self):
        contents = (ROOT / "package.json").read_text(encoding="utf-8")
        build_script = json.loads(contents)["scripts"]["build"]
        self.assertIn("replace(/\\r\\n/g,'\\n')", build_script)
        self.assertIn("replace(/[ \\t]+$/gm,'')", build_script)


if __name__ == "__main__":
    unittest.main()
