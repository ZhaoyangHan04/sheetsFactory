"""Container-only LibreOffice UNO runner; no network access is needed."""
import json
from pathlib import Path
import subprocess
import sys
import time

import uno
from com.sun.star.beans import PropertyValue


def prop(name, value):
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def calculation_snapshot(document):
    """Capture every used cell, including downstream values outside a cycle."""
    sheets = document.getSheets()
    result = []
    for name in sheets.getElementNames():
        sheet = sheets.getByName(name)
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(True)
        address = cursor.getRangeAddress()
        cells = sheet.getCellRangeByPosition(0, 0, address.EndColumn, address.EndRow)
        result.append((name, tuple(tuple(row) for row in cells.getDataArray())))
    return tuple(result)


def calculate_to_stability(document, max_outer_passes=64):
    """Finish imported iterative models or reject bounded non-convergence.

    Calc can finish one local iteration before refreshing an entire cross-sheet
    feedback chain. Repeating calculateAll propagates that chain. Full-sheet
    equality, twice consecutively, also covers dependent cells outside the loop.
    Ordinary workbooks retain the single calculateAll call.
    """
    document.calculateAll()
    if not document.getPropertyValue("IsIterationEnabled"):
        return {"passes": 1, "iterative": False}
    previous = calculation_snapshot(document)
    unchanged = 0
    for count in range(2, max_outer_passes + 1):
        document.calculateAll()
        current = calculation_snapshot(document)
        unchanged = unchanged + 1 if current == previous else 0
        if unchanged >= 2:
            return {"passes": count, "iterative": True, "full_used_area_stable": True}
        previous = current
    raise RuntimeError("Iterative workbook did not reach full-sheet stability within "
                       + str(max_outer_passes) + " calculation passes")


def main():
    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    pipe_name = "sheetsfactory_uno"
    process = subprocess.Popen([
        "/usr/bin/libreoffice", "--headless", "--nologo", "--nodefault",
        "--norestore", "--nofirststartwizard",
        "-env:UserInstallation=file:///tmp/sheetsfactory-profile",
        f"--accept=pipe,name={pipe_name};urp;StarOffice.ComponentContext",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    document = None
    desktop = None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local)
        for _ in range(300):
            try:
                remote = resolver.resolve(
                    f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext")
                break
            except Exception:
                if process.poll() is not None:
                    error = process.stderr.read().decode("utf-8", errors="replace")
                    raise RuntimeError("LibreOffice exited before UNO was available: " + error[-1500:])
                time.sleep(0.1)
        else:
            raise RuntimeError("UNO startup timed out")
        desktop = remote.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", remote)
        # NEVER_EXECUTE macros; NO_UPDATE external links. The container also has
        # --network none and cannot access the host seed or reference directories.
        document = desktop.loadComponentFromURL(source.as_uri(), "_blank", 0, (
            prop("Hidden", True), prop("ReadOnly", False),
            prop("MacroExecutionMode", 0), prop("UpdateDocMode", 0),
        ))
        if document is None or not document.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            raise RuntimeError("Input did not open as a spreadsheet")
        document.enableAutomaticCalculation(True)
        calculation = calculate_to_stability(document)
        document.storeAsURL(destination.as_uri(), (
            prop("FilterName", "Calc MS Excel 2007 XML"), prop("Overwrite", True),
        ))
        document.close(True)
        document = None
        print(json.dumps({"status": "ok", "bytes": destination.stat().st_size,
                          "calculation": calculation}))
    finally:
        if document is not None:
            try:
                document.close(True)
            except Exception:
                pass
        if desktop is not None:
            try:
                desktop.terminate()
            except Exception:
                pass
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
