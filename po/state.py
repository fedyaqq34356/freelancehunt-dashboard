import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "owner_chat_id": None,
    "my_id": None,
    "initialized": False,
    "projects_initialized": False,
    "paused": False,
    "min_budget": 0,
    "seen_message_ids": [],
    "seen_feed_ids": [],
    "seen_project_ids": [],
    "shown_project_ids": [],
    "reply_map": {},
}

CAPS = {"seen_message_ids": 2000, "seen_feed_ids": 2000, "seen_project_ids": 3000, "shown_project_ids": 3000}


class State:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text())
                if "shown_project_ids" not in saved:
                    saved["shown_project_ids"] = list(saved.get("seen_project_ids") or [])
                self.data.update(saved)
            except (ValueError, OSError):
                pass

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def mark(self, key: str, item_id: Any) -> bool:
        """Добавляет id в список просмотренных. Возвращает True, если id новый."""
        seen = self.data[key]
        if item_id in seen:
            return False
        seen.append(item_id)
        return True

    def save(self) -> None:
        for key, cap in CAPS.items():
            self.data[key] = self.data[key][-cap:]
        if len(self.data["reply_map"]) > 1000:
            self.data["reply_map"] = dict(list(self.data["reply_map"].items())[-1000:])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False))
        os.replace(tmp, self.path)
