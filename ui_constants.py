from __future__ import annotations

import os


FILTER_OPTIONS = [
    "??",
    "????",
    "??",
    "??/??",
    "??",
    "????",
    "??",
    "????",
    "????",
    "????",
    "?????",
]

ANALYSIS_PROGRESS_STEPS = 5
DEFAULT_ANALYSIS_WORKERS = max(1, min(12, os.cpu_count() or 4))
DEFAULT_REPAIR_WORKERS = max(1, min(4, max(1, (os.cpu_count() or 4) // 2)))
ANALYSIS_TIMING_LABELS = [
    ("????", ("image_read",)),
    ("????", ("image_open",)),
    ("EXIF ????", ("exif_transpose",)),
    ("????", ("image_convert",)),
    ("?????", ("resize", "working_resize")),
    ("????", ("array_convert",)),
    ("????", ("basic_stats",)),
    ("??", ("exposure",)),
    ("??", ("color",)),
    ("???", ("sharpness",)),
    ("??", ("noise",)),
    ("????", ("scene_classify",)),
    ("??/???/??/????", ("face_detect", "portrait_region_build", "quality_stats", "issue_build")),
    ("??", ("face_detect", "portrait_region_build")),
    ("cleanup candidate", ("cleanup_candidate",)),
]
ANALYSIS_BATCH_TIMING_LABELS = ANALYSIS_TIMING_LABELS + [
    ("?????", ("similar_detection",)),
    ("???/??/UI", ("thumbnail", "preview", "ui_refresh", "UI_update", "ui_update")),
    ("Console ??", ("console_flush",)),
]
REPAIR_TIMING_LABELS = [
    ("??????", ("planner",)),
    ("????", ("image_read",)),
    ("??????", ("candidate_generation", "op:auto_tone", "op:recover_highlights", "op:lift_shadows", "op:boost_contrast", "op:boost_vibrance", "op:reduce_saturation", "op:warm_up", "op:cool_down", "op:add_magenta", "op:add_green", "op:boost_clarity", "op:reduce_noise", "op:portrait_local_face_enhance", "op:portrait_subject_midcontrast", "op:portrait_dark_clothing_detail", "op:protect_high_key_background")),
    ("????/????", ("candidate_scoring", "mask_build", "mask_feather")),
    ("????", ("save_output",)),
    ("?????", ("metadata_preserve",)),
]


class AnalysisCanceled(Exception):
    pass
