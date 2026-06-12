"""Command-line interface for Finbot."""

import argparse
import json
import sys
from pathlib import Path

from finbot.config.settings import Settings
from finbot.core.domain.dto.validate_strategy_request import (
    ValidateStrategyRequest,
)
from finbot.startup.service_factory import (
    create_replay_strategy_use_case,
    create_run_bot_request,
    create_run_bot_use_case,
    create_validate_strategy_use_case,
)


def main() -> None:
    """Run the Finbot command-line interface."""
    parser = argparse.ArgumentParser(description="Finbot live trading runtime")
    sub = parser.add_subparsers(dest="command")

    _add_run_parser(sub)
    _add_validate_parser(sub)
    _add_compat_parser(sub)
    _add_replay_parser(sub)

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "validate-strategy":
        _cmd_validate(args)
    elif args.command == "strategy-compat":
        _cmd_compat(args)
    elif args.command == "replay":
        _cmd_replay(args)
    else:
        parser.print_help()


def _add_run_parser(sub) -> None:
    p = sub.add_parser("run", help="Start the live trading runtime")
    p.add_argument("--strategy", required=True)
    p.add_argument("--symbol", default="BTC")
    p.add_argument("--interval", default="1h")


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


def _cmd_run(args) -> None:
    settings = Settings()
    use_case = create_run_bot_use_case(settings, args.strategy)
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


def _cmd_replay(args) -> None:
    from finbot.core.domain.dto.replay_strategy_request import (
        ReplayStrategyRequest,
    )

    content = _read_strategy_file(args.strategy)
    bars_csv = ""
    if args.bars:
        bars_csv = _read_strategy_file(args.bars)

    use_case = create_replay_strategy_use_case(
        bar_source_csv=bars_csv,
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


def _read_strategy_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


if __name__ == "__main__":
    main()
