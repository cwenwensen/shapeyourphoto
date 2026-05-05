from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from models import AnalysisResult, CleanupCandidate, FaceCandidate, FaceStat, Issue, MetricItem


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".jfif"}
_GARBLED_TEXT_FRAGMENTS = ("????", "杩", "璁", "銆", "锛", "鍙", "鏄", "鐗", "浜", "淇", "\ufffd")


def _level(score: float) -> str:
    if score >= 0.82:
        return "严重"
    if score >= 0.62:
        return "明显"
    return "轻微"


def _metric(label: str, value: float, display: str, color: str, max_value: float = 1.0) -> MetricItem:
    ratio = 0.0 if max_value <= 0 else max(0.0, min(1.0, value / max_value))
    return MetricItem(label=label, value=display, ratio=ratio, color=color)


def _looks_garbled_text(text: str) -> bool:
    if not text:
        return False
    if any(fragment in text for fragment in _GARBLED_TEXT_FRAGMENTS):
        return True
    question_count = text.count("?")
    return question_count >= 2 and question_count / max(len(text), 1) >= 0.08


def _fallback_issue_text(issue: Issue) -> tuple[str, str, str]:
    fallback_map: dict[str, tuple[str, str, str]] = {
        "overexposed": (
            "过曝",
            "亮部区域明显过亮，部分高光可能已经接近或进入裁切。",
            "建议适度压低曝光或高光，尽量保留亮部层次。",
        ),
        "underexposed": (
            "欠曝",
            "暗部信息偏少，主体细节可能被压暗。",
            "建议保守提亮主体并恢复暗部层次，避免把背景整体抬灰。",
        ),
        "out_of_focus": (
            "失焦/模糊",
            "局部清晰度不足，画面可能存在失焦或抖动问题。",
            "建议优先保留原图；自动修复只能做轻微锐化，无法真正恢复失焦细节。",
        ),
        "portrait_out_of_focus": (
            "人像主体虚焦",
            "人物脸部或主体关键区域明显未对焦，保留价值较低。",
            "不适合保留 / 建议删除；自动锐化无法恢复脸部失焦细节。",
        ),
        "low_contrast": (
            "低对比度",
            "整体层次偏平，画面对比度不足。",
            "建议轻微提升中间调对比和局部层次，避免把高光压脏或把阴影抬灰。",
        ),
        "color_cast": (
            "偏色",
            "整体存在可见偏色，中性区域可能不够自然。",
            "建议微调白平衡或色温，优先观察白色、灰色和肤色是否恢复自然。",
        ),
        "muted_colors": (
            "色彩寡淡",
            "画面整体饱和度偏低，颜色层次较弱。",
            "建议使用保守的 vibrance 式增强，优先提升低饱和区域色彩并保护肤色自然。",
        ),
        "over_saturated": (
            "过饱和",
            "颜色整体偏浓，亮部高饱和区域可能显得发脏。",
            "建议适度回收饱和度并保护高光，避免鲜艳区域细节堵塞。",
        ),
    }
    return fallback_map.get(
        issue.code,
        (
            issue.code.replace("_", " ").strip() or "诊断结果",
            "检测到一项需要关注的问题，原始说明已回退为通用描述。",
            "建议结合原图观察主体区域，再决定是否修复或清理。",
        ),
    )


def _sanitize_issues(issues: list[Issue]) -> list[Issue]:
    sanitized: list[Issue] = []
    for issue in issues:
        fallback_label, fallback_detail, fallback_suggestion = _fallback_issue_text(issue)
        label = fallback_label if _looks_garbled_text(issue.label) else issue.label
        detail = fallback_detail if _looks_garbled_text(issue.detail) else issue.detail
        suggestion = fallback_suggestion if _looks_garbled_text(issue.suggestion) else issue.suggestion
        sanitized.append(
            Issue(
                code=issue.code,
                label=label,
                score=issue.score,
                level=issue.level,
                detail=detail,
                suggestion=suggestion,
                meta=dict(issue.meta),
            )
        )
    return sanitized


def _add_timing(perf_timings: dict[str, float], key: str, started_at: float) -> None:
    perf_timings[key] = perf_timings.get(key, 0.0) + (time.perf_counter() - started_at) * 1000.0


def _laplacian_variance(gray: np.ndarray) -> float:
    center = gray[1:-1, 1:-1] * -4.0
    neighbors = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    laplacian = center + neighbors
    return float(np.var(laplacian))


def _local_range(gray: np.ndarray) -> float:
    step = max(1, min(gray.shape[0], gray.shape[1]) // 32)
    sampled = gray[::step, ::step]
    return float(np.percentile(sampled, 90) - np.percentile(sampled, 10))


def _box_iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0, ix1 - ix0)
    ih = max(0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1, (bx1 - bx0) * (by1 - by0))
    return inter / float(area_a + area_b - inter)


def _tile_sharpness(gray: np.ndarray, grid: int = 6) -> tuple[float, float, float]:
    height, width = gray.shape
    values: list[float] = []
    for yi in range(grid):
        for xi in range(grid):
            y0 = yi * height // grid
            y1 = (yi + 1) * height // grid
            x0 = xi * width // grid
            x1 = (xi + 1) * width // grid
            tile = gray[y0:y1, x0:x1]
            if tile.shape[0] < 3 or tile.shape[1] < 3:
                continue
            values.append(_laplacian_variance(tile))

    if not values:
        return 0.0, 0.0, 0.0

    sharpness = np.asarray(values, dtype=np.float32)
    return (
        float(np.percentile(sharpness, 50)),
        float(np.percentile(sharpness, 90)),
        float(np.max(sharpness)),
    )


def _issue(
    code: str,
    label: str,
    score: float,
    detail: str,
    suggestion: str,
    meta: dict[str, str] | None = None,
) -> Issue:
    return Issue(
        code=code,
        label=label,
        score=score,
        level=_level(score),
        detail=detail,
        suggestion=suggestion,
        meta=meta or {},
    )


def _describe_color_cast(
    r_mean: float, g_mean: float, b_mean: float, rgb_balance: float
) -> tuple[str, str, str, dict[str, str]]:
    mean_value = (r_mean + g_mean + b_mean) / 3.0
    offsets = {
        "red": r_mean - mean_value,
        "green": g_mean - mean_value,
        "blue": b_mean - mean_value,
    }
    positive = {name for name, value in offsets.items() if value > 0.015}
    negative = min(offsets.items(), key=lambda item: item[1])[0]

    if positive == {"red", "green"}:
        bias_name = "偏暖/偏黄"
        suggestion = "建议略微降低色温，观察白色衣物或墙面是否发黄。"
        method_hint = "cool_down"
    elif positive == {"green", "blue"}:
        bias_name = "偏冷/偏青"
        suggestion = "建议略微提高色温或微调品红，观察肤色是否偏冷。"
        method_hint = "warm_up"
    elif positive == {"red", "blue"}:
        bias_name = "偏洋红"
        suggestion = "建议向绿色方向微调白平衡，避免肤色偏粉紫。"
        method_hint = "add_green"
    elif "red" in positive:
        bias_name = "偏红"
        suggestion = "建议适度降低红色或色温，检查高光区域是否偏暖。"
        method_hint = "cool_down"
    elif "green" in positive:
        bias_name = "偏绿"
        suggestion = "建议向品红方向微调，重点检查肤色和中性灰区域。"
        method_hint = "add_magenta"
    else:
        bias_name = "偏蓝"
        suggestion = "建议适度提高色温，检查白色区域是否发蓝。"
        method_hint = "warm_up"

    detail = f"整体存在 {bias_name}，最大通道偏差 {rgb_balance:.3f}，相对被压低的是 {negative} 通道。"
    meta = {"bias_name": bias_name, "method_hint": method_hint}
    return bias_name, detail, suggestion, meta


def _saturation_map(rgb: np.ndarray) -> np.ndarray:
    rgb01 = rgb / 255.0
    maxc = np.max(rgb01, axis=2)
    minc = np.min(rgb01, axis=2)
    return np.divide(maxc - minc, np.maximum(maxc, 1e-6), out=np.zeros_like(maxc), where=maxc > 1e-6)


def _hue_map(rgb: np.ndarray) -> np.ndarray:
    rgb01 = rgb / 255.0
    r = rgb01[:, :, 0]
    g = rgb01[:, :, 1]
    b = rgb01[:, :, 2]
    maxc = np.max(rgb01, axis=2)
    minc = np.min(rgb01, axis=2)
    delta = maxc - minc
    hue = np.zeros_like(maxc)

    mask = delta > 1e-6
    rmask = mask & (maxc == r)
    gmask = mask & (maxc == g)
    bmask = mask & (maxc == b)
    hue[rmask] = ((g[rmask] - b[rmask]) / delta[rmask]) % 6.0
    hue[gmask] = ((b[gmask] - r[gmask]) / delta[gmask]) + 2.0
    hue[bmask] = ((r[bmask] - g[bmask]) / delta[bmask]) + 4.0
    return hue / 6.0


def _skin_ratio(rgb: np.ndarray) -> float:
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    maxc = np.max(rgb, axis=2)
    minc = np.min(rgb, axis=2)
    mask = (
        (r > 95)
        & (g > 40)
        & (b > 20)
        & ((maxc - minc) > 15)
        & (np.abs(r - g) > 15)
        & (r > g)
        & (r > b)
    )
    return float(np.mean(mask))


def _hue_entropy(hue: np.ndarray, saturation: np.ndarray) -> float:
    mask = saturation > 0.18
    if not np.any(mask):
        return 0.0
    hist, _ = np.histogram(hue[mask], bins=12, range=(0.0, 1.0), density=False)
    total = np.sum(hist)
    if total <= 0:
        return 0.0
    probs = hist / total
    probs = probs[probs > 1e-6]
    entropy = -np.sum(probs * np.log2(probs))
    return float(entropy / np.log2(12.0))


def _masked_mean(values: np.ndarray, mask: np.ndarray, fallback: float) -> float:
    if np.any(mask):
        return float(np.mean(values[mask]))
    return fallback


def _masked_percentile(values: np.ndarray, mask: np.ndarray, q: float, fallback: float) -> float:
    if np.any(mask):
        return float(np.percentile(values[mask], q))
    return fallback


def _region_mean(values: np.ndarray, mask: np.ndarray) -> float | None:
    if np.any(mask):
        return float(np.mean(values[mask]))
    return None


def _region_median(values: np.ndarray, mask: np.ndarray) -> float | None:
    if np.any(mask):
        return float(np.median(values[mask]))
    return None


def _region_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if ys.size == 0 or xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _merge_region_boxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not boxes:
        return None
    xs0 = [box[0] for box in boxes]
    ys0 = [box[1] for box in boxes]
    xs1 = [box[2] for box in boxes]
    ys1 = [box[3] for box in boxes]
    return min(xs0), min(ys0), max(xs1), max(ys1)


def _skin_mask_ycbcr(rgb: np.ndarray, gray: np.ndarray) -> np.ndarray:
    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]
    cb = 128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b
    maxc = np.max(rgb, axis=2)
    minc = np.min(rgb, axis=2)
    return (
        (r >= 95.0)
        & (g >= 40.0)
        & (b >= 20.0)
        & (r > g)
        & (r > b)
        & (np.abs(r - g) >= 12.0)
        & (cb >= 77.0)
        & (cb <= 127.0)
        & (cr >= 133.0)
        & (cr <= 176.0)
        & (cr >= cb + 8.0)
        & ((maxc - minc) >= 12.0)
        & (gray >= 0.22)
        & (gray <= 0.95)
    )


def _cleanup_binary_mask(mask: np.ndarray) -> np.ndarray:
    image = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    image = image.filter(ImageFilter.MaxFilter(5))
    image = image.filter(ImageFilter.MinFilter(5))
    image = image.filter(ImageFilter.MedianFilter(size=3))
    return np.asarray(image, dtype=np.uint8) >= 128


def _component_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    height, width = mask.shape
    visited = np.zeros((height, width), dtype=bool)
    components: list[tuple[int, int, int, int, int]] = []

    for y in range(height):
        for x in range(width):
            if visited[y, x] or not mask[y, x]:
                continue

            stack = [(y, x)]
            visited[y, x] = True
            min_x = max_x = x
            min_y = max_y = y
            area = 0

            while stack:
                cy, cx = stack.pop()
                area += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)

                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if not visited[ny, nx] and mask[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))

            components.append((min_x, min_y, max_x + 1, max_y + 1, area))

    return components


def _box_iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(1, (bx1 - bx0) * (by1 - by0))
    return inter / float(area_a + area_b - inter)


def _boxes_close(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> bool:
    if _box_iou(box_a, box_b) >= 0.12:
        return True
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    aw = ax1 - ax0
    ah = ay1 - ay0
    bw = bx1 - bx0
    bh = by1 - by0
    acx = (ax0 + ax1) / 2.0
    acy = (ay0 + ay1) / 2.0
    bcx = (bx0 + bx1) / 2.0
    bcy = (by0 + by1) / 2.0
    return abs(acx - bcx) <= max(aw, bw) * 0.55 and abs(acy - bcy) <= max(ah, bh) * 0.55


def _merge_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        used = [False] * len(merged)
        for idx, box in enumerate(merged):
            if used[idx]:
                continue
            x0, y0, x1, y1 = box
            used[idx] = True
            for other_idx in range(idx + 1, len(merged)):
                if used[other_idx]:
                    continue
                other = merged[other_idx]
                if _boxes_close((x0, y0, x1, y1), other):
                    ox0, oy0, ox1, oy1 = other
                    x0 = min(x0, ox0)
                    y0 = min(y0, oy0)
                    x1 = max(x1, ox1)
                    y1 = max(y1, oy1)
                    used[other_idx] = True
                    changed = True
            next_boxes.append((x0, y0, x1, y1))
        merged = next_boxes
    return merged


def _expanded_box(
    shape: tuple[int, int],
    box: tuple[int, int, int, int],
    *,
    expand_x: float = 0.0,
    expand_y_top: float = 0.0,
    expand_y_bottom: float = 0.0,
) -> tuple[int, int, int, int]:
    height, width = shape
    x0, y0, x1, y1 = box
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)
    left = max(0, int(round(x0 - bw * expand_x)))
    right = min(width, int(round(x1 + bw * expand_x)))
    top = max(0, int(round(y0 - bh * expand_y_top)))
    bottom = min(height, int(round(y1 + bh * expand_y_bottom)))
    return left, top, right, bottom


def _mask_from_box(
    shape: tuple[int, int],
    box: tuple[int, int, int, int],
    *,
    expand_x: float = 0.0,
    expand_y_top: float = 0.0,
    expand_y_bottom: float = 0.0,
) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    left, top, right, bottom = _expanded_box(
        shape,
        box,
        expand_x=expand_x,
        expand_y_top=expand_y_top,
        expand_y_bottom=expand_y_bottom,
    )
    mask[top:bottom, left:right] = True
    return mask


def _box_ring_mask(
    shape: tuple[int, int],
    box: tuple[int, int, int, int],
    *,
    expand_x: float = 0.9,
    expand_y_top: float = 0.65,
    expand_y_bottom: float = 1.0,
) -> np.ndarray:
    outer = _mask_from_box(
        shape,
        box,
        expand_x=expand_x,
        expand_y_top=expand_y_top,
        expand_y_bottom=expand_y_bottom,
    )
    inner = _mask_from_box(shape, box)
    return outer & ~inner


def _masked_laplacian_variance(values: np.ndarray, mask: np.ndarray) -> float | None:
    if values.shape[0] < 3 or values.shape[1] < 3:
        return None
    inner_mask = mask[1:-1, 1:-1]
    if np.count_nonzero(inner_mask) < 16:
        return None
    center = values[1:-1, 1:-1] * -4.0
    neighbors = values[:-2, 1:-1] + values[2:, 1:-1] + values[1:-1, :-2] + values[1:-1, 2:]
    laplacian = center + neighbors
    return float(np.var(laplacian[inner_mask]))


def _crop_mask(shape: tuple[int, int], box: tuple[int, int, int, int], inset_ratio: float) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    x0, y0, x1, y1 = box
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)
    dx = min(max(1, int(round(bw * inset_ratio))), max(1, bw // 3))
    dy = min(max(1, int(round(bh * inset_ratio))), max(1, bh // 3))
    ix0 = min(x1 - 1, x0 + dx)
    iy0 = min(y1 - 1, y0 + dy)
    ix1 = max(ix0 + 1, x1 - dx)
    iy1 = max(iy0 + 1, y1 - dy)
    mask[iy0:iy1, ix0:ix1] = True
    return mask


def _cleanup_severity(score: float) -> str:
    if score >= 0.92:
        return "critical"
    if score >= 0.72:
        return "high"
    if score >= 0.52:
        return "medium"
    return "low"


def _face_candidate_metrics(
    rgb: np.ndarray,
    gray: np.ndarray,
    box: tuple[int, int, int, int],
) -> dict[str, float]:
    x0, y0, x1, y1 = box
    crop_rgb = rgb[y0:y1, x0:x1]
    crop_gray = gray[y0:y1, x0:x1]
    height, width = crop_gray.shape
    if height < 4 or width < 4:
        return {
            "skin_ratio": 0.0,
            "inner_skin_ratio": 0.0,
            "center_skin_ratio": 0.0,
            "ring_skin_ratio": 0.0,
            "green_ratio": 0.0,
            "neutral_ratio": 1.0,
            "symmetry": 0.0,
            "vertical_skin_balance": 0.0,
            "sharpness": 0.0,
            "contrast": float(np.std(crop_gray)) if crop_gray.size else 0.0,
        }

    skin_mask = _skin_mask_ycbcr(crop_rgb, crop_gray)
    saturation = _saturation_map(crop_rgb)
    green_mask = (crop_rgb[:, :, 1] > crop_rgb[:, :, 0] * 1.05) & (crop_rgb[:, :, 1] > crop_rgb[:, :, 2] * 1.05)
    neutral_mask = (saturation < 0.12) & (crop_gray > 0.20) & (crop_gray < 0.90)

    inner_mask = _crop_mask((height, width), (0, 0, width, height), 0.18)
    center_mask = _crop_mask((height, width), (0, 0, width, height), 0.28)
    ring_mask = ~inner_mask

    top_half = slice(0, max(1, height // 2))
    bottom_half = slice(max(1, height // 2), height)
    top_skin = float(np.mean(skin_mask[top_half, :])) if skin_mask[top_half, :].size else 0.0
    bottom_skin = float(np.mean(skin_mask[bottom_half, :])) if skin_mask[bottom_half, :].size else 0.0
    vertical_skin_balance = min(top_skin, bottom_skin) / max(0.01, max(top_skin, bottom_skin))

    half_width = max(1, width // 2)
    left = crop_gray[:, :half_width]
    right = np.fliplr(crop_gray[:, width - half_width : width])
    paired_height = min(left.shape[0], right.shape[0])
    paired_width = min(left.shape[1], right.shape[1])
    if paired_height >= 2 and paired_width >= 2:
        diff = np.mean(np.abs(left[:paired_height, :paired_width] - right[:paired_height, :paired_width]))
        symmetry = max(0.0, 1.0 - min(1.0, diff / 0.22))
    else:
        symmetry = 0.0

    return {
        "skin_ratio": float(np.mean(skin_mask)),
        "inner_skin_ratio": float(np.mean(skin_mask[inner_mask])) if np.any(inner_mask) else float(np.mean(skin_mask)),
        "center_skin_ratio": float(np.mean(skin_mask[center_mask])) if np.any(center_mask) else float(np.mean(skin_mask)),
        "ring_skin_ratio": float(np.mean(skin_mask[ring_mask])) if np.any(ring_mask) else 0.0,
        "green_ratio": float(np.mean(green_mask)),
        "neutral_ratio": float(np.mean(neutral_mask)),
        "symmetry": float(symmetry),
        "vertical_skin_balance": float(vertical_skin_balance),
        "sharpness": _laplacian_variance(crop_gray) if height >= 3 and width >= 3 else 0.0,
        "contrast": float(np.std(crop_gray)),
    }


def _build_cleanup_candidates(image_path: Path, issues: list[Issue]) -> list[CleanupCandidate]:
    cleanup_candidates: list[CleanupCandidate] = []
    for issue in issues:
        reason_code = issue.meta.get("cleanup_reason_code", "")
        reason_text = issue.meta.get("cleanup_reason_text", "")
        severity = issue.meta.get("cleanup_severity", "")
        confidence_text = issue.meta.get("cleanup_confidence", "")
        enabled = issue.meta.get("cleanup_candidate", "false").lower() == "true"

        if not enabled:
            if issue.code == "out_of_focus" and issue.score >= 0.84:
                enabled = True
                reason_code = "global_out_of_focus"
                reason_text = "严重糊片，主体关键细节无法可靠辨认。"
                severity = "high"
            elif issue.code == "overexposed" and issue.score >= 0.90:
                enabled = True
                reason_code = "severe_overexposed"
                reason_text = "高光严重溢出，主要信息已不可恢复。"
                severity = "high"
            elif issue.code == "underexposed" and issue.score >= 0.92:
                enabled = True
                reason_code = "severe_underexposed"
                reason_text = "主体严重欠曝且难以辨认，保留价值较低。"
                severity = "high"

        if not enabled or not reason_code:
            continue

        cleanup_candidates.append(
            CleanupCandidate(
                image_path=image_path,
                thumbnail_path=image_path,
                reason_code=reason_code,
                reason_text=reason_text or issue.detail,
                severity=severity or _cleanup_severity(issue.score),
                confidence=float(confidence_text) if confidence_text else float(issue.score),
                source_issue=issue.code,
            )
        )
    return cleanup_candidates


def _build_mask_from_boxes(
    shape: tuple[int, int],
    boxes: list[tuple[int, int, int, int]],
    *,
    expand_x: float = 0.0,
    expand_y_top: float = 0.0,
    expand_y_bottom: float = 0.0,
) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in boxes:
        bw = max(1, x1 - x0)
        bh = max(1, y1 - y0)
        left = max(0, int(round(x0 - bw * expand_x)))
        right = min(width, int(round(x1 + bw * expand_x)))
        top = max(0, int(round(y0 - bh * expand_y_top)))
        bottom = min(height, int(round(y1 + bh * expand_y_bottom)))
        mask[top:bottom, left:right] = True
    return mask


def _expand_subject_boxes(
    shape: tuple[int, int],
    face_boxes: list[tuple[int, int, int, int]],
    portrait_likely: bool,
) -> list[tuple[int, int, int, int]]:
    height, width = shape
    if face_boxes:
        subject_boxes: list[tuple[int, int, int, int]] = []
        for x0, y0, x1, y1 in face_boxes:
            bw = max(1, x1 - x0)
            bh = max(1, y1 - y0)
            left = max(0, int(round(x0 - bw * 1.00)))
            right = min(width, int(round(x1 + bw * 1.00)))
            top = max(0, int(round(y0 - bh * 0.55)))
            bottom = min(height, int(round(y1 + bh * 2.45)))
            subject_boxes.append((left, top, right, bottom))
        return subject_boxes
    if portrait_likely:
        return [(int(width * 0.22), int(height * 0.14), int(width * 0.78), int(height * 0.94))]
    return []


def _build_subject_mask(
    shape: tuple[int, int],
    face_boxes: list[tuple[int, int, int, int]],
    portrait_likely: bool,
) -> np.ndarray:
    height, width = shape
    subject_boxes = _expand_subject_boxes(shape, face_boxes, portrait_likely)
    if subject_boxes:
        mask = np.zeros((height, width), dtype=bool)
        for box in subject_boxes:
            x0, y0, x1, y1 = box
            mask[y0:y1, x0:x1] = True
        return mask
    return np.zeros((height, width), dtype=bool)


def _detect_portrait_regions(
    image: Image.Image,
) -> dict[str, object]:
    max_side = max(image.width, image.height)
    if max_side > 320:
        scale = 320.0 / max_side
        small_size = (
            max(48, int(round(image.width * scale))),
            max(48, int(round(image.height * scale))),
        )
        small = image.resize(small_size, Image.Resampling.BILINEAR)
    else:
        small = image.copy()

    small_arr = np.asarray(small, dtype=np.float32)
    small_gray = (
        small_arr[:, :, 0] * 0.299 + small_arr[:, :, 1] * 0.587 + small_arr[:, :, 2] * 0.114
    ) / 255.0
    skin_mask = _skin_mask_ycbcr(small_arr, small_gray)
    cleaned = _cleanup_binary_mask(skin_mask)

    height, width = cleaned.shape
    central_slice = cleaned[
        height // 8 : max(height // 8 + 1, height * 7 // 8),
        width // 6 : max(width // 6 + 1, width * 5 // 6),
    ]
    central_skin_ratio = float(np.mean(central_slice)) if central_slice.size else 0.0

    total_area = float(height * width)
    center_x = width / 2.0
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []

    for x0, y0, x1, y1, area in _component_boxes(cleaned):
        bw = x1 - x0
        bh = y1 - y0
        if bw < 6 or bh < 8:
            continue
        if area < max(36, int(total_area * 0.0007)):
            continue
        area_ratio = area / total_area
        if area_ratio > 0.18:
            continue
        aspect = bw / max(bh, 1)
        if aspect < 0.45 or aspect > 1.85:
            continue

        fill_ratio = area / max(1, bw * bh)
        if fill_ratio < 0.16:
            continue

        y_center_ratio = ((y0 + y1) / 2.0) / max(height, 1)
        if y_center_ratio > 0.88:
            continue

        box_luma = float(np.mean(small_gray[y0:y1, x0:x1])) if (y1 > y0 and x1 > x0) else 0.0
        if box_luma < 0.24 or box_luma > 0.92:
            continue

        center_score = 1.0 - min(1.0, abs(((x0 + x1) / 2.0) - center_x) / max(1.0, width * 0.65))
        size_score = min(1.0, area_ratio / 0.012)
        score = fill_ratio * 0.46 + center_score * 0.24 + size_score * 0.20 + min(1.0, box_luma / 0.55) * 0.10
        if score < 0.30:
            continue

        candidates.append((score, (x0, y0, x1, y1)))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:10]
    selected_small_boxes = _merge_boxes([box for _, box in selected])[:10]

    scale_x = image.width / max(1, width)
    scale_y = image.height / max(1, height)
    full_arr = np.asarray(image, dtype=np.float32)
    full_gray = (
        full_arr[:, :, 0] * 0.299 + full_arr[:, :, 1] * 0.587 + full_arr[:, :, 2] * 0.114
    ) / 255.0
    raw_face_candidates = [
        (
            max(0, int(round(x0 * scale_x))),
            max(0, int(round(y0 * scale_y))),
            min(image.width, int(round(x1 * scale_x))),
            min(image.height, int(round(y1 * scale_y))),
        )
        for x0, y0, x1, y1 in selected_small_boxes
    ]
    raw_face_candidates = [box for box in raw_face_candidates if box[2] - box[0] >= 8 and box[3] - box[1] >= 8]

    scored_candidates = [
        (
            score,
            (
                max(0, int(round(box[0] * scale_x))),
                max(0, int(round(box[1] * scale_y))),
                min(image.width, int(round(box[2] * scale_x))),
                min(image.height, int(round(box[3] * scale_y))),
            ),
        )
        for score, box in selected
    ]

    candidate_pool: list[tuple[tuple[int, int, int, int], float]] = []
    validated_face_boxes: list[tuple[int, int, int, int]] = []
    face_confidences: list[float] = []
    face_candidates: list[FaceCandidate] = []
    for score, box in scored_candidates:
        bw = max(1, box[2] - box[0])
        bh = max(1, box[3] - box[1])
        box_area_ratio = (bw * bh) / max(1.0, float(image.width * image.height))
        aspect_ratio = bw / max(1.0, float(bh))
        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        centrality = 1.0 - min(1.0, abs(cx - image.width / 2.0) / max(1.0, image.width * 0.62))
        metrics = _face_candidate_metrics(full_arr, full_gray, box)
        confidence = min(
            1.0,
            score * 0.40
            + centrality * 0.14
            + min(1.0, box_area_ratio / 0.010) * 0.08
            + metrics["inner_skin_ratio"] * 0.18
            + metrics["center_skin_ratio"] * 0.12
            + metrics["symmetry"] * 0.08,
        )
        rejection_reasons: list[str] = []
        if bh < image.height * 0.035 or bw < image.width * 0.024:
            confidence *= 0.70
            rejection_reasons.append("尺寸过小")
        if box_area_ratio < 0.0014:
            confidence *= 0.58
            rejection_reasons.append("面积占比过低")
        if box_area_ratio > 0.060:
            confidence *= 0.72
            rejection_reasons.append("面积占比异常偏大")
        if aspect_ratio < 0.62 or aspect_ratio > 1.38:
            confidence *= 0.64
            rejection_reasons.append("宽高比不符合人脸")
        if cy < image.height * 0.08 or cy > image.height * 0.86:
            confidence *= 0.70
            rejection_reasons.append("位置过靠近画面边缘")
        if cy > image.height * 0.68:
            confidence *= 0.50
            rejection_reasons.append("位置过低，更像手部或衣物区域")
        elif cy > image.height * 0.58 and bh < image.height * 0.12:
            confidence *= 0.70
            rejection_reasons.append("下半区小目标可信度不足")
        if metrics["inner_skin_ratio"] < 0.06:
            confidence *= 0.40
            rejection_reasons.append("中心肤色占比不足")
        elif metrics["center_skin_ratio"] < 0.08 and metrics["skin_ratio"] < 0.10:
            confidence *= 0.60
            rejection_reasons.append("主体中心肤色弱")
        if metrics["ring_skin_ratio"] > metrics["inner_skin_ratio"] + 0.08:
            confidence *= 0.72
            rejection_reasons.append("肤色主要出现在边缘，缺少稳定脸部结构")
        if metrics["green_ratio"] > 0.28 and metrics["inner_skin_ratio"] < 0.12:
            confidence *= 0.35
            rejection_reasons.append("区域偏绿且肤色不足，疑似绿植纹理")
        elif metrics["green_ratio"] > 0.20:
            confidence *= 0.72
            rejection_reasons.append("绿色纹理干扰较强")
        if metrics["neutral_ratio"] > 0.72 and metrics["inner_skin_ratio"] < 0.10:
            confidence *= 0.62
            rejection_reasons.append("中性纹理占比过高，疑似椅背文字或背景边缘")
        if metrics["symmetry"] < 0.36:
            confidence *= 0.60
            rejection_reasons.append("局部结构对称性不足")
        elif metrics["symmetry"] < 0.46:
            confidence *= 0.82
            rejection_reasons.append("局部结构偏弱")
        if metrics["vertical_skin_balance"] < 0.16 and metrics["inner_skin_ratio"] < 0.15:
            confidence *= 0.72
            rejection_reasons.append("上下肤色分布不稳定")
        if metrics["contrast"] < 0.035 and metrics["inner_skin_ratio"] < 0.10:
            confidence *= 0.78
            rejection_reasons.append("局部层次过低")

        accepted = confidence >= 0.54
        candidate_pool.append((box, float(confidence)))
        face_candidates.append(
            FaceCandidate(
                box=box,
                detector_score=float(score),
                confidence=float(confidence),
                accepted=accepted,
                rejection_reasons=[] if accepted else rejection_reasons,
            )
        )
        if accepted:
            validated_face_boxes.append(box)
            face_confidences.append(float(confidence))

    if validated_face_boxes:
        deduped: list[tuple[tuple[int, int, int, int], float]] = []
        for box, confidence in sorted(zip(validated_face_boxes, face_confidences), key=lambda item: item[1], reverse=True):
            if any(_box_iou(box, kept_box) >= 0.30 for kept_box, _ in deduped):
                continue
            deduped.append((box, confidence))
        validated_face_boxes = [box for box, _ in deduped]
        face_confidences = [confidence for _, confidence in deduped]

    if len(validated_face_boxes) > 2:
        centers_x = [((box[0] + box[2]) / 2.0) for box in validated_face_boxes]
        centers_y = [((box[1] + box[3]) / 2.0) for box in validated_face_boxes]
        median_x = float(np.median(np.asarray(centers_x, dtype=np.float32)))
        median_y = float(np.median(np.asarray(centers_y, dtype=np.float32)))
        max_dx = image.width * 0.24
        max_dy = image.height * 0.28
        clustered: list[tuple[tuple[int, int, int, int], float]] = []
        for box, confidence in zip(validated_face_boxes, face_confidences):
            if (
                abs(((box[0] + box[2]) / 2.0) - median_x) <= max_dx
                and abs(((box[1] + box[3]) / 2.0) - median_y) <= max_dy
            ):
                clustered.append((box, confidence))
        if clustered:
            validated_face_boxes = [box for box, _ in clustered]
            face_confidences = [confidence for _, confidence in clustered]

    if len(validated_face_boxes) > 3:
        heights = np.asarray([box[3] - box[1] for box in validated_face_boxes], dtype=np.float32)
        centers_y = np.asarray([((box[1] + box[3]) / 2.0) for box in validated_face_boxes], dtype=np.float32)
        median_height = float(np.median(heights))
        median_center_y = float(np.median(centers_y))
        filtered: list[tuple[tuple[int, int, int, int], float]] = []
        for box, confidence in sorted(zip(validated_face_boxes, face_confidences), key=lambda item: item[1], reverse=True):
            height_ratio = (box[3] - box[1]) / max(1.0, median_height)
            center_y = (box[1] + box[3]) / 2.0
            geometry_ok = 0.58 <= height_ratio <= 1.55 and center_y <= median_center_y + image.height * 0.12
            if geometry_ok or confidence >= max(face_confidences) - 0.06:
                filtered.append((box, confidence))
        if filtered:
            filtered = filtered[:4]
            validated_face_boxes = [box for box, _ in filtered]
            face_confidences = [confidence for _, confidence in filtered]

    if 1 < len(validated_face_boxes) < 3:
        median_height = float(np.median(np.asarray([box[3] - box[1] for box in validated_face_boxes], dtype=np.float32)))
        promoted: list[tuple[tuple[int, int, int, int], float]] = []
        for box, confidence in sorted(candidate_pool, key=lambda item: item[1], reverse=True):
            if confidence < 0.38:
                continue
            if box in validated_face_boxes:
                continue
            if any(_box_iou(box, kept) >= 0.18 for kept in validated_face_boxes):
                continue
            height_ratio = (box[3] - box[1]) / max(1.0, median_height)
            center_y = (box[1] + box[3]) / 2.0
            if 0.60 <= height_ratio <= 1.85 and center_y <= image.height * 0.74:
                promoted.append((box, confidence))
            if len(promoted) >= 1:
                break
        if promoted:
            validated_face_boxes.extend([box for box, _ in promoted])
            face_confidences.extend([confidence for _, confidence in promoted])

    kept_boxes = list(validated_face_boxes)
    for candidate in face_candidates:
        if candidate.box in kept_boxes:
            candidate.accepted = True
            candidate.rejection_reasons = []
        else:
            if candidate.accepted and not candidate.rejection_reasons:
                candidate.rejection_reasons = ["与更高置信度候选重叠或聚类后被剔除"]
            candidate.accepted = False

    rejection_reason = ""
    if raw_face_candidates and not validated_face_boxes:
        rejected_reasons = []
        for candidate in sorted(face_candidates, key=lambda item: item.confidence, reverse=True):
            if candidate.accepted or not candidate.rejection_reasons:
                continue
            rejected_reasons.extend(candidate.rejection_reasons[:2])
            if len(rejected_reasons) >= 3:
                break
        reason_suffix = f" 主要原因：{'、'.join(rejected_reasons[:3])}。" if rejected_reasons else ""
        rejection_reason = f"检测到 {len(raw_face_candidates)} 个低置信度人脸候选，但未达到 portrait-aware 阈值。{reason_suffix}"

    return {
        "raw_face_candidates": raw_face_candidates[:10],
        "validated_face_boxes": validated_face_boxes[:6],
        "face_confidences": face_confidences[:6],
        "face_candidates": face_candidates[:12],
        "face_confidence": float(max(face_confidences, default=0.0)),
        "central_skin_ratio": central_skin_ratio,
        "portrait_rejection_reason": rejection_reason,
    }


def _exposure_status(value: float | None, *, dark: float, bright: float, over: float) -> str:
    if value is None:
        return "unknown"
    if value < dark:
        return "underexposed"
    if value >= over:
        return "overexposed"
    if value >= bright:
        return "bright"
    return "normal"


def _confirm_portrait(
    image_size: tuple[int, int],
    raw_face_candidates: list[tuple[int, int, int, int]],
    validated_face_boxes: list[tuple[int, int, int, int]],
    face_confidences: list[float],
    skin_ratio: float,
    central_skin_ratio: float,
) -> tuple[bool, str]:
    if not validated_face_boxes:
        if raw_face_candidates:
            return False, f"检测到 {len(raw_face_candidates)} 个低置信度人脸候选，但未启用 portrait-aware。"
        return False, ""

    best_conf = max(face_confidences, default=0.0)
    avg_conf = float(np.mean(np.asarray(face_confidences, dtype=np.float32))) if face_confidences else 0.0
    avg_face_height_ratio = float(
        np.mean(np.asarray([(box[3] - box[1]) / max(1, image_size[1]) for box in validated_face_boxes], dtype=np.float32))
    )

    if len(validated_face_boxes) >= 2 and avg_conf >= 0.48:
        return True, ""
    if len(validated_face_boxes) == 1 and best_conf >= 0.54 and avg_face_height_ratio >= 0.045 and (
        central_skin_ratio >= 0.010 or skin_ratio >= 0.008
    ):
        return True, ""
    if raw_face_candidates:
        return False, f"检测到 {len(raw_face_candidates)} 个人脸候选，但有效人脸置信度不足，未启用 portrait-aware。"
    return False, "有效人脸数量或置信度不足，未启用 portrait-aware。"


def _face_stats(
    gray: np.ndarray,
    saturation: np.ndarray,
    rgb: np.ndarray,
    face_boxes: list[tuple[int, int, int, int]],
    face_confidences: list[float],
) -> list[FaceStat]:
    stats: list[FaceStat] = []
    redness_map = np.clip(
        (rgb[:, :, 0] / 255.0) - ((rgb[:, :, 1] / 255.0) * 0.6 + (rgb[:, :, 2] / 255.0) * 0.4),
        0.0,
        1.0,
    )
    for index, box in enumerate(face_boxes):
        x0, y0, x1, y1 = box
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        gray_region = gray[y0:y1, x0:x1]
        sat_region = saturation[y0:y1, x0:x1]
        red_region = redness_map[y0:y1, x0:x1]
        sharpness = None
        if gray_region.shape[0] >= 3 and gray_region.shape[1] >= 3:
            sharpness = _laplacian_variance(gray_region)
        stats.append(
            FaceStat(
                box=box,
                confidence=float(face_confidences[index]) if index < len(face_confidences) else 0.0,
                luma_mean=float(np.mean(gray_region)),
                saturation_mean=float(np.mean(sat_region)),
                sharpness=sharpness,
                redness=float(np.mean(red_region)),
            )
        )
    return stats


def _analyze_portrait_regions(
    rgb: np.ndarray,
    gray: np.ndarray,
    saturation: np.ndarray,
    face_boxes: list[tuple[int, int, int, int]],
    face_confidences: list[float],
    raw_face_candidates: list[tuple[int, int, int, int]],
    face_candidates: list[FaceCandidate],
    portrait_likely: bool,
    portrait_rejection_reason: str,
) -> dict[str, object]:
    face_mask = _build_mask_from_boxes(gray.shape, face_boxes) if face_boxes else np.zeros_like(gray, dtype=bool)
    subject_mask = _build_subject_mask(gray.shape, face_boxes, portrait_likely)
    subject_boxes = _expand_subject_boxes(gray.shape, face_boxes, portrait_likely)
    if not np.any(subject_mask) and np.any(face_mask):
        subject_mask = face_mask.copy()
    background_mask = ~subject_mask if np.any(subject_mask) else np.ones_like(gray, dtype=bool)
    highlight_mask = background_mask & (gray >= 0.92)

    face_stats = _face_stats(gray, saturation, rgb, face_boxes, face_confidences)
    face_region = _merge_region_boxes(face_boxes)
    subject_region = _region_box(subject_mask)
    background_region = _region_box(background_mask)
    highlight_region = _region_box(highlight_mask)

    face_luma_median = _region_median(gray, face_mask)
    face_luma_mean = _region_mean(gray, face_mask)
    face_saturation_mean = _region_mean(saturation, face_mask)
    face_sharpness_mean = (
        float(np.mean(np.asarray([stat.sharpness for stat in face_stats if stat.sharpness is not None], dtype=np.float32)))
        if any(stat.sharpness is not None for stat in face_stats)
        else None
    )
    subject_luma_estimate = _region_mean(gray, subject_mask)
    subject_saturation_mean = _region_mean(saturation, subject_mask)
    subject_sharpness = _masked_laplacian_variance(gray, subject_mask)
    background_luma_estimate = _region_mean(gray, background_mask)
    background_saturation_mean = _region_mean(saturation, background_mask)
    background_sharpness = _masked_laplacian_variance(gray, background_mask)
    face_context_sharpness = max(
        (
            _masked_laplacian_variance(gray, _box_ring_mask(gray.shape, box))
            for box in face_boxes
        ),
        default=None,
    )
    highlight_clipping_ratio = (
        float(np.mean(background_mask & (gray >= 0.985))) if np.any(background_mask) else float(np.mean(gray >= 0.985))
    )

    subject_background_separation = 0.0
    if subject_luma_estimate is not None and background_luma_estimate is not None:
        subject_background_separation = abs(subject_luma_estimate - background_luma_estimate)

    face_status = _exposure_status(face_luma_mean, dark=0.31, bright=0.76, over=0.84)
    subject_status = _exposure_status(subject_luma_estimate, dark=0.28, bright=0.74, over=0.82)

    background_status = 'unknown'
    if background_luma_estimate is not None:
        if highlight_clipping_ratio >= 0.04 or background_luma_estimate >= 0.82:
            background_status = 'high_key'
        elif background_luma_estimate >= 0.72:
            background_status = 'bright'
        elif background_luma_estimate <= 0.22:
            background_status = 'dark'
        else:
            background_status = 'normal'

    portrait_scene_type = 'non_portrait'
    portrait_repair_policy = 'standard'
    portrait_exposure_status = 'not_portrait'
    diagnostic_tags: list[str] = []
    diagnostic_notes: list[str] = []
    exposure_warning_reason = ''

    if portrait_likely:
        portrait_scene_type = 'multi_person_portrait' if len(face_boxes) >= 2 else 'normal_portrait'
        diagnostic_notes.append(
            f"检测到 {len(face_boxes)} 张有效人脸，按{'多人像' if len(face_boxes) >= 2 else '人像'}场景评估曝光。"
        )

        if (
            face_status == 'normal'
            and subject_status == 'underexposed'
            and face_luma_mean is not None
            and background_luma_estimate is not None
            and face_luma_mean >= max(0.34, background_luma_estimate + 0.12)
        ):
            subject_status = 'normal'

        high_key_background = background_status in {'high_key', 'bright'}
        dark_background = background_status == 'dark'
        if high_key_background and face_status == 'normal':
            if (
                background_luma_estimate is not None
                and subject_luma_estimate is not None
                and face_luma_mean is not None
                and background_luma_estimate >= subject_luma_estimate + 0.08
                and face_luma_mean <= 0.40
            ):
                portrait_scene_type = 'backlit_portrait'
                diagnostic_tags.extend(['bright_background_portrait', 'protect_high_key_background'])
            else:
                portrait_scene_type = 'high_key_portrait'
                diagnostic_tags.extend(
                    ['high_key_background', 'bright_background_portrait', 'protect_high_key_background', 'suppress_global_highlight_compression']
                )
        elif len(face_boxes) >= 2:
            diagnostic_tags.append('multi_person_portrait')

        if face_status == 'underexposed' or subject_status == 'underexposed':
            portrait_exposure_status = 'subject_dark'
            if portrait_scene_type == 'backlit_portrait':
                portrait_repair_policy = 'gentle_subject_lift_protect_background'
                exposure_warning_reason = '检测到人像逆光或亮背景场景，应优先保护背景并温和增强主体。'
                diagnostic_notes.append('背景明显更亮，主体与背景需要分区域处理。')
            else:
                portrait_repair_policy = 'gentle_subject_lift'
                exposure_warning_reason = '检测到人像主体亮度偏低，可做温和主体提亮。'
                diagnostic_notes.append('主体与脸部亮度偏低，允许适度提亮。')
        elif face_status in {'bright', 'overexposed'} or subject_status in {'bright', 'overexposed'}:
            portrait_exposure_status = 'subject_bright'
            if portrait_scene_type == 'high_key_portrait':
                portrait_repair_policy = 'protect_face_and_high_key_background'
                exposure_warning_reason = '人物主体偏亮，背景也偏亮，不建议整体压暗，应优先保护脸部与高调背景。'
                diagnostic_notes.append('检测到人像高调背景场景。')
                diagnostic_notes.append('背景偏亮但不建议整体压暗，以免白墙或浅色建筑变灰。')
            else:
                portrait_repair_policy = 'protect_face_highlights'
                exposure_warning_reason = '人像主体已经偏亮，应优先保护脸部与高光。'
                diagnostic_notes.append('主体已经偏亮，避免继续整体提亮。')
        else:
            portrait_exposure_status = 'subject_normal'
            diagnostic_tags.append('portrait_subject_ok')
            if dark_background and background_luma_estimate is not None:
                subject_reference = face_luma_mean if face_luma_mean is not None else subject_luma_estimate
                if subject_reference is not None and subject_reference > background_luma_estimate + 0.10:
                    portrait_scene_type = 'dark_background_portrait'
                    portrait_repair_policy = 'local_subject_preserve_dark_background'
                    diagnostic_tags.extend(['dark_background', 'global_underexposure_suspect_but_subject_ok'])
                    exposure_warning_reason = '主体曝光基本正常，背景偏暗但可作为氛围，不建议强行全局提亮。'
                    diagnostic_notes.append('主体曝光基本正常，背景偏暗但可作为氛围。')
            elif high_key_background:
                if portrait_scene_type == 'backlit_portrait':
                    portrait_repair_policy = 'gentle_subject_lift_protect_background'
                    exposure_warning_reason = '检测到人像逆光或亮背景场景，应优先保护背景并温和增强主体。'
                    diagnostic_notes.append('背景明显更亮，主体与背景需要分区域处理。')
                else:
                    portrait_scene_type = 'high_key_portrait'
                    portrait_repair_policy = 'local_subject_enhance_protect_high_key_background'
                    exposure_warning_reason = '人物主体曝光基本正常，背景偏亮但不建议整体压暗。'
                    diagnostic_notes.append('已优先保护高调背景，避免把白墙或浅色建筑压成灰白。')
            else:
                portrait_repair_policy = 'local_portrait_enhance_only'
                exposure_warning_reason = '检测到人像主体曝光基本正常。'
                diagnostic_notes.append('主体曝光基本正常，可优先做轻微局部增强。')
    elif portrait_rejection_reason:
        diagnostic_notes.append(portrait_rejection_reason)

    return {
        'face_mask': face_mask,
        'subject_mask': subject_mask,
        'background_mask': background_mask,
        'highlight_mask': highlight_mask,
        'face_region': face_region,
        'subject_boxes': subject_boxes,
        'subject_region': subject_region,
        'background_region': background_region,
        'highlight_region': highlight_region,
        'face_stats': face_stats,
        'face_luma_median': face_luma_median,
        'face_luma_mean': face_luma_mean,
        'face_saturation_mean': face_saturation_mean,
        'face_sharpness_mean': face_sharpness_mean,
        'subject_luma_estimate': subject_luma_estimate,
        'subject_saturation_mean': subject_saturation_mean,
        'subject_sharpness': subject_sharpness,
        'background_luma_estimate': background_luma_estimate,
        'background_saturation_mean': background_saturation_mean,
        'background_sharpness': background_sharpness,
        'face_context_sharpness': face_context_sharpness,
        'face_exposure_status': face_status,
        'subject_exposure_status': subject_status,
        'background_exposure_status': background_status,
        'highlight_clipping_ratio': highlight_clipping_ratio,
        'subject_background_separation': subject_background_separation,
        'portrait_scene_type': portrait_scene_type,
        'portrait_repair_policy': portrait_repair_policy,
        'portrait_exposure_status': portrait_exposure_status,
        'diagnostic_tags': diagnostic_tags,
        'diagnostic_notes': diagnostic_notes,
        'exposure_warning_reason': exposure_warning_reason,
        'portrait_rejection_reason': portrait_rejection_reason,
        'raw_face_candidates': raw_face_candidates,
        'face_candidates': face_candidates,
        'validated_face_boxes': face_boxes,
        'face_confidences': face_confidences,
        'face_confidence': float(max(face_confidences, default=0.0)),
    }


def analyze_image(
    path: str | Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> AnalysisResult:
    image_path = Path(path)
    perf_timings: dict[str, float] = {}
    analyze_started_at = time.perf_counter()
    if progress_callback is not None:
        progress_callback(1, 5, "读取图像")
    with Image.open(image_path) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")

    arr = np.asarray(rgb, dtype=np.float32)
    gray = (arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114) / 255.0

    if progress_callback is not None:
        progress_callback(2, 5, "统计亮度、主体与背景")
    brightness = float(np.mean(gray))
    highlight_ratio = float(np.mean(gray >= 0.96))
    clipped_highlights = float(np.mean(gray >= 0.985))
    shadow_ratio = float(np.mean(gray <= 0.08))
    crushed_shadows = float(np.mean(gray <= 0.03))
    contrast = float(np.std(gray))
    dyn_range = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    local_dyn = _local_range(gray)
    scene_detail = float(np.var(gray))
    _sharp_p50, sharp_p90, sharp_max = _tile_sharpness(gray)
    p99 = float(np.percentile(gray, 99))
    p999 = float(np.percentile(gray, 99.9))

    r_mean = float(np.mean(arr[:, :, 0])) / 255.0
    g_mean = float(np.mean(arr[:, :, 1])) / 255.0
    b_mean = float(np.mean(arr[:, :, 2])) / 255.0
    rgb_balance = max(abs(r_mean - g_mean), abs(g_mean - b_mean), abs(r_mean - b_mean))
    saturation = _saturation_map(arr)
    hue = _hue_map(arr)
    mean_saturation = float(np.mean(saturation))
    high_sat_ratio = float(np.mean(saturation >= 0.82))
    p90_saturation = float(np.percentile(saturation, 90))
    midtone_mask = (gray > 0.22) & (gray < 0.78)
    bright_mask = gray > 0.45
    shadow_mask = gray < 0.25
    green_dominant_mask = (arr[:, :, 1] > arr[:, :, 0] * 1.08) & (arr[:, :, 1] > arr[:, :, 2] * 1.08)
    mid_mean_saturation = _masked_mean(saturation, midtone_mask, mean_saturation)
    mid_p90_saturation = _masked_percentile(saturation, midtone_mask, 90, p90_saturation)
    bright_high_sat_ratio = float(np.mean(bright_mask & (saturation >= 0.82)))
    shadow_high_sat_ratio = float(np.mean(shadow_mask & (saturation >= 0.72)))
    green_ratio = float(np.mean(green_dominant_mask))
    green_high_sat_ratio = float(np.mean(green_dominant_mask & (saturation >= 0.82)))
    skin_ratio = _skin_ratio(arr)
    hue_entropy = _hue_entropy(hue, saturation)
    neutral_mask = (saturation < 0.18) & (gray > 0.18) & (gray < 0.88)
    neutral_ratio = float(np.mean(neutral_mask))
    if np.any(neutral_mask):
        neutral_r = float(np.mean(arr[:, :, 0][neutral_mask])) / 255.0
        neutral_g = float(np.mean(arr[:, :, 1][neutral_mask])) / 255.0
        neutral_b = float(np.mean(arr[:, :, 2][neutral_mask])) / 255.0
        neutral_balance = max(abs(neutral_r - neutral_g), abs(neutral_g - neutral_b), abs(neutral_r - neutral_b))
    else:
        neutral_balance = rgb_balance
    hdr_hint = 1.0 if "HDR" in image_path.name.upper() else 0.0

    started_at = time.perf_counter()
    portrait_detect = _detect_portrait_regions(rgb)
    _add_timing(perf_timings, "face_detect", started_at)
    raw_face_candidates = list(portrait_detect["raw_face_candidates"])
    validated_face_boxes = list(portrait_detect["validated_face_boxes"])
    face_confidences = list(portrait_detect["face_confidences"])
    face_candidates = list(portrait_detect.get("face_candidates", []))
    portrait_likely, portrait_rejection_reason = _confirm_portrait(
        rgb.size,
        raw_face_candidates,
        validated_face_boxes,
        face_confidences,
        skin_ratio,
        float(portrait_detect["central_skin_ratio"]),
    )

    started_at = time.perf_counter()
    portrait_data = _analyze_portrait_regions(
        arr,
        gray,
        saturation,
        validated_face_boxes,
        face_confidences,
        raw_face_candidates,
        face_candidates,
        portrait_likely,
        portrait_rejection_reason or str(portrait_detect.get("portrait_rejection_reason", "")),
    )
    _add_timing(perf_timings, "portrait_region_build", started_at)

    if progress_callback is not None:
        progress_callback(3, 5, "计算锐度、色彩与人像特征")
    noise_probe = gray - np.clip(
        (
            gray
            + np.roll(gray, 1, 0)
            + np.roll(gray, -1, 0)
            + np.roll(gray, 1, 1)
            + np.roll(gray, -1, 1)
        )
        / 5.0,
        0.0,
        1.0,
    )
    noise_score_raw = float(np.std(noise_probe))

    issues: list[Issue] = []

    if progress_callback is not None:
        progress_callback(4, 5, "判定问题标签与修复建议")
    portrait_over_relief = 0.0
    if portrait_likely:
        scene_type = str(portrait_data["portrait_scene_type"])
        portrait_exposure_status = str(portrait_data["portrait_exposure_status"])
        highlight_clipping_ratio = float(portrait_data["highlight_clipping_ratio"])
        background_exposure_status = str(portrait_data["background_exposure_status"])
        if scene_type == "high_key_portrait" and portrait_exposure_status == "subject_normal":
            portrait_over_relief += 0.72 + highlight_clipping_ratio * 2.4
            if background_exposure_status == "high_key":
                portrait_over_relief += 0.18
        elif scene_type == "backlit_portrait" and portrait_exposure_status in {"subject_normal", "subject_dark"}:
            portrait_over_relief += 0.42 + highlight_clipping_ratio * 1.4
        elif portrait_exposure_status == "subject_bright":
            portrait_over_relief -= 0.18

    over_score = min(
        1.0,
        max(
            0.0,
            (clipped_highlights - 0.03) * 8.0
            + (highlight_ratio - 0.08) * 2.5
            + max(0.0, brightness - 0.84) * 1.8
            + max(0.0, p99 - 0.985) * 2.5
            + max(0.0, p999 - 0.995) * 1.5
            - portrait_over_relief,
        ),
    )
    if over_score >= 0.38:
        if portrait_likely and str(portrait_data["portrait_scene_type"]) == "backlit_portrait":
            detail = (
                f"亮部占比 {highlight_ratio:.1%}，高光裁切约 {clipped_highlights:.1%}；"
                "当前更接近逆光人像，高亮背景对判断有明显干扰。"
            )
            suggestion = "建议优先压低背景高光并保护主体层次，避免把逆光人像整体压灰。"
        else:
            detail = f"亮部占比 {highlight_ratio:.1%}，高光裁切约 {clipped_highlights:.1%}，亮部细节已有损失风险。"
            suggestion = "建议适度降低曝光或高光，通常以回收约 0.3 到 1 EV 为起点更稳妥。"
        issues.append(_issue("overexposed", "过曝", over_score, detail, suggestion))

    p50 = float(np.percentile(gray, 50))
    p95 = float(np.percentile(gray, 95))
    low_key_relief = (
        max(0.0, dyn_range - 0.75) * 3.0
        + max(0.0, p95 - 0.84) * 4.5
        + max(0.0, highlight_ratio - 0.02) * 6.0
        + max(0.0, p99 - 0.96) * 4.0
    )
    portrait_under_relief = 0.0
    subject_dark_push = 0.0
    if portrait_likely:
        portrait_exposure_status = str(portrait_data["portrait_exposure_status"])
        face_luma_mean = portrait_data["face_luma_mean"]
        subject_luma_estimate = portrait_data["subject_luma_estimate"]
        background_luma_estimate = portrait_data["background_luma_estimate"]
        scene_type = str(portrait_data["portrait_scene_type"])
        if portrait_exposure_status == "subject_normal":
            portrait_under_relief += 0.50
            if face_luma_mean is not None:
                portrait_under_relief += max(0.0, float(face_luma_mean) - 0.38) * 1.45
            if subject_luma_estimate is not None and background_luma_estimate is not None:
                portrait_under_relief += max(0.0, float(subject_luma_estimate) - float(background_luma_estimate) - 0.10) * 1.75
            if scene_type == "high_key_portrait":
                portrait_under_relief += 0.22
        elif portrait_exposure_status == "subject_bright":
            portrait_under_relief += 0.62
        elif portrait_exposure_status == "subject_dark":
            subject_reference = face_luma_mean if face_luma_mean is not None else subject_luma_estimate
            if subject_reference is not None:
                subject_dark_push += max(0.0, 0.36 - float(subject_reference)) * 2.5
            if scene_type == "backlit_portrait":
                subject_dark_push += 0.10

    under_score = min(
        1.0,
        max(
            0.0,
            (crushed_shadows - 0.04) * 7.5
            + (shadow_ratio - 0.14) * 1.8
            + max(0.0, 0.24 - brightness) * 2.6
            + max(0.0, 0.18 - p50) * 2.2
            + subject_dark_push
            - low_key_relief
            - portrait_under_relief,
        ),
    )
    if under_score >= 0.38:
        detail = f"暗部占比 {shadow_ratio:.1%}，压黑区域 {crushed_shadows:.1%}，整体亮度偏低。"
        suggestion = "建议适度提亮暗部与中间调，同时保护高光，避免把黑色区域抬灰。"
        if portrait_likely and str(portrait_data["portrait_exposure_status"]) == "subject_dark":
            subject_value = portrait_data["subject_luma_estimate"]
            detail = (
                f"暗部占比 {shadow_ratio:.1%}，压黑区域 {crushed_shadows:.1%}；"
                f"主体亮度约 {0.0 if subject_value is None else float(subject_value):.3f}，人物主体也偏暗。"
            )
            suggestion = "建议优先做保守的人像主体提亮与局部层次修复，避免把背景一并大幅抬亮。"
        issues.append(
            _issue(
                "underexposed",
                "欠曝",
                under_score,
                detail,
                suggestion,
                meta={"severity": f"{under_score:.3f}"},
            )
        )

    texture_ready = scene_detail >= 0.0025 or dyn_range >= 0.20
    blur_score = min(
        1.0,
        max(
            0.0,
            (0.0012 - sharp_p90) / 0.0012 * 0.8
            + (0.00018 - sharp_max) / 0.00018 * 0.2,
        ),
    )
    if texture_ready and blur_score >= 0.42:
        issues.append(
            _issue(
                "out_of_focus",
                "失焦/模糊",
                blur_score,
                f"局部锐度不足，清晰度 P90={sharp_p90:.4f}，峰值={sharp_max:.4f}，画面可能存在对焦或抖动问题。",
                "建议优先保留原图；自动修复只能做轻微锐化，无法真正恢复失焦细节。",
            )
        )

    portrait_focus_score = 0.0
    if portrait_likely and validated_face_boxes:
        face_sharpness_mean = portrait_data.get("face_sharpness_mean")
        subject_sharpness = portrait_data.get("subject_sharpness")
        background_sharpness = portrait_data.get("background_sharpness")
        face_context_sharpness = portrait_data.get("face_context_sharpness")
        reference_candidates = [
            float(value)
            for value in [face_context_sharpness, background_sharpness, subject_sharpness]
            if value is not None
        ]
        reference_sharpness = max(reference_candidates, default=0.0)
        if face_sharpness_mean is not None:
            face_sharpness_value = float(face_sharpness_mean)
            sharpness_gap_ratio = reference_sharpness / max(face_sharpness_value, 1e-6)
            subject_gap_ratio = (
                float(subject_sharpness) / max(face_sharpness_value, 1e-6)
                if subject_sharpness is not None
                else sharpness_gap_ratio
            )
            base_face_blur = max(0.0, 0.00105 - face_sharpness_value) / 0.00105
            background_priority = max(0.0, sharpness_gap_ratio - 1.18) / 1.85
            subject_priority = max(0.0, subject_gap_ratio - 1.06) / 1.55
            blur_support = max(0.0, blur_score - 0.20) * 0.60
            portrait_focus_score = min(
                1.0,
                base_face_blur * 0.62 + background_priority * 0.26 + subject_priority * 0.16 + blur_support,
            )
            if portrait_focus_score >= 0.58 and (face_sharpness_value <= 0.0010 or sharpness_gap_ratio >= 1.35):
                detail = (
                    f"有效脸部锐度约 {face_sharpness_value:.4f}，"
                    f"主体/背景参考锐度约 {reference_sharpness:.4f}，"
                    f"清晰度差约 {sharpness_gap_ratio:.2f}x；人物脸部明显未对焦。"
                )
                issues.append(
                    _issue(
                        "portrait_out_of_focus",
                        "人像主体虚焦",
                        portrait_focus_score,
                        detail,
                        "不适合保留 / 建议删除；自动锐化无法恢复脸部失焦细节。",
                        meta={
                            "cleanup_candidate": "true",
                            "cleanup_reason_code": "portrait_out_of_focus",
                            "cleanup_reason_text": "正面人像脸部严重虚焦，保留价值很低。",
                            "cleanup_severity": "high",
                            "cleanup_confidence": f"{portrait_focus_score:.3f}",
                        },
                    )
                )

    low_contrast_score = min(1.0, max(0.0, (0.16 - contrast) * 4.0 + max(0.0, 0.33 - dyn_range)))
    if low_contrast_score >= 0.36:
        issues.append(
            _issue(
                "low_contrast",
                "低对比度",
                low_contrast_score,
                f"整体对比度 {contrast:.3f}、动态范围 {dyn_range:.3f} 偏低，画面层次不够通透。",
                "建议轻微提升中间调对比和局部层次，避免把高光压脏或把阴影抬灰。",
            )
        )

    cast_relief = (
        max(0.0, hue_entropy - 0.62) * 0.9
        + max(0.0, high_sat_ratio - 0.18) * 0.65
        + max(0.0, 0.10 - neutral_ratio) * 0.35
    )
    cast_score = min(1.0, max(0.0, (neutral_balance - 0.06) * 4.0 - cast_relief))
    if cast_score >= 0.36:
        bias_name, detail, suggestion, meta = _describe_color_cast(r_mean, g_mean, b_mean, rgb_balance)
        issues.append(_issue("color_cast", "偏色", cast_score, f"{detail} 当前主要表现为 {bias_name}。", suggestion, meta=meta))

    portrait_relief = (
        max(0.0, skin_ratio - 0.018) * 2.2
        + max(0.0, neutral_ratio - 0.10) * 0.35
        + max(0.0, 0.16 - rgb_balance) * 0.25
    )
    muted_color_score = min(
        1.0,
        max(
            0.0,
            (0.19 - mean_saturation) * 4.0
            + (0.36 - p90_saturation) * 1.8
            + max(0.0, 0.20 - contrast) * 0.6,
            - portrait_relief,
        ),
    )
    if muted_color_score >= 0.38:
        issues.append(
            _issue(
                "muted_colors",
                "色彩寡淡",
                muted_color_score,
                f"平均饱和度 {mean_saturation:.3f} 偏低，画面色彩层次较弱。",
                "建议使用保守的 vibrance 式增强，优先提升低饱和衣物与背景色彩，保护肤色自然。",
            )
        )

    vivid_scene_relief = (
        max(0.0, hue_entropy - 0.72) * 1.1
        + max(0.0, dyn_range - 0.62) * 0.35
        + hdr_hint * 0.24
        + max(0.0, 0.09 - neutral_balance) * 1.2
    )
    foliage_shadow_relief = (
        max(0.0, green_ratio - 0.22) * 1.6
        + max(0.0, green_high_sat_ratio - 0.12) * 1.8
        + max(0.0, shadow_high_sat_ratio - 0.18) * 1.3
        + max(0.0, 0.02 - bright_high_sat_ratio) * 6.0
    )
    over_saturation_score = min(
        1.0,
        max(
            0.0,
            (mid_mean_saturation - 0.31) * 2.6
            + (mid_p90_saturation - 0.78) * 2.0
            + (bright_high_sat_ratio - 0.012) * 9.0
            + (high_sat_ratio - 0.12) * 0.75
            - vivid_scene_relief
            - foliage_shadow_relief,
        ),
    )
    if over_saturation_score >= 0.42:
        issues.append(
            _issue(
                "over_saturated",
                "过饱和",
                over_saturation_score,
                f"中间调饱和度 {mid_mean_saturation:.3f} 偏高，亮部高饱和区域占比 {bright_high_sat_ratio:.1%}，颜色可能过于浓重。",
                "建议适度回收饱和度并保护高光，避免鲜艳区域出现脏色或细节堵塞。",
            )
        )
    if progress_callback is not None:
        progress_callback(5, 5, "生成指标与最终结果")
    metrics = [
        _metric("平均亮度", brightness, f"{brightness:.3f}", "#8fc18d"),
        _metric("高光占比", highlight_ratio, f"{highlight_ratio:.1%}", "#efb65a"),
        _metric("高光剪切", clipped_highlights, f"{clipped_highlights:.1%}", "#e47b43"),
        _metric("暗部占比", shadow_ratio, f"{shadow_ratio:.1%}", "#7189d8"),
        _metric("暗部压死", crushed_shadows, f"{crushed_shadows:.1%}", "#4f66ad"),
        _metric("全局对比度", contrast, f"{contrast:.3f}", "#8d6aca", max_value=0.45),
        _metric("动态范围", dyn_range, f"{dyn_range:.3f}", "#58b4b2"),
        _metric("局部层次", local_dyn, f"{local_dyn:.3f}", "#59a36b"),
        _metric("局部锐度P90", sharp_p90, f"{sharp_p90:.4f}", "#d16b6b", max_value=0.012),
        _metric("局部锐度峰值", sharp_max, f"{sharp_max:.4f}", "#b24e4e", max_value=0.022),
        _metric("通道偏差", rgb_balance, f"{rgb_balance:.3f}", "#c98745", max_value=0.28),
        _metric("中性偏差", neutral_balance, f"{neutral_balance:.3f}", "#ad7b45", max_value=0.18),
        _metric("平均饱和度", mean_saturation, f"{mean_saturation:.3f}", "#c96d7e", max_value=0.6),
        _metric("中间调饱和度", mid_mean_saturation, f"{mid_mean_saturation:.3f}", "#c05b70", max_value=0.6),
        _metric("高饱和占比", high_sat_ratio, f"{high_sat_ratio:.1%}", "#b95773"),
        _metric("亮部高饱和", bright_high_sat_ratio, f"{bright_high_sat_ratio:.1%}", "#b04e68", max_value=0.18),
        _metric("色相分布", hue_entropy, f"{hue_entropy:.3f}", "#9f6ac9"),
        _metric("肤色占比", skin_ratio, f"{skin_ratio:.1%}", "#cc8c73", max_value=0.2),
        _metric("有效人脸数", float(len(validated_face_boxes)), str(len(validated_face_boxes)), "#b38f5b", max_value=6.0),
        _metric("脸部亮度", float(portrait_data["face_luma_mean"] or 0.0), "-" if portrait_data["face_luma_mean"] is None else f"{float(portrait_data['face_luma_mean']):.3f}", "#d98b72"),
        _metric("脸部锐度", float(portrait_data["face_sharpness_mean"] or 0.0), "-" if portrait_data["face_sharpness_mean"] is None else f"{float(portrait_data['face_sharpness_mean']):.4f}", "#cf7f60", max_value=0.006),
        _metric("主体亮度", float(portrait_data["subject_luma_estimate"] or 0.0), "-" if portrait_data["subject_luma_estimate"] is None else f"{float(portrait_data['subject_luma_estimate']):.3f}", "#74a6c7"),
        _metric("主体锐度", float(portrait_data["subject_sharpness"] or 0.0), "-" if portrait_data["subject_sharpness"] is None else f"{float(portrait_data['subject_sharpness']):.4f}", "#6798bf", max_value=0.006),
        _metric("背景亮度", float(portrait_data["background_luma_estimate"] or 0.0), "-" if portrait_data["background_luma_estimate"] is None else f"{float(portrait_data['background_luma_estimate']):.3f}", "#62788f"),
        _metric("背景锐度", float(portrait_data["background_sharpness"] or 0.0), "-" if portrait_data["background_sharpness"] is None else f"{float(portrait_data['background_sharpness']):.4f}", "#5f7389", max_value=0.006),
        _metric("高光裁切比", float(portrait_data["highlight_clipping_ratio"]), f"{float(portrait_data['highlight_clipping_ratio']):.1%}", "#d9b36f", max_value=0.15),
        _metric("主体背景分离", float(portrait_data["subject_background_separation"]), f"{float(portrait_data['subject_background_separation']):.3f}", "#6d9fc7", max_value=0.35),
        _metric("人像失焦风险", portrait_focus_score, f"{portrait_focus_score:.2f}", "#c96363"),
        _metric("噪声指标", noise_score_raw, f"{noise_score_raw:.4f}", "#7c9db7", max_value=0.05),
    ]

    _add_timing(perf_timings, "analyze_total", analyze_started_at)
    perf_notes: list[str] = []
    if perf_timings.get("face_detect", 0.0) > 75.0:
        perf_notes.append("人脸候选筛选耗时较长")
    if perf_timings.get("portrait_region_build", 0.0) > 45.0:
        perf_notes.append("人像区域构建耗时较长")
    if perf_timings.get("analyze_total", 0.0) > 260.0:
        perf_notes.append("分析耗时较长")
    if len(validated_face_boxes) >= 3:
        perf_notes.append("检测到多人像区域")
    issues = _sanitize_issues(issues)
    overall = max((issue.score for issue in issues), default=0.0)
    cleanup_candidates = _build_cleanup_candidates(image_path, issues)

    return AnalysisResult(
        path=image_path,
        width=rgb.width,
        height=rgb.height,
        overall_score=overall,
        issues=issues,
        metrics=metrics,
        face_count=len(raw_face_candidates),
        raw_face_count=len(raw_face_candidates),
        face_boxes=validated_face_boxes,
        raw_face_candidates=raw_face_candidates,
        validated_face_boxes=validated_face_boxes,
        validated_face_count=len(validated_face_boxes),
        face_confidence=float(max(face_confidences, default=0.0)),
        face_confidences=face_confidences,
        face_candidates=face_candidates,
        subject_boxes=list(portrait_data.get("subject_boxes", [])),
        face_stats=list(portrait_data.get("face_stats", [])),
        face_region=portrait_data["face_region"],
        subject_region=portrait_data["subject_region"],
        background_region=portrait_data["background_region"],
        highlight_region=portrait_data["highlight_region"],
        portrait_likely=portrait_likely,
        portrait_scene_type=str(portrait_data["portrait_scene_type"]),
        face_luma_median=portrait_data["face_luma_median"],
        face_luma_mean=portrait_data["face_luma_mean"],
        face_saturation_mean=portrait_data["face_saturation_mean"],
        face_sharpness_mean=portrait_data.get("face_sharpness_mean"),
        subject_luma_estimate=portrait_data["subject_luma_estimate"],
        subject_saturation_mean=portrait_data["subject_saturation_mean"],
        subject_sharpness=portrait_data.get("subject_sharpness"),
        background_luma_estimate=portrait_data["background_luma_estimate"],
        background_saturation_mean=portrait_data["background_saturation_mean"],
        background_sharpness=portrait_data.get("background_sharpness"),
        face_exposure_status=str(portrait_data["face_exposure_status"]),
        subject_exposure_status=str(portrait_data["subject_exposure_status"]),
        background_exposure_status=str(portrait_data["background_exposure_status"]),
        portrait_exposure_status=str(portrait_data["portrait_exposure_status"]),
        portrait_focus_score=portrait_focus_score,
        highlight_clipping_ratio=float(portrait_data["highlight_clipping_ratio"]),
        subject_background_separation=float(portrait_data["subject_background_separation"]),
        portrait_repair_policy=str(portrait_data["portrait_repair_policy"]),
        exposure_warning_reason=str(portrait_data["exposure_warning_reason"]),
        diagnostic_tags=list(portrait_data["diagnostic_tags"]),
        diagnostic_notes=list(portrait_data["diagnostic_notes"]),
        portrait_rejection_reason=str(portrait_data.get("portrait_rejection_reason", portrait_rejection_reason)),
        cleanup_candidates=cleanup_candidates,
        perf_timings=perf_timings,
        perf_notes=perf_notes,
    )


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS
