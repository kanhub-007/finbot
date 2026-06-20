"""Command-line interface for Finbot."""

import argparse
import json
import sys
from pathlib import Path

from finbot.config.settings import Settings
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.core.domain.entities.order_intent import OrderIntent
from finbot.core.domain.entities.order_side import OrderSide
from finbot.core.domain.entities.order_type import OrderType
from finbot.core.domain.entities.position_direction import PositionDirection
from finbot.startup.service_factory import (
    create_exchange_gateway,
    create_live_trading_runtime_use_case,
    create_replay_strategy_use_case,
    create_run_bot_request,
    create_run_bot_use_case,
    create_status_use_case,
    create_validate_strategy_use_case,
)


def main() -> None:
    """Run the Finbot command-line interface."""
    from finbot.infrastructure.services.log_redactor import setup_logging

    setup_logging()

    parser = argparse.ArgumentParser(description="Finbot live trading runtime")
    sub = parser.add_subparsers(dest="command")

    _add_run_parser(sub)
    _add_validate_parser(sub)
    _add_compat_parser(sub)
    _add_replay_parser(sub)
    _add_status_parser(sub)
    _add_db_parser(sub)
    _add_panic_parser(sub)

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "validate-strategy":
        _cmd_validate(args)
    elif args.command == "strategy-compat":
        _cmd_compat(args)
    elif args.command == "replay":
        _cmd_replay(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "db":
        _cmd_db(args)
    elif args.command == "panic":
        _cmd_panic(args)
    else:
        parser.print_help()


def _add_run_parser(sub) -> None:
    p = sub.add_parser("run", help="Start the live trading runtime")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbol", default="BTC")
    p.add_argument("--interval", default="1h")
    p.add_argument(
        "--live-data",
        action="store_true",
        help="Use Hyperliquid websocket for market data (dry-run only)",
    )


def _add_validate_parser(sub) -> None:
    p = sub.add_parser("validate-strategy", help="Validate a strategy file")
    p.add_argument("--strategy", required=True)


def _add_compat_parser(sub) -> None:
    p = sub.add_parser("strategy-compat", help="Check strategy feature compatibility")
    p.add_argument("--strategy", required=True)


def _add_replay_parser(sub) -> None:
    p = sub.add_parser("replay", help="Replay a strategy over historical bar data")
    p.add_argument("--strategy", required=True)
    p.add_argument("--bars", default="")
    p.add_argument("--symbol", default="BTC")
    p.add_argument("--interval", default="1h")
    p.add_argument(
        "--warmup-bars",
        type=int,
        default=0,
        help="Minimum warmup bars before evaluating (0 = no warmup)",
    )


def _add_status_parser(sub) -> None:
    sub.add_parser("status", help="Show bot status (last signal, last order, counts)")


def _add_db_parser(sub) -> None:
    p = sub.add_parser("db", help="Database management commands")
    sp = p.add_subparsers(dest="db_command")
    sp.add_parser("migrate", help="Apply pending schema migrations")


def _add_panic_parser(sub) -> None:
    p = sub.add_parser("panic", help="Emergency order/position management")
    p.add_argument("--symbol", required=True)
    p.add_argument("--cancel-orders", action="store_true")
    p.add_argument("--close-position", action="store_true")


def _cmd_run(args) -> None:
    settings = Settings()

    # Mode/URL consistency — refuse testnet-vs-mainnet mismatches before
    # any live/testnet startup touches an execution gateway.
    from finbot.core.domain.services.mode_url_guard import (
        check_mode_url_consistency,
    )

    reasons = check_mode_url_consistency(
        mode=settings.mode,
        hyperliquid_testnet=settings.hyperliquid_testnet,
    )
    blocking = [r for r in reasons if settings.mode != "dry_run"]
    if blocking:
        for reason in blocking:
            print(f"MODE/URL MISMATCH: {reason}")
        sys.exit(1)
    for reason in reasons:
        print(f"WARNING: {reason}")

    # Live-mode safety gate.
    if settings.mode == "live":
        _check_live_mode_gate(settings)

    if args.live_data:
        # New runtime: blocking event loop with real pipeline.
        # The bot loop (and account stream for testnet/live) are built in
        # the composition root, not here, so wiring stays single-sourced.
        runtime = create_live_trading_runtime_use_case(
            args.strategy,
            args.symbol,
            args.interval,
            mode=settings.mode,
            live_data=True,
        )
        if settings.mode in ("testnet", "live"):
            # Live/testnet go through the full safety + compatibility gates.
            from finbot.startup.service_factory import create_bot_config

            result = runtime.start_live(
                strategy_path=args.strategy,
                symbol=args.symbol,
                interval=args.interval,
                config=create_bot_config(settings),
            )
            if result.status != "running":
                print(f"{result.status}: {result.message}")
                sys.exit(1)
        else:
            runtime.start(args.strategy, args.symbol, args.interval)
        print(
            f"running: {args.strategy} on {args.symbol}/{args.interval}"
            f" [{settings.mode}]"
        )
        try:
            runtime.run_forever()
        except KeyboardInterrupt:
            print("\nshutting down...")
            runtime.stop()
    else:
        # Legacy: validate and exit
        use_case = create_run_bot_use_case(
            settings,
            args.strategy,
            symbol=args.symbol,
            interval=args.interval,
            live_data=False,
        )
        request = create_run_bot_request(
            settings=settings,
            strategy_path=args.strategy,
            symbol=args.symbol,
            interval=args.interval,
        )
        result = use_case.execute(request)
        print(f"{result.status}: {result.message}")


def _cmd_validate(args) -> None:
    use_case = create_validate_strategy_use_case()
    content = _read_strategy_file(args.strategy)
    request = ValidateStrategyRequest(
        strategy_path=args.strategy, strategy_content=content
    )
    result = use_case.validate(request)

    if result.valid:
        print(f"VALID  {result.strategy_name}  ({result.schema_version})")
        print(
            f"       timeframe={result.primary_timeframe},"
            f" indicators={result.indicator_count}"
        )
    else:
        print("INVALID")
        for err in result.errors:
            print(f"  - {err}")
        sys.exit(1)


def _cmd_compat(args) -> None:
    use_case = create_validate_strategy_use_case()
    content = _read_strategy_file(args.strategy)
    request = ValidateStrategyRequest(
        strategy_path=args.strategy, strategy_content=content
    )
    result = use_case.compatibility(request)

    print(
        json.dumps(
            {"strategy": result.strategy_name, "modes": result.modes},
            indent=2,
        )
    )


def _check_live_mode_gate(settings: Settings) -> None:
    """Validate all live-mode preconditions and exit(1) if any fail."""
    from finbot.core.domain.services.live_mode_guard import check_live_mode

    check = check_live_mode(
        mode=settings.mode,
        live_trading_ack=settings.live_trading_ack,
        private_key=settings.hyperliquid_private_key.get_secret_value(),
        max_position_usd=float(settings.max_position_usd),
        database_path=settings.database_path,
    )
    if not check.allowed:
        for reason in check.reasons:
            print(f"LIVE MODE BLOCKED: {reason}")
        sys.exit(1)


def _cmd_replay(args) -> None:
    from finbot.core.domain.dto.replay_strategy_request import (
        ReplayStrategyRequest,
    )

    content = _read_strategy_file(args.strategy)
    bars_csv = ""
    if args.bars:
        bars_csv = _read_strategy_file(args.bars)

    use_case = create_replay_strategy_use_case(
        warmup_min_bars=args.warmup_bars or 0,
    )
    request = ReplayStrategyRequest(
        strategy_path=args.strategy,
        strategy_content=content,
        bars_csv=bars_csv,
        symbol=args.symbol,
        interval=args.interval,
    )
    result = use_case.execute(request)
    print(f"{result.status}: {result.signal_count} signals")
    if result.errors:
        for err in result.errors:
            print(f"  ERROR: {err}")
    for sig in result.signals:
        extras = ""
        if sig.stop_price:
            extras += f" stop={sig.stop_price:.2f}"
        if sig.target_price:
            extras += f" target={sig.target_price:.2f}"
        print(
            f"  bar={sig.bar_index} {sig.action.value}"
            f" close={sig.close:.2f}{extras}"
        )


def _cmd_status(args) -> None:
    _ = args
    use_case = create_status_use_case()
    result = use_case.execute()
    print(
        json.dumps(
            {
                "active_bot_run_id": result.active_bot_run_id,
                "strategy": result.strategy_name,
                "symbol": result.symbol,
                "interval": result.interval,
                "mode": result.mode,
                "last_signal": {
                    "key": result.last_signal_key,
                    "action": result.last_signal_action,
                    "timestamp": result.last_signal_timestamp,
                },
                "last_order": {
                    "intent_id": result.last_order_intent_id,
                    "status": result.last_order_status,
                },
                "totals": {
                    "signals": result.total_signals,
                    "orders": result.total_orders,
                    "fills": result.total_fills,
                },
            },
            indent=2,
        )
    )


def _cmd_db(args) -> None:
    if args.db_command == "migrate":
        from finbot.startup.db import run_migrations
        from finbot.startup.service_factory import db_path_from_settings

        db_path = db_path_from_settings()
        version = run_migrations(db_path)
        print(f"Database migrated to version {version}")
    else:
        print("Usage: finbot db migrate")


def _cmd_panic(args) -> None:
    """Emergency kill-switch — cancels orders and closes positions.

    ARCHITECTURE EXCEPTION: Panic bypasses use cases and repositories,
    calling the exchange gateway directly.  This is intentional —
    kill-switch operations must not go through risk gates, order
    planning, or any other pipeline.  A minimal audit event is
    persisted on a best-effort basis so there is a record of the
    panic action; reconcile after panic.
    """
    settings = Settings()
    if not settings.hyperliquid_private_key.get_secret_value():
        print("ERROR: FINBOT_HYPERLIQUID_PRIVATE_KEY not set")
        sys.exit(1)

    # Best-effort audit trail — fire-and-forget; don't block the kill switch.
    try:
        from finbot.core.domain.entities.audit_log_entry import AuditLogEntry
        from finbot.startup.service_factory import create_bot_state_repository

        repo = create_bot_state_repository(migrate=False)
        repo.append_audit_log(
            AuditLogEntry(
                event_type="panic",
                event_data_json=json.dumps(
                    {
                        "symbol": args.symbol,
                        "cancel_orders": args.cancel_orders,
                        "close_position": args.close_position,
                    }
                ),
            )
        )
    except Exception:
        pass

    gateway = create_exchange_gateway(settings)

    if args.cancel_orders:
        result = gateway.cancel_all(args.symbol)
        print(json.dumps({"cancel_orders": result}, indent=2))

    if args.close_position:
        pos = gateway.get_position(args.symbol)
        if pos.direction != PositionDirection.FLAT:
            side = (
                OrderSide.SELL
                if pos.direction == PositionDirection.LONG
                else OrderSide.BUY
            )
            intent = OrderIntent(
                symbol=args.symbol,
                side=side,
                size=pos.size,
                order_type=OrderType.MARKET,
                reduce_only=True,
            )
            result = gateway.submit_order(intent)
            print(json.dumps({"close_position": result}, indent=2))
        else:
            print("No open position to close")

    if not args.cancel_orders and not args.close_position:
        print("Usage: finbot panic --symbol BTC --cancel-orders [--close-position]")


def _read_strategy_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
