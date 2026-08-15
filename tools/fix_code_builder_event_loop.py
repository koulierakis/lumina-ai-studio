from __future__ import annotations

from pathlib import Path

TARGET = Path.cwd() / "backend" / "code_builder" / "ollama_service.py"

old = '''        if client is None:\n            self._client = httpx.AsyncClient(\n                base_url=self.configuration.base_url,\n                timeout=self.configuration.timeouts.to_httpx_timeout(),\n                verify=self.configuration.verify_tls,\n                follow_redirects=(\n                    self.configuration.follow_redirects\n                ),\n                headers={\n                    "Accept": "application/json",\n                    "Content-Type": "application/json",\n                    "User-Agent": self.configuration.user_agent,\n                },\n                limits=httpx.Limits(\n                    max_connections=20,\n                    max_keepalive_connections=10,\n                    keepalive_expiry=30.0,\n                ),\n                trust_env=False,\n            )\n        else:\n            self._client = client\n'''

new = '''        self._client_loop: asyncio.AbstractEventLoop | None = None\n\n        if client is None:\n            self._client = self._build_client()\n        else:\n            self._client = client\n\n    def _build_client(self) -> httpx.AsyncClient:\n        """Build an AsyncClient owned by the currently active event loop."""\n        return httpx.AsyncClient(\n            base_url=self.configuration.base_url,\n            timeout=self.configuration.timeouts.to_httpx_timeout(),\n            verify=self.configuration.verify_tls,\n            follow_redirects=self.configuration.follow_redirects,\n            headers={\n                "Accept": "application/json",\n                "Content-Type": "application/json",\n                "User-Agent": self.configuration.user_agent,\n            },\n            limits=httpx.Limits(\n                max_connections=20,\n                max_keepalive_connections=10,\n                keepalive_expiry=30.0,\n            ),\n            trust_env=False,\n        )\n\n    async def _client_for_current_loop(self) -> httpx.AsyncClient:\n        """Return a client bound to this loop, replacing stale pooled clients."""\n        current_loop = asyncio.get_running_loop()\n\n        if not self._owns_client:\n            return self._client\n\n        if self._client_loop is current_loop and not self._client.is_closed:\n            return self._client\n\n        previous_client = self._client\n        previous_loop = self._client_loop\n        self._client = self._build_client()\n        self._client_loop = current_loop\n\n        if previous_loop is current_loop and not previous_client.is_closed:\n            await previous_client.aclose()\n\n        return self._client\n'''

request_old = '''                response = await self._client.request(\n                    method=method,\n'''
request_new = '''                client = await self._client_for_current_loop()\n                response = await client.request(\n                    method=method,\n'''

close_old = '''        if self._owns_client:\n            await self._client.aclose()\n'''
close_new = '''        if self._owns_client and not self._client.is_closed:\n            current_loop = asyncio.get_running_loop()\n            if self._client_loop is None or self._client_loop is current_loop:\n                await self._client.aclose()\n'''

if not TARGET.is_file():
    raise SystemExit(f"Target not found: {TARGET}")

text = TARGET.read_text(encoding="utf-8")
for before, after, label in (
    (old, new, "client construction"),
    (request_old, request_new, "request client selection"),
    (close_old, close_new, "client close"),
):
    count = text.count(before)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block, found {count}; refusing unsafe patch")
    text = text.replace(before, after, 1)

TARGET.write_text(text, encoding="utf-8")
print(f"Patched {TARGET}")
