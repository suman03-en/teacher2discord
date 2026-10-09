import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_shared_client = httpx.Client(timeout=60.0)


class Webhook:
    """Sends JSON payloads to a Discord webhook URL."""

    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url
        self.client = _shared_client

    def send_message(
        self, message: dict[str, Any], files: dict[str, Any] | None = None
    ) -> bool:
        """Posts a JSON message to the webhook. Returns True on success."""
        try:
            if files:
                data = {"payload_json": json.dumps(message)}
                response = self.client.post(self.url, data=data, files=files)
            else:
                response = self.client.post(self.url, json=message)

            if response.is_success:
                return True
            logger.warning(
                "Webhook '%s' returned %s: %s",
                self.name,
                response.status_code,
                response.text,
            )
            return False
        except httpx.HTTPError as e:
            logger.error("Failed to send webhook '%s': %s", self.name, e)
            return False

    def ping(self) -> bool:
        """Verifies if the webhook URL is valid and active via a GET request."""
        try:
            response = self.client.get(self.url, timeout=5.0)
            return response.is_success
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        """No-op since the client is shared."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @classmethod
    def from_url(cls, url: str, name: str = "unnamed") -> "Webhook":
        """Create a Webhook from a URL, optionally with a descriptive name."""
        return cls(name, url)
