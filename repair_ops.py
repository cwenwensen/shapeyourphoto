from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from models import AnalysisResult


def as_array(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


def from_array(array: np.ndarray) -> Image.Image:
    clipped = np.clip(array, 0.0, 1.0)
    return Image.fromarray((clipped * 255.0).astype(np.uint8), mode="RGB")


def _issue_score(result: AnalysisResult | None, code: str, default: float = 0.0) -> float:
    if result is None:
        return default
    issue = next((item for item in result.issues if item.code == code), None)
    return issue.score if issue is not None else default


def recover_highlights(image: Image.Image) -> Image.Image:
    arr = as_array(image)
    mask = np.clip((arr - 0.72) / 0.28, 0.0, 1.0)
    arr = arr - mask * 0.18
    return from_array(arr)


def lift_shadows(image: Image.Image, result: AnalysisResult | None) -> Image.Image:
    arr = as_array(image)
    luma = arr[:, :, 0] * 0.299 + arr[:, :, 1] * 0.587 + arr[:, :, 2] * 0.114

    severity = 0.58
    if result is not None:
        under_issue = next((issue for issue in result.issues if issue.code == "underexposed"), None)
        if under_issue is not None:
            severity = max(severity, under_issue.score)

    gamma = max(0.60, 0.82 - severity * 0.12)
    lifted = np.power(np.clip(arr, 0.0, 1.0), gamma)

    mid_shadow_mask = np.clip((luma - 0.035) / 0.22, 0.0, 1.0) * np.clip((0.78 - luma) / 0.42, 0.0, 1.0)
    mid_shadow_mask = np.sqrt(np.clip(mid_shadow_mask * (1.35 + severity * 0.35), 0.0, 1.0))[..., None]

    result_arr = arr * (1.0 - mid_shadow_mask) + lifted * mid_shadow_mask
    result_arr = result_arr + mid_shadow_mask * (0.08 + severity * 0.04) * (1.0 - result_arr)

    deep_black_mask = np.clip((0.12 - luma) / 0.12, 0.0, 1.0)[..., None]
    result_arr = result_arr * (1.0 - deep_black_mask * 0.18)

    highlight_guard = np.clip((luma - 0.70) / 0.30, 0.0, 1.0)[..., None]
    result_arr = result_arr * (1.0 - highlight_guard * 0.06)
    return from_array(result_arr)


def cool_down(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    arr = as_array(image)
    strength = 0.04 + _issue_score(result, "color_cast", 0.3) * 0.04
    arr[:, :, 0] *= 1.0 - strength
    arr[:, :, 1] *= 0.99
    arr[:, :, 2] *= 1.0 + strength * 0.85
    return from_array(arr)


def warm_up(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    arr = as_array(image)
    strength = 0.04 + _issue_score(result, "color_cast", 0.3) * 0.04
    arr[:, :, 0] *= 1.0 + strength
    arr[:, :, 2] *= 1.0 - strength
    return from_array(arr)


def add_magenta(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    arr = as_array(image)
    strength = 0.04 + _issue_score(result, "color_cast", 0.3) * 0.05
    arr[:, :, 1] *= 1.0 - strength
    arr[:, :, 0] *= 1.0 + strength * 0.45
    arr[:, :, 2] *= 1.0 + strength * 0.45
    return from_array(arr)


def add_green(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    arr = as_array(image)
    strength = 0.05 + _issue_score(result, "color_cast", 0.3) * 0.04
    arr[:, :, 1] *= 1.0 + strength
    arr[:, :, 0] *= 1.0 - strength * 0.55
    arr[:, :, 2] *= 1.0 - strength * 0.35
    return from_array(arr)


def auto_tone(image: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(image, cutoff=1)


def boost_contrast(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    score = max(_issue_score(result, "low_contrast"), _issue_score(result, "flat_tone"), _issue_score(result, "muted_colors"))
    factor = 1.10 + score * 0.18
    return ImageEnhance.Contrast(image).enhance(factor)


def boost_vibrance(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    score = _issue_score(result, "muted_colors", 0.4)
    factor = 1.08 + score * 0.22
    return ImageEnhance.Color(image).enhance(factor)


def reduce_saturation(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    score = _issue_score(result, "over_saturated", 0.4)
    factor = max(0.72, 0.96 - score * 0.18)
    return ImageEnhance.Color(image).enhance(factor)


def boost_clarity(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    score = _issue_score(result, "out_of_focus", 0.35)
    radius = 1.4 + score * 0.9
    percent = int(105 + score * 70)
    return image.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3))


def reduce_noise(image: Image.Image, result: AnalysisResult | None = None) -> Image.Image:
    score = max(_issue_score(result, "high_noise"), _issue_score(result, "underexposed") * 0.8)
    size = 3 if score < 0.72 else 5
    return image.filter(ImageFilter.MedianFilter(size=size))
