import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nworks_mail_mcp.state import MailStateStore


class MailStateStoreTest(unittest.TestCase):
    def test_missing_state_file_starts_without_last_uid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MailStateStore(Path(tmpdir) / "state.json")

            self.assertIsNone(store.get_last_uid("INBOX"))

    def test_updates_last_uid_per_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            store = MailStateStore(state_path)

            store.update_last_uid("INBOX", 123)
            store.update_last_uid("Sent", 7)

            reloaded = MailStateStore(state_path)
            self.assertEqual(reloaded.get_last_uid("INBOX"), 123)
            self.assertEqual(reloaded.get_last_uid("Sent"), 7)

            raw_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("updated_at", raw_state["folders"]["INBOX"])

    def test_updates_last_uid_with_uidvalidity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            store = MailStateStore(state_path)

            store.update_checkpoint("INBOX", last_uid=123, uidvalidity=777)

            reloaded = MailStateStore(state_path)
            self.assertEqual(reloaded.get_checkpoint("INBOX").last_uid, 123)
            self.assertEqual(reloaded.get_checkpoint("INBOX").uidvalidity, 777)

    def test_uses_env_state_path_when_no_path_is_passed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "env-state.json"

            with patch.dict(os.environ, {"NWORKS_STATE_PATH": str(state_path)}):
                store = MailStateStore()
                store.update_checkpoint("INBOX", last_uid=9, uidvalidity=10)

            self.assertTrue(state_path.exists())

    def test_corrupt_json_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            state_path.write_text("{not json", encoding="utf-8")
            store = MailStateStore(state_path)

            with self.assertRaisesRegex(RuntimeError, "Mail state file is not valid JSON"):
                store.get_last_uid("INBOX")


if __name__ == "__main__":
    unittest.main()
