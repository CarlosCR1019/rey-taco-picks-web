import unittest

from scripts.vip_miniapp_entry import ensure_entry, ENTRY_TEXT, MINI_APP_URL


class EntryTests(unittest.TestCase):
    def run_entry(self, *, publish=False, pinned=None, fail_send=False):
        calls = []
        chat = {"id": -100123, "type": "channel", "title": "VIP", "pinned_message": pinned}
        def api(method, payload):
            calls.append(method)
            if method == "getMe":
                return {"id": 12, "username": "ExampleBot"}
            if method == "getChat":
                return chat
            if method == "getChatMember":
                return {"status": "administrator", "can_post_messages": True, "can_edit_messages": True}
            if method == "getChatMenuButton":
                return {"type": "web_app", "web_app": {"url": MINI_APP_URL}}
            if method == "sendMessage":
                if fail_send:
                    raise RuntimeError("ambiguous delivery")
                chat["pinned_message"] = {"message_id": 42, "text": ENTRY_TEXT, "reply_markup": payload["reply_markup"]}
                return chat["pinned_message"]
            if method == "pinChatMessage":
                return True
            raise AssertionError(method)
        return calls, lambda: ensure_entry(api, "-100123", publish=publish)

    def test_preview_never_writes(self):
        calls, run = self.run_entry()
        self.assertEqual(run()["status"], "preview")
        self.assertNotIn("sendMessage", calls)
        self.assertNotIn("pinChatMessage", calls)

    def test_create_and_verify_pin(self):
        calls, run = self.run_entry(publish=True)
        self.assertEqual(run()["message_id"], 42)
        self.assertEqual(calls.count("sendMessage"), 1)
        self.assertEqual(calls[-1], "getChat")

    def test_existing_entry_is_not_resent(self):
        pinned = {"message_id": 42, "text": ENTRY_TEXT, "reply_markup": {"inline_keyboard": [[{"text": "Abrir bot y Mini App", "url": "https://t.me/ExampleBot"}]]}}
        calls, run = self.run_entry(publish=True, pinned=pinned)
        self.assertEqual(run()["status"], "already_pinned")
        self.assertNotIn("sendMessage", calls)

    def test_ambiguous_send_is_not_retried(self):
        calls, run = self.run_entry(publish=True, fail_send=True)
        with self.assertRaises(RuntimeError):
            run()
        self.assertEqual(calls.count("sendMessage"), 1)
        self.assertNotIn("pinChatMessage", calls)


if __name__ == "__main__":
    unittest.main()
