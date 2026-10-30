# Bounded LibreOffice and workbook parser runtime

This isolated variant retains `sheetsfactory-lo:24.2-iterative-v1` at image ID `sha256:5c74b8a362305b20d736bdbad041a12a6159e31f3bde4a0a068a7ee71d6937d6` and installs only the SHA-pinned openpyxl 3.1.5 wheel. The existing LibreOffice binary, bounded recalculation script and et-xmlfile dependency remain unchanged.

The [private runtime release](https://github.com/ZhaoyangHan04/sheetsFactory/releases/tag/runtime-lo-24.2-iterative-openpyxl315-v1) contains the exact image at OCI image ID `sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043`. Its archive is 205,047,110 bytes with SHA256 `10df3fce775506e5b92d16ca0169cf964f2c717c481cc3a3b1694f79297442e2`. Download into a new directory and verify before loading:

```bash
mkdir sheetsfactory-lo-24.2-iterative-openpyxl315-v1
cd sheetsfactory-lo-24.2-iterative-openpyxl315-v1
gh release download runtime-lo-24.2-iterative-openpyxl315-v1 --repo ZhaoyangHan04/sheetsFactory --pattern 'sheetsfactory-lo-24.2-iterative-openpyxl315-v1.tar.gz*' --pattern runtime_manifest.json
sha256sum --check sheetsfactory-lo-24.2-iterative-openpyxl315-v1.tar.gz.sha256
docker image load --input sheetsfactory-lo-24.2-iterative-openpyxl315-v1.tar.gz
test "$(docker image inspect sheetsfactory-lo:24.2-iterative-openpyxl315-v1 --format '{{.Id}}')" = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
```

The release manifest binds the archive and image identities to the lock and build recipe hashes, and records successful actual Docker loading with the earlier runtime tags preserved.

From the repository root, build once with:

```bash
.venv312/bin/python runtime/lo24.2-iterative-openpyxl315-v1/build.py
```

The builder refuses to overwrite an existing output tag or use a different base identity. It records package bytes, recipe hashes, full layer ancestry and before/after engine checks under `outputs/research/`. The output tag is `sheetsfactory-lo:24.2-iterative-openpyxl315-v1`. Ordinary workbooks use one full calculation. Workbooks that explicitly enable iteration must satisfy the existing convergence bound. Earlier runtime tags and frozen task exports remain unchanged.

No model score or task qualification is inferred from building this image.
