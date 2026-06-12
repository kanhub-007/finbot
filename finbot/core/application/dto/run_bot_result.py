"""Result DTO for a bot run command."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunBotResult:
    """Output from attempting to start or run a bot."""

    status: str
    message: str
