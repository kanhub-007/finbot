"""Command-line interface for Finbot."""

import argparse

from finbot.config.settings import Settings
from finbot.startup.service_factory import (
    create_run_bot_request,
    create_run_bot_use_case,
)


def main() -> None:
    """Run the Finbot command-line interface."""
    parser = argparse.ArgumentParser(description="Finbot live trading runtime")
    parser.add_argument("--strategy", required=False, default="")
    parser.add_argument("--symbol", required=False, default="BTC")
    parser.add_argument("--interval", required=False, default="1h")
    args = parser.parse_args()

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
