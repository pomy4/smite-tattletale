import datetime
import hashlib
import os
import time

import requests
import urllib3.exceptions

requests.packages.urllib3.disable_warnings(
    category=urllib3.exceptions.InsecureRequestWarning
)


class Api:
    base_url = "https://api.smitegame.com/smiteapi.svc"

    def __init__(
        self,
        dev_id: str = os.getenv("SMITE_DEV_ID"),
        auth_key: str = os.getenv("SMITE_AUTH_KEY"),
        delay: datetime.timedelta | None = datetime.timedelta(milliseconds=100),
    ):
        self.dev_id = dev_id
        self.auth_key = auth_key
        self.delay = delay
        self.last: datetime.datetime | None = None
        self.session: str | None = None
        assert self.dev_id and self.auth_key

    @staticmethod
    def ping():
        return requests.get(f"{Api.base_url}/pingjson")

    def create_signature(self, method_name: str, timestamp: str):
        return hashlib.md5(
            f"{self.dev_id}{method_name}{self.auth_key}{timestamp}".encode("utf8")
        ).hexdigest()

    def _call_method(self, method_name: str, *args):
        now = datetime.datetime.now(datetime.timezone.utc)
        if self.delay is not None:
            if self.last is None or self.last + self.delay <= now:
                self.last = now
            else:
                self.last += self.delay
                to_sleep = self.last + self.delay - now
                time.sleep(to_sleep.total_seconds())

        timestamp = now.strftime("%Y%m%d%H%M%S")
        signature = self.create_signature(method_name, timestamp)
        url = (
            f"{self.base_url}/{method_name}json/{self.dev_id}/{signature}/"
            + (f"{self.session}/" if self.session else "")
            + timestamp
        )
        for arg in args:
            url += f"/{arg}"
        return requests.get(url, verify=False)  # TODO parameter (in __init__?)

    def create_session(self):
        self.session = self._call_method("createsession").json()["session_id"]

    def call_method(self, *args):
        if self.session is None:
            self.create_session()
        return self._call_method(*args)
