import ssl as _ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from shared.config import settings

_db_url = settings.DATABASE_URL
if _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://")
    # Strip sslmode param (asyncpg uses ssl connect_arg instead)
    _db_url = _db_url.split("?sslmode=")[0] if "?sslmode=" in _db_url else _db_url

_connect_args = {}
if _db_url and "supabase" in _db_url:
    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE
    _connect_args = {"ssl": _ssl_ctx}

engine = create_async_engine(
    _db_url or "sqlite+aiosqlite:///./dev.db",
    echo=settings.LOG_LEVEL == "DEBUG",
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
) if _db_url else None

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
) if engine else None


async def get_db():
    if async_session is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL in .env")
    async with async_session() as session:
        yield session
