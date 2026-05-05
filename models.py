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
class FaceStat:
    box: tuple[int, int, int, int]
    confidence: float = 0.0
    luma_mean: float | None = None
    saturation_mean: float | None = None
    sharpness: float | None = None
    redness: float | None = None


@dataclass
class FaceCandidate:
    box: tuple[int, int, int, int]
    detector_score: float = 0.0
    confidence: float = 0.0
    accepted: bool = False
    classification: str = "unknown"
    is_real_face: bool = False
    is_frontal: bool = False
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass
class CleanupCandidate:
    image_path: Path
    thumbnail_path: Path | None
    reason_code: str
    reason_text: str
    severity: str
    confidence: float
    source_issue: str


@dataclass
class AnalysisResult:
    path: Path
    width: int
    height: int
    overall_score: float
    issues: list[Issue] = field(default_factory=list)
    metrics: list[MetricItem] = field(default_factory=list)
    face_count: int = 0
    raw_face_count: int = 0
    face_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    raw_face_candidates: list[tuple[int, int, int, int]] = field(default_factory=list)
    validated_face_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    validated_face_count: int = 0
    rejected_face_count: int = 0
    face_confidence: float = 0.0
    face_confidences: list[float] = field(default_factory=list)
    face_candidates: list[FaceCandidate] = field(default_factory=list)
    subject_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    face_stats: list[FaceStat] = field(default_factory=list)
    face_region: tuple[int, int, int, int] | None = None
    subject_region: tuple[int, int, int, int] | None = None
    background_region: tuple[int, int, int, int] | None = None
    highlight_region: tuple[int, int, int, int] | None = None
    portrait_likely: bool = False
    portrait_type: str = "non_portrait"
    portrait_scene_type: str = "non_portrait"
    scene_type: str = "generic_scene"
    face_luma_median: float | None = None
    face_luma_mean: float | None = None
    face_saturation_mean: float | None = None
    face_sharpness_mean: float | None = None
    subject_luma_estimate: float | None = None
    subject_saturation_mean: float | None = None
    subject_sharpness: float | None = None
    background_luma_estimate: float | None = None
    background_saturation_mean: float | None = None
    background_sharpness: float | None = None
    face_exposure_status: str = "unknown"
    subject_exposure_status: str = "unknown"
    background_exposure_status: str = "unknown"
    portrait_exposure_status: str = "unknown"
    exposure_type: str = "normal"
    highlight_recovery_type: str = "not_needed"
    portrait_focus_score: float = 0.0
    highlight_clipping_ratio: float = 0.0
    subject_background_separation: float = 0.0
    portrait_repair_policy: str = "standard"
    color_type: str = "balanced"
    exposure_warning_reason: str = ""
    diagnostic_tags: list[str] = field(default_factory=list)
    diagnostic_notes: list[str] = field(default_factory=list)
    portrait_rejection_reason: str = ""
    cleanup_candidates: list[CleanupCandidate] = field(default_factory=list)
    perf_timings: dict[str, float] = field(default_factory=dict)
    perf_notes: list[str] = field(default_factory=list)


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
class RepairPlan:
    mode: str
    method_ids: list[str]
    op_strengths: dict[str, float] = field(default_factory=dict)
    policy: str = "standard"
    notes: list[str] = field(default_factory=list)


@dataclass
class RepairRecord:
    source_path: Path
    output_path: Path
    method_ids: list[str]
    op_strengths: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    policy_notes: list[str] = field(default_factory=list)
    saved_output: bool = True
    skipped_reason: str = ""
    applied_strength: float | None = None
    perf_timings: dict[str, float] = field(default_factory=dict)
    perf_notes: list[str] = field(default_factory=list)


@dataclass
class SessionStats:
    analyzed_images: int = 0
    analyzed_bytes: int = 0
    repaired_images: int = 0
    repaired_bytes: int = 0
    issue_images: int = 0
    issue_points: list[tuple[str, float]] = field(default_factory=list)
