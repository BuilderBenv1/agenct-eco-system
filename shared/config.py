from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    DATABASE_URL: str = ""

    # Blockchain
    AVALANCHE_RPC_URL: str = "https://api.avax.network/ext/bc/C/rpc"
    CHAIN_ID: int = 43114
    ORACLE_PRIVATE_KEY: str = ""

    # Contract addresses (deployed Phase 1)
    AGENT_NFT_ADDRESS: str = "0x5690E91C7F1c350Ad0A233850E1cA50929f58314"
    AGENT_REGISTRY_ADDRESS: str = "0x887eA44bC7f39D9892d69762b43d68b9579127d5"
    ESCROW_ADDRESS: str = "0xb12cb6eE75E7Ba75C8B35C85Aa2533aa735EC5fb"
    SUBSCRIPTION_MANAGER_ADDRESS: str = "0x52Fd16FA8d676351c7FEEf7564968D3bD58126a3"
    AGENT_PROOF_ORACLE_ADDRESS: str = "0x1Ad40004c96F0C0c20f881b084807EEc6D2E5BF2"

    # ERC-8004 Agent IDs
    TIPSTER_ERC8004_ID: int = 1633
    NARRATIVE_ERC8004_ID: int = 1634
    WHALE_ERC8004_ID: int = 1635

    # TBA addresses
    TIPSTER_TBA: str = "0x9048F022ef0278473067b8E0a46670ba6cF56095"
    NARRATIVE_TBA: str = "0x55e17721f86AF9718C912787062E6820beaebf20"
    WHALE_TBA: str = "0x2FF63F41cD1B27949e51f2ec844323F2bc532d80"

    # APIs
    ANTHROPIC_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    COINGECKO_API_URL: str = "https://api.coingecko.com/api/v3"

    # Clawntenna
    CLAWNTENNA_CHAIN: str = "avalanche"
    CLAWNTENNA_TIPSTER_TOPIC: str = ""
    CLAWNTENNA_WHALE_TOPIC: str = ""
    CLAWNTENNA_NARRATIVE_TOPIC: str = ""

    # Auditor
    AUDITOR_ERC8004_ID: int = 0  # Set after minting auditor NFT
    AUDITOR_TBA: str = ""

    # Liquidation Sentinel
    LIQUIDATION_ERC8004_ID: int = 0
    LIQUIDATION_TBA: str = ""

    # Yield Oracle
    YIELD_ORACLE_ERC8004_ID: int = 0
    YIELD_ORACLE_TBA: str = ""

    # Convergence
    CONVERGENCE_ERC8004_ID: int = 0  # Set after minting convergence NFT
    CONVERGENCE_TBA: str = ""
    CONVERGENCE_WINDOW_HOURS: int = 24
    CONVERGENCE_CHECK_INTERVAL: int = 3600  # 1 hour

    # Agent Lightning
    LIGHTNING_ENABLED: bool = True
    LIGHTNING_STORE_TYPE: str = "local"  # 'local' or 'mongo'
    LIGHTNING_MONGO_URI: str = ""

    # Application
    API_SECRET_KEY: str = "dev-secret-key"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    REDIS_URL: str = "redis://localhost:6379/0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
