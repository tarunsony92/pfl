"""CLI for admin operations (Click-based, using typer dependency).

Usage:
    poetry run python -m app.cli seed-admin --email you@pfl.com [--password SECRET]

If no password is provided, one is generated and printed once.

Note: Uses Click directly due to a Typer 0.12.5 / Click 8.3 incompatibility
where TyperOption passes flag_value=None (instead of UNSET) to click.Option,
causing all string options to be misdetected as boolean flags.
"""

import asyncio
import secrets
import sys

import click

from app.db import AsyncSessionLocal
from app.enums import UserRole
from app.services import users as users_svc


@click.group()
def app() -> None:
    """PFL Credit AI admin CLI."""


@app.command("seed-admin")
@click.option("--email", required=True, help="Admin email")
@click.option("--full-name", default="Admin", show_default=True, help="Full name")
@click.option("--password", default=None, help="Password (random if omitted)")
def seed_admin(email: str, full_name: str, password: str | None) -> None:
    """Create the first admin user. Errors if email already exists."""
    pw = password or secrets.token_urlsafe(16)

    async def _run() -> None:
        async with AsyncSessionLocal() as session:
            try:
                user = await users_svc.create_user(
                    session,
                    email=email,
                    password=pw,
                    full_name=full_name,
                    role=UserRole.ADMIN,
                )
            except ValueError as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)
            await session.commit()
            click.echo(f"Admin created: id={user.id} email={user.email}")
            if password is None:
                click.echo(f"Generated password (save this now, not shown again): {pw}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
