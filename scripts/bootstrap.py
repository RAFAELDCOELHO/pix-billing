"""Bootstrap a local API key for development."""
import asyncio

from src.api.auth import bootstrap_api_key
from src.billing.db import init_db


async def main() -> None:
    await init_db()
    key = await bootstrap_api_key("local")
    print(f"\n✓ API key created: {key}\n")
    print("Add to your requests: Authorization: Bearer <key>")


asyncio.run(main())
