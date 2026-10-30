# Bounded LibreOffice and workbook parser runtime

This isolated variant retains `sheetsfactory-lo:24.2-iterative-v1` at image ID `sha256:5c74b8a362305b20d736bdbad041a12a6159e31f3bde4a0a068a7ee71d6937d6` and installs only the SHA-pinned openpyxl 3.1.5 wheel. The existing LibreOffice binary, bounded recalculation script and et-xmlfile dependency remain unchanged.

From the repository root, build once with:

```bash
.venv312/bin/python runtime/lo24.2-iterative-openpyxl315-v1/build.py
```

The builder refuses to overwrite an existing output tag or use a different base identity. It records package bytes, recipe hashes, full layer ancestry and before/after engine checks under `outputs/research/`. The output tag is `sheetsfactory-lo:24.2-iterative-openpyxl315-v1`. Ordinary workbooks use one full calculation. Workbooks that explicitly enable iteration must satisfy the existing convergence bound. Earlier runtime tags and frozen task exports remain unchanged.

No model score or task qualification is inferred from building this image.
