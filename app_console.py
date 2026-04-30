from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AppConsole:
    lines: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.lines.append(f"[{timestamp}] {message}")
        self.lines = self.lines[-400:]

    def dump(self) -> str:
        return "\n".join(self.lines) if self.lines else "控制台暂无输出。"
