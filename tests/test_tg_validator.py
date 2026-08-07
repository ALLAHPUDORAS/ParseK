import unittest
from unittest.mock import AsyncMock, patch

from src.validators.telegram_validator import TelegramValidator


class TelegramValidatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_failure_preserves_normalized_handle(self):
        validator = TelegramValidator.__new__(TelegramValidator)
        validator.pacing_delay = 0
        validator._is_handle_alive = AsyncMock(return_value=None)

        with patch("src.validators.telegram_validator._client", object()):
            results = await validator._validate_handles_async(["telegram"])

        self.assertEqual(results, ["@telegram"])

    async def test_explicitly_invalid_handle_is_removed(self):
        validator = TelegramValidator.__new__(TelegramValidator)
        validator.pacing_delay = 0
        validator._is_handle_alive = AsyncMock(return_value=False)

        with patch("src.validators.telegram_validator._client", object()):
            results = await validator._validate_handles_async(["@missing_user"])

        self.assertEqual(results, [])

    def test_normalize_handles_does_not_call_telegram(self):
        self.assertEqual(
            TelegramValidator.normalize_handles(["telegram", "@telegram", "bad-name"]),
            ["@telegram"],
        )


if __name__ == "__main__":
    unittest.main()
