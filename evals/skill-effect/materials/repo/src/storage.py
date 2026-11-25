"""在庫データの読み書き。1 つの JSON ファイルに全件を持つ。"""
import json
from pathlib import Path


class Storage:
    def __init__(self, path: str):
        self.path = Path(path)

    def items(self) -> list:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, item: dict) -> None:
        items = self.items()
        items.append(item)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
