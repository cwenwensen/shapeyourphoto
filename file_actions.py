from __future__ import annotations

import ctypes
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from analyzer import is_supported_image


_OUTPUT_PATH_LOCK = threading.Lock()


@dataclass
class CleanupOperationResult:
    moved: int
    mode: str
    destination_label: str
    fallback_folder: Path | None = None


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


def _send_path_to_recycle_bin(path: Path) -> bool:
    if not path.exists():
        return False
    if ctypes.sizeof(ctypes.c_void_p) == 0:
        return False
    if not hasattr(ctypes, "windll") or not hasattr(ctypes.windll, "shell32"):
        return False

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    operation = SHFILEOPSTRUCTW()
    operation.wFunc = 3
    operation.pFrom = f"{str(path)}\0\0"
    operation.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return result == 0 and not bool(operation.fAnyOperationsAborted)


def safe_cleanup_paths(paths: list[Path], base_folder: str | Path) -> CleanupOperationResult:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return CleanupOperationResult(moved=0, mode="noop", destination_label="无可处理文件")

    recycled = 0
    fallback_needed = False
    pending_for_folder: list[Path] = []
    for path in existing_paths:
        if _send_path_to_recycle_bin(path):
            recycled += 1
        else:
            fallback_needed = True
            pending_for_folder.append(path)

    moved = recycled
    fallback_folder: Path | None = None
    if pending_for_folder:
        moved_to_folder, fallback_folder = move_to_cleanup_folder(pending_for_folder, base_folder)
        moved += moved_to_folder

    if recycled and not fallback_needed:
        return CleanupOperationResult(
            moved=moved,
            mode="recycle_bin",
            destination_label="系统回收站",
        )
    if fallback_folder is not None and recycled:
        return CleanupOperationResult(
            moved=moved,
            mode="mixed",
            destination_label=f"部分已移入回收站，其余移入 {fallback_folder}",
            fallback_folder=fallback_folder,
        )
    if fallback_folder is not None:
        return CleanupOperationResult(
            moved=moved,
            mode="quarantine_folder",
            destination_label=str(fallback_folder),
            fallback_folder=fallback_folder,
        )
    return CleanupOperationResult(moved=0, mode="noop", destination_label="无可处理文件")


def build_repaired_output_path(
    source_path: Path,
    base_folder: str | Path,
    output_folder_name: str,
    filename_suffix: str,
    overwrite_original: bool = False,
) -> Path:
    if overwrite_original:
        return source_path
    with _OUTPUT_PATH_LOCK:
        base_path = Path(base_folder)
        repair_root = base_path / output_folder_name
        try:
            relative = source_path.relative_to(base_path)
        except ValueError:
            relative = Path(source_path.name)

        output_dir = repair_root / relative.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = filename_suffix or "_fixed"
        candidate = output_dir / f"{source_path.stem}{suffix}{source_path.suffix}"
        if not candidate.exists():
            return candidate
        index = 1
        while True:
            numbered = output_dir / f"{source_path.stem}{suffix}_{index}{source_path.suffix}"
            if not numbered.exists():
                return numbered
            index += 1
