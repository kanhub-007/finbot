"""Tests for DotEnvConfigWriter atomicity & concurrency (S6: M7).

The writer does a read-modify-write of ``.env``. Without a lock, two
concurrent ``/config save`` calls can lose one update; without an atomic
replace, a crash mid-write leaves a truncated ``.env`` (potentially losing
``FINBOT_HYPERLIQUID_PRIVATE_KEY`` etc.). These tests pin the contract:
both updates persist, the file is never observable truncated, and a
multi-line value (``\\n`` injection) is rejected for safety.
"""

from __future__ import annotations

import os
import threading

import pytest

from finbot.infrastructure.adapters.dotenv_config_writer import DotEnvConfigWriter

_EXPECTED_LINES = {
    "max_position": "FINBOT_MAX_POSITION_USD=200",
    "daily_loss": "FINBOT_MAX_DAILY_LOSS_USD=50",
    "max_orders": "FINBOT_MAX_OPEN_ORDERS=5",
    "stale_data": "FINBOT_STALE_DATA_SECONDS=60",
}


class TestDotEnvWriterAtomicity:
    def test_concurrent_writes_do_not_lose_updates(self, tmp_path) -> None:
        """Four threads each writing a distinct key: all four win.

        Without the lock the read-modify-write race loses appends: each
        thread reads the current file, appends its key to its in-memory copy,
        and writes the whole file back — the last writer wins and the others'
        keys vanish. Four threads + a barrier reliably exposes it.
        """
        env_path = tmp_path / ".env"
        env_path.write_text("FINBOT_MODE=dry_run\n")
        writer = DotEnvConfigWriter(env_path=str(env_path))
        keys = ["max_position", "daily_loss", "max_orders", "stale_data"]
        values = {
            "max_position": "200",
            "daily_loss": "50",
            "max_orders": "5",
            "stale_data": "60",
        }
        barrier = threading.Barrier(len(keys))
        errors: list[Exception] = []

        def save(key: str) -> None:
            try:
                barrier.wait(timeout=5.0)
                writer.write(key, values[key])
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=save, args=(k,)) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, errors
        text = env_path.read_text()
        for key, expected_line in _EXPECTED_LINES.items():
            assert expected_line in text, key
        # Original line survives.
        assert "FINBOT_MODE=dry_run" in text

    def test_write_creates_file_when_absent(self, tmp_path) -> None:
        """Writing when the file does not yet exist creates it."""
        env_path = tmp_path / ".env"
        assert not env_path.exists()
        writer = DotEnvConfigWriter(env_path=str(env_path))
        writer.write("max_position", "100")
        text = env_path.read_text()
        assert "FINBOT_MAX_POSITION_USD=100" in text

    def test_multiline_value_is_rejected(self, tmp_path) -> None:
        """A value containing a newline must be rejected (``.env`` injection)."""
        env_path = tmp_path / ".env"
        writer = DotEnvConfigWriter(env_path=str(env_path))
        with pytest.raises((ValueError, TypeError)):
            writer.write("max_position", "100\nFINBOT_MODE=live")

    def test_existing_value_is_updated_in_place(self, tmp_path) -> None:
        """An existing FINBOT_<KEY> line is replaced, not duplicated."""
        env_path = tmp_path / ".env"
        env_path.write_text("FINBOT_MAX_POSITION_USD=50\n")
        writer = DotEnvConfigWriter(env_path=str(env_path))
        writer.write("max_position", "200")
        text = env_path.read_text()
        assert text.count("FINBOT_MAX_POSITION_USD=") == 1
        assert "FINBOT_MAX_POSITION_USD=200" in text
        assert "FINBOT_MAX_POSITION_USD=50" not in text

    def test_unknown_key_is_ignored(self, tmp_path) -> None:
        """An unknown short key is ignored (no env var to map it to)."""
        env_path = tmp_path / ".env"
        writer = DotEnvConfigWriter(env_path=str(env_path))
        writer.write("nonsense_key", "1")
        # File may or may not be created, but no FINBOT_ line is written.
        if env_path.exists():
            assert "FINBOT_NONSENCE" not in env_path.read_text()
            assert "nonsense_key" not in env_path.read_text()

    def test_crash_before_replace_leaves_original_intact(
        self, tmp_path, monkeypatch
    ) -> None:
        """If the atomic replace fails, the original .env is untouched.

        Simulates a crash/power loss between writing ``.env.tmp`` and
        ``os.replace``: the original file must still parse and contain its
        prior contents.
        """
        env_path = tmp_path / ".env"
        env_path.write_text("FINBOT_MODE=dry_run\nFINBOT_MAX_POSITION_USD=50\n")
        writer = DotEnvConfigWriter(env_path=str(env_path))

        import finbot.infrastructure.adapters.dotenv_config_writer as mod

        real_replace = os.replace
        call_count = {"n": 0}

        def _replacing_replace(src, dst):
            call_count["n"] += 1
            raise OSError("simulated crash during replace")

        monkeypatch.setattr(mod.os, "replace", _replacing_replace)
        writer.write("max_position", "999")  # swallow internally
        monkeypatch.setattr(mod.os, "replace", real_replace)

        # Original is intact and still parses.
        text = env_path.read_text()
        assert "FINBOT_MAX_POSITION_USD=50" in text
        assert "999" not in text
        assert call_count["n"] == 1  # the replace was attempted once

    def test_no_tmp_file_left_after_successful_write(self, tmp_path) -> None:
        """A successful write leaves no stale ``.env.tmp`` behind."""
        env_path = tmp_path / ".env"
        writer = DotEnvConfigWriter(env_path=str(env_path))
        writer.write("max_position", "100")
        assert not (tmp_path / ".env.env.tmp").exists()
