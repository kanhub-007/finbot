"""Tests for DotEnvConfigWriter and /config save (Slice 3 scenario)."""

from pathlib import Path

from finbot.infrastructure.adapters.dotenv_config_writer import (
    DotEnvConfigWriter,
)
from finbot.infrastructure.adapters.in_memory_config_writer import (
    InMemoryConfigWriter,
)


class TestDotEnvConfigWriter:
    def test_appends_new_key_to_empty_env(self, tmp_path: Path):
        writer = DotEnvConfigWriter(str(tmp_path / ".env"))
        writer.write("max_position", "500")

        content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "FINBOT_MAX_POSITION_USD=500" in content

    def test_updates_existing_key(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "FINBOT_MAX_POSITION_USD=100\nFINBOT_MODE=dry_run\n",
            encoding="utf-8",
        )
        writer = DotEnvConfigWriter(str(env_file))
        writer.write("max_position", "500")

        content = env_file.read_text(encoding="utf-8")
        assert "FINBOT_MAX_POSITION_USD=500" in content
        assert "FINBOT_MODE=dry_run" in content
        # No duplicate
        assert content.count("FINBOT_MAX_POSITION_USD") == 1

    def test_unknown_key_is_noop(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("FINBOT_MODE=dry_run\n", encoding="utf-8")
        writer = DotEnvConfigWriter(str(env_file))
        writer.write("nonsense", "1")

        # File unchanged
        assert env_file.read_text(encoding="utf-8") == "FINBOT_MODE=dry_run\n"

    def test_all_supported_keys(self, tmp_path: Path):
        writer = DotEnvConfigWriter(str(tmp_path / ".env"))
        writer.write("daily_loss", "75")
        writer.write("max_orders", "5")
        writer.write("stale_data", "60")

        content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "FINBOT_MAX_DAILY_LOSS_USD=75" in content
        assert "FINBOT_MAX_OPEN_ORDERS=5" in content
        assert "FINBOT_STALE_DATA_SECONDS=60" in content


class TestInMemoryConfigWriter:
    def test_records_writes(self):
        writer = InMemoryConfigWriter()
        writer.write("max_position", "500")
        assert writer.writes["max_position"] == "500"


class TestSaveConfigToEnv:
    """BotManager.save_config_to_env delegates to the config writer."""

    def test_save_writes_all_keys(self):
        import time as _time

        from finbot.core.domain.services.bot_manager import BotManager
        from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
            InMemoryBotStateRepository,
        )

        writer = InMemoryConfigWriter()
        manager = BotManager(
            runtime_factory=lambda **kw: None,
            repository=InMemoryBotStateRepository(),
            startup_time=_time.time(),
            config_writer=writer,
        )
        manager.update_bot_config("max_position", "500")

        result = manager.save_config_to_env()

        assert result["status"] == "ok"
        assert result["saved"] == 4
        assert writer.writes["max_position"] == "500"

    def test_save_without_writer_rejected(self):
        import time as _time

        from finbot.core.domain.services.bot_manager import BotManager
        from finbot.infrastructure.repositories.in_memory_bot_state_repository import (
            InMemoryBotStateRepository,
        )

        manager = BotManager(
            runtime_factory=lambda **kw: None,
            repository=InMemoryBotStateRepository(),
            startup_time=_time.time(),
        )

        result = manager.save_config_to_env()

        assert result["status"] == "rejected"
        assert "not configured" in result["message"].lower()
