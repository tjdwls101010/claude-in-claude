"""SKILL.md against the code it points at: its frontmatter, the invocation its pre-approval matches, and every command, flag and reply field it names existing in the CLI's own help."""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
import unittest

from support.harness import ENTRY, SKILL_DIR, Sandbox

SKILL_MD = SKILL_DIR / "SKILL.md"
COMMANDS = ("start", "resume", "send", "batch", "status", "log", "result", "stop", "clean", "doctor")


def frontmatter():
    text = SKILL_MD.read_text()
    head = text.split("\n---\n", 1)[0].removeprefix("---\n")
    out = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"')
    return out, text


def all_help():
    texts = [subprocess.run([sys.executable, str(ENTRY), "--help"], capture_output=True, text=True).stdout]
    for c in COMMANDS:
        texts.append(subprocess.run([sys.executable, str(ENTRY), c, "--help"], capture_output=True, text=True).stdout)
    return "\n".join(texts)


class Frontmatter(unittest.TestCase):
    def test_name_description_and_pre_approval(self):
        fm, _ = frontmatter()
        self.assertEqual(fm["name"], "claude")
        self.assertLessEqual(len(fm["description"]), 1024)
        self.assertIn("클로드", fm["description"])
        self.assertNotIn("codex", fm["description"].lower())
        self.assertEqual(fm["allowed-tools"], 'Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)')

    def test_body_names_no_other_delegation_tool(self):
        _, text = frontmatter()
        self.assertNotIn("codex", text.lower())


class NamedThingsExist(unittest.TestCase):
    def test_commands_flags_and_fields_are_in_the_help(self):
        _, text = frontmatter()
        help_text = all_help()
        body = text.split("\n---\n", 1)[1]
        # Flags in a span that runs claude itself (`claude --resume …`) are Claude Code's, not this CLI's.
        spans = [c for c in re.findall(r"`([^`]+)`", body) if not c.startswith("claude ")]
        flags = {f for c in spans for f in re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", c)}
        self.assertTrue(flags, "SKILL.md names no flag at all")
        missing = sorted(f for f in flags if f not in help_text)
        self.assertEqual(missing, [], "SKILL.md names flags no --help mentions")
        for code in re.findall(r"`([^`]+)`", body):
            word = code.split()[0]
            if word in COMMANDS:
                self.assertTrue(f"\n    {word} " in help_text, f"SKILL.md names command {word}")
        fields = ("next.command", "profile_exceptions", "permission_denials", "files_edited", "attention", "quota", "mode_mismatch", "stderr_tail", "session_id")
        for field in fields:
            if f"`{field}`" in body or f"`{field}`" in body.replace("next.command", "next"):
                self.assertTrue(field.split(".")[0] in help_text, f"SKILL.md names reply field {field}")


class Invocation(Sandbox):
    def test_printed_commands_match_the_pre_approval(self):
        fm, _ = frontmatter()
        pattern = fm["allowed-tools"].removeprefix("Bash(").removesuffix(")").replace("${CLAUDE_SKILL_DIR}", str(SKILL_DIR))
        reply = self.start("x")
        self.wait_state(reply["run_id"])
        command = reply["next"]["command"]
        self.assertTrue(fnmatch.fnmatchcase(command, pattern), f"{command!r} does not match {pattern!r}")
        self.assertNotIn("\n", command)
        _, text = frontmatter()
        self.assertIn('uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command>', text)


if __name__ == "__main__":
    unittest.main()
