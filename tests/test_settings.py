"""Which settings a run gets: a flag over the session's record over the skill's defaults, and a session the registry never saw needing a profile."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support.harness import engine

runs = engine("claude.runs")
Refusal = engine("claude.errors").Refusal

NONE = {"profile": None, "model": None, "effort": None, "schema": None}


class SettingsFor(unittest.TestCase):
    def test_defaults(self):
        s = runs.settings_for(dict(NONE))
        self.assertEqual((s["profile"], s["model"], s["effort"], s["schema_text"]), ("write", "sonnet", "high", None))
        self.assertEqual(s["changed"], {})

    def test_record_then_flag(self):
        record = {"profile": "read-only", "model": "haiku", "effort": "low", "schema_text": '{"type": "object"}'}
        s = runs.settings_for({**NONE, "resume": True}, record)
        self.assertEqual((s["profile"], s["model"], s["effort"], s["schema_text"]), ("read-only", "haiku", "low", '{"type": "object"}'))
        s = runs.settings_for({**NONE, "resume": True, "profile": "auto", "effort": "max"}, record)
        self.assertEqual((s["profile"], s["model"], s["effort"]), ("auto", "haiku", "max"))
        self.assertEqual(s["changed"], {"profile": "read-only", "effort": "low"})

    def test_unknown_session_needs_a_profile(self):
        with self.assertRaises(Refusal) as e:
            runs.settings_for({**NONE, "resume": True}, None)
        self.assertTrue(e.exception.arguments)
        s = runs.settings_for({**NONE, "resume": True, "profile": "read-only"}, None)
        self.assertEqual((s["profile"], s["model"]), ("read-only", "sonnet"))

    def test_schema_file(self):
        d = Path(tempfile.mkdtemp())
        (d / "s.json").write_text('{ "type" : "object" }')
        self.assertEqual(json.loads(runs.settings_for({**NONE, "schema": str(d / "s.json")})["schema_text"]), {"type": "object"})
        (d / "bad.json").write_text("not json")
        for path in (d / "bad.json", d / "missing.json"):
            with self.assertRaises(Refusal) as e:
                runs.settings_for({**NONE, "schema": str(path)})
            self.assertTrue(e.exception.arguments)


if __name__ == "__main__":
    unittest.main()
