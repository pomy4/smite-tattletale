import asyncio
import datetime
import hashlib
import os

import aiohttp


class Api:
    base_url = "https://api.smitegame.com/smiteapi.svc"

    def __init__(
        self,
        dev_id: str = os.getenv("SMITE_DEV_ID"),
        auth_key: str = os.getenv("SMITE_AUTH_KEY"),
        delay: datetime.timedelta | None = datetime.timedelta(milliseconds=100),
        verify: bool = False,
        session: aiohttp.ClientSession | None = None,
    ):
        self.dev_id = dev_id
        self.auth_key = auth_key
        self.delay = delay
        self.verify = verify
        self.session = session
        self.last: datetime.datetime | None = None
        self.session_id: str | None = None
        self.lock = asyncio.Lock()
        assert self.dev_id and self.auth_key

    async def __aenter__(self):
        assert self.session is None
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    async def ping(self):
        async with self.session.get(f"{Api.base_url}/pingjson") as resp:
            resp.raise_for_status()
            return await resp.text()

    def create_signature(self, method_name: str, timestamp: str):
        return hashlib.md5(
            f"{self.dev_id}{method_name}{self.auth_key}{timestamp}".encode("utf8")
        ).hexdigest()

    async def _call_method(self, method_name: str, *args):
        now = datetime.datetime.now(datetime.timezone.utc)
        if self.delay is not None:
            if self.last is None or self.last + self.delay <= now:
                self.last = now
            else:
                self.last += self.delay
                to_sleep = self.last + self.delay - now
                await asyncio.sleep(to_sleep.total_seconds())

        timestamp = now.strftime("%Y%m%d%H%M%S")
        signature = self.create_signature(method_name, timestamp)
        url = (
            f"{self.base_url}/{method_name}json/{self.dev_id}/{signature}/"
            + (f"{self.session_id}/" if self.session_id else "")
            + timestamp
        )
        for arg in args:
            url += f"/{arg}"

        async with self.session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def create_session(self):
        self.session_id = (await self._call_method("createsession"))["session_id"]

    async def call_method(self, *args):
        async with self.lock:
            if self.session_id is None:
                await self.create_session()
        return await self._call_method(*args)
