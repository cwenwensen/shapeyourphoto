# Local Test Images

This folder is for local real-photo performance and regression checks.

- Put your own real photos here when benchmarking ShapeYourPhoto.
- Image files in this folder are intentionally ignored by git and must not be committed.
- Keep this README in version control so the local benchmark convention is documented.
- Recommended coverage: portraits, similar/burst shots, architecture, window/backlit scenes, vivid color, noisy/high ISO images, and large high-resolution photos.
- Recommended local image naming: keep camera filenames when useful for burst/similar checks, or use short scenario prefixes such as `portrait_backlit_01.jpg`, `architecture_whitewall_01.jpg`, `noise_highiso_01.jpg`, `similar_burst_01.jpg`.
- If you want expected-result checks, copy `manifest.example.json` to `manifest.json` and edit it locally. `manifest.json` is ignored by git because it may contain user photo filenames.
- Manifest entries can describe filename, scene type, expected issue codes, cleanup candidate expectation, similar-group expectation, issue codes that must not appear, and notes.

If the folder is empty, benchmark scripts should skip safely.

Benchmark reports are written to the ignored `benchmark_reports/` folder by default. Reports are local diagnostics and should not be committed.
