"""Regression protection for capabilities already published on GitHub."""

from typer.main import get_command

from sqlgraph.cli import app


def test_public_cli_keeps_existing_github_commands():
    commands = get_command(app).commands

    for command in (
        "build",
        "stats",
        "analyze",
        "profile",
        "serve",
        "playground",
        "demo",
    ):
        assert command in commands
