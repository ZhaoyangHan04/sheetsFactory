This separate image retains the pinned LibreOffice 24.2.7.2 engine and UNO script, and loads openpyxl 3.1.5 ahead of the base image's distribution package. The existing et-xmlfile 1.0.1 dependency is retained.

Build from the repository root:

```sh
.venv312/bin/python runtime/lo24.2-openpyxl315-v1/build.py
```

The builder verifies the immutable base image ID, downloads the 250,910-byte wheel with its pinned SHA256, and builds with network disabled. It refuses an existing output tag. Build logs, package bytes, source hashes, image ID, loaded package versions, LibreOffice version and unchanged UNO script proof are recorded under `outputs/research/runtime_openpyxl315_<UTC>/`.

The new tag is `sheetsfactory-lo:24.2-openpyxl315-v1`. Neither `sheetsfactory-lo:24.2` nor any iterative image is replaced. New source and Harbor exports must explicitly select the new tag and undergo their actual recalculation, stability and verifier checks. Historical exports keep their original runtime binding.

The compatibility issue concerns style aliases: the Ofgem workbook's LibreOffice output has many named styles sharing a smaller valid set of style records. openpyxl 3.1.2 assigns new consecutive indices while converting those names and raises `IndexError`. Version 3.1.5 preserves the original style indices and removes aliases before expansion. No financial formula, source value, tax policy or LibreOffice calculation rule is changed by this image.
