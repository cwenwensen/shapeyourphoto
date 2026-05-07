# Performance Benchmarks

## Local Real-Image Test Folder

`/test` is reserved for local real-photo performance and regression checks.

- Real photos in `/test` are ignored by git and must not be committed.
- Keep `/test/README.md` in version control so the convention is visible.
- The folder may contain user-owned portraits, burst/similar shots, architecture, window/backlit scenes, vivid color, noisy/high ISO images, and large high-resolution photos.
- `benchmark_test_images.py` skips safely when `/test` is missing or empty.

The intended gitignore rules are:

```gitignore
/test/*
!/test/README.md
!/test/.gitkeep
```

## Timing Terms

- `wall_time`: the real time the user waited for the batch.
- `worker_cumulative_time`: the sum of each worker image job's wall time. This can be much larger than `wall_time` when workers run concurrently.
- `average_wall_time_per_image`: `wall_time / image_count`.
- `average_worker_time_per_image`: `worker_cumulative_time / successful_image_count`.
- `queue_wait_cumulative`: accumulated time jobs waited between submission and worker start.
- `parallel_efficiency`: `worker_cumulative_time / wall_time`.

Console summaries should lead with `wall_time`. Cumulative worker time is useful for diagnosis, but it is not user-visible waiting time.

## Worker Settings

Analysis worker selection is centralized in `app_settings.resolve_analysis_worker_plan()`.

- `low`: conservative, up to 2 workers.
- `medium`: balanced, up to 6 workers.
- `high`: aggressive, up to 16 workers.
- `custom`: user supplied value, capped by settings validation.

The actual worker count is also capped by the image count. Console output must show setting mode, requested workers, actual workers, and the reason when a cap applies.

## GPU State

GPU acceleration remains optional. `gpu_accel.py` detects optional CuPy CUDA, OpenCV CUDA, or torch CUDA backends when available, but the default analysis path remains CPU. If no backend is available or GPU mode is off, the app starts normally and reports CPU fallback.

Do not add CUDA, CuPy, OpenCV-CUDA, torch, pyvips, numba, or similar packages as required dependencies. Any real offload must prove that transfer and setup cost is lower than the CPU path on `/test` real images.

## 2026-05-07 Real-Image Baseline

Local `/test` contained 16 real JPG photos. Before the working-image optimization, representative timings were:

| mode | workers | wall time | avg wall/img | worker cumulative | efficiency | similar |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| single | 1 | 164.03s | 10.25s | 158.49s | 0.97x | 5.55s |
| low | 2 | 103.25s | 6.45s | 195.79s | 1.90x | 3.03s |
| medium | 6 | 53.51s | 3.34s | 283.96s | 5.31x | 1.39s |
| high | 16 | 53.29s | 3.33s | 609.98s | 11.45x | 0.94s |

The bottleneck was not Tk or Console refresh. Full-resolution `basic_stats` and `color` array work dominated, and high worker count mostly increased memory bandwidth pressure.

After the working-image path, noise scale correction, and JPEG draft feature extraction:

| mode | workers | wall time | avg wall/img | worker cumulative | efficiency | similar |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| single | 1 | 76.67s | 4.79s | 75.29s | 0.98x | 1.38s |
| low | 2 | 46.78s | 2.92s | 89.07s | 1.90x | 0.76s |
| medium | 6 | 26.21s | 1.64s | 140.11s | 5.35x | 0.34s |
| high | 16 | 23.92s | 1.49s | 274.30s | 11.47x | 0.33s |

Quality spot check on the same `/test` set remained stable: 6 issue images, 3 cleanup candidates, and 4 similar groups. The high-worker path is now faster than medium, but only modestly; the remaining bottleneck is still memory-heavy numpy/Pillow work in `basic_stats`, `color`, and portrait/quality stages.
