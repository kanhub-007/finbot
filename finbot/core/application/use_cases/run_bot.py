"""Use case for starting a Finbot strategy runner."""

from finbot.core.application.dto.run_bot_request import RunBotRequest
from finbot.core.application.dto.run_bot_result import RunBotResult
from finbot.core.domain.entities.safety_validation import SafetyValidation
from finbot.core.domain.entities.trading_mode import TradingMode
from finbot.core.domain.interfaces.bot_state_repository import BotStateRepository
from finbot.core.domain.interfaces.exchange_gateway import ExchangeGateway
from finbot.core.domain.interfaces.market_data_stream import MarketDataStream
from finbot.core.domain.interfaces.strategy_evaluator import StrategyEvaluator


class RunBotUseCase:
    """Coordinates startup safety checks for a bot run.

    The first implementation deliberately stops after validation and exchange
    reconciliation. Live order placement belongs behind a later, tested signal
    processing pipeline.

    Dependencies are constructor-injected. market_data_stream,
    strategy_evaluator, and state_repository are wired now so the signature
    is stable; they will be used in later phases.
    """

    def __init__(
        self,
        exchange_gateway: ExchangeGateway,
        market_data_stream: MarketDataStream,
        strategy_evaluator: StrategyEvaluator,
        state_repository: BotStateRepository,
    ):
        self._exchange_gateway = exchange_gateway
        self._market_data_stream = market_data_stream
        self._strategy_evaluator = strategy_evaluator
        self._state_repository = state_repository

    def execute(self, request: RunBotRequest) -> RunBotResult:
        """Run startup checks and prepare the bot for streaming."""
        validation = self._validate_safety(request)
        if not validation.is_valid:
            return RunBotResult(
                status="rejected",
                message="; ".join(validation.errors),
            )

        position = self._exchange_gateway.get_position(request.symbol)
        open_orders = self._exchange_gateway.list_open_orders(request.symbol)
        message = (
            f"mode={request.config.mode}, symbol={request.symbol}, "
            f"position_size={position.size}, open_orders={len(open_orders)}"
        )
        return RunBotResult(status="ready", message=message)

    def _validate_safety(self, request: RunBotRequest) -> SafetyValidation:
        mode_check = self._validate_mode(request)
        config_check = self._validate_config_limits(request)
        return mode_check.merge(config_check)

    def _validate_mode(self, request: RunBotRequest) -> SafetyValidation:
        if (
            request.config.mode == TradingMode.LIVE
            and not request.config.live_trading_ack
        ):
            return SafetyValidation.failure(
                "live mode requires explicit live_trading_ack=true"
            )
        return SafetyValidation.success()

    def _validate_config_limits(self, request: RunBotRequest) -> SafetyValidation:
        errors: list[str] = []
        if request.config.max_open_orders < 1:
            errors.append("max_open_orders must be at least 1")
        if request.config.stale_data_seconds < 1:
            errors.append("stale_data_seconds must be positive")
        if request.config.max_position_usd <= 0:
            errors.append(
                "max_position_usd must be positive"
                f" (got {request.config.max_position_usd})"
            )
        if request.config.max_daily_loss_usd <= 0:
            errors.append(
                "max_daily_loss_usd must be positive"
                f" (got {request.config.max_daily_loss_usd})"
            )
        if errors:
            return SafetyValidation.failure(*errors)
        return SafetyValidation.success()
