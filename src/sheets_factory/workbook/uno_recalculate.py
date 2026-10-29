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
        document.calculateAll()
        document.storeAsURL(destination.as_uri(), (
            prop("FilterName", "Calc MS Excel 2007 XML"), prop("Overwrite", True),
        ))
        document.close(True)
        document = None
        print(json.dumps({"status": "ok", "bytes": destination.stat().st_size}))
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
