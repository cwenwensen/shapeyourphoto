from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Issue:
    code: str
    label: str
    score: float
    level: str
    detail: str
    suggestion: str
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricItem:
    label: str
    value: str
    ratio: float
    color: str


@dataclass
class AnalysisResult:
    path: Path
    width: int
    height: int
    overall_score: float
    issues: list[Issue] = field(default_factory=list)
    metrics: list[MetricItem] = field(default_factory=list)


@dataclass(frozen=True)
class RepairMethod:
    method_id: str
    label: str
    description: str


@dataclass
class RepairSelection:
    mode: str
    selected_method_ids: list[str]
    output_folder_name: str
    filename_suffix: str
    use_suffix: bool = True
    overwrite_original: bool = False


@dataclass
class RepairRecord:
    source_path: Path
    output_path: Path
    method_ids: list[str]


@dataclass
class SessionStats:
    analyzed_images: int = 0
    analyzed_bytes: int = 0
    repaired_images: int = 0
    repaired_bytes: int = 0
    issue_images: int = 0
    issue_points: list[tuple[str, float]] = field(default_factory=list)
