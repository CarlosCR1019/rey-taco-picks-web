from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
