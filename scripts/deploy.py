"""
Deploy helper — verifies all agents are importable and DB is reachable
before deploying to production. Run this locally to catch issues early.

Usage:
    python -m scripts.deploy --check
    python -m scripts.deploy --init-db
"""
import sys
import asyncio


def check_imports():
    """Verify all agent modules import cleanly."""
    print("Checking imports...")
    errors = []

    agents = [
        ("Convergence", "shared.convergence_main"),
        ("Tipster", "agents.tipster.main"),
        ("Whale", "agents.whale.main"),
        ("Narrative", "agents.narrative.main"),
        ("Auditor", "agents.auditor.main"),
        ("Liquidation", "agents.liquidation.main"),
        ("Yield Oracle", "agents.yield_oracle.main"),
        ("Gateway", "scripts.gateway"),
    ]

    for name, module_path in agents:
        try:
            __import__(module_path)
            print(f"  {name:20s} OK")
        except Exception as e:
            print(f"  {name:20s} FAILED: {e}")
            errors.append((name, str(e)))

    return errors


async def check_database():
    """Verify database connectivity."""
    print("\nChecking database...")
    try:
        from shared.database import async_session
        if async_session is None:
            print("  Database: NOT CONFIGURED (no DATABASE_URL)")
            return False

        from sqlalchemy import text
        async with async_session() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"))
            count = result.scalar()
            print(f"  Database: CONNECTED ({count} tables)")
            return True
    except Exception as e:
        print(f"  Database: FAILED ({e})")
        return False


async def check_blockchain():
    """Verify Avalanche RPC connectivity."""
    print("\nChecking blockchain...")
    try:
        from shared.web3_client import w3
        block = w3.eth.block_number
        print(f"  Avalanche: CONNECTED (block {block:,})")
        return True
    except Exception as e:
        print(f"  Avalanche: FAILED ({e})")
        return False


def check_env():
    """Check critical environment variables."""
    print("\nChecking environment...")
    from shared.config import settings

    checks = {
        "DATABASE_URL": bool(settings.DATABASE_URL),
        "ANTHROPIC_API_KEY": bool(settings.ANTHROPIC_API_KEY),
        "ORACLE_PRIVATE_KEY": bool(settings.ORACLE_PRIVATE_KEY),
        "TELEGRAM_BOT_TOKEN": bool(settings.TELEGRAM_BOT_TOKEN),
        "API_SECRET_KEY": settings.API_SECRET_KEY != "dev-secret-key",
    }

    all_ok = True
    for name, ok in checks.items():
        status = "SET" if ok else "MISSING"
        print(f"  {name:25s} {status}")
        if not ok:
            all_ok = False

    return all_ok


async def main():
    print("=" * 50)
    print("AgentProof Deployment Check")
    print("=" * 50)

    errors = check_imports()
    env_ok = check_env()
    db_ok = await check_database()
    chain_ok = await check_blockchain()

    print("\n" + "=" * 50)
    print("RESULTS:")
    print(f"  Imports:    {'PASS' if not errors else f'FAIL ({len(errors)} errors)'}")
    print(f"  Env vars:   {'PASS' if env_ok else 'FAIL'}")
    print(f"  Database:   {'PASS' if db_ok else 'FAIL'}")
    print(f"  Blockchain: {'PASS' if chain_ok else 'FAIL'}")

    if errors or not env_ok:
        print("\nFix issues before deploying.")
        sys.exit(1)
    else:
        print("\nReady to deploy!")
        print("\nTo deploy on Railway:")
        print("  1. Push code to GitHub")
        print("  2. railway login && railway init")
        print("  3. Set env vars: railway variables set KEY=VALUE")
        print("  4. railway up")
        print("\nOr deploy with Docker:")
        print("  docker build -t agentproof .")
        print("  docker run -p 8080:8080 --env-file .env -e SERVICE=gateway agentproof")


if __name__ == "__main__":
    if "--init-db" in sys.argv:
        from scripts.init_db import init_database
        asyncio.run(init_database())
    else:
        asyncio.run(main())
