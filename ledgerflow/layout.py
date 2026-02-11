from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    data_dir: Path

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def sources_index_path(self) -> Path:
        return self.sources_dir / "index.json"

    @property
    def ledger_dir(self) -> Path:
        return self.data_dir / "ledger"

    @property
    def transactions_path(self) -> Path:
        return self.ledger_dir / "transactions.jsonl"

    @property
    def corrections_path(self) -> Path:
        return self.ledger_dir / "corrections.jsonl"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def charts_dir(self) -> Path:
        return self.data_dir / "charts"

    @property
    def alerts_dir(self) -> Path:
        return self.data_dir / "alerts"

    @property
    def alert_rules_path(self) -> Path:
        return self.alerts_dir / "alert_rules.json"

    @property
    def rules_dir(self) -> Path:
        return self.data_dir / "rules"

    @property
    def categories_path(self) -> Path:
        return self.rules_dir / "categories.json"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def index_db_path(self) -> Path:
        return self.index_dir / "ledgerflow.db"

    @property
    def meta_dir(self) -> Path:
        return self.data_dir / "meta"

    @property
    def schema_state_path(self) -> Path:
        return self.meta_dir / "schema.json"


def layout_for(data_dir: str | Path) -> Layout:
    return Layout(Path(data_dir))
