convergence: uvicorn shared.convergence_main:app --host 0.0.0.0 --port ${PORT:-8000}
tipster: uvicorn agents.tipster.main:app --host 0.0.0.0 --port ${PORT:-8001}
whale: uvicorn agents.whale.main:app --host 0.0.0.0 --port ${PORT:-8002}
narrative: uvicorn agents.narrative.main:app --host 0.0.0.0 --port ${PORT:-8003}
auditor: uvicorn agents.auditor.main:app --host 0.0.0.0 --port ${PORT:-8004}
liquidation: uvicorn agents.liquidation.main:app --host 0.0.0.0 --port ${PORT:-8005}
yield_oracle: uvicorn agents.yield_oracle.main:app --host 0.0.0.0 --port ${PORT:-8006}
bot: python -m bot.main
