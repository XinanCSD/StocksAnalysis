from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


INITIAL_SYMBOLS = ("^NDX", "^GSPC", "SPY", "QQQ", "VOO", "VTI")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    update_interval_minutes: int = 30
    daily_overlap_days: int = 10
    intraday_overlap_days: int = 3
    intraday_initial_days: int = 59
    request_pause_seconds: float = 1.0
    prepost: bool = False

    @property
    def database_path(self) -> Path:
        return self.data_dir / "market_data.sqlite"


def default_data_dir() -> Path:
    configured = os.getenv("STOCK_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "data"


def make_settings(data_dir: str | Path | None = None) -> Settings:
    path = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
    return Settings(
        data_dir=path,
        update_interval_minutes=int(os.getenv("STOCK_UPDATE_MINUTES", "30")),
        request_pause_seconds=float(os.getenv("STOCK_REQUEST_PAUSE_SECONDS", "1")),
        prepost=os.getenv("STOCK_PREPOST", "0").lower() in {"1", "true", "yes"},
    )

