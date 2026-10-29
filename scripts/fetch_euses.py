#!/usr/bin/env python3
"""Download the official EUSES financial archive and extract a ranked subset.

Archive members are selected by their own workbook statistics. No benchmark
questions or solutions are imported. The manifest records the exact bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import urllib.request
import zipfile

URL = "https://zenodo.org/records/581673/files/financial.zip?download=1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_xls(data: bytes) -> dict:
    import xlrd
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    sheets = []
    for sheet in book.sheets():
        nonempty = sum(1 for row in sheet.get_rows() for cell in row
                       if cell.ctype not in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK))
        sheets.append({"name": sheet.name, "rows": sheet.nrows,
                       "columns": sheet.ncols, "nonempty": nonempty})
    # Formula records are BIFF records, not text guesses. xlrd exposes the
    # workbook stream bytes so the legacy cached values need not be rewritten.
    stream = book.mem
    start = book.base
    end = start + book.stream_len
    offset, formulas = start, 0
    while offset + 4 <= end:
        opcode = int.from_bytes(stream[offset:offset+2], "little")
        length = int.from_bytes(stream[offset+2:offset+4], "little")
        if opcode == 0x0006:
            formulas += 1
        offset += 4 + length
    book.release_resources()
    return {"sheet_count": len(sheets), "nonempty_sheet_count": sum(
        s["nonempty"] > 0 for s in sheets), "formula_count": formulas,
        "sheets": sheets}


def financial_score(path: str, stats: dict) -> float:
    text = (path + " " + " ".join(s["name"] for s in stats["sheets"])).lower()
    score = min(stats["formula_count"], 5000) / 500
    terms = {
        "financial-model": 70, "projections": 55, "forecast": 45,
        "valuation": 50, "cash flow": 25, "cashflow": 25,
        "income": 20, "balance": 20, "assumption": 30,
        "budget": 15, "profit": 15, "expense": 10,
        "depreciation": 15, "debt": 10, "loan": 10,
        "master.xls": 35,
    }
    score += sum(weight for term, weight in terms.items() if term in text)
    score += min(stats["nonempty_sheet_count"], 12)
    if stats["formula_count"] > 20000:
        score -= 40
    return round(score, 3)


def fetch(destination: Path, manifest_path: Path, max_files: int = 70,
          min_sheets: int = 4, min_formulas: int = 30) -> dict:
    archive_path = destination.parent / "euses_financial.zip"
    destination.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        request = urllib.request.Request(URL, headers={"User-Agent": "sheetsFactory/1.0"})
        with urllib.request.urlopen(request, timeout=180) as response:
            archive_path.write_bytes(response.read())
    archive_bytes = archive_path.read_bytes()
    candidates, rejected, seen = [], [], set()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe ZIP member")
            if member.file_size > 64 * 1024 * 1024:
                raise ValueError("Oversized ZIP member")
            if path.suffix.lower() != ".xls" or "/processed/" not in member.filename:
                continue
            data = archive.read(member)
            digest = sha256(data)
            if digest in seen:
                continue
            seen.add(digest)
            try:
                stats = inspect_xls(data)
                row = {"archive_member": member.filename, "sha256": digest, **stats}
                if stats["nonempty_sheet_count"] < min_sheets or stats["formula_count"] < min_formulas:
                    rejected.append({"archive_member": member.filename, "reason": "minimum_structure"})
                    continue
                row["rank_score"] = financial_score(member.filename, stats)
                candidates.append(row)
            except Exception as exc:
                rejected.append({"archive_member": member.filename,
                                 "reason": type(exc).__name__, "detail": str(exc)[:200]})
        candidates.sort(key=lambda row: (-row["rank_score"], row["archive_member"]))
        selected = candidates[:max_files]
        for row in selected:
            basename = PurePosixPath(row["archive_member"]).name
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", basename)
            output = destination / (row["sha256"][:10] + "_" + safe_name)
            output.write_bytes(archive.read(row["archive_member"]))
            row["local_path"] = str(output.resolve())
    manifest = {
        "dataset": "EUSES financial", "source_record": "https://zenodo.org/records/581673",
        "download_url": URL, "archive_sha256": sha256(archive_bytes),
        "archive_bytes": len(archive_bytes), "unique_workbooks_inspected": len(seen),
        "eligible_count": len(candidates), "selected_count": len(selected),
        "selection": {"min_nonempty_sheets": min_sheets, "min_formulas": min_formulas,
                      "max_files": max_files, "ranking": "financial_score_v1"},
        "selected": selected, "rejected": rejected,
        "license_note": "Retain source provenance; archive accessibility does not grant unrestricted redistribution.",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=Path("data/seeds/euses_financial"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/euses_financial.json"))
    parser.add_argument("--max-files", type=int, default=70)
    args = parser.parse_args()
    result = fetch(args.destination, args.manifest, args.max_files)
    print(json.dumps({key: result[key] for key in ("unique_workbooks_inspected", "eligible_count", "selected_count")}))
