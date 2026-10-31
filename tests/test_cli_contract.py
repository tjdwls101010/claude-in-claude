"""The command surface as the calling model reads it: the root map, each command's own help with what it prints and how it exits, argument errors as JSON with the help to read, and help text never re-wrapped."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from support.harness import ENTRY, Sandbox, build_parser

COMMANDS = ("start", "resume", "send", "batch", "status", "log", "result", "stop", "clean")


def run(*args):
    return subprocess.run([sys.executable, str(ENTRY), *args], capture_output=True, text=True, timeout=60)


def subcommand_help(name):
    return run(name, "--help").stdout


class Help(unittest.TestCase):
    def test_root_map_lists_the_commands_and_hides_the_supervisor(self):
        out = run("--help").stdout
        for name in COMMANDS:
            self.assertRegex(out, rf"\n\s+{name}\s+\S")
        self.assertNotIn("__supervise", out)
        self.assertIn("Exit codes: 0 success; 1", out)

    def test_each_command_says_what_it_prints_and_how_it_exits(self):
        for name in COMMANDS:
            with self.subTest(name):
                out = subcommand_help(name)
                self.assertIn("\nPrints: ", out)
                self.assertIn("\nExits: 0 ", out)
                self.assertTrue(out.startswith(f"usage: cli.py {name} "), out[:80])
                usage = out.split("\n\n", 1)[0]
                self.assertLessEqual(usage.count("\n"), 4, usage)

    def test_every_argument_has_help(self):
        import argparse

        parser = build_parser()
        subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        for name in COMMANDS:
            for action in subs.choices[name]._actions:
                if isinstance(action, argparse._HelpAction):
                    continue
                self.assertTrue(action.help, f"{name}: {action.dest} has no help")

    def test_paragraphs_are_not_rewrapped(self):
        out = subcommand_help("status")
        self.assertIn("\n  stalled      starting, running or finishing with no event for 600 s; advisory, nothing is killed — read `in_progress` beside it\n", out)
        start = subcommand_help("start")
        self.assertIn("  read-only  reads anything, and runs any shell command inside a sandbox that can write only its TMPDIR and ~/.cache", start)

    def test_closed_sets_are_choices(self):
        start = subcommand_help("start")
        self.assertIn("{read-only,write,auto}", start)
        self.assertIn("{low,medium,high,xhigh,max}", start)


class ArgumentErrors(unittest.TestCase):
    def check(self, args, help_name):
        proc = run(*args)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        reply = json.loads(proc.stdout)
        self.assertEqual(reply["help"], help_name)
        self.assertTrue(reply["error"])
        self.assertEqual(proc.stdout.count("\n"), 1)

    def test_unknown_command(self):
        self.check(["frobnicate"], "--help")

    def test_bad_choice_names_the_command_help(self):
        self.check(["start", "x", "--profile", "bypass"], "start --help")
        self.check(["start", "x", "--effort", "ultra"], "start --help")

    def test_missing_required(self):
        self.check(["log"], "log --help")
        self.check(["result"], "result --help")

    def test_bad_numbers(self):
        self.check(["start", "x", "--timeout", "-1"], "start --help")
        self.check(["result", "--run", "r", "--wait", "--wait-timeout", "abc"], "result --help")

    def test_no_command(self):
        self.check([], "--help")


class Entry(Sandbox):
    def test_pep723_header_and_python_floor(self):
        head = ENTRY.read_text().splitlines()[:4]
        self.assertEqual(head, ["# /// script", '# requires-python = ">=3.11"', "# dependencies = []", "# ///"])

    def test_runs_through_uv_from_another_directory(self):
        import shutil

        if not shutil.which("uv"):
            self.skipTest("uv not installed")
        proc = subprocess.run(["uv", "run", str(ENTRY), "status"], cwd=self.project, capture_output=True, text=True, env={**self.env, "PATH": self.env["PATH"] + ":" + str(__import__("pathlib").Path(shutil.which("uv")).parent)}, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["runs"], [])
