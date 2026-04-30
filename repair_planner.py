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
]

REPAIR_METHOD_MAP = {method.method_id: method for method in REPAIR_METHODS}


def get_repair_methods() -> list[RepairMethod]:
    return list(REPAIR_METHODS)


def suggest_methods_for_result(result: AnalysisResult | None) -> list[str]:
    if result is None:
        return []

    ordered: list[str] = []
    seen: set[str] = set()

    def add(method_id: str) -> None:
        if method_id not in seen and method_id in REPAIR_METHOD_MAP:
            seen.add(method_id)
            ordered.append(method_id)

    for issue in result.issues:
        if issue.code == "overexposed":
            add("recover_highlights")
        elif issue.code == "underexposed":
            add("lift_shadows")
            if issue.score >= 0.55:
                add("reduce_noise")
            if issue.score >= 0.72:
                add("boost_contrast")
        elif issue.code == "low_contrast":
            add("auto_tone")
            add("boost_contrast")
        elif issue.code == "flat_tone":
            add("boost_contrast")
        elif issue.code == "muted_colors":
            add("boost_vibrance")
            if issue.score >= 0.55:
                add("boost_contrast")
        elif issue.code == "over_saturated":
            add("reduce_saturation")
        elif issue.code == "out_of_focus":
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
