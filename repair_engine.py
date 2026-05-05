from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, PngImagePlugin

from file_actions import build_repaired_output_path
from models import AnalysisResult, RepairRecord, RepairSelection
from repair_planner import suggest_methods_for_result
from repair_ops import (
    add_green,
    add_magenta,
    as_array,
    auto_tone,
    boost_clarity,
    boost_contrast,
    boost_vibrance,
    build_region_masks,
    cool_down,
    hue_map,
    lift_shadows,
    luma_map,
    portrait_dark_clothing_detail,
    portrait_local_face_enhance,
    portrait_subject_midcontrast,
    protect_high_key_background,
    recover_highlights,
    reduce_noise,
    reduce_saturation,
    saturation_map,
    skin_like_mask,
    skin_redness_map,
    warm_up,
)


SOFTWARE_NAME = "ShapeYourPhoto"
AUTHOR_NAME = "Helloalp"
AUTHOR_URL = "https://helloalp.top/tools/shapeyourphoto"


def _weighted_mean(values: np.ndarray, mask: np.ndarray) -> float | None:
    weights = np.clip(mask, 0.0, 1.0)
    total = float(np.sum(weights))
    if total <= 1e-6:
        return None
    return float(np.sum(values * weights) / total)


def _weighted_percentile(values: np.ndarray, mask: np.ndarray, low_q: float, high_q: float) -> float:
    region = values[mask > 0.1]
    if region.size == 0:
        return 0.0
    return float(np.percentile(region, high_q) - np.percentile(region, low_q))


def _region_sharpness(gray: np.ndarray, mask: np.ndarray) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    center = gray[1:-1, 1:-1] * -4.0
    neighbors = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    lap = np.abs(center + neighbors)
    region = lap[mask[1:-1, 1:-1] > 0.1]
    if region.size == 0:
        return 0.0
    return float(np.mean(region))


def _add_timing(perf_timings: dict[str, float], key: str, started_at: float) -> None:
    perf_timings[key] = perf_timings.get(key, 0.0) + (time.perf_counter() - started_at) * 1000.0


def _resize_for_metrics(image: Image.Image, max_side: int = 960) -> Image.Image:
    longest = max(image.width, image.height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize(
        (
            max(64, int(round(image.width * scale))),
            max(64, int(round(image.height * scale))),
        ),
        Image.Resampling.BILINEAR,
    )


def _scale_box(
    box: tuple[int, int, int, int],
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    src_w, src_h = source_size
    dst_w, dst_h = target_size
    if src_w <= 0 or src_h <= 0:
        return box
    x0, y0, x1, y1 = box
    return (
        int(round(x0 * dst_w / src_w)),
        int(round(y0 * dst_h / src_h)),
        int(round(x1 * dst_w / src_w)),
        int(round(y1 * dst_h / src_h)),
    )


def _face_box_metrics(
    luma: np.ndarray,
    sat: np.ndarray,
    redness: np.ndarray,
    hue: np.ndarray,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
    boxes: list[tuple[int, int, int, int]],
) -> list[dict[str, float]]:
    items: list[dict[str, float]] = []
    for box in boxes:
        x0, y0, x1, y1 = _scale_box(box, source_size, target_size)
        x0 = max(0, min(target_size[0], x0))
        x1 = max(0, min(target_size[0], x1))
        y0 = max(0, min(target_size[1], y0))
        y1 = max(0, min(target_size[1], y1))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        region_mask = np.zeros_like(luma, dtype=np.float32)
        region_mask[y0:y1, x0:x1] = 1.0
        items.append(
            {
                "luma": float(np.mean(luma[y0:y1, x0:x1])),
                "saturation": float(np.mean(sat[y0:y1, x0:x1])),
                "redness": float(np.mean(redness[y0:y1, x0:x1])),
                "hue": float(np.mean(hue[y0:y1, x0:x1])),
                "sharpness": _region_sharpness(luma, region_mask),
            }
        )
    return items


def _candidate_metrics(
    image: Image.Image,
    result: AnalysisResult | None,
    perf_timings: dict[str, float],
) -> dict[str, object]:
    started_at = time.perf_counter()
    metric_image = _resize_for_metrics(image)
    arr = as_array(metric_image)
    luma = luma_map(arr)
    sat = saturation_map(arr)
    hue = hue_map(arr)
    redness = skin_redness_map(arr)
    masks = build_region_masks(result, metric_image.size, perf_timings=perf_timings, working_max_side=680)

    face_mask = masks["face"]
    subject_mask = masks["subject"]
    subject_only_mask = masks["subject_only"]
    background_mask = masks["background"]
    highlight_mask = masks["highlight"]

    subject_luma = _weighted_mean(luma, subject_mask)
    background_luma = _weighted_mean(luma, background_mask)
    background_highlight_luma = _weighted_mean(
        luma,
        background_mask * highlight_mask * (luma >= 0.80).astype(np.float32),
    )
    separation = 0.0
    if subject_luma is not None and background_luma is not None:
        separation = abs(subject_luma - background_luma)

    dark_clothing_mask = np.clip(
        subject_only_mask * ((luma >= 0.05) & (luma <= 0.28) & (sat <= 0.40)).astype(np.float32),
        0.0,
        1.0,
    )
    skin_mask = np.clip(subject_mask * skin_like_mask(arr).astype(np.float32), 0.0, 1.0)
    exposed_skin_mask = np.clip(subject_only_mask * skin_like_mask(arr).astype(np.float32) * (luma >= 0.18).astype(np.float32), 0.0, 1.0)
    subject_midtone_mask = np.clip(subject_only_mask * (1.0 - np.abs(luma - 0.50) / 0.34), 0.0, 1.0)
    clothing_color_mask = np.clip(
        subject_only_mask * (1.0 - skin_mask) * ((sat >= 0.05) & (luma >= 0.10) & (luma <= 0.82)).astype(np.float32),
        0.0,
        1.0,
    )
    background_color_mask = np.clip(
        background_mask * ((sat >= 0.04) & (luma >= 0.14) & (luma <= 0.88)).astype(np.float32),
        0.0,
        1.0,
    )

    face_boxes = result.validated_face_boxes if result is not None and result.validated_face_boxes else (
        result.face_boxes if result is not None else []
    )
    face_items = _face_box_metrics(
        luma,
        sat,
        redness,
        hue,
        image.size,
        metric_image.size,
        face_boxes,
    )
    face_lumas = [item["luma"] for item in face_items]
    face_sats = [item["saturation"] for item in face_items]
    face_redness = [item["redness"] for item in face_items]
    face_hues = [item["hue"] for item in face_items]
    skin_redness = _weighted_mean(redness, skin_mask) or 0.0

    _add_timing(perf_timings, "candidate_scoring", started_at)
    return {
        "face_luma": _weighted_mean(luma, face_mask) or 0.0,
        "face_saturation": _weighted_mean(sat, face_mask) or 0.0,
        "subject_luma": subject_luma or 0.0,
        "background_luma": background_luma or 0.0,
        "background_highlight_luma": background_highlight_luma or 0.0,
        "subject_background_separation": separation,
        "subject_local_range": _weighted_percentile(luma, subject_mask, 15, 85),
        "face_local_range": _weighted_percentile(luma, face_mask, 20, 80),
        "subject_midtone_contrast": _weighted_percentile(luma, subject_midtone_mask, 25, 75),
        "face_sharpness": _region_sharpness(luma, face_mask),
        "dark_clothing_luma": _weighted_mean(luma, dark_clothing_mask) or 0.0,
        "global_saturation": float(np.mean(sat)),
        "skin_redness": skin_redness,
        "exposed_skin_redness": _weighted_mean(redness, exposed_skin_mask) or 0.0,
        "skin_hue": _weighted_mean(hue, skin_mask) or 0.0,
        "clothing_saturation": _weighted_mean(sat, clothing_color_mask) or 0.0,
        "background_color_saturation": _weighted_mean(sat, background_color_mask) or 0.0,
        "subject_color_naturalness": 1.0 - min(1.0, max(0.0, skin_redness - 0.12) * 3.0),
        "face_items": face_items,
        "face_luma_spread": float(np.std(np.asarray(face_lumas, dtype=np.float32))) if len(face_lumas) > 1 else 0.0,
        "face_sat_spread": float(np.std(np.asarray(face_sats, dtype=np.float32))) if len(face_sats) > 1 else 0.0,
        "face_redness_max": max(face_redness, default=0.0),
        "face_hue_mean": float(np.mean(np.asarray(face_hues, dtype=np.float32))) if face_hues else 0.0,
    }


def _evaluate_candidate(
    original_metrics: dict[str, object],
    candidate_metrics: dict[str, object],
    result: AnalysisResult | None,
) -> tuple[float, list[str]]:
    notes: list[str] = []
    penalties = 0.0

    if float(candidate_metrics["face_luma"]) < float(original_metrics["face_luma"]) - 0.025:
        penalties += 1.0
        notes.append("脸部亮度下降")
    if float(candidate_metrics["face_saturation"]) < float(original_metrics["face_saturation"]) - 0.05:
        penalties += 1.0
        notes.append("脸部饱和度下降")
    if float(candidate_metrics["subject_background_separation"]) < float(original_metrics["subject_background_separation"]) - 0.03:
        penalties += 1.1
        notes.append("主体背景分离变差")
    if float(candidate_metrics["dark_clothing_luma"]) > float(original_metrics["dark_clothing_luma"]) + 0.05:
        penalties += 1.0
        notes.append("深色服装被提灰")
    if float(candidate_metrics["background_highlight_luma"]) < float(original_metrics["background_highlight_luma"]) - 0.06:
        penalties += 1.1
        notes.append("高调背景被压灰")
    if float(candidate_metrics["global_saturation"]) < float(original_metrics["global_saturation"]) - 0.06:
        penalties += 0.9
        notes.append("整体饱和度下降")
    if float(candidate_metrics["skin_redness"]) > float(original_metrics["skin_redness"]) + 0.018:
        penalties += 1.2
        notes.append("肤色偏红或偏洋红")
    if float(candidate_metrics["exposed_skin_redness"]) > float(original_metrics["exposed_skin_redness"]) + 0.014:
        penalties += 1.3
        notes.append("曝光肤色偏红加重")
    if abs(float(candidate_metrics["skin_hue"]) - float(original_metrics["skin_hue"])) > 0.035:
        penalties += 0.8
        notes.append("肤色色相偏移")
    if float(candidate_metrics["face_luma_spread"]) > float(original_metrics["face_luma_spread"]) + 0.028:
        penalties += 1.0
        notes.append("脸部明暗不均加重")

    original_faces = original_metrics.get("face_items", [])
    candidate_faces = candidate_metrics.get("face_items", [])
    for original_face, candidate_face in zip(original_faces, candidate_faces):
        if float(candidate_face["luma"]) < float(original_face["luma"]) - 0.035:
            penalties += 0.7
            notes.append("单张人脸变暗")
            break
        if float(candidate_face["luma"]) > float(original_face["luma"]) + 0.10:
            penalties += 0.6
            notes.append("单张人脸提亮过度")
            break
    for original_face, candidate_face in zip(original_faces, candidate_faces):
        if float(candidate_face["saturation"]) < float(original_face["saturation"]) - 0.05:
            penalties += 0.7
            notes.append("单张人脸饱和度下降")
            break
    for original_face, candidate_face in zip(original_faces, candidate_faces):
        if float(candidate_face["redness"]) > float(original_face["redness"]) + 0.02:
            penalties += 0.9
            notes.append("单张人脸偏红")
            break

    gain = 0.0
    if result is not None:
        if result.portrait_scene_type in {"high_key_portrait", "dark_background_portrait"} and result.portrait_exposure_status == "subject_normal":
            gain += max(0.0, float(candidate_metrics["subject_local_range"]) - float(original_metrics["subject_local_range"])) * 7.0
            gain += max(0.0, float(candidate_metrics["face_sharpness"]) - float(original_metrics["face_sharpness"])) * 3.5
            gain += max(0.0, float(candidate_metrics["face_local_range"]) - float(original_metrics["face_local_range"])) * 6.0
            gain += max(0.0, float(candidate_metrics["subject_midtone_contrast"]) - float(original_metrics["subject_midtone_contrast"])) * 8.0
        elif result.portrait_scene_type == "backlit_portrait":
            gain += max(0.0, float(candidate_metrics["face_luma"]) - float(original_metrics["face_luma"])) * 4.2
            gain += max(0.0, float(candidate_metrics["subject_local_range"]) - float(original_metrics["subject_local_range"])) * 5.0
        else:
            gain += max(0.0, float(candidate_metrics["subject_local_range"]) - float(original_metrics["subject_local_range"])) * 4.0
            gain += max(0.0, float(candidate_metrics["face_sharpness"]) - float(original_metrics["face_sharpness"])) * 2.5

        if result.portrait_scene_type == "high_key_portrait":
            if float(candidate_metrics["background_highlight_luma"]) >= float(original_metrics["background_highlight_luma"]) - 0.02:
                gain += 0.18
            if float(candidate_metrics["exposed_skin_redness"]) <= float(original_metrics["exposed_skin_redness"]) + 0.006:
                gain += 0.08

        if any(issue.code == "muted_colors" for issue in result.issues):
            gain += max(0.0, float(candidate_metrics["clothing_saturation"]) - float(original_metrics["clothing_saturation"])) * 4.4
            gain += max(0.0, float(candidate_metrics["background_color_saturation"]) - float(original_metrics["background_color_saturation"])) * 3.0
            gain += max(0.0, float(candidate_metrics["subject_color_naturalness"]) - float(original_metrics["subject_color_naturalness"])) * 2.0

    score = gain - penalties * 1.6
    return score, notes
def _assess_repair_safety(
    original: Image.Image,
    fixed: Image.Image,
    result: AnalysisResult | None,
) -> list[str]:
    if result is None:
        return []

    perf_timings: dict[str, float] = {}
    original_metrics = _candidate_metrics(original, result, perf_timings)
    fixed_metrics = _candidate_metrics(fixed, result, perf_timings)
    warnings: list[str] = []

    face_lift = float(fixed_metrics["face_luma"]) - float(original_metrics["face_luma"])
    if face_lift > 0.12:
        warnings.append("人脸亮度提升过多，建议复查脸部是否偏白或失去层次。")
    if float(fixed_metrics["dark_clothing_luma"]) > float(original_metrics["dark_clothing_luma"]) + 0.05:
        warnings.append("黑色区域明显被抬亮，服装或暗背景可能开始发灰。")
    if float(fixed_metrics["global_saturation"]) < float(original_metrics["global_saturation"]) - 0.08:
        warnings.append("整体饱和度下降较明显，需留意是否出现发灰或肤色变淡。")
    if (
        result.portrait_exposure_status == "subject_normal"
        and float(fixed_metrics["background_luma"]) > float(original_metrics["background_luma"]) + 0.12
        and float(fixed_metrics["background_luma"]) > float(fixed_metrics["face_luma"]) + 0.04
    ):
        warnings.append("背景被过度抬亮，原本的暗背景氛围可能已经下降。")
    if result.portrait_scene_type == "high_key_portrait" and float(fixed_metrics["background_highlight_luma"]) < float(original_metrics["background_highlight_luma"]) - 0.06:
        warnings.append("高调背景被明显压暗，白墙或浅色建筑可能开始发灰。")
    if float(fixed_metrics["skin_redness"]) > float(original_metrics["skin_redness"]) + 0.02:
        warnings.append("肤色/裸露皮肤红度增加，建议复核脸部、手臂或膝盖是否变红。")
    return warnings


def _build_skipped_record(
    source_path: Path,
    *,
    method_ids: list[str],
    reason: str,
    notes: list[str] | None = None,
    perf_timings: dict[str, float] | None = None,
    perf_notes: list[str] | None = None,
) -> RepairRecord:
    return RepairRecord(
        source_path=source_path,
        output_path=source_path,
        method_ids=method_ids,
        warnings=[],
        policy_notes=list(notes or []),
        saved_output=False,
        skipped_reason=reason,
        applied_strength=None,
        perf_timings=dict(perf_timings or {}),
        perf_notes=list(perf_notes or []),
    )


def apply_method(
    image: Image.Image,
    method_id: str,
    result: AnalysisResult | None = None,
    *,
    strength_scale: float = 1.0,
    original_image: Image.Image | None = None,
    perf_timings: dict[str, float] | None = None,
) -> Image.Image:
    started_at = time.perf_counter()
    if method_id == "auto_tone":
        fixed = auto_tone(image, strength_scale)
    elif method_id == "recover_highlights":
        fixed = recover_highlights(image, result, strength_scale)
    elif method_id == "lift_shadows":
        fixed = lift_shadows(image, result, strength_scale)
    elif method_id == "boost_contrast":
        fixed = boost_contrast(image, result, strength_scale)
    elif method_id == "boost_vibrance":
        fixed = boost_vibrance(image, result, strength_scale)
    elif method_id == "reduce_saturation":
        fixed = reduce_saturation(image, result, strength_scale)
    elif method_id == "boost_clarity":
        fixed = boost_clarity(image, result, strength_scale)
    elif method_id == "reduce_noise":
        fixed = reduce_noise(image, result, strength_scale)
    elif method_id == "cool_down":
        fixed = cool_down(image, result, strength_scale)
    elif method_id == "warm_up":
        fixed = warm_up(image, result, strength_scale)
    elif method_id == "add_magenta":
        fixed = add_magenta(image, result, strength_scale)
    elif method_id == "add_green":
        fixed = add_green(image, result, strength_scale)
    elif method_id == "portrait_local_face_enhance":
        fixed = portrait_local_face_enhance(image, result, strength_scale)
    elif method_id == "portrait_subject_midcontrast":
        fixed = portrait_subject_midcontrast(image, result, strength_scale)
    elif method_id == "portrait_dark_clothing_detail":
        fixed = portrait_dark_clothing_detail(image, result, strength_scale)
    elif method_id == "protect_high_key_background":
        fixed = protect_high_key_background(image, result, strength_scale, original_image=original_image)
    else:
        fixed = image
    if perf_timings is not None:
        _add_timing(perf_timings, f"op:{method_id}", started_at)
    return fixed


def apply_methods(
    image: Image.Image,
    method_ids: list[str],
    result: AnalysisResult | None = None,
    *,
    strength_scale: float = 1.0,
    original_image: Image.Image | None = None,
    perf_timings: dict[str, float] | None = None,
) -> Image.Image:
    fixed = image
    for method_id in method_ids:
        fixed = apply_method(
            fixed,
            method_id,
            result,
            strength_scale=strength_scale,
            original_image=original_image or image,
            perf_timings=perf_timings,
        )
    return fixed


def resolve_method_ids(result: AnalysisResult | None, selection: RepairSelection) -> list[str]:
    if selection.mode in {"adaptive", "auto"}:
        return suggest_methods_for_result(result)
    return selection.selected_method_ids


def _portrait_cleanup_skip_reason(result: AnalysisResult | None) -> str | None:
    if result is None:
        return None
    for candidate in result.cleanup_candidates:
        if candidate.reason_code == "portrait_out_of_focus" and candidate.confidence >= 0.58:
            return "检测到人像主体严重虚焦，建议加入“不适合保留”候选列表，不建议自动修复。"
    return None


def _summarize_perf_notes(perf_timings: dict[str, float], result: AnalysisResult | None) -> list[str]:
    notes: list[str] = []
    if perf_timings.get("analyze_total", 0.0) > 260.0:
        notes.append("分析耗时较长")
    if perf_timings.get("face_detect", 0.0) > 75.0:
        notes.append("人脸候选筛选耗时较长")
    if perf_timings.get("mask_feather", 0.0) > 95.0:
        notes.append("高分辨率 mask 羽化耗时")
    if perf_timings.get("candidate_scoring", 0.0) > 180.0:
        notes.append("候选评分耗时较长")
    if perf_timings.get("save_output", 0.0) > 220.0:
        notes.append("保存输出耗时较长")
    if perf_timings.get("metadata_preserve", 0.0) > 120.0:
        notes.append("元数据写回耗时较长")
    if result is not None and result.validated_face_count >= 3:
        notes.append(f"检测到 {result.validated_face_count} 张有效人脸")
    if result is not None and result.raw_face_candidates and not result.portrait_likely and result.portrait_rejection_reason:
        notes.append("低置信度人脸候选未启用 portrait policy")
    deduped: list[str] = []
    for note in notes:
        if note not in deduped:
            deduped.append(note)
    return deduped


def _select_portrait_candidate(
    image: Image.Image,
    method_ids: list[str],
    result: AnalysisResult,
    perf_timings: dict[str, float],
) -> tuple[Image.Image | None, float | None, list[str], list[str]]:
    original_metrics = _candidate_metrics(image, result, perf_timings)
    policy_notes = [
        f"检测到 {result.portrait_scene_type}。",
        f"当前修复策略：{result.portrait_repair_policy}。",
    ]
    if result.validated_face_count >= 2:
        policy_notes.append(f"检测到 {result.validated_face_count} 张有效人脸，候选评分采用最差人脸保护。")

    best_image: Image.Image | None = None
    best_strength: float | None = None
    best_score = 0.05
    best_warnings: list[str] = []
    rejected: list[str] = []

    for strength in (0.15, 0.25):
        started_at = time.perf_counter()
        candidate = apply_methods(
            image,
            method_ids,
            result,
            strength_scale=strength,
            original_image=image,
            perf_timings=perf_timings,
        )
        _add_timing(perf_timings, "candidate_generation", started_at)

        candidate_metrics = _candidate_metrics(candidate, result, perf_timings)
        score, notes = _evaluate_candidate(original_metrics, candidate_metrics, result)
        safe_high_key_candidate = (
            result.portrait_scene_type == "high_key_portrait"
            and strength <= 0.15
            and float(candidate_metrics["background_highlight_luma"]) >= float(original_metrics["background_highlight_luma"]) - 0.02
            and float(candidate_metrics["skin_redness"]) <= float(original_metrics["skin_redness"]) + 0.010
            and float(candidate_metrics["exposed_skin_redness"]) <= float(original_metrics["exposed_skin_redness"]) + 0.010
            and float(candidate_metrics["face_saturation"]) >= float(original_metrics["face_saturation"]) - 0.02
            and (
                float(candidate_metrics["face_local_range"]) > float(original_metrics["face_local_range"]) + 0.004
                or float(candidate_metrics["subject_midtone_contrast"]) > float(original_metrics["subject_midtone_contrast"]) + 0.004
                or float(candidate_metrics["face_sharpness"]) > float(original_metrics["face_sharpness"]) + 0.0015
            )
        )
        if score > best_score or (best_image is None and safe_high_key_candidate and score > -0.12):
            best_score = score
            best_image = candidate
            best_strength = strength
            best_warnings = _assess_repair_safety(image, candidate, result)
        else:
            reason = "、".join(notes) if notes else ("局部增强收益不足" if result.portrait_scene_type == "high_key_portrait" else "未优于原图")
            prefix = "候选被降级" if best_image is not None else "候选已回退"
            rejected.append(f"{prefix}：strength={strength:.2f} | {reason}")
            if (
                best_image is None
                and strength <= 0.15
                and result.portrait_scene_type == "dark_background_portrait"
                and not result.issues
            ):
                rejected.append("已提前停止更强候选：第一档保守增强已无明显收益。")
                break

    if best_image is None or best_strength is None:
        policy_notes.extend(rejected)
        policy_notes.append("自动修复候选未优于原图，已取消输出或保持最保守方案。")
        return None, None, [], policy_notes

    if result.portrait_scene_type == "high_key_portrait":
        policy_notes.append("已使用局部人像增强，避免白墙灰化。")
    elif result.portrait_scene_type == "dark_background_portrait":
        policy_notes.append("已限制背景提亮，优先保护黑色服装和暗背景氛围。")
    elif result.portrait_scene_type == "backlit_portrait":
        policy_notes.append("已优先保护亮背景，再对主体做温和局部增强。")
    elif result.portrait_scene_type == "multi_person_portrait":
        policy_notes.append("多人像场景已启用分脸统计和最差人脸保护。")
    policy_notes.extend(rejected)
    return best_image, best_strength, best_warnings, policy_notes


def _build_jpeg_exif(exif_bytes: bytes | None, _filename: str) -> bytes | None:
    if not exif_bytes:
        return b""
    try:
        exif = Image.Exif()
        exif.load(exif_bytes)
        # Pixels are already normalized through ImageOps.exif_transpose at load time.
        exif[274] = 1
        return exif.tobytes()
    except Exception:
        return exif_bytes


def _build_png_info(_filename: str) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", SOFTWARE_NAME)
    info.add_text("Author", AUTHOR_NAME)
    return info


def repair_image_file(
    source_path: Path,
    result: AnalysisResult | None,
    selection: RepairSelection,
    base_folder: str | Path,
) -> RepairRecord | None:
    perf_timings: dict[str, float] = {}
    repair_started_at = time.perf_counter()
    cleanup_skip_reason = _portrait_cleanup_skip_reason(result)

    started_at = time.perf_counter()
    method_ids = resolve_method_ids(result, selection)
    _add_timing(perf_timings, "planner", started_at)
    if not method_ids:
        perf_notes = _summarize_perf_notes(perf_timings, result)
        if selection.mode == "manual":
            return _build_skipped_record(
                source_path,
                method_ids=[],
                reason="未选择任何修复方法，已跳过。",
                perf_timings=perf_timings,
                perf_notes=perf_notes,
            )
        return _build_skipped_record(
            source_path,
            method_ids=[],
            reason=cleanup_skip_reason or "当前分析结果不建议自动修复，已跳过。",
            notes=(
                ["当前图片已进入“不适合保留”候选列表。"]
                if cleanup_skip_reason
                else ["自动推荐阶段未找到比原图更稳妥的修复策略。"] if result is not None and result.portrait_likely else []
            ),
            perf_timings=perf_timings,
            perf_notes=perf_notes,
        )

    with Image.open(source_path) as img:
        exif_bytes = img.info.get("exif")
        dpi = img.info.get("dpi")
        icc_profile = img.info.get("icc_profile")
        xmp_data = img.info.get("xmp")
        image = ImageOps.exif_transpose(img).convert("RGB")

    policy_notes: list[str] = []
    warnings: list[str] = []
    applied_strength: float | None = None

    if cleanup_skip_reason and selection.mode in {"adaptive", "auto"}:
        _add_timing(perf_timings, "repair_total", repair_started_at)
        perf_notes = _summarize_perf_notes(perf_timings, result)
        return RepairRecord(
            source_path=source_path,
            output_path=source_path,
            method_ids=[],
            warnings=[],
            policy_notes=["当前图片已进入“不适合保留”候选列表。"],
            saved_output=False,
            skipped_reason=cleanup_skip_reason,
            applied_strength=None,
            perf_timings=perf_timings,
            perf_notes=perf_notes,
        )

    if result is not None and result.portrait_likely:
        fixed, applied_strength, warnings, policy_notes = _select_portrait_candidate(image, method_ids, result, perf_timings)
        if fixed is None:
            _add_timing(perf_timings, "repair_total", repair_started_at)
            perf_notes = _summarize_perf_notes(perf_timings, result)
            return RepairRecord(
                source_path=source_path,
                output_path=source_path,
                method_ids=[],
                warnings=[],
                policy_notes=policy_notes,
                saved_output=False,
                skipped_reason=cleanup_skip_reason or "不建议自动修复：原图人像主体已较正常。",
                applied_strength=None,
                perf_timings=perf_timings,
                perf_notes=perf_notes,
            )
    else:
        fixed = apply_methods(
            image,
            method_ids,
            result,
            strength_scale=1.0,
            original_image=image,
            perf_timings=perf_timings,
        )
        warnings = _assess_repair_safety(image, fixed, result)

    output_path = build_repaired_output_path(
        source_path,
        base_folder,
        selection.output_folder_name,
        selection.filename_suffix,
        overwrite_original=selection.overwrite_original,
    )

    started_at = time.perf_counter()
    save_kwargs: dict[str, object] = {}
    if dpi:
        save_kwargs["dpi"] = dpi
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    if xmp_data is not None:
        save_kwargs["xmp"] = xmp_data
    if source_path.suffix.lower() in {".jpg", ".jpeg", ".jfif"}:
        save_kwargs.update({"quality": 95, "optimize": True, "exif": _build_jpeg_exif(exif_bytes, source_path.name)})
    elif source_path.suffix.lower() == ".png":
        save_kwargs["pnginfo"] = _build_png_info(source_path.name)
    elif source_path.suffix.lower() == ".webp":
        save_kwargs.update({"quality": 95, "exif": _build_jpeg_exif(exif_bytes, source_path.name)})
    _add_timing(perf_timings, "metadata_preserve", started_at)

    started_at = time.perf_counter()
    fixed.save(output_path, **save_kwargs)
    _add_timing(perf_timings, "save_output", started_at)
    _add_timing(perf_timings, "repair_total", repair_started_at)
    perf_notes = _summarize_perf_notes(perf_timings, result)

    return RepairRecord(
        source_path=source_path,
        output_path=output_path,
        method_ids=method_ids,
        warnings=warnings,
        policy_notes=policy_notes,
        saved_output=True,
        skipped_reason="",
        applied_strength=applied_strength,
        perf_timings=perf_timings,
        perf_notes=perf_notes,
    )
