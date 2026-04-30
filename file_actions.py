from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from analyzer import is_supported_image


def scan_image_paths(folder: str | Path) -> list[Path]:
    root = Path(folder)
    paths = [path for path in root.rglob("*") if path.is_file() and is_supported_image(path)]
    paths.sort()
    return paths


def scan_image_paths_with_progress(
    folder: str | Path,
    progress_callback: Callable[[int, int, int, Path | None], None] | None = None,
) -> list[Path]:
    root = Path(folder)
    all_files = [path for path in root.rglob("*") if path.is_file()]
    total = len(all_files)
    supported: list[Path] = []

    if progress_callback is not None:
        progress_callback(0, total, 0, None)

    for index, path in enumerate(all_files, start=1):
        if is_supported_image(path):
            supported.append(path)
        if progress_callback is not None:
            progress_callback(index, total, len(supported), path)

    supported.sort()
    return supported


def export_cleanup_list(paths: list[Path], base_folder: str | Path) -> Path:
    output_path = Path(base_folder) / "cleanup_list.txt"
    output_path.write_text("\n".join(str(path) for path in paths), encoding="utf-8")
    return output_path


def move_to_cleanup_folder(paths: list[Path], base_folder: str | Path) -> tuple[int, Path]:
    target_folder = Path(base_folder) / "_cleanup_candidates"
    target_folder.mkdir(parents=True, exist_ok=True)

    moved = 0
    for path in paths:
        destination = target_folder / path.name
        if destination.exists():
            stem = destination.stem
            suffix = destination.suffix
            index = 1
            while destination.exists():
                destination = target_folder / f"{stem}_{index}{suffix}"
                index += 1
        shutil.move(str(path), str(destination))
        moved += 1

    return moved, target_folder


def build_repaired_output_path(
    source_path: Path,
    base_folder: str | Path,
    output_folder_name: str,
    filename_suffix: str,
    overwrite_original: bool = False,
) -> Path:
    if overwrite_original:
        return source_path
    base_path = Path(base_folder)
    repair_root = base_path / output_folder_name
    try:
        relative = source_path.relative_to(base_path)
    except ValueError:
        relative = Path(source_path.name)

    output_dir = repair_root / relative.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = filename_suffix or "_fixed"
    output_name = f"{source_path.stem}{suffix}{source_path.suffix}"
    return output_dir / output_name
