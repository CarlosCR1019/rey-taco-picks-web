import json
from pathlib import Path
import unittest
from urllib.error import URLError

from backend.telegram_publisher import (
    DeliveryResult,
    TelegramDestination,
    TelegramHttpTransport,
    chunk_messages,
    deliver_batch,
)


def pick(**overrides):
    row = {
        "partido": "Lobos vs Tigres",
        "horario": "2026-08-21 20:00",
        "pick": "Lobos +0.5",
        "cuota": "+110",
        "confianza": "72%",
        "razonamiento": "La línea ofrece valor según la forma reciente.",
        "visibility": "premium",
    }
    row.update(overrides)
    return row


class FakeTransport:
    def __init__(self, failing_names=()):
        self.calls = []
        self.failing_names = set(failing_names)

    def __call__(self, destination, text):
        self.calls.append((destination, text))
        if destination.name in self.failing_names:
            raise ConnectionError("unavailable")


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


class TelegramPublisherTests(unittest.TestCase):
    def test_chunks_are_bounded_and_overlong_rationale_is_truncated_as_one_block(self):
        huge_reason = "x" * 9_000
        messages = chunk_messages([pick(razonamiento=huge_reason), pick(partido="Pumas vs Atlas")])

        self.assertTrue(messages)
        self.assertTrue(all(len(message) <= 4_000 for message in messages))
        self.assertTrue(any("Evento: Lobos vs Tigres" in message and "Pick: Lobos +0.5" in message for message in messages))
        self.assertTrue(any("Evento: Pumas vs Atlas" in message and "Pick: Lobos +0.5" in message for message in messages))
        joined = "\n".join(messages)
        self.assertIn("Evento: Lobos vs Tigres", joined)
        self.assertIn("Pick: Lobos +0.5", joined)
        self.assertRegex(joined, r"Rationale: x{20,}\u2026\nNota:")
        self.assertNotIn("x" * 4_001, joined)
        self.assertNotIn("Rationale: No especificada", joined)
        self.assertIn("Evento: Pumas vs Atlas", joined)
        self.assertIn("Pick: Lobos +0.5", joined)

    def test_public_destination_receives_only_public_payload_while_all_destinations_receive_full_batch(self):
        public = pick(pick="PUBLIC PICK", visibility="public", razonamiento="Visible rationale")
        premium = pick(pick="PREMIUM SECRET", visibility="premium", razonamiento="Private rationale")
        transport = FakeTransport()
        destinations = [
            TelegramDestination("free", "free-id", "public"),
            TelegramDestination("vip", "vip-id", "all"),
            TelegramDestination("admin", "admin-id", "all"),
        ]

        results = deliver_batch([public, premium], destinations, transport)

        by_name = {destination.name: text for destination, text in transport.calls}
        self.assertIn("PUBLIC PICK", by_name["free"])
        self.assertNotIn("PREMIUM SECRET", by_name["free"])
        self.assertNotIn("Private rationale", by_name["free"])
        self.assertNotIn("Visible rationale", by_name["free"])
        self.assertNotIn("Rationale:", by_name["free"])
        self.assertIn("PUBLIC PICK", by_name["vip"])
        self.assertIn("PREMIUM SECRET", by_name["vip"])
        self.assertIn("Visible rationale", by_name["vip"])
        self.assertIn("Rationale:", by_name["vip"])
        self.assertIn("PREMIUM SECRET", by_name["admin"])
        self.assertIn("Visible rationale", by_name["admin"])
        self.assertIn("Rationale:", by_name["admin"])
        self.assertEqual(results["free"], DeliveryResult(success=True, message_count=1))

    def test_destination_failure_is_isolated_from_other_destinations(self):
        transport = FakeTransport(failing_names={"admin"})
        destinations = [
            TelegramDestination("admin", "admin-id", "all"),
            TelegramDestination("vip", "vip-id", "all"),
            TelegramDestination("free", "free-id", "public"),
        ]

        results = deliver_batch([pick(visibility="public")], destinations, transport)

        self.assertFalse(results["admin"].success)
        self.assertEqual(results["admin"].error, "delivery_failed")
        self.assertTrue(results["vip"].success)
        self.assertTrue(results["free"].success)
        self.assertEqual([destination.name for destination, _ in transport.calls], ["admin", "vip", "free"])

    def test_delivery_error_is_fixed_and_does_not_leak_a_malicious_exception_name(self):
        marker = "ATTACKER_MARKER_" + "X" * 200
        malicious_error = type(marker, (Exception,), {})

        def malicious_transport(destination, text):
            raise malicious_error()

        result = deliver_batch(
            [pick()],
            [TelegramDestination("admin", "admin-id", "all")],
            malicious_transport,
        )["admin"]

        self.assertFalse(result.success)
        self.assertEqual(result.error, "delivery_failed")
        self.assertLessEqual(len(result.error), 32)
        self.assertNotIn(marker, result.error)

    def test_completed_destination_is_skipped_without_transport_call(self):
        transport = FakeTransport()
        destination = TelegramDestination("vip", "vip-id", "all")

        results = deliver_batch([pick()], [destination], transport, completed=frozenset({"vip"}))

        self.assertEqual(results["vip"], DeliveryResult(success=True, skipped=True))
        self.assertEqual(transport.calls, [])

    def test_empty_public_payload_skips_cleanly(self):
        transport = FakeTransport()
        destination = TelegramDestination("free", "free-id", "public")

        results = deliver_batch([pick(visibility="premium")], [destination], transport)

        self.assertEqual(results["free"], DeliveryResult(success=True, skipped=True))
        self.assertEqual(transport.calls, [])

    def test_http_transport_uses_timeout_and_bounded_backoff_before_success(self):
        attempts = []
        sleeps = []

        def urlopen(request, timeout):
            attempts.append((request, timeout))
            if len(attempts) < 3:
                raise URLError("temporary")
            return FakeResponse()

        transport = TelegramHttpTransport("token-not-to-log", retries=2, sleep=sleeps.append, urlopen=urlopen)
        transport(TelegramDestination("free", "free-id", "public"), "hello")

        self.assertEqual(len(attempts), 3)
        self.assertEqual([timeout for _, timeout in attempts], [10, 10, 10])
        self.assertEqual(sleeps, [1, 2])
        payload = json.loads(attempts[0][0].data.decode("utf-8"))
        self.assertEqual(payload, {"chat_id": "free-id", "text": "hello", "disable_web_page_preview": True})
        self.assertEqual(attempts[0][0].headers["Content-type"], "application/json")

    def test_http_transport_sanitizes_permanent_failures_and_validates_inputs(self):
        def urlopen(*unused, **kwargs):
            raise URLError("https://api.telegram.org/botsecret-token/sendMessage")

        with self.assertRaisesRegex(RuntimeError, "URLError") as caught:
            TelegramHttpTransport("secret-token", retries=1, urlopen=urlopen)(
                TelegramDestination("free", "free-id", "public"), "hello"
            )

        self.assertNotIn("secret-token", str(caught.exception))
        with self.assertRaises(ValueError):
            TelegramHttpTransport("")
        with self.assertRaises(ValueError):
            TelegramDestination("unknown", "id", "all")
        with self.assertRaises(ValueError):
            TelegramDestination("free", "", "public")
        with self.assertRaises(ValueError):
            TelegramDestination("free", "id", "unknown")

    def test_http_transport_rejects_an_empty_200_response(self):
        transport = TelegramHttpTransport("token", retries=0, urlopen=lambda *unused, **kwargs: FakeResponse(body=b""))

        with self.assertRaisesRegex(RuntimeError, "RuntimeError"):
            transport(TelegramDestination("free", "free-id", "public"), "hello")

    def test_http_transport_rejects_malformed_or_not_ok_200_response(self):
        for body in (b"not-json", b'{"ok": false}'):
            with self.subTest(body=body):
                transport = TelegramHttpTransport(
                    "token", retries=0, urlopen=lambda *unused, **kwargs: FakeResponse(body=body)
                )
                with self.assertRaisesRegex(RuntimeError, "RuntimeError"):
                    transport(TelegramDestination("free", "free-id", "public"), "hello")

    def test_publisher_source_does_not_queue_future_free_or_premium_messages(self):
        source = (Path(__file__).resolve().parents[1] / "backend" / "telegram_publisher.py").read_text(encoding="utf-8").lower()

        self.assertNotIn("channel_queue", source)
        self.assertNotIn("timestamp_programado", source)
        self.assertNotIn("schedule_future", source)


if __name__ == "__main__":
    unittest.main()
