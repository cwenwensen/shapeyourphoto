from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from analyzer import analyze_image
from app_settings import ANALYSIS_CONCURRENCY_HIGH, ANALYSIS_CONCURRENCY_LOW, ANALYSIS_CONCURRENCY_MEDIUM, resolve_analysis_worker_plan
from analysis.core import is_supported_image
from models import AnalysisResult
from similar_detector import detect_similar_groups


DEFAULT_MODES = ("single", ANALYSIS_CONCURRENCY_LOW, ANALYSIS_CONCURRENCY_MEDIUM, ANALYSIS_CONCURRENCY_HIGH)
STAGE_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("image_open", ("image_open",)),
    ("exif_transpose", ("exif_transpose",)),
    ("resize", ("resize", "working_resize")),
    ("array_convert", ("array_convert",)),
    ("basic_stats", ("basic_stats",)),
    ("exposure", ("exposure",)),
    ("color", ("color",)),
    ("sharpness", ("sharpness",)),
    ("noise", ("noise",)),
    ("portrait", ("face_detect", "portrait_region_build")),
    ("quality_stats", ("quality_stats",)),
    ("cleanup_candidate", ("cleanup_candidate",)),
)


def _format_ms(value: float) -> str:
    if value >= 1000.0:
        return f"{value / 1000.0:.2f}s"
    return f"{value:.0f}ms"


def _test_images(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_file() and is_supported_image(path)), key=lambda path: path.name.casefold())


def _resolve_workers(mode: str, image_count: int) -> tuple[str, int, int, str]:
    if mode == "single":
        return "single", 1, 1, "single-thread baseline"
    plan = resolve_analysis_worker_plan(image_count, mode, 0)
    return plan.mode, plan.requested_workers, plan.actual_workers, plan.reason


def _stage_totals(results: dict[Path, AnalysisResult], similar_ms: float) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for result in results.values():
        timings = result.perf_timings
        for label, keys in STAGE_LABELS:
            totals[label] = totals.get(label, 0.0) + sum(float(timings.get(key, 0.0)) for key in keys)
    totals["similar_detection"] = similar_ms
    return [(label, value) for label, value in sorted(totals.items(), key=lambda item: item[1], reverse=True) if value > 0.0]


def _run_mode(paths: list[Path], mode: str) -> dict[str, object]:
    mode_name, requested_workers, actual_workers, reason = _resolve_workers(mode, len(paths))
    started = time.perf_counter()
    results: dict[Path, AnalysisResult] = {}
    errors: dict[Path, str] = {}
    with ThreadPoolExecutor(max_workers=actual_workers) as pool:
        futures = {}
        for path in paths:
            queued_at = time.perf_counter()

            def job(p: Path = path, queued: float = queued_at) -> AnalysisResult:
                job_started = time.perf_counter()
                result = analyze_image(p)
                job_finished = time.perf_counter()
                result.perf_timings["worker_queue_wait"] = (job_started - queued) * 1000.0
                result.perf_timings["worker_wall_time"] = (job_finished - job_started) * 1000.0
                return result

            futures[pool.submit(job)] = path
        for future in as_completed(futures):
            path = futures[future]
            try:
                results[path] = future.result()
            except Exception as exc:
                errors[path] = str(exc)

    similar_started = time.perf_counter()
    similar_groups = detect_similar_groups(paths, results, max_workers=actual_workers)
    similar_ms = (time.perf_counter() - similar_started) * 1000.0
    wall_ms = (time.perf_counter() - started) * 1000.0
    worker_cumulative_ms = sum(
        result.perf_timings.get("worker_wall_time", result.perf_timings.get("analyze_total", 0.0))
        for result in results.values()
    )
    queue_wait_ms = sum(result.perf_timings.get("worker_queue_wait", 0.0) for result in results.values())
    slow_images = sorted(results.values(), key=lambda result: result.perf_timings.get("worker_wall_time", 0.0), reverse=True)[:5]
    return {
        "mode": mode_name,
        "requested_workers": requested_workers,
        "actual_workers": actual_workers,
        "reason": reason,
        "images": len(paths),
        "success": len(results),
        "failed": len(errors),
        "wall_ms": wall_ms,
        "avg_wall_ms": wall_ms / max(1, len(paths)),
        "worker_cumulative_ms": worker_cumulative_ms,
        "parallel_efficiency": worker_cumulative_ms / max(1.0, wall_ms),
        "queue_wait_ms": queue_wait_ms,
        "similar_ms": similar_ms,
        "similar_groups": len(similar_groups),
        "slow_stages": _stage_totals(results, similar_ms)[:5],
        "slow_images": [(result.path.name, result.perf_timings.get("worker_wall_time", 0.0)) for result in slow_images],
        "issues": sum(1 for result in results.values() if result.issues),
        "cleanup_candidates": sum(len(result.cleanup_candidates) for result in results.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local real test images under /test.")
    parser.add_argument("--root", default="test", help="Local test image folder. Defaults to ./test.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES), help="Comma-separated modes: single,low,medium,high.")
    args = parser.parse_args()

    root = Path(args.root)
    paths = _test_images(root)
    if not paths:
        print(f"No local test images found in {root.resolve()}; skipped.")
        return 0

    modes = [mode.strip().lower() for mode in args.modes.split(",") if mode.strip()]
    print(f"Local test image benchmark: root={root.resolve()} images={len(paths)}")
    print("mode | workers(requested/actual) | wall | avg wall/img | worker cumulative | efficiency | queue/wait | similar | groups | issues | cleanup")
    for mode in modes:
        result = _run_mode(paths, mode)
        reason = f" ({result['reason']})" if result["reason"] else ""
        print(
            f"{result['mode']} | {result['requested_workers']}/{result['actual_workers']}{reason} | "
            f"{_format_ms(float(result['wall_ms']))} | {_format_ms(float(result['avg_wall_ms']))} | "
            f"{_format_ms(float(result['worker_cumulative_ms']))} | {float(result['parallel_efficiency']):.2f}x | "
            f"{_format_ms(float(result['queue_wait_ms']))} | {_format_ms(float(result['similar_ms']))} | "
            f"{result['similar_groups']} | {result['issues']} | {result['cleanup_candidates']}"
        )
        print("  slow stages top5: " + " | ".join(f"{label} {_format_ms(value)}" for label, value in result["slow_stages"]))
        print("  slow images top5: " + " | ".join(f"{name} {_format_ms(value)}" for name, value in result["slow_images"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
