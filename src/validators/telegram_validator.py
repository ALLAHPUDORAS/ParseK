import asyncio
import logging
import re
import threading
from concurrent.futures import Future
from typing import List, Optional

from telethon import TelegramClient, errors

from src.config import TG_API_ENABLED, TG_API_HASH, TG_API_ID

logger = logging.getLogger("LeadPipeline.TelegramValidator")

_SESSION_NAME = "parsek_session"
_client: Optional[TelegramClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_init_lock = threading.Lock()


def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def _connect_client() -> TelegramClient:
    client = TelegramClient(_SESSION_NAME, TG_API_ID, TG_API_HASH)
    await client.connect()
    return client


def _ensure_telegram_client() -> None:
    global _client, _loop, _thread
    if not TG_API_ENABLED:
        return

    with _init_lock:
        if _client and _loop and _thread and _thread.is_alive():
            return

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=_run_event_loop, args=(loop,), daemon=True)
        thread.start()

        try:
            future = asyncio.run_coroutine_threadsafe(_connect_client(), loop)
            client = future.result(timeout=30)
        except Exception as exc:
            logger.warning("Failed to initialize Telegram client: %s", exc)
            loop.call_soon_threadsafe(loop.stop)
            raise

        _client = client
        _loop = loop
        _thread = thread


async def _shutdown_client_async() -> None:
    if _client and _client.is_connected():
        try:
            await _client.disconnect()
        except Exception as exc:
            logger.warning("Error disconnecting Telegram client: %s", exc)


def shutdown_telegram_client() -> None:
    global _loop, _thread
    if not _loop:
        return
    try:
        future = asyncio.run_coroutine_threadsafe(_shutdown_client_async(), _loop)
        future.result(timeout=30)
    except Exception as exc:
        logger.warning("Error shutting down Telegram client: %s", exc)
    finally:
        _loop.call_soon_threadsafe(_loop.stop)
        if _thread and _thread.is_alive():
            _thread.join(timeout=5)


def _run_coroutine(coro: asyncio.Future) -> any:
    if not _loop:
        raise RuntimeError("Telegram client event loop is not initialized.")
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=60)


class TelegramValidator:
    def __init__(self, timeout: float = 12.0, pacing_delay: float = 0.75):
        self.timeout = timeout
        self.pacing_delay = pacing_delay
        if TG_API_ENABLED:
            _ensure_telegram_client()

    @staticmethod
    def normalize_handles(handles: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for handle in handles or []:
            if not isinstance(handle, str):
                continue
            candidate = handle.strip().lstrip("@")
            if not candidate:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", candidate):
                continue
            value = f"@{candidate}"
            if value not in seen:
                normalized.append(value)
                seen.add(value)
        return normalized

    async def _is_handle_alive(self, client: TelegramClient, handle: str) -> Optional[bool]:
        username = handle.lstrip("@")
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if not client.is_connected():
                    logger.warning("[TELEGRAM] client disconnected, reconnecting before validating %s", handle)
                    await client.connect()

                await client.get_entity(username)
                logger.info("[TG VALID] %s -> OK", handle)
                return True
            except (errors.UsernameInvalidError, errors.UsernameNotOccupiedError, ValueError) as exc:
                logger.info("[TG DEAD] %s -> REMOVED (%s)", handle, exc.__class__.__name__)
                return False
            except errors.FloodWaitError as exc:
                delay = getattr(exc, "seconds", None) or getattr(exc, "wait", None) or 0
                if delay > 0:
                    logger.warning("[TELEGRAM] Flood wait: sleeping for %s seconds", delay)
                    await asyncio.sleep(delay + 1)
                    continue
                logger.warning("[TELEGRAM] Flood wait without delay for %s", handle)
                return False
            except (ConnectionError, OSError, errors.RpcCallFailError) as exc:
                logger.warning(
                    "[TELEGRAM] network/reconnect issue for %s (attempt %d/%d): %s",
                    handle,
                    attempt,
                    max_attempts,
                    exc,
                )
                try:
                    await client.connect()
                except Exception as reconnect_exc:
                    logger.warning("[TELEGRAM] reconnect failed for %s: %s", handle, reconnect_exc)

                if attempt == max_attempts:
                    logger.error("[TELEGRAM] validation unavailable for %s after %d attempts", handle, attempt)
                    return None
                await asyncio.sleep(2)
                continue
            except Exception as exc:
                logger.warning("[TG UNKNOWN] Could not validate %s: %s", handle, exc)
                return None
        logger.error("[TELEGRAM] validation unavailable for %s after %d attempts", handle, max_attempts)
        return None

    async def _validate_handles_async(self, handles: List[str]) -> List[str]:
        if not _client:
            return self.normalize_handles(handles)
        normalized = self.normalize_handles(handles)
        if not normalized:
            return []

        valid: List[str] = []
        for index, handle in enumerate(normalized, start=1):
            if index > 1:
                await asyncio.sleep(self.pacing_delay)
            is_alive = await self._is_handle_alive(_client, handle)
            if is_alive is True:
                valid.append(handle)
            elif is_alive is None:
                logger.warning("[TG UNKNOWN] Preserving %s because validation failed", handle)
                valid.append(handle)
        return valid

    def validate_telegram_handles(self, handles: List[str]) -> List[str]:
        if not TG_API_ENABLED:
            logger.warning("Telegram API credentials missing; preserving normalized handles without API validation.")
            return self.normalize_handles(handles)

        return _run_coroutine(self._validate_handles_async(handles))


def validate_telegram_handles(handles: List[str]) -> List[str]:
    validator = TelegramValidator()
    return validator.validate_telegram_handles(handles)
