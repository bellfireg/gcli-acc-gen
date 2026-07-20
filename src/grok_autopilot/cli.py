"""
Grok Autopilot — CLI Entry Point
==================================
Usage:
    grok-autopilot -n 3
    python -m grok_autopilot -n 1 --headless
"""

import argparse
import asyncio
import sys

from .register import run
from .utils.logger import log, set_log_file


def main() -> int:
    p = argparse.ArgumentParser(
        prog="grok-autopilot",
        description="Automated Grok (accounts.x.ai) account registration",
    )
    p.add_argument("-n", "--count", type=int, default=1, help="Number of accounts to create")
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (default: visible — useful for debugging)",
    )
    p.add_argument(
        "--mail",
        default="mailtm",
        choices=["mailtm", "cloudflare", "moca"],
        help="Temp mail provider (default: mailtm)",
    )
    p.add_argument(
        "--out",
        default="./accounts",
        help="Output directory for accounts.json",
    )
    p.add_argument(
        "--register-9router",
        action="store_true",
        help="After creating accounts, register each to 9Router grok-cli (E2E pipeline)",
    )
    p.add_argument("--log-file", default=None, help="Write logs to file")
    args = p.parse_args()

    if args.log_file:
        set_log_file(args.log_file)

    log(f"Grok Autopilot — {args.count} account(s) via {args.mail}")
    accounts = asyncio.run(
        run(
            n=args.count,
            headless=args.headless,
            out_dir=args.out,
            mail_provider=args.mail,
        )
    )

    ok = sum(1 for a in accounts if a.status in ("verified", "password_set"))
    log(f"\n{'='*60}")
    log(f"SIGNUP DONE: {ok}/{args.count} accounts created")

    # E2E: register each successful account to 9Router
    if args.register_9router and ok > 0:
        log(f"\n{'='*60}")
        log(f"9ROUTER REGISTRATION PHASE")
        try:
            from .ninerouter_grok import (
                ninerouter_login,
                register_account_to_ninerouter,
            )
            import os as _os
            from dataclasses import asdict as _asdict
            nr = ninerouter_login()
            nr_ok = 0
            for i, acct in enumerate(accounts, 1):
                if acct.status not in ("verified", "password_set", "partial"):
                    continue
                log(f"\n[9Router {i}/{ok}]")
                try:
                    # Pass full account dict (includes session_cookies)
                    acct_dict = _asdict(acct) if hasattr(acct, "__dataclass_fields__") else acct
                    if asyncio.run(register_account_to_ninerouter(
                        acct_dict,
                        nr=nr,
                        headless=args.headless,
                        mailbox_secret=_os.environ.get("CF_MAILBOX_SECRET"),
                        worker_url=_os.environ.get("WORKER_URL") or None,
                    )):
                        nr_ok += 1
                except Exception as e:
                    from .utils.logger import log_err as _le
                    _le(f"   ❌ 9Router failed for {acct.email}: {e}")
            log(f"\n9ROUTER DONE: {nr_ok}/{ok} accounts registered")
            ok = nr_ok
        except Exception as e:
            from .utils.logger import log_err as _le
            _le(f"9Router phase failed: {e}")

    for a in accounts:
        log(f"  - {a.email} [{a.status}]")
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
