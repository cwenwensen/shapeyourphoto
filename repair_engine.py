from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, PngImagePlugin

from file_actions import build_repaired_output_path
from models import AnalysisResult, RepairRecord, RepairSelection
from repair_planner import suggest_methods_for_result
from repair_ops import add_green, add_magenta, auto_tone, boost_clarity, boost_contrast, boost_vibrance, cool_down, lift_shadows, recover_highlights, reduce_noise, reduce_saturation, warm_up


SOFTWARE_NAME = "ShapeYourPhoto"
AUTHOR_NAME = "Helloalp"
AUTHOR_URL = "https://helloalp.top/tools/shapeyourphoto"


def apply_method(image: Image.Image, method_id: str, result: AnalysisResult | None = None) -> Image.Image:
    if method_id == "auto_tone":
        return auto_tone(image)
    if method_id == "recover_highlights":
        return recover_highlights(image)
    if method_id == "lift_shadows":
        return lift_shadows(image, result)
    if method_id == "boost_contrast":
        return boost_contrast(image, result)
    if method_id == "boost_vibrance":
        return boost_vibrance(image, result)
    if method_id == "reduce_saturation":
        return reduce_saturation(image, result)
    if method_id == "boost_clarity":
        return boost_clarity(image, result)
    if method_id == "reduce_noise":
        return reduce_noise(image, result)
    if method_id == "cool_down":
        return cool_down(image, result)
    if method_id == "warm_up":
        return warm_up(image, result)
    if method_id == "add_magenta":
        return add_magenta(image, result)
    if method_id == "add_green":
        return add_green(image, result)
    return image


def apply_methods(image: Image.Image, method_ids: list[str], result: AnalysisResult | None = None) -> Image.Image:
    fixed = image
    for method_id in method_ids:
        fixed = apply_method(fixed, method_id, result)
    return fixed


def resolve_method_ids(result: AnalysisResult | None, selection: RepairSelection) -> list[str]:
    if selection.mode == "adaptive":
        return suggest_methods_for_result(result)
    return selection.selected_method_ids


def _build_jpeg_exif(source_exif: bytes | None, source_name: str) -> Image.Exif:
    exif = Image.Exif()
    if source_exif:
        try:
            exif = Image.Exif()
            exif.load(source_exif)
        except Exception:
            exif = Image.Exif()
    title = f"{source_name} | Modified by {SOFTWARE_NAME} | {AUTHOR_NAME} | {AUTHOR_URL}"
    exif[0x0131] = SOFTWARE_NAME
    exif[0x013B] = AUTHOR_NAME
    exif[0x010E] = title
    exif[0x9C9B] = (title + "\x00").encode("utf-16le")
    exif[0x9C9C] = (f"Modified by {SOFTWARE_NAME} | {AUTHOR_NAME} | {AUTHOR_URL}" + "\x00").encode("utf-16le")
    exif[0x8298] = f"Modified by {SOFTWARE_NAME} | {AUTHOR_NAME} | {AUTHOR_URL}"
    return exif


def _build_png_info(source_name: str) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    info.add_text("Title", f"{source_name} | Modified by {SOFTWARE_NAME} | {AUTHOR_NAME}")
    info.add_text("Software", SOFTWARE_NAME)
    info.add_text("Author", AUTHOR_NAME)
    info.add_text("Comment", f"Modified by {SOFTWARE_NAME} | {AUTHOR_NAME} | {AUTHOR_URL}")
    return info


def repair_image_file(
    source_path: Path,
    result: AnalysisResult | None,
    selection: RepairSelection,
    base_folder: str | Path,
) -> RepairRecord | None:
    method_ids = resolve_method_ids(result, selection)
    if not method_ids:
        return None

    with Image.open(source_path) as img:
        exif_bytes = img.info.get("exif")
        dpi = img.info.get("dpi")
        icc_profile = img.info.get("icc_profile")
        xmp_data = img.info.get("xmp")
        image = ImageOps.exif_transpose(img).convert("RGB")

    fixed = apply_methods(image, method_ids, result)
    output_path = build_repaired_output_path(
        source_path,
        base_folder,
        selection.output_folder_name,
        selection.filename_suffix,
        overwrite_original=selection.overwrite_original,
    )

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
    fixed.save(output_path, **save_kwargs)
    return RepairRecord(source_path=source_path, output_path=output_path, method_ids=method_ids)
