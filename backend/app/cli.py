"""IGuard management CLI: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.database.session import session_scope
from app.models import User
from app.models.enums import RoleName
from app.services import auth_service


def cmd_create_admin(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password: ")
    if not args.password and password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return 2
    with session_scope() as db:
        if db.scalar(select(User).where(User.username == args.username)):
            print(f"User '{args.username}' already exists", file=sys.stderr)
            return 1
        auth_service.create_user(
            db,
            email=args.email,
            username=args.username,
            password=password,
            role=RoleName(args.role),
            full_name=args.full_name or "",
        )
    print(f"Created {args.role} user '{args.username}'")
    return 0


def cmd_seed(_: argparse.Namespace) -> int:
    from app.database.seed import seed_demo

    with session_scope() as db:
        report = seed_demo(db)
    for u in report["users"]:  # type: ignore[attr-defined]
        shown = u["password"] or "(value of IGUARD_SEED_PASSWORD)"
        print(f"demo user {u['username']}: {shown}")
    print(f"recovery policies: {report['recovery_policies']}")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    from app.recovery.policies import PolicyError, load_policy_files

    s = get_settings()
    problems: list[str] = []
    try:
        n = len(load_policy_files(s.recovery_policies_dir))
        print(f"recovery policies OK ({n} actions)")
    except PolicyError as exc:
        problems.append(str(exc))
    if s.recovery_adapter == "agent" and not s.recovery_agent_secret.get_secret_value():
        problems.append("recovery adapter 'agent' needs IGUARD_RECOVERY_AGENT_SECRET")
    if s.workers_enabled and s.is_production and not s.webhook_token.get_secret_value():
        print("note: IGUARD_WEBHOOK_TOKEN unset - Alertmanager webhook is disabled")
    if not s.telegram_configured:
        print("note: Telegram not configured - notifications will be recorded as SKIPPED")
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if not problems:
        print("configuration OK")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="iguard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--username", required=True)
    a.add_argument("--password", help="Avoid: visible in process list. Omit to be prompted.")
    a.add_argument("--full-name")
    a.add_argument("--role", default="ADMIN", choices=[r.value for r in RoleName])
    a.set_defaults(fn=cmd_create_admin)
    sub.add_parser("seed").set_defaults(fn=cmd_seed)
    sub.add_parser("validate-config").set_defaults(fn=cmd_validate)
    args = parser.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
