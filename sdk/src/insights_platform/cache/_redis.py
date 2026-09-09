from typing import Self

import redis.asyncio

_TIMEOUT_S = 10


class RedisCache:
    name = "redis"

    def __init__(self, client: redis.asyncio.Redis) -> None:
        self.client = client

    @classmethod
    def from_url(cls, url: str) -> Self:
        return cls(
            redis.asyncio.Redis.from_url(
                url,
                socket_timeout=_TIMEOUT_S,
                socket_connect_timeout=_TIMEOUT_S,
                decode_responses=True,
            )
        )

    async def get(self, key: str) -> str | None:
        value = await self.client.get(key)
        return value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, *, ttl: int) -> None:
        await self.client.set(key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def aclose(self) -> None:
        await self.client.aclose()
