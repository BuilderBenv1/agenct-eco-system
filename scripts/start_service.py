"""
Service starter — reads SERVICE env var and starts the appropriate agent.
Used by Docker/Railway to run individual services or the unified gateway.
"""
import os
import sys
import uvicorn

SERVICE = os.environ.get("SERVICE", "gateway")
PORT = int(os.environ.get("PORT", 8080))

SERVICES = {
    "convergence": ("shared.convergence_main:app", 8000),
    "tipster": ("agents.tipster.main:app", 8001),
    "whale": ("agents.whale.main:app", 8002),
    "narrative": ("agents.narrative.main:app", 8003),
    "auditor": ("agents.auditor.main:app", 8004),
    "liquidation": ("agents.liquidation.main:app", 8005),
    "yield_oracle": ("agents.yield_oracle.main:app", 8006),
    "bot": None,  # Special case: not uvicorn
    "gateway": ("scripts.gateway:app", 8080),
}


def main():
    if SERVICE not in SERVICES:
        print(f"ERROR: Unknown service '{SERVICE}'. Options: {', '.join(SERVICES.keys())}")
        sys.exit(1)

    if SERVICE == "bot":
        print("Starting Telegram bot...")
        from bot.main import create_bot
        import asyncio
        bot = create_bot()
        asyncio.run(bot.run_polling())
        return

    app_path, default_port = SERVICES[SERVICE]
    port = PORT if PORT != 8080 else default_port

    print(f"Starting {SERVICE} on port {port}...")
    uvicorn.run(
        app_path,
        host="0.0.0.0",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
