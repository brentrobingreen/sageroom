from __future__ import annotations
import os
from supabase import AsyncClient, acreate_client

_client: AsyncClient | None = None


async def get_supabase() -> AsyncClient:
    global _client
    if _client is None:
        _client = await acreate_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _client
