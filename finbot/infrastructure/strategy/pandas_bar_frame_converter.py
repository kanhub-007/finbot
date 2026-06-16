"""PandasBarFrameConverter — pandas implementation of BarFrameConverter."""

import pandas as pd

from finbot.core.domain.interfaces.bar_frame_converter import BarFrameConverter


class PandasBarFrameConverter(BarFrameConverter):
    """Convert OHLCV bar dictionaries to and from pandas DataFrames."""

    def bars_to_frame(self, bars: list[dict]) -> pd.DataFrame:
        """Convert list of OHLCV bar dicts to a DataFrame with datetime index."""
        df = pd.DataFrame(bars)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp").sort_index()
        return df

    def frame_to_bars(self, frame: pd.DataFrame) -> list[dict]:
        """Convert a DataFrame back to JSON-serializable bar dictionaries."""
        df = frame.reset_index()
        datetime_cols = df.select_dtypes(
            include=["datetime64[ns]", "datetime64[ns, UTC]"]
        ).columns
        for col in datetime_cols:
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
        df = df.where(pd.notna(df), None)
        return df.to_dict(orient="records")

    def latest_bar(self, frame: pd.DataFrame) -> dict:
        """Return the last row as a dict."""
        return frame.iloc[-1].to_dict()

    def append_bar(self, frame: pd.DataFrame, bar: dict) -> pd.DataFrame:
        """Append one bar to the frame, returning a new frame.

        Cost is ``O(n)`` — ``pd.concat`` copies every row — but it avoids
        rebuilding the OHLCV base from the full warmup list each candle.
        The caller trims the result to the warmup max length so the frame
        stays bounded. (This does not make the per-candle indicator
        recompute incremental; that requires a streaming calculator.)
        """
        import pandas as pd

        ts = bar.get("timestamp")
        index_val = (
            pd.Timestamp(ts, unit="s")
            if isinstance(ts, (int, float))
            else pd.Timestamp(ts)
        )
        row = pd.DataFrame([bar], index=pd.DatetimeIndex([index_val], name="timestamp"))
        return pd.concat([frame, row])

    def is_empty(self, frame: pd.DataFrame) -> bool:
        """True when the DataFrame has no rows or columns."""
        return frame.empty
