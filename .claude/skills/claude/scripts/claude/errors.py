"""Refusal: the one error a command turns into an exit code."""

from __future__ import annotations


class Refusal(Exception):
    """A command that cannot go ahead. `arguments` says the command line itself must change (exit 2) rather than the state (exit 1); `fields` go into the JSON reply beside `error`, such as `instead`."""

    def __init__(self, error, /, *, arguments=False, **fields):
        super().__init__(error)
        self.message = error
        self.arguments = arguments
        self.fields = fields

    def reply(self):
        return {"error": self.message, **self.fields}
