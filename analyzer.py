from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageOps

from models import AnalysisResult, Issue, MetricItem


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".jfif"}


def _level(score: float) -> str:
    if score >= 0.82:
        return "严重"
    if score >= 0.62:
        return "明显"
    return "轻微"


def _metric(label: str, value: float, display: str, color: str, max_value: float = 1.0) -> MetricItem:
    ratio = 0.0 if max_value <= 0 else max(0.0, min(1.0, value / max_value))
    return MetricItem(label=label, value=display, ratio=ratio, color=color)


def _laplacian_variance(gray: np.ndarray) -> float:
    center = gray[1:-1, 1:-1] * -4.0
    neighbors = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    laplacian = center + neighbors
    return float(np.var(laplacian))


def _local_range(gray: np.ndarray) -> float:
    step = max(1, min(gray.shape[0], gray.shape[1]) // 32)
    sampled = gray[::step, ::step]
    return float(np.percentile(sampled, 90) - np.percentile(sampled, 10))


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
        "红": r_mean - mean_value,
        "绿": g_mean - mean_value,
        "蓝": b_mean - mean_value,
    }
    positive = {name for name, value in offsets.items() if value > 0.015}
    negative = min(offsets.items(), key=lambda item: item[1])[0]

    if positive == {"红", "绿"}:
        bias_name = "偏黄暖"
        suggestion = "建议略降低色温，观察白色衣物或墙面是否发黄。"
        method_hint = "cool_down"
    elif positive == {"绿", "蓝"}:
        bias_name = "偏青冷"
        suggestion = "建议略提升色温或微调品红，观察肤色是否偏冷。"
        method_hint = "warm_up"
    elif positive == {"红", "蓝"}:
        bias_name = "偏洋红"
        suggestion = "建议往绿色方向微调白平衡，避免肤色偏粉紫。"
        method_hint = "add_green"
    elif "红" in positive:
        bias_name = "偏红"
        suggestion = "建议适度降低红色或色温，检查高光区域是否偏暖。"
        method_hint = "cool_down"
    elif "绿" in positive:
        bias_name = "偏绿"
        suggestion = "建议向品红方向微调，重点检查肤色和中性灰区域。"
        method_hint = "add_magenta"
    else:
        bias_name = "偏蓝"
        suggestion = "建议适度提升色温，检查白色区域是否发蓝。"
        method_hint = "warm_up"

    detail = f"整体{bias_name}，最大通道偏差 {rgb_balance:.3f}，相对被压低的是{negative}通道。"
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


def analyze_image(
    path: str | Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> AnalysisResult:
    image_path = Path(path)
    if progress_callback is not None:
        progress_callback(1, 5, "读取图像")
    with Image.open(image_path) as img:
        rgb = ImageOps.exif_transpose(img).convert("RGB")

    arr = np.asarray(rgb, dtype=np.float32)
    gray = (arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114) / 255.0

    if progress_callback is not None:
        progress_callback(2, 5, "统计亮度、对比与动态范围")
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

    if progress_callback is not None:
        progress_callback(3, 5, "计算锐度、色彩与噪声特征")
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
    over_score = min(
        1.0,
        max(
            0.0,
            (clipped_highlights - 0.03) * 8.0
            + (highlight_ratio - 0.08) * 2.5
            + max(0.0, brightness - 0.84) * 1.8
            + max(0.0, p99 - 0.985) * 2.5
            + max(0.0, p999 - 0.995) * 1.5,
        ),
    )
    if over_score >= 0.38:
        issues.append(
            _issue(
                "overexposed",
                "过曝",
                over_score,
                f"高亮占比 {highlight_ratio:.1%}，近白剪切区域 {clipped_highlights:.1%}，亮部细节开始流失。",
                "建议降低曝光补偿 0.3 到 1 EV，拍摄时观察直方图右侧是否顶死。",
            )
        )

    p50 = float(np.percentile(gray, 50))
    p95 = float(np.percentile(gray, 95))
    low_key_relief = (
        max(0.0, dyn_range - 0.75) * 3.0
        + max(0.0, p95 - 0.84) * 4.5
        + max(0.0, highlight_ratio - 0.02) * 6.0
        + max(0.0, p99 - 0.96) * 4.0
    )
    under_score = min(
        1.0,
        max(
            0.0,
            (crushed_shadows - 0.04) * 7.5
            + (shadow_ratio - 0.14) * 1.8
            + max(0.0, 0.24 - brightness) * 2.6
            + max(0.0, 0.18 - p50) * 2.2
            - low_key_relief,
        ),
    )
    if under_score >= 0.34:
        issues.append(
            _issue(
                "underexposed",
                "欠曝",
                under_score,
                f"暗部占比 {shadow_ratio:.1%}，近黑压死区域 {crushed_shadows:.1%}，中间调亮度偏低。",
                "建议适度提高曝光、补光或延长快门；后期提亮时优先抬阴影和中间调，而不是整体硬拉亮度。",
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
                f"局部清晰区域不足，锐度分位值 P90={sharp_p90:.4f}，峰值={sharp_max:.4f}，说明主体区域也偏软。",
                "建议优先检查主体眼部或主要边缘，提升快门、缩短对焦误差，必要时连拍挑片。",
            )
        )

    low_contrast_score = min(1.0, max(0.0, (0.16 - contrast) * 4.0 + max(0.0, 0.33 - dyn_range)))
    if low_contrast_score >= 0.36:
        issues.append(
            _issue(
                "low_contrast",
                "低对比度",
                low_contrast_score,
                f"全局对比度 {contrast:.3f} 偏低，动态范围 {dyn_range:.3f}，画面黑白层次拉不开。",
                "建议适度提升对比度、黑场和白场，阴天或逆光环境可考虑局部对比增强。",
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
        issues.append(
            _issue(
                "color_cast",
                "偏色",
                cast_score,
                f"{detail} 当前判定为 {bias_name}。",
                suggestion,
                meta=meta,
            )
        )

    portrait_relief = (
        max(0.0, skin_ratio - 0.015) * 6.0
        + max(0.0, neutral_ratio - 0.08) * 0.8
        + max(0.0, 0.18 - rgb_balance) * 0.6
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
                f"平均饱和度 {mean_saturation:.3f} 偏低，高饱和区域不足，画面色彩表现偏平。",
                "建议优先轻微提升自然饱和度或局部颜色层次，避免直接把全部颜色一把拉满。",
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
                "饱和度偏高",
                over_saturation_score,
                f"中高亮区域饱和度偏强（中间调均值 {mid_mean_saturation:.3f}，亮部高饱和占比 {bright_high_sat_ratio:.1%}），颜色可能开始失真或刺眼。",
                "建议优先压制中高亮区域的极端颜色，而不是把整张图片一并去色；重点观察肤色、霓虹灯和高纯色物体是否过于扎眼。",
            )
        )

    noise_score = min(1.0, max(0.0, (noise_score_raw - 0.035) * 11.0))
    if noise_score >= 0.42:
        issues.append(
            _issue(
                "high_noise",
                "噪点偏高",
                noise_score,
                f"高频噪声指标 {noise_score_raw:.4f} 偏高，细节区域有颗粒化风险。",
                "建议降低 ISO、增加光照，或在后期启用适度降噪并保留边缘细节。",
            )
        )

    flat_tone_score = min(
        1.0,
        max(0.0, (0.12 - local_dyn) * 4.0 + max(0.0, 0.13 - contrast) * 1.5),
    )
    if flat_tone_score >= 0.35:
        issues.append(
            _issue(
                "flat_tone",
                "层次不足",
                flat_tone_score,
                f"局部层次范围 {local_dyn:.3f} 偏窄，对比度 {contrast:.3f} 偏平，画面容易显得发灰。",
                "建议拉开白场与黑场，并适度增加局部对比或清晰度，避免整张图灰蒙蒙。",
            )
        )

    issues.sort(key=lambda item: item.score, reverse=True)
    overall = max((item.score for item in issues), default=0.0)

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
        _metric("局部锐度 P90", sharp_p90, f"{sharp_p90:.4f}", "#d16b6b", max_value=0.012),
        _metric("局部锐度峰值", sharp_max, f"{sharp_max:.4f}", "#b24e4e", max_value=0.022),
        _metric("通道偏差", rgb_balance, f"{rgb_balance:.3f}", "#c98745", max_value=0.28),
        _metric("中性偏差", neutral_balance, f"{neutral_balance:.3f}", "#ad7b45", max_value=0.18),
        _metric("平均饱和度", mean_saturation, f"{mean_saturation:.3f}", "#c96d7e", max_value=0.6),
        _metric("中间调饱和度", mid_mean_saturation, f"{mid_mean_saturation:.3f}", "#c05b70", max_value=0.6),
        _metric("高饱和占比", high_sat_ratio, f"{high_sat_ratio:.1%}", "#b95773"),
        _metric("亮部高饱和", bright_high_sat_ratio, f"{bright_high_sat_ratio:.1%}", "#b04e68", max_value=0.18),
        _metric("色相分布", hue_entropy, f"{hue_entropy:.3f}", "#9f6ac9"),
        _metric("肤色占比", skin_ratio, f"{skin_ratio:.1%}", "#cc8c73", max_value=0.2),
        _metric("噪声指标", noise_score_raw, f"{noise_score_raw:.4f}", "#7c9db7", max_value=0.05),
    ]

    return AnalysisResult(
        path=image_path,
        width=rgb.width,
        height=rgb.height,
        overall_score=overall,
        issues=issues,
        metrics=metrics,
    )


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS
