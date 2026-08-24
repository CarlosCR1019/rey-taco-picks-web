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
    def test_runbook_documents_baseline_persisted_retry_and_no_live_parlay_claim(self):
        runbook = " ".join(
            (ROOT / "docs/operations/security-and-payments.md")
            .read_text(encoding="utf-8")
            .lower()
            .split()
        )

        self.assertIn("20260820210000_base_profiles_picks.sql", runbook)
        self.assertIn("filas ya persistidas", runbook)
        self.assertIn("no publica parlays en producción", runbook)
        self.assertIn("cuota independiente", runbook)
        self.assertIn("seis campos de auditoría", runbook)
        self.assertIn("source_starts_at", runbook)
        self.assertIn("instante absoluto utc", runbook)
        self.assertNotIn(
            "same-day parlays assembled only from individually verified legs",
            runbook,
        )

    def test_runbook_documents_pre_scrape_resume_and_inactive_fail_closed(self):
        runbook = " ".join(
            (ROOT / "docs/operations/security-and-payments.md")
            .read_text(encoding="utf-8")
            .lower()
            .split()
        )

        self.assertIn("antes de abrir chrome o consultar fuentes", runbook)
        self.assertIn("corrida completada y activa", runbook)
        self.assertIn("solo las entregas faltantes", runbook)
        self.assertIn("inactivo o reemplazado", runbook)
        self.assertIn("sin restaurar el archivo público ni telegram", runbook)
        self.assertIn("source_starts_at` es menor o igual al reloj utc", runbook)
        self.assertIn("--collect-only", runbook)
        self.assertIn("sin archivo publico, telegram o meta", runbook)
        self.assertIn("--deliver-only", runbook)
        self.assertIn("supuesto operativo de escritor único", runbook)
        self.assertIn("no debe solaparse", runbook)

    def test_tracked_public_fallback_is_empty_and_cannot_leak_pick_details(self):
        for relative in ("frontend/public/picks.json", "dist/picks.json"):
            with self.subTest(relative=relative):
                rows = json.loads((ROOT / relative).read_text(encoding="utf-8"))

                self.assertIsInstance(rows, list)
                for row in rows:
                    self.assertNotIn("razonamiento", row)
                    self.assertEqual(row.get("visibility"), "public")
                    self.assertIs(row.get("es_parlay"), False)
                self.assertEqual(
                    rows,
                    [],
                    f"{relative} must never ship a stale pending pick",
                )

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

    def test_ticket_listener_builds_the_get_updates_endpoint_as_literal_text(self):
        contents = (ROOT / "backend/ticket_listener.py").read_text(encoding="utf-8")

        self.assertIn('/getUpdates?offset=', contents)
        self.assertNotIn('{getUpdates}', contents)

    def test_results_recap_does_not_claim_an_unconditional_positive_day(self):
        contents = (ROOT / "backend/verificar_resultados.py").read_text(encoding="utf-8")
        self.assertNotIn("Jornada Positiva +EV", contents)

    def test_social_consumers_do_not_claim_unconditional_positive_value(self):
        for relative in (
            "backend/render_html_banner.py",
            "backend/banner_template.html",
            "backend/social_banner.py",
            "backend/social_background.py",
            "backend/social_poster.py",
            "send_telegram_status_report.py",
        ):
            with self.subTest(relative=relative):
                contents = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("+EV", contents)
        social_banner = (ROOT / "backend/social_banner.py").read_text(
            encoding="utf-8"
        )
        render_banner = (ROOT / "backend/render_html_banner.py").read_text(
            encoding="utf-8"
        )
        social_background = (
            ROOT / "backend/social_background.py"
        ).read_text(encoding="utf-8")
        self.assertFalse((ROOT / "backend/temp_banner.html").exists())
        self.assertIn("SocialContent", social_banner)
        self.assertIn("render_social_jpeg", social_banner)
        self.assertNotIn(" Confianza", social_banner)
        for contents in (social_banner, render_banner, social_background):
            self.assertNotIn("image.pollinations.ai", contents)
            self.assertNotIn("urllib.request", contents)
            self.assertNotIn("picks.json", contents)

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
