"""One nonblocking HA vocabulary snapshot shared by every Wyoming endpoint."""

import asyncio
import logging
import time
from contextlib import suppress

from .vocabulary import RecognitionContext

_LOGGER = logging.getLogger(__name__)


class HassNameCache:
    def __init__(self, hass, refresh_seconds: float = 60.0):
        self.hass = hass
        self.refresh_seconds = refresh_seconds
        self.context = RecognitionContext()
        self._attempted = None
        self._task = None
        self._failed = False
        self._closed = False

    def schedule_refresh(self):
        """Deduplicate concurrent requests; throttle failures as well as successes."""
        if self._closed or (self._task is not None and not self._task.done()):
            return
        now = time.monotonic()
        if self._attempted is not None and now - self._attempted < self.refresh_seconds:
            return
        self._attempted = now
        self._task = asyncio.create_task(self._refresh())

    async def _refresh(self):
        try:
            context = await self.hass.get_context()
        except Exception:
            # Do not log response bodies, exception text, credentials, URLs or vocabulary.
            if not self._failed:
                _LOGGER.warning("HA vocabulary refresh failed; retaining previous names")
            self._failed = True
            return
        if self._failed:
            _LOGGER.info("HA vocabulary refresh recovered")
        self._failed = False
        if context != self.context:
            self.context = context

    async def close(self):
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
