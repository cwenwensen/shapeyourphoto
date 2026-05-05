from __future__ import annotations

from models import AnalysisResult, RepairMethod


REPAIR_METHODS = [
    RepairMethod("auto_tone", "自动层次校正", "拉开黑白场，快速改善整体灰感。"),
    RepairMethod("recover_highlights", "压高光", "压住过亮区域，尽量保留亮部细节。"),
    RepairMethod("lift_shadows", "提暗部", "提升阴影和中间调，减少欠曝带来的细节损失。"),
    RepairMethod("boost_contrast", "增强对比度", "提升全局反差，让层次更清楚。"),
    RepairMethod("boost_vibrance", "增强自然饱和度", "适合色彩寡淡但不希望整体过饱和的画面。"),
    RepairMethod("reduce_saturation", "降低饱和度", "压住过强颜色，减少刺眼和失真。"),
    RepairMethod("boost_clarity", "增强清晰度", "用轻量锐化提升主体边缘和微对比。"),
    RepairMethod("reduce_noise", "轻度降噪", "减少颗粒噪点，适合高 ISO 或暗部拉亮后的图像。"),
    RepairMethod("cool_down", "降低色温 / 去偏暖", "适合整体偏黄、偏红、偏暖的画面。"),
    RepairMethod("warm_up", "升高色温 / 去偏冷", "适合整体偏蓝、偏青、偏冷的画面。"),
    RepairMethod("add_magenta", "补品红 / 去偏绿", "适合整体发绿的画面。"),
    RepairMethod("add_green", "补绿色 / 去偏洋红", "适合整体发紫或偏洋红的画面。"),
    RepairMethod("portrait_local_face_enhance", "人像局部面部增强", "对脸部做轻微局部清晰感与微对比增强，尽量不改变肤色和亮度。"),
    RepairMethod("portrait_subject_midcontrast", "人像主体中间调增强", "对人物主体做轻微局部中间调对比增强，保持整体自然。"),
    RepairMethod("portrait_dark_clothing_detail", "深色服装细节增强", "轻微提升深色衣物纹理感，避免把黑色抬成灰色。"),
    RepairMethod("protect_high_key_background", "保护高调背景", "保护白墙、浅色建筑等高调背景，避免自动修复把背景压成灰白。"),
]

REPAIR_METHOD_MAP = {method.method_id: method for method in REPAIR_METHODS}


def get_repair_methods() -> list[RepairMethod]:
    return list(REPAIR_METHODS)


def suggest_methods_for_result(result: AnalysisResult | None) -> list[str]:
    if result is None:
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    portrait_enabled = result.portrait_likely and result.validated_face_count > 0
    cleanup_reason_codes = {candidate.reason_code for candidate in result.cleanup_candidates}
    severe_portrait_focus_failure = (
        any(issue.code == "portrait_out_of_focus" and issue.score >= 0.58 for issue in result.issues)
        or "portrait_out_of_focus" in cleanup_reason_codes
    )
    portrait_subject_ok = result.portrait_exposure_status == "subject_normal" or "portrait_subject_ok" in result.diagnostic_tags
    dark_background_portrait = portrait_subject_ok and "dark_background" in result.diagnostic_tags
    high_key_portrait = result.portrait_scene_type == "high_key_portrait"
    backlit_portrait = result.portrait_scene_type == "backlit_portrait"
    multi_person_portrait = result.portrait_scene_type == "multi_person_portrait"

    def add(method_id: str) -> None:
        if method_id not in seen and method_id in REPAIR_METHOD_MAP:
            seen.add(method_id)
            ordered.append(method_id)

    if severe_portrait_focus_failure:
        return []

    if portrait_enabled:
        if high_key_portrait:
            add("protect_high_key_background")
            add("portrait_subject_midcontrast")
            add("portrait_local_face_enhance")
        elif dark_background_portrait:
            add("portrait_subject_midcontrast")
            add("portrait_local_face_enhance")
            add("portrait_dark_clothing_detail")
        elif backlit_portrait:
            add("protect_high_key_background")
            add("portrait_subject_midcontrast")
            add("portrait_local_face_enhance")
        elif multi_person_portrait:
            add("portrait_subject_midcontrast")
            add("portrait_local_face_enhance")
        elif portrait_subject_ok or result.portrait_exposure_status == "subject_bright":
            add("portrait_local_face_enhance")
            if result.portrait_exposure_status == "subject_bright":
                add("protect_high_key_background")

    for issue in result.issues:
        if issue.code == "overexposed":
            if result.portrait_scene_type not in {"high_key_portrait", "backlit_portrait"}:
                add("recover_highlights")
            elif high_key_portrait or backlit_portrait:
                add("protect_high_key_background")
                add("portrait_local_face_enhance")
                if high_key_portrait:
                    add("portrait_subject_midcontrast")
        elif issue.code == "underexposed":
            if portrait_subject_ok:
                add("portrait_subject_midcontrast")
                if dark_background_portrait:
                    add("portrait_dark_clothing_detail")
                if any(color_issue.code == "color_cast" for color_issue in result.issues):
                    add(next((color_issue.meta.get("method_hint", "cool_down") for color_issue in result.issues if color_issue.code == "color_cast"), "cool_down"))
            else:
                add("lift_shadows")
                if issue.score >= 0.55:
                    add("reduce_noise")
                if issue.score >= 0.72:
                    add("boost_contrast")
        elif issue.code == "low_contrast":
            if not dark_background_portrait and not high_key_portrait:
                add("auto_tone")
            if portrait_enabled:
                add("portrait_subject_midcontrast")
            else:
                add("boost_contrast")
        elif issue.code == "flat_tone":
            if portrait_enabled:
                add("portrait_subject_midcontrast")
            else:
                add("boost_contrast")
        elif issue.code == "muted_colors":
            add("boost_vibrance")
            if issue.score >= 0.55:
                if portrait_enabled:
                    add("portrait_subject_midcontrast")
                else:
                    add("boost_contrast")
        elif issue.code == "over_saturated":
            add("reduce_saturation")
        elif issue.code == "out_of_focus":
            if portrait_enabled:
                add("portrait_local_face_enhance")
            else:
                add("boost_clarity")
        elif issue.code == "high_noise":
            add("reduce_noise")
        elif issue.code == "color_cast":
            add(issue.meta.get("method_hint", "cool_down"))

    return ordered


def suggest_methods_for_results(results: list[AnalysisResult]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for result in results:
        for method_id in suggest_methods_for_result(result):
            if method_id not in seen:
                seen.add(method_id)
                ordered.append(method_id)
    return ordered


def get_method_labels(method_ids: list[str]) -> list[str]:
    return [REPAIR_METHOD_MAP[method_id].label for method_id in method_ids if method_id in REPAIR_METHOD_MAP]
