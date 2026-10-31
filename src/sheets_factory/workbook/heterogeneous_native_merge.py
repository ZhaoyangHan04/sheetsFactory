"""Pure OOXML composition of independent financial workbooks.

This compiler does not calculate, certify business logic, or create a task. Cells
keep their coordinates. It copies supported relationship graphs, translates
parsed references, and retains typed cached values. Unsupported content fails
closed. A successful composition still requires native value/date equivalence
and two-pass stability before any downstream admission.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from decimal import Decimal
from dataclasses import dataclass
from pathlib import Path
from xml.dom import Node, minidom
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple

KIND = "heterogeneous_native_ooxml_review_pack"
VERSION = 1
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/package/2006/content-types"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
CHART = "http://schemas.openxmlformats.org/drawingml/2006/chart"
REL_TYPES = {
    "officeDocument", "core-properties", "extended-properties", "custom-properties",
    "worksheet", "styles", "sharedStrings", "theme", "drawing", "chart",
    "image", "comments", "vmlDrawing", "table", "hyperlink",
}
PART = re.compile(
    r"(?:\[Content_Types\]\.xml|_rels/\.rels|docProps/(?:core|app|custom)\.xml|"
    r"xl/(?:workbook\.xml|_rels/workbook\.xml\.rels|styles\.xml|sharedStrings\.xml|"
    r"theme/theme\d+\.xml|worksheets/(?:sheet\d+\.xml|_rels/sheet\d+\.xml\.rels)|"
    r"drawings/(?:drawing\d+\.xml|(?:vmlDrawing|commentsDrawing)\d+\.vml|_rels/[^/]+\.rels)|"
    r"charts/(?:chart\d+\.xml|_rels/[^/]+\.rels)|(?:comments/)?comments?\d+\.xml|"
    r"tables/table\d+\.xml|media/[^/]+\.(?:png|jpe?g|gif|bmp|emf|wmf)))$", re.I
)
CELL_RANGE = re.compile(r"\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?$")
AXIS_RANGE = re.compile(r"(?:\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}|\$?\d+:\$?\d+)$")
DATE_FUNCTIONS = {"DATE", "DATEVALUE", "DAY", "DAYS", "DAYS360", "EDATE", "EOMONTH", "HOUR", "MINUTE", "MONTH", "NETWORKDAYS", "NOW", "SECOND", "TIME", "TIMEVALUE", "TODAY", "WEEKDAY", "WEEKNUM", "WORKDAY", "YEAR", "YEARFRAC", "XIRR", "XNPV"}
STYLE_SECTIONS = ("numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs", "cellStyles", "dxfs", "tableStyles", "colors")


class UnsupportedWorkbook(ValueError):
    """A concrete preservation requirement is not supported by this version."""


def require(value, message):
    if not value:
        raise UnsupportedWorkbook(message)


def file_ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def checked_ref(ref):
    require(set(ref) == {"path", "sha256", "bytes"}, "File reference must have exactly path/sha256/bytes")
    actual = file_ref(ref["path"])
    require(actual == ref, "Frozen file reference changed: " + ref["path"])
    return Path(ref["path"])


def _xml(data):
    require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "DTD/entities are unsupported")
    return minidom.parseString(data)


def _elements(node):
    return [x for x in node.childNodes if x.nodeType == Node.ELEMENT_NODE]


def _all(node):
    if node.nodeType == Node.DOCUMENT_NODE:
        node = node.documentElement
    yield node
    for child in _elements(node):
        yield from _all(child)


def _children(node, local):
    return [x for x in _elements(node) if x.localName == local]


def _one(node, local):
    found = _children(node, local)
    return found[0] if found else None


def _text(node):
    return "".join(x.data for x in node.childNodes if x.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def _set_text(node, text):
    for x in list(node.childNodes):
        node.removeChild(x)
    node.appendChild(node.ownerDocument.createTextNode(text))


def _doc(namespace, root):
    d = minidom.Document()
    n = d.createElementNS(namespace, root)
    n.setAttribute("xmlns", namespace)
    d.appendChild(n)
    return d


def _add(parent, name, attrs=None, text=None):
    n = parent.ownerDocument.createElementNS(parent.namespaceURI, name)
    for key, val in (attrs or {}).items():
        n.setAttribute(key, str(val))
    if text is not None:
        _set_text(n, text)
    parent.appendChild(n)
    return n


def _bytes(doc):
    return doc.toxml(encoding="UTF-8")


def _rels_source(name):
    if name == "_rels/.rels":
        return ""
    directory, leaf = posixpath.split(name)
    require(posixpath.basename(directory) == "_rels" and leaf.endswith(".rels"), "Invalid relationship part: " + name)
    return posixpath.join(posixpath.dirname(directory), leaf[:-5])


def _resolve(source, target):
    require("\\" not in target and "?" not in target and "#" not in target, "Unsupported internal relationship target: " + target)
    result = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(source), target))
    require(result != ".." and not result.startswith("../"), "Relationship escapes package: " + target)
    return result


def sheet_namespace(prefix, sheets, used=None):
    require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", prefix), "Invalid readable donor prefix")
    used = set() if used is None else used
    out = {}
    for old in sheets:
        require(old and old.casefold() not in {x.casefold() for x in out}, "Duplicate donor sheet name")
        name = prefix + " - " + old
        if len(name) > 31:
            name = name[:24] + "~" + hashlib.sha256(name.encode()).hexdigest()[:6]
        require(name.casefold() not in used, "Sheet namespace collision: " + name)
        used.add(name.casefold())
        out[old] = name
    return out


def _quote(name):
    return "'" + name.replace("'", "''") + "'"


def _unquote(name):
    return name[1:-1].replace("''", "'") if name.startswith("'") and name.endswith("'") else name


def rewrite_formula(formula, sheets, names=None, tables=None, *, local_sheet=None, table_context=None, defined_name=False):
    """Rewrite parsed RANGE operands; never substitute inside arbitrary text."""
    names = names or {}
    tables = tables or {}
    sheet_lookup = {k.casefold(): v for k, v in sheets.items()}
    table_lookup = {k.casefold(): v for k, v in tables.items()}
    body = formula[1:] if formula.startswith("=") else formula
    try:
        tokens = Tokenizer("=" + body).items
    except Exception as exc:
        raise UnsupportedWorkbook("Formula cannot be tokenized: " + formula) from exc
    out = []
    for token in tokens:
        value = token.value
        if defined_name:
            require(token.type not in {"OP_PRE", "OP_IN", "OP_POST", "PAREN", "ARRAY"}, "Expression defined names are unsupported: " + formula)
        if token.type == "ARRAY":
            raise UnsupportedWorkbook("Array formula expression is unsupported: " + formula)
        if token.type == "FUNC" and token.subtype == "OPEN":
            function = value[:-1].split(".")[-1].upper()
            require(function not in {"INDIRECT", "ADDRESS", "EVALUATE", "GET.CELL", "CALL", "REGISTER.ID", "RTD"}, "Text/dynamic address function is unsupported: " + value)
            require(not defined_name, "Expression defined names are unsupported: " + formula)
        if token.type == "OPERAND" and token.subtype == "TEXT":
            literal = value[1:-1].replace('""', '"')
            require(not re.search(r"(?:!\$?[A-Za-z]{1,3}\$?\d|^#?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?$)", literal), "Text address literal is unsupported: " + value)
        if token.type != "OPERAND" or token.subtype != "RANGE":
            out.append(value)
            continue
        qualifier = None
        operand = value
        if "!" in operand:
            raw_sheet, operand = operand.rsplit("!", 1)
            qualifier = _unquote(raw_sheet)
            require("[" not in qualifier and "]" not in qualifier and ":" not in qualifier, "External/3D workbook reference is unsupported: " + value)
            require(qualifier.casefold() in sheet_lookup, "Unknown sheet reference: " + value)
        if CELL_RANGE.fullmatch(operand) or AXIS_RANGE.fullmatch(operand):
            if defined_name:
                require(qualifier is not None and all(x.startswith("$") and (re.fullmatch(r"\$[A-Za-z]+\$\d+", x) or re.fullmatch(r"\$(?:[A-Za-z]+|\d+)", x)) for x in operand.split(":")), "Relative defined-name address is unsupported: " + value)
            mapped = operand
        elif "[" in operand:
            require(not defined_name, "Structured-reference defined name is unsupported")
            table, bracket, suffix = operand.partition("[")
            require("]" in suffix and suffix.count("[") + 1 == suffix.count("]"), "Malformed structured reference: " + value)
            if table:
                require(table.casefold() in table_lookup and qualifier is None, "Unknown/external structured reference: " + value)
                mapped = table_lookup[table.casefold()] + bracket + suffix
            else:
                require(table_context is not None, "Unscoped structured reference: " + value)
                mapped = operand
        else:
            scope = qualifier if qualifier is not None else local_sheet
            key = (scope.casefold() if scope else None, operand.casefold())
            fallback = (None, operand.casefold())
            require(key in names or fallback in names, "Unknown named reference: " + value)
            mapped = names.get(key, names.get(fallback))
        out.append((_quote(sheet_lookup[qualifier.casefold()]) + "!" if qualifier is not None else "") + mapped)
    return ("=" if formula.startswith("=") else "") + "".join(out)


@dataclass
class Donor:
    spec: dict
    parts: dict
    workbook: object
    sheets: list
    sheet_parts: dict
    sheet_map: dict
    names: dict
    tables: dict
    palette: dict
    indexed_colors: list
    dates: list
    date_functions: list
    settings: dict


def _theme_palette(parts):
    found = [p for p in parts if re.fullmatch(r"xl/theme/theme\d+\.xml", p)]
    require(len(found) == 1, "Exactly one source presentation theme is required")
    d = _xml(parts[found[0]])
    schemes = [n for n in _all(d) if n.localName == "clrScheme"]
    require(len(schemes) == 1, "Theme color scheme missing/ambiguous")
    palette = {}
    for n in _elements(schemes[0]):
        c = _elements(n)
        require(len(c) == 1 and c[0].localName in {"srgbClr", "sysClr"}, "Unsupported theme color")
        palette[n.localName] = c[0].getAttribute("val" if c[0].localName == "srgbClr" else "lastClr")
    return palette


def _colors(doc, palette, indexed):
    """Keep business color cues even when the package shares one theme."""
    order = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"]
    aliases = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    for node in list(_all(doc)):
        if node.hasAttribute("theme"):
            i = int(node.getAttribute("theme"))
            require(0 <= i < len(order), "Unknown theme color index")
            node.removeAttribute("theme")
            node.setAttribute("rgb", "FF" + palette[order[i]][-6:])
        if node.hasAttribute("indexed") and indexed:
            i = int(node.getAttribute("indexed"))
            if i < 64:
                require(i < len(indexed), "Missing source indexed color")
                node.removeAttribute("indexed")
                node.setAttribute("rgb", indexed[i])
        if node.namespaceURI == A and node.localName == "schemeClr":
            key = aliases.get(node.getAttribute("val"), node.getAttribute("val"))
            require(key in palette, "Unresolved drawing theme color: " + key)
            replacement = node.ownerDocument.createElementNS(A, (node.prefix + ":" if node.prefix else "") + "srgbClr")
            replacement.setAttribute("val", palette[key][-6:])
            for child in list(node.childNodes):
                replacement.appendChild(child.cloneNode(True))
            node.parentNode.replaceChild(replacement, node)


def _load(spec, used):
    require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", spec["id"]), "Invalid donor id")
    path = checked_ref(spec["workbook"])
    with ZipFile(path) as archive:
        infos = archive.infolist()
        require(len(infos) <= 5000 and sum(x.file_size for x in infos) < 100_000_000, "Oversized workbook package")
        require(len({x.filename for x in infos}) == len(infos), "Duplicate ZIP member")
        require(all(not x.flag_bits & 1 and PART.fullmatch(x.filename) for x in infos), "Unsupported package component: " + ", ".join(x.filename for x in infos if not PART.fullmatch(x.filename)))
        parts = {x.filename: archive.read(x) for x in infos}
    for name, data in parts.items():
        if name.endswith(".rels"):
            for rel in _elements(_xml(data).documentElement):
                suffix = rel.getAttribute("Type").rsplit("/", 1)[-1]
                require(suffix in REL_TYPES, "Unsupported relationship type: " + rel.getAttribute("Type"))
                if rel.getAttribute("TargetMode") == "External":
                    require(suffix == "hyperlink" and re.match(r"^(?:https?://|mailto:)", rel.getAttribute("Target"), re.I), "External financial/object relationship is unsupported")
                else:
                    target = _resolve(_rels_source(name), rel.getAttribute("Target"))
                    require(target in parts, "Missing relationship target: " + target)
    w = _xml(parts["xl/workbook.xml"])
    allowed = {"fileVersion", "workbookPr", "workbookProtection", "bookViews", "sheets", "definedNames", "calcPr", "extLst"}
    require(all(n.localName in allowed for n in _elements(w.documentElement)), "Unsupported workbook metadata")
    protection = _one(w.documentElement, "workbookProtection")
    require(protection is None or not protection.attributes.length, "Protected workbook is unsupported")
    ext = _one(w.documentElement, "extLst")
    if ext:
        for n in _all(ext):
            require(n.localName in {"extLst", "ext", "extCalcPr"}, "Unsupported workbook extension: " + n.localName)
            if n.localName == "extCalcPr":
                require(dict(n.attributes.items()) in ({"stringRefSyntax": "CalcA1"}, {"stringRefSyntax": "ExcelA1"}), "Unsupported calculation extension")
    descriptors = _children(_one(w.documentElement, "sheets"), "sheet")
    sheets = [n.getAttribute("name") for n in descriptors]
    sheet_map = sheet_namespace(spec["prefix"], sheets, used)
    wr = {n.getAttribute("Id"): n for n in _elements(_xml(parts["xl/_rels/workbook.xml.rels"]).documentElement)}
    sheet_parts = {n.getAttribute("name"): _resolve("xl/workbook.xml", wr[n.getAttributeNS(R, "id")].getAttribute("Target")) for n in descriptors}
    names = {}
    definitions = _one(w.documentElement, "definedNames")
    for n in _children(definitions, "definedName") if definitions else []:
        scope = sheets[int(n.getAttribute("localSheetId"))] if n.hasAttribute("localSheetId") else None
        old = n.getAttribute("name")
        key = (scope.casefold() if scope else None, old.casefold())
        require(key not in names, "Duplicate defined name")
        names[key] = old if old.startswith("_xlnm.") else spec["prefix"] + "__" + old
        require(not old.startswith("_xlnm.") or scope is not None, "Global built-in defined name is unsupported")
    tables = {}
    for part, data in parts.items():
        if re.fullmatch(r"xl/tables/table\d+\.xml", part):
            root = _xml(data).documentElement
            old = root.getAttribute("name")
            require(old.casefold() not in {x.casefold() for x in tables}, "Duplicate table name")
            require(root.getAttribute("displayName") == old, "Different table name/displayName unsupported")
            tables[old] = spec["prefix"] + "__" + old
    styles = _xml(parts["xl/styles.xml"])
    require(all(n.localName in STYLE_SECTIONS for n in _elements(styles.documentElement)), "Unsupported styles extension")
    palette = _theme_palette(parts)
    ic = [n.getAttribute("rgb") for n in _all(styles) if n.localName == "rgbColor"]
    donor = Donor(spec, parts, w, sheets, sheet_parts, sheet_map, names, tables, palette, ic, [], [], {})
    for n in _children(definitions, "definedName") if definitions else []:
        scope = sheets[int(n.getAttribute("localSheetId"))] if n.hasAttribute("localSheetId") else None
        rewrite_formula(_text(n), sheet_map, names, tables, local_sheet=scope, defined_name=True)
    name_edges = {}
    for n in _children(definitions, "definedName") if definitions else []:
        scope = sheets[int(n.getAttribute("localSheetId"))].casefold() if n.hasAttribute("localSheetId") else None
        key = (scope, n.getAttribute("name").casefold());name_edges[key] = []
        for token in Tokenizer("=" + _text(n)).items:
            if token.type == "OPERAND" and token.subtype == "RANGE":
                value = token.value
                local = scope
                if "!" in value:
                    qualifier, value = value.rsplit("!", 1);local = _unquote(qualifier).casefold()
                target = (local, value.casefold())
                target = target if target in names else (None, value.casefold())
                if target in names:
                    name_edges[key].append(target)
    def visit_name(key, pending, complete):
        require(key not in pending, "Cyclic defined names are unsupported")
        if key in complete:
            return
        for target in name_edges[key]:
            visit_name(target, pending | {key}, complete)
        complete.add(key)
    complete = set()
    for key in name_edges:
        visit_name(key, set(), complete)
    formats = dict(BUILTIN_FORMATS)
    for n in _all(styles):
        if n.localName == "numFmt":
            formats[int(n.getAttribute("numFmtId"))] = n.getAttribute("formatCode")
    xfs = _elements(_one(styles.documentElement, "cellXfs"))
    for sheet, part in sheet_parts.items():
        doc = _xml(parts[part])
        for n in _all(doc):
            if n.localName == "c":
                index = int(n.getAttribute("s") or "0")
                require(index < len(xfs), "Cell style index out of bounds")
                v = _one(n, "v")
                if n.getAttribute("t") == "d" or (v and n.getAttribute("t") in {"", "n"} and is_date_format(formats.get(int(xfs[index].getAttribute("numFmtId") or "0"), ""))):
                    donor.dates.append({"sheet": sheet, "cell": n.getAttribute("r"), "type": n.getAttribute("t") or "n", "cached_text": _text(v) if v else None})
            if n.localName == "f":
                require(n.getAttribute("t") in {"", "normal"} and not n.hasAttribute("ref") and not n.hasAttribute("si"), "Shared/array/dataTable formula is unsupported: " + sheet)
                require(all(k in {"t", "aca", "ca"} for k in n.attributes.keys()), "Unhandled formula attribute")
                for token in Tokenizer("=" + _text(n)).items:
                    if token.type == "FUNC" and token.subtype == "OPEN" and token.value[:-1].upper().split(".")[-1] in DATE_FUNCTIONS:
                        donor.date_functions.append({"sheet": sheet, "cell": n.parentNode.getAttribute("r"), "function": token.value[:-1], "formula": _text(n)})
    props = _one(w.documentElement, "workbookPr")
    calc = _one(w.documentElement, "calcPr")
    donor.settings = {"date1904": bool(props and props.getAttribute("date1904") in {"true", "1"}), "calcPr": dict(calc.attributes.items()) if calc else {}}
    return donor


def _part_rewrite(donor, name, data, offsets=None, table_ids=None):
    if not (name.endswith(".xml") or name.endswith(".vml")):
        return data
    d = _xml(data)
    _colors(d, donor.palette, donor.indexed_colors)
    sheet = next((s for s, p in donor.sheet_parts.items() if p == name), None)
    table_context = d.documentElement.getAttribute("name") if name.startswith("xl/tables/") else None
    for n in _all(d):
        require(n.localName != "overrideClrMapping", "Custom drawing color mapping is unsupported: " + name)
        if n.localName in {"externalReferences", "oleObjects", "controls", "pivotTable"}:
            raise UnsupportedWorkbook("Unsupported calculation/object extension in " + name + ": " + n.localName)
        if n.localName == "extLst":
            for descendant in _all(n):
                require(descendant.localName in {"extLst", "ext", "showLeaderLines"}, "Unhandled object extension in " + name + ": " + descendant.localName)
                if descendant.localName == "ext":
                    require(descendant.getAttribute("uri") == "{CE6537A1-D6FC-4f65-9D91-7224C49458BB}", "Unhandled chart extension URI")
                if descendant.localName == "showLeaderLines":
                    require(descendant.namespaceURI == "http://schemas.microsoft.com/office/drawing/2012/chart" and descendant.getAttribute("val") in {"0", "1"}, "Unhandled chart leader-line setting")
        if n.localName in {"f", "formula", "formula1", "formula2", "calculatedColumnFormula", "totalsRowFormula"}:
            require(n.namespaceURI in {S, CHART, A}, "Unsupported formula namespace in " + name)
            if n.localName == "f":
                require(n.getAttribute("t") in {"", "normal"}, "Nonordinary formula in " + name)
            _set_text(n, rewrite_formula(_text(n), donor.sheet_map, donor.names, donor.tables, local_sheet=sheet, table_context=table_context))
        if n.localName in {"FmlaLink", "FmlaRange", "FmlaMacro", "FmlaPict"}:
            require(not _text(n).strip(), "VML control formula is unsupported: " + name)
        if n.localName == "hyperlink" and n.hasAttribute("location"):
            n.setAttribute("location", rewrite_formula(n.getAttribute("location"), donor.sheet_map, donor.names, donor.tables, local_sheet=sheet))
        if n.localName == "table" and table_context:
            n.setAttribute("name", donor.tables[table_context])
            n.setAttribute("displayName", donor.tables[table_context])
            if table_ids:
                n.setAttribute("id", str(table_ids[table_context]))
        if offsets:
            for attr, mapping in (("s", "cellXfs"), ("style", "cellXfs"), ("dxfId", "dxfs"), ("dataDxfId", "dxfs"), ("headerRowDxfId", "dxfs"), ("totalsRowDxfId", "dxfs")):
                if n.hasAttribute(attr) and ((attr == "s" and n.localName in {"c", "row"}) or (attr == "style" and n.localName == "col") or "DxfId" in attr or attr == "dxfId"):
                    old = int(n.getAttribute(attr));require(old < offsets["counts"][mapping], "Style/differential index out of bounds")
                    n.setAttribute(attr, str(old + offsets[mapping]))
            if n.localName == "c":
                if not n.hasAttribute("s"):
                    n.setAttribute("s", str(offsets["cellXfs"]))
                if n.getAttribute("t") == "s":
                    v = _one(n, "v");require(v is not None, "Shared string has no index")
                    old = int(_text(v));require(old < offsets["counts"]["sst"], "Shared-string index out of bounds")
                    _set_text(v, str(old + offsets["sst"]))
    return _bytes(d)


def dependency_census(donor):
    """Static A1 dependency observations, explicitly partial for OFFSET/tables."""
    formulas = {}
    by_sheet = {}
    for sheet, part in donor.sheet_parts.items():
        by_sheet[sheet.casefold()] = []
        for n in _all(_xml(donor.parts[part])):
            if n.localName == "c" and _one(n, "f") is not None:
                address = n.getAttribute("r");key = (sheet, address)
                formulas[key] = _text(_one(n, "f"))
                row, col = coordinate_to_tuple(address)
                by_sheet[sheet.casefold()].append((key, row, col))
    edges = {k: set() for k in formulas}
    reverse = {k: set() for k in formulas}
    partial = []
    date_seeds = {(x["sheet"], x["cell"]) for x in donor.dates if x["type"] != "d"}
    date_dependents = {k: set() for k in date_seeds}
    for key, formula in formulas.items():
        for token in Tokenizer("=" + formula).items:
            if token.type == "FUNC" and token.subtype == "OPEN" and token.value[:-1].upper() == "OFFSET":
                partial.append({"sheet": key[0], "cell": key[1], "reason": "OFFSET reference target is dynamic"})
            if token.type != "OPERAND" or token.subtype != "RANGE":
                continue
            raw = token.value;sheet = key[0]
            if "!" in raw:
                sheet, raw = raw.rsplit("!", 1);sheet = _unquote(sheet)
            if not (CELL_RANGE.fullmatch(raw) or AXIS_RANGE.fullmatch(raw)):
                partial.append({"sheet": key[0], "cell": key[1], "reason": "Named/structured dependency not expanded in this census", "reference": token.value})
                continue
            lo_col, lo_row, hi_col, hi_row = range_boundaries(raw)
            def inside(row, col):
                return (lo_col is None or lo_col <= col <= hi_col) and (lo_row is None or lo_row <= row <= hi_row)
            for target, row, col in by_sheet.get(sheet.casefold(), []):
                if inside(row, col):
                    edges[key].add(target);reverse[target].add(key)
            for seed in date_seeds:
                row, col = coordinate_to_tuple(seed[1])
                if seed[0].casefold() == sheet.casefold() and inside(row, col):
                    date_dependents[seed].add(key)
    # Iterative Kosaraju avoids recursion limits on long workbook chains.
    seen = set();order = []
    for start in edges:
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node);continue
            if node in seen:
                continue
            seen.add(node);stack.append((node, True))
            stack.extend((x, False) for x in edges[node] if x not in seen)
    seen = set();cycles = []
    for start in reversed(order):
        if start in seen:
            continue
        component = [];stack = [start];seen.add(start)
        while stack:
            node = stack.pop();component.append(node)
            for target in reverse[node]:
                if target not in seen:
                    seen.add(target);stack.append(target)
        if len(component) > 1 or start in edges[start]:
            cycles.append([{"sheet": s, "cell": a} for s, a in sorted(component)])
    exposed = []
    for seed, first in sorted(date_dependents.items()):
        reached = set(first);todo = list(first)
        while todo:
            for target in reverse[todo.pop()]:
                if target not in reached:
                    reached.add(target);todo.append(target)
        exposed.append({"date_cell": {"sheet": seed[0], "cell": seed[1]}, "transitive_formula_dependents": [{"sheet": s, "cell": a} for s, a in sorted(reached)]})
    cycles.sort(key=repr)
    return {"physical_formulas": len(formulas), "static_formula_edges": sum(map(len, edges.values())), "observed_static_cycles": cycles, "unexpanded_references": partial, "complete_static_closure": not partial, "date_dependents": exposed, "calculation_executed": False, "business_correctness_claimed": False}


def _date_adjustments(donor, target_epoch):
    if donor.settings["date1904"] == target_epoch:
        return []
    dates = [x for x in donor.dates if x["type"] != "d"]
    require(not donor.date_functions, "Date-sensitive formulas need a separate epoch equivalence proof")
    frozen = donor.spec.get("date_conversion", {})
    require(frozen.get("source_date1904") == donor.settings["date1904"] and frozen.get("target_date1904") == target_epoch, "Different epoch requires an explicit frozen date conversion")
    delta = 1462 if donor.settings["date1904"] else -1462
    require(frozen.get("serial_delta") == delta, "Incorrect date epoch serial conversion")
    expected = {(x["sheet"], x["cell"]): x["cached_text"] for x in dates}
    provided = {(x["sheet"], x["cell"]): x["original_cached_text"] for x in frozen.get("cells", [])}
    require(len(provided) == len(frozen.get("cells", [])) and provided == expected, "Frozen date conversion must cover exactly every numeric date cell")
    census = dependency_census(donor)
    require(census["complete_static_closure"], "Different epoch has unresolved dynamic/named dependencies")
    exposed = {(x["sheet"], x["cell"]) for row in census["date_dependents"] for x in row["transitive_formula_dependents"]}
    require(exposed <= set(provided), "Numeric date has a non-date dependent requiring an explicit semantic conversion")
    result = []
    for cell in dates:
        value = Decimal(cell["cached_text"])
        require(value.is_finite(), "Nonfinite date cache")
        result.append({**cell, "original_cached_text": cell["cached_text"], "converted_cached_text": str(value + delta), "serial_delta": delta})
    return result


def _common_settings(donors):
    target_epoch = donors[0].settings["date1904"]
    holds = []
    for d in donors:
        if d.settings["date1904"] != target_epoch:
            try:
                _date_adjustments(d, target_epoch)
            except UnsupportedWorkbook as exc:
                holds.append({"donor": d.spec["id"], "reason": str(exc), "date_cells": d.dates, "date_functions": d.date_functions})
    deltas = [float(d.settings["calcPr"].get("iterateDelta", "0.001")) for d in donors]
    counts = [int(d.settings["calcPr"].get("iterateCount", "100")) for d in donors]
    for d in donors:
        calc = d.settings["calcPr"]
        if calc.get("refMode", "A1") != "A1" or calc.get("fullPrecision", "true") in {"0", "false"} or calc.get("calcMode", "auto") not in {"auto", "autoNoTable"}:
            holds.append({"donor": d.spec["id"], "reason": "Unsupported calculation precision/mode", "calcPr": calc})
    return {"date1904": target_epoch, "iterate": True, "iterateDelta": min(deltas), "iterateCount": max(counts), "refMode": "A1", "calcMode": "auto", "requires_actual_value_date_equivalence": True, "requires_two_pass_stability": True}, holds


def inspect_donors(specs):
    """Return a frozen preflight description; it performs no writes/calculation."""
    require(specs and len({d["id"] for d in specs}) == len(specs), "Unique nonempty donor set required")
    donors = []
    holds = []
    used = set()
    for spec in specs:
        try:
            donors.append(_load(spec, used))
        except (UnsupportedWorkbook, KeyError, ValueError) as exc:
            holds.append({"donor": spec.get("id"), "reason": str(exc)})
    policy, metadata_holds = _common_settings(donors) if donors else ({}, [])
    holds.extend(metadata_holds)
    try:
        _, style_offsets = _merge_styles(donors)
        _merge_sst(donors, style_offsets)
    except (UnsupportedWorkbook, ValueError) as exc:
        holds.append({"reason": "Global style/shared-string preservation: " + str(exc)})
        style_offsets = [None] * len(donors)
    rows = []
    for d, offsets in zip(donors, style_offsets):
        formula_count = 0
        reference_audits = {}
        for part, data in d.parts.items():
            if part.startswith(("xl/worksheets/", "xl/charts/", "xl/drawings/", "xl/tables/", "xl/comments")) and not part.endswith(".rels"):
                try:
                    translated = _part_rewrite(d, part, data, offsets)
                    reference_audits[part] = audit_formula_translation(d, part, translated)
                    if part in d.sheet_parts.values():
                        formula_count += sum(n.localName == "f" for n in _all(_xml(data)))
                except (UnsupportedWorkbook, ValueError) as exc:
                    holds.append({"donor": d.spec["id"], "part": part, "reason": str(exc)})
        census = dependency_census(d)
        mapped_risks = []
        for lineage in d.spec.get("risk_lineage", []):
            for risk in lineage.get("risks", []):
                regions = []
                for region in risk.get("unsafe_regions", []):
                    if region.get("sheet") not in d.sheet_map:
                        holds.append({"donor": d.spec["id"], "reason": "Risk region sheet is absent from selected goal", "region": region})
                    else:
                        regions.append({**region, "sheet": d.sheet_map[region["sheet"]]})
                mapped_risks.append({"source_sha256": d.spec.get("source_sha256"), "workbook_sha256": d.spec["workbook"]["sha256"], "original_risk": risk, "mapped_unsafe_regions": regions, "future_full_actual_D_intersection_required": True, "risk_not_dismissed_by_composition": True})
        cached_errors = []
        for sheet, part in d.sheet_parts.items():
            for cell in _all(_xml(d.parts[part])):
                if cell.localName == "c" and cell.getAttribute("t") == "e":
                    value = _one(cell, "v")
                    cached_errors.append({"original_sheet": sheet, "mapped_sheet": d.sheet_map[sheet], "cell": cell.getAttribute("r"), "cached_error": _text(value) if value else None, "future_full_actual_D_disjointness_or_review_required": True, "unchanged_error_not_repaired": True})
        definitions = _one(d.workbook.documentElement, "definedNames")
        print_errors = [{"name": n.getAttribute("name"), "localSheetId": n.getAttribute("localSheetId"), "value": _text(n), "unchanged_metadata_error": True} for n in _children(definitions, "definedName") if _text(n) == "#REF!"] if definitions else []
        rows.append({"id": d.spec["id"], "prefix": d.spec["prefix"], "workbook": d.spec["workbook"], "source_sha256": d.spec.get("source_sha256"), "sheet_map": d.sheet_map, "sheet_parts": d.sheet_parts, "table_map": d.tables, "name_map": [{"scope": k[0], "old": k[1], "new": v} for k, v in sorted(d.names.items(), key=str)], "formula_count": formula_count, "all_formula_metadata_reference_roundtrips": reference_audits, "defined_name_metadata_errors_retained": print_errors, "dependency_census": census, "date_cells": d.dates, "date_sensitive_formulas": d.date_functions, "original_settings": d.settings, "part_inventory": {p: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for p, b in sorted(d.parts.items())}, "scoped_audits": d.spec.get("scoped_audits", []), "risk_lineage": d.spec.get("risk_lineage", []), "mapped_risk_lineage": mapped_risks, "retained_cached_error_lineage": cached_errors, "whole_source_financial_certified": False})
    return {"kind": KIND + "_preflight", "version": VERSION, "passed": not holds and len(donors) == len(specs), "holds": holds, "donors": rows, "calculation_policy": policy, "theme_policy": "One shared presentation theme; source theme/indexed color references resolved to source RGB so financial input color cues remain. Theme typography may normalize; no pixel-identity claim.", "coordinates_relocated": False, "cross_business_financial_aggregation": False, "all_other_typed_cached_values_preserved": True, "explicit_date_cache_conversions": [{"donor": d.spec["id"], **x} for d in donors for x in (_date_adjustments(d, policy["date1904"]) if not metadata_holds else [])], "OFFSET_scope": "Same coordinates and parsed qualified-reference translation only; no static dependency closure or financial certificate", "requires_actual_value_date_equivalence": True, "requires_two_pass_stability": True, "financial_certified": False, "source_admitted": False, "LO_model_solver_Harbor_calls": 0}


def _formula_entries(data):
    entries = []
    for n in _all(_xml(data)):
        if n.localName in {"f", "formula", "formula1", "formula2", "calculatedColumnFormula", "totalsRowFormula"}:
            entries.append((n.localName, _text(n)))
        if n.localName == "hyperlink" and n.hasAttribute("location"):
            entries.append(("hyperlink_location", n.getAttribute("location")))
    return entries


def _formula_tokens(formula):
    result = []
    for token in Tokenizer("=" + formula.removeprefix("=")).items:
        value = token.value
        if token.type == "OPERAND" and token.subtype == "RANGE":
            if "!" in value:
                qualifier, operand = value.rsplit("!", 1)
                value = _unquote(qualifier).casefold() + "!" + operand.casefold()
            else:
                value = value.casefold()
        elif token.type == "FUNC":
            value = value.casefold()
        result.append((token.type, token.subtype, value))
    return result


def audit_formula_translation(donor, part, translated):
    """Independently reverse every translated formula operand to its donor."""
    if not (part.endswith(".xml") or part.endswith(".vml")):
        return 0
    old = _formula_entries(donor.parts[part]);new = _formula_entries(translated)
    require(len(old) == len(new), "Formula-bearing metadata was lost: " + part)
    reverse_sheets = {v: k for k, v in donor.sheet_map.items()}
    reverse_names = {(donor.sheet_map[next(s for s in donor.sheets if s.casefold() == scope)].casefold() if scope else None, mapped.casefold()): original for (scope, original), mapped in donor.names.items()}
    reverse_tables = {v: k for k, v in donor.tables.items()}
    local_sheet = next((donor.sheet_map[s] for s, p in donor.sheet_parts.items() if p == part), None)
    table_context = _xml(translated).documentElement.getAttribute("name") if part.startswith("xl/tables/") else None
    for (old_kind, original), (new_kind, rewritten) in zip(old, new):
        require(old_kind == new_kind, "Formula-bearing metadata changed kind: " + part)
        reversed_formula = rewrite_formula(rewritten, reverse_sheets, reverse_names, reverse_tables, local_sheet=local_sheet, table_context=table_context)
        require(_formula_tokens(original) == _formula_tokens(reversed_formula), "Formula reference round trip failed: " + part + ": " + original)
    return len(old)


def _merge_styles(donors):
    doc = _doc(S, "styleSheet")
    root = doc.documentElement
    sections = {name: _add(root, name, {"count": "0"}) for name in STYLE_SECTIONS if name != "colors"}
    offsets = []
    next_format = 164
    for d in donors:
        source = _xml(d.parts["xl/styles.xml"])
        _colors(source, d.palette, d.indexed_colors)
        old = {name: _one(source.documentElement, name) for name in STYLE_SECTIONS}
        off = {name: len(_elements(sections[name])) for name in sections}
        off["counts"] = {name: len(_elements(old[name])) if old[name] else 0 for name in old}
        fmt_map = {}
        if old["numFmts"]:
            for n in _elements(old["numFmts"]):
                fmt_map[int(n.getAttribute("numFmtId"))] = next_format
                next_format += 1
        for section in sections:
            if section == "tableStyles":
                require(not old[section] or not _elements(old[section]), "Custom table styles are unsupported")
                continue
            for n in _elements(old[section]) if old[section] else []:
                n = n.cloneNode(True)
                for x in _all(n):
                    if x.hasAttribute("numFmtId") and int(x.getAttribute("numFmtId")) in fmt_map:
                        x.setAttribute("numFmtId", str(fmt_map[int(x.getAttribute("numFmtId"))]))
                    for attr, family in (("fontId", "fonts"), ("fillId", "fills"), ("borderId", "borders"), ("xfId", "cellStyleXfs")):
                        if x.hasAttribute(attr):
                            index = int(x.getAttribute(attr));require(index < off["counts"][family], "Invalid source style component index")
                            x.setAttribute(attr, str(index + off[family]))
                if section == "cellStyles":
                    n.setAttribute("name", d.spec["prefix"] + "__" + n.getAttribute("name"))
                    if n.hasAttribute("builtinId"):
                        n.removeAttribute("builtinId")
                sections[section].appendChild(doc.importNode(n, True))
        offsets.append(off)
    for section, node in sections.items():
        node.setAttribute("count", str(len(_elements(node))))
        if section == "tableStyles":
            node.setAttribute("defaultTableStyle", "TableStyleMedium2")
            node.setAttribute("defaultPivotStyle", "PivotStyleLight16")
    return _bytes(doc), offsets


def _merge_sst(donors, offsets):
    doc = _doc(S, "sst")
    root = doc.documentElement
    for d, off in zip(donors, offsets):
        off["sst"] = len(_elements(root))
        source = _xml(d.parts["xl/sharedStrings.xml"]) if "xl/sharedStrings.xml" in d.parts else None
        if source:
            _colors(source, d.palette, d.indexed_colors)
        items = _children(source.documentElement, "si") if source else []
        off["counts"]["sst"] = len(items)
        for item in items:
            root.appendChild(doc.importNode(item, True))
    # count/uniqueCount are optional. Entries retain their original indexes and
    # may duplicate strings from other donors, so neither count is invented.
    return _bytes(doc)


def _semantic(node):
    if node.nodeType != Node.ELEMENT_NODE:
        return None
    return (node.namespaceURI, node.localName, tuple(sorted(((node.attributes.item(i).namespaceURI, node.attributes.item(i).localName, node.attributes.item(i).value) for i in range(node.attributes.length) if not node.attributes.item(i).name.startswith("xmlns")), key=repr)), tuple(_semantic(n) if n.nodeType == Node.ELEMENT_NODE else n.data for n in node.childNodes if n.nodeType in (Node.ELEMENT_NODE, Node.TEXT_NODE, Node.CDATA_SECTION_NODE)))


def _typed_cells(data, strings):
    out = {}
    for c in _all(_xml(data)):
        if c.localName != "c" or c.namespaceURI != S:
            continue
        value = _one(c, "v")
        inline = _one(c, "is")
        t = c.getAttribute("t") or "n"
        v = _text(value) if value else None
        if t == "s":
            v = _semantic(strings[int(v)])
        if inline:
            v = _semantic(inline)
        out[c.getAttribute("r")] = (t, v)
    return out


def _string_items(parts):
    return _children(_xml(parts["xl/sharedStrings.xml"]).documentElement, "si") if "xl/sharedStrings.xml" in parts else []


def compose(specs, output_path):
    """Emit one fresh package after a complete supported-content preflight."""
    output = Path(output_path)
    require(not output.exists(), "Review-pack output must be fresh")
    preflight = inspect_donors(specs)
    require(preflight["passed"], "Composition held: " + json.dumps(preflight["holds"], sort_keys=True))
    used = set()
    donors = [_load(d, used) for d in specs]
    styles, offsets = _merge_styles(donors)
    strings = _merge_sst(donors, offsets)
    parts = {"xl/styles.xml": styles, "xl/sharedStrings.xml": strings}
    theme = next(k for k in donors[0].parts if re.fullmatch(r"xl/theme/theme\d+\.xml", k))
    parts["xl/theme/theme1.xml"] = donors[0].parts[theme]
    w = _doc(S, "workbook");wr = w.documentElement;wr.setAttribute("xmlns:r", R)
    policy = preflight["calculation_policy"]
    _add(wr, "workbookPr", {"date1904": str(policy["date1904"]).lower(), "showObjects": "all"})
    views = _add(wr, "bookViews");_add(views, "workbookView", {"activeTab": "0"})
    ws = _add(wr, "sheets");names = _add(wr, "definedNames")
    rels = _doc(P, "Relationships"); rr = rels.documentElement
    for rid, suffix, target in (("theme", "theme", "theme/theme1.xml"), ("styles", "styles", "styles.xml"), ("strings", "sharedStrings", "sharedStrings.xml")):
        _add(rr, "Relationship", {"Id": rid, "Type": R + "/" + suffix, "Target": target})
    ct = _doc(C, "Types");cr = ct.documentElement
    _add(cr, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    content_types = {"xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml", "xl/styles.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml", "xl/sharedStrings.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml", "xl/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml"}
    copies = []
    date_conversions = []
    sheet_index = 0
    table_id = 0
    for donor, off in zip(donors, offsets):
        conversions = _date_adjustments(donor, policy["date1904"])
        date_conversions.extend({"donor": donor.spec["id"], **x} for x in conversions)
        namespace = "xl/donors/" + donor.spec["id"] + "/"
        mapping = {p: namespace + p for p in donor.parts}
        mapping.update({"xl/styles.xml": "xl/styles.xml", "xl/sharedStrings.xml": "xl/sharedStrings.xml"})
        for p in donor.parts:
            if re.fullmatch(r"xl/theme/theme\d+\.xml", p):
                mapping[p] = "xl/theme/theme1.xml"
        table_ids = {}
        for table in donor.tables:
            table_id += 1;table_ids[table] = table_id
        ctd = _xml(donor.parts["[Content_Types].xml"]).documentElement
        defaults = {n.getAttribute("Extension"): n.getAttribute("ContentType") for n in _children(ctd, "Default")}
        overrides = {n.getAttribute("PartName").lstrip("/"): n.getAttribute("ContentType") for n in _children(ctd, "Override")}
        excluded = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml", "xl/sharedStrings.xml"} | {p for p in donor.parts if re.fullmatch(r"xl/theme/theme\d+\.xml", p)}
        for p, data in donor.parts.items():
            if p in excluded:
                continue
            new = mapping[p]
            if p.endswith(".rels"):
                doc = _xml(data)
                for rel in _elements(doc.documentElement):
                    if rel.getAttribute("TargetMode") != "External":
                        target = _resolve(_rels_source(p), rel.getAttribute("Target"))
                        rel.setAttribute("Target", posixpath.relpath(mapping[target], posixpath.dirname(mapping[_rels_source(p)])))
                translated = _bytes(doc)
            else:
                translated = _part_rewrite(donor, p, data, off, table_ids) if p.startswith("xl/") else data
                selected_dates = [x for x in conversions if donor.sheet_parts[x["sheet"]] == p]
                if selected_dates:
                    doc = _xml(translated)
                    cells = {n.getAttribute("r"): n for n in _all(doc) if n.localName == "c" and n.namespaceURI == S}
                    for adjustment in selected_dates:
                        value = _one(cells[adjustment["cell"]], "v")
                        require(value is not None and _text(value) == adjustment["original_cached_text"], "Date cache changed before explicit conversion")
                        _set_text(value, adjustment["converted_cached_text"])
                    translated = _bytes(doc)
            parts[new] = translated
            content_types[new] = overrides.get(p, defaults.get(p.rsplit(".", 1)[-1]))
            require(content_types[new], "Missing source content type: " + p)
        for descriptor in _children(_one(donor.workbook.documentElement, "sheets"), "sheet"):
            old = descriptor.getAttribute("name");sheet_index += 1;rid = "sheet" + str(sheet_index)
            attrs = dict(descriptor.attributes.items());attrs.update({"name": donor.sheet_map[old], "sheetId": str(sheet_index), "r:id": rid})
            attrs = {k: v for k, v in attrs.items() if not (k.endswith(":id") and k != "r:id")}
            _add(ws, "sheet", attrs)
            _add(rr, "Relationship", {"Id": rid, "Type": R + "/worksheet", "Target": posixpath.relpath(mapping[donor.sheet_parts[old]], "xl")})
        defs = _one(donor.workbook.documentElement, "definedNames")
        for old in _children(defs, "definedName") if defs else []:
            n = old.cloneNode(True);scope = donor.sheets[int(old.getAttribute("localSheetId"))] if old.hasAttribute("localSheetId") else None
            key = (scope.casefold() if scope else None, old.getAttribute("name").casefold())
            n.setAttribute("name", donor.names[key])
            if scope is not None:
                n.setAttribute("localSheetId", str(sheet_index - len(donor.sheets) + donor.sheets.index(scope)))
            _set_text(n, rewrite_formula(_text(old), donor.sheet_map, donor.names, donor.tables, local_sheet=scope, defined_name=True))
            names.appendChild(w.importNode(n, True))
        copies.append({"id": donor.spec["id"], "part_map": {p: mapping[p] for p in donor.parts if p not in excluded}, "global_part_normalizations": {p: mapping[p] for p in excluded if p in mapping}, "style_offsets": off})
    if not _elements(names):
        wr.removeChild(names)
    _add(wr, "calcPr", {k: str(policy[k]).lower() if isinstance(policy[k], bool) else str(policy[k]) for k in ("iterate", "iterateDelta", "iterateCount", "refMode", "calcMode")})
    parts["xl/workbook.xml"] = _bytes(w);parts["xl/_rels/workbook.xml.rels"] = _bytes(rels)
    rootrels = _doc(P, "Relationships")
    _add(rootrels.documentElement, "Relationship", {"Id": "workbook", "Type": R + "/officeDocument", "Target": "xl/workbook.xml"})
    parts["_rels/.rels"] = _bytes(rootrels)
    for p, content_type in sorted(content_types.items()):
        _add(cr, "Override", {"PartName": "/" + p, "ContentType": content_type})
    parts["[Content_Types].xml"] = _bytes(ct)
    # Validate all copied internal edges and every typed cached cell before I/O.
    for p, data in parts.items():
        if p.endswith(".rels"):
            for rel in _elements(_xml(data).documentElement):
                if rel.getAttribute("TargetMode") != "External":
                    require(_resolve(_rels_source(p), rel.getAttribute("Target")) in parts, "Translated relationship does not resolve: " + p)
    final_strings = _string_items(parts)
    typed_count = 0
    for donor, copy_record in zip(donors, copies):
        original_strings = _string_items(donor.parts)
        # Color normalization changes SST run colors, not the typed string value.
        for item in original_strings:
            _colors(item, donor.palette, donor.indexed_colors)
        for p in donor.sheet_parts.values():
            normalized = _xml(donor.parts[p]);_colors(normalized, donor.palette, donor.indexed_colors)
            before = _typed_cells(_bytes(normalized), original_strings)
            for adjustment in date_conversions:
                if adjustment["donor"] == donor.spec["id"] and donor.sheet_parts[adjustment["sheet"]] == p:
                    old_type, old_value = before[adjustment["cell"]]
                    require(old_value == adjustment["original_cached_text"], "Date original typed value mismatch")
                    before[adjustment["cell"]] = (old_type, adjustment["converted_cached_text"])
            after = _typed_cells(parts[copy_record["part_map"][p]], final_strings)
            require(before == after, "Typed cached cell changed during composition: " + donor.spec["id"] + "/" + p)
            typed_count += len(before)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            for name, data in sorted(parts.items()):
                info = ZipInfo(name, (2000, 1, 1, 0, 0, 0));info.compress_type = ZIP_DEFLATED
                archive.writestr(info, data)
    return {"kind": KIND, "version": VERSION, "workbook": file_ref(output), "preflight": preflight, "copies": copies, "typed_cached_cells_checked": typed_count, "explicit_date_cache_conversions": date_conversions, "all_other_typed_cached_values_preserved": True, "all_internal_relationships_resolved": True, "all_source_coordinates_retained": True, "formula_translation_complete_for_supported_parts": True, "source_core_extended_custom_properties_archived_under_donor_namespace": True, "financial_certified": False, "source_admitted": False, "LO_model_solver_Harbor_calls": 0, "requires_actual_value_date_equivalence": True, "requires_two_pass_stability": True}
