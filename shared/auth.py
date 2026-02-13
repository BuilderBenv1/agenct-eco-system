from fastapi import HTTPException, Header, Query
from shared.config import settings
from shared.contracts import subscription_manager


async def verify_api_key(x_api_key: str = Header(...)) -> bool:
    if x_api_key != settings.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


def check_subscription(wallet_address: str, plan_id: int) -> bool:
    """Check on-chain if wallet has active subscription to the given plan."""
    try:
        return subscription_manager.has_active_subscription(wallet_address, plan_id)
    except Exception:
        return False


def require_subscription(plan_id: int):
    """Dependency factory for FastAPI routes requiring subscription."""
    async def _check(wallet_address: str = Query(..., description="Subscriber wallet address")):
        if not check_subscription(wallet_address, plan_id):
            raise HTTPException(
                status_code=403,
                detail="No active subscription. Subscribe on-chain first.",
            )
        return wallet_address
    return _check
