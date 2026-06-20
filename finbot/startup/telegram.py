"""Telegram control plane — startup factory for Telegram integration."""

from __future__ import annotations

import asyncio
import logging
import threading

from finbot.config.settings import Settings
from finbot.core.application.use_cases.handle_telegram_command import (
    HandleTelegramCommand,
)
from finbot.core.domain.interfaces.bot_manager_port import BotManagerPort
from finbot.core.domain.interfaces.telegram_chat_repository import (
    TelegramChatRepository,
)
from finbot.infrastructure.adapters import (
    thread_safe_telegram_notification_dispatcher as telegram_dispatcher,
)
from finbot.infrastructure.adapters.filesystem_strategy_directory import (
    FilesystemStrategyDirectory,
)
from finbot.infrastructure.adapters.python_telegram_bot_adapter import (
    PythonTelegramBotAdapter,
)
from finbot.infrastructure.repositories.sqlite_telegram_chat_repository import (
    SqliteTelegramChatRepository,
)
from finbot.presentation.telegram.bot_handler import TelegramBotHandler
from finbot.presentation.telegram.notification_sender import (
    TelegramNotificationSender,
)

logger = logging.getLogger(__name__)
NotificationDispatcher = telegram_dispatcher.ThreadSafeTelegramNotificationDispatcher


class TelegramControlPlane:
    """Owns the Telegram asyncio event loop and background thread.

    Does not depend on an existing event loop. Creates its own loop on
    a daemon thread, and provides the thread-safe notification dispatcher
    for the trading runtime thread to schedule async sends.

    Call ``attach_bot_manager()`` before ``start_in_background()`` so
    the command use case has a real BotManager reference.
    """

    def __init__(
        self,
        settings: Settings,
        chat_repo: TelegramChatRepository,
    ) -> None:
        self._settings = settings
        self._chat_repo = chat_repo
        self._bot_manager: BotManagerPort | None = None
        self._handler: TelegramBotHandler | None = None
        self._adapter: PythonTelegramBotAdapter | None = None
        self._notification_sender: TelegramNotificationSender | None = None
        self._dispatcher: NotificationDispatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    @property
    def notification_dispatcher(
        self,
    ) -> NotificationDispatcher | None:
        """Return the thread-safe dispatcher for runtime notification scheduling."""
        return self._dispatcher

    def attach_bot_manager(self, bot_manager: BotManagerPort) -> None:
        """Attach the BotManager after it has been created by MCP startup.

        Must be called before ``start_in_background()``.
        """
        self._bot_manager = bot_manager

    def start_in_background(self) -> None:
        """Start the Telegram event loop on a daemon thread."""
        if self._bot_manager is None:
            raise RuntimeError("BotManager must be attached before starting Telegram")

        token = self._settings.telegram_bot_token.get_secret_value()
        if not token:
            raise ValueError("FINBOT_TELEGRAM_BOT_TOKEN is required")

        self._adapter = PythonTelegramBotAdapter(bot_token=token)
        self._notification_sender = TelegramNotificationSender(
            bot_port=self._adapter,
            chat_repo=self._chat_repo,
        )

        strategy_dir = FilesystemStrategyDirectory(
            self._settings.telegram_strategies_dir
        )

        from finbot.infrastructure.adapters.hyperliquid_metadata_provider import (
            HyperliquidMetadataProvider,
        )
        from finbot.infrastructure.adapters.in_memory_telegram_session_store import (
            InMemoryTelegramSessionStore,
        )

        metadata_provider = HyperliquidMetadataProvider()

        from finbot.infrastructure.strategy.yaml_strategy_definition_loader import (
            YamlStrategyDefinitionLoader,
        )

        strategy_loader = YamlStrategyDefinitionLoader()

        command_use_case = HandleTelegramCommand(
            bot_manager=self._bot_manager,
            chat_repo=self._chat_repo,
            strategy_dir=strategy_dir,
            session_store=InMemoryTelegramSessionStore(),
            allowed_users=self._settings.telegram_allowed_user_ids,
            live_trading_ack=self._settings.live_trading_ack,
            mode=self._settings.mode,
            hyperliquid_testnet=self._settings.hyperliquid_testnet,
            metadata_provider=metadata_provider,
            log_reader=_make_log_reader(),
            strategy_loader=strategy_loader,
        )

        self._handler = TelegramBotHandler(
            bot_token=token,
            command_use_case=command_use_case,
            bot_port=self._adapter,
        )

        self._thread = threading.Thread(
            target=self._run_loop,
            name="finbot-telegram",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the Telegram event loop cleanly."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_loop(self) -> None:
        """Run the Telegram event loop on this thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Create dispatcher now that loop exists
        if self._notification_sender is not None:
            self._dispatcher = NotificationDispatcher(
                loop=self._loop,
                sender=self._notification_sender,
            )

        try:
            self._loop.run_until_complete(self._handler.start_polling())
            self._loop.run_forever()
        except Exception:
            logger.exception("Telegram event loop crashed")
        finally:
            try:
                self._loop.run_until_complete(self._handler.stop())
            except Exception:
                pass
            self._loop.close()


def create_telegram_control_plane(
    settings: Settings,
    chat_repo: TelegramChatRepository | None = None,
) -> TelegramControlPlane | None:
    """Create a TelegramControlPlane if Telegram is enabled.

    Returns None if Telegram is disabled so callers can skip the
    Telegram integration entirely.
    """
    if not settings.telegram_enabled:
        return None

    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        raise ValueError(
            "FINBOT_TELEGRAM_BOT_TOKEN is required when " "FINBOT_TELEGRAM_ENABLED=true"
        )

    if chat_repo is None:
        chat_repo = SqliteTelegramChatRepository(settings.database_path)

    return TelegramControlPlane(settings=settings, chat_repo=chat_repo)


def _make_log_reader():
    """Create the strategy log reader for Telegram /log command."""
    from finbot.infrastructure.services.strategy_log_writer import (
        StrategyLogFileReader,
    )

    return StrategyLogFileReader()
