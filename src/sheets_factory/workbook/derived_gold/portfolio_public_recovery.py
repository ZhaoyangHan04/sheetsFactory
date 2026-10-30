"""Standalone public-only recovery for the documented fully owned portfolio.

This adapter reuses the independent, default-free public project journal.  It
does not import the portfolio emitter, read a reference workbook or infer
missing assumptions from another subsidiary.
"""
from __future__ import annotations

import ast

from .public_recovery import compile_public_project_recovery


_PORTFOLIO_REPLAY = r'''

import tempfile


def _portfolio_public_mapping(book):
    required = {"Portfolio Index", "Group Statements", "Group Summary"}
    if not required.issubset(book.sheetnames):
        raise ValueError("Missing public portfolio index or group reports")
    index = book["Portfolio Index"]
    policy = " ".join(str(c.value).lower() for row in index for c in row
                      if isinstance(c.value, str) and len(c.value) >= 60)
    if not all(text in policy for text in ("100%", "no intercompany", "no additional parent",
            "cannot be shared", "sum", "annual opening", "annual closing")):
        raise ValueError("The explicit fully owned, separate-tax, no-intercompany group policy is missing")
    headings = None
    mapping = {}
    for row in index:
        labels = {_public_label(c.value): c.column - 1 for c in row if c.value is not None}
        if {"entity id", "original sheet", "portfolio sheet"}.issubset(labels):
            if headings is not None:
                raise ValueError("Ambiguous public portfolio mapping header")
            headings = labels
            continue
        if headings is None:
            continue
        entity = row[headings["entity id"]].value
        original = row[headings["original sheet"]].value
        target = row[headings["portfolio sheet"]].value
        if entity is None and original is None and target is None:
            continue
        if (not isinstance(entity, str) or not re.fullmatch(r"T[0-9]{2}", entity)
                or not isinstance(original, str) or not isinstance(target, str)
                or target != entity + " " + original or target not in book.sheetnames):
            raise ValueError("Invalid public subsidiary sheet mapping")
        entity_map = mapping.setdefault(entity, {})
        if original in entity_map or target in {v for m in mapping.values() for v in m.values()}:
            raise ValueError("Duplicate public subsidiary sheet mapping")
        entity_map[original] = target
    project = {"Read Me", "Source Inputs", "Scenario", "Calendar", "Operations", "Assets",
               "Debt", "Tax", "Cash Flow", "Balance Sheet", "Equity Value", "Annual Statements"}
    if headings is None or len(mapping) < 2 or any(not project.issubset(m) for m in mapping.values()):
        raise ValueError("Incomplete public subsidiary mapping")
    mapped = {v for m in mapping.values() for v in m.values()}
    if set(book.sheetnames) != mapped | required:
        raise ValueError("Unmapped public portfolio worksheets are unsupported")
    return dict(sorted(mapping.items()))


def _portfolio_public_reconstruct(source, destination):
    source, destination = Path(source), Path(destination)
    book = openpyxl.load_workbook(source, keep_links=False)
    public = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    try:
        mappings = _portfolio_public_mapping(public)
        calendars = []
        for mapping in mappings.values():
            calendar = public[mapping["Calendar"]]
            date_row = _public_rows(calendar).get("date")
            if date_row is None:
                raise ValueError("Missing public subsidiary calendar dates")
            dates = [calendar.cell(date_row, column).value for column in range(3, 39)]
            if not all(hasattr(value, "isoformat") for value in dates):
                raise ValueError("Missing public subsidiary calendar date cache")
            calendars.append(dates)
        if any(dates != calendars[0] for dates in calendars[1:]) or [
                public["Group Statements"].cell(1, column).value for column in range(3, 39)] != calendars[0]:
            raise ValueError("Public subsidiary and group reporting dates differ")
        results = []
        equity_funding = []
        calculated_modules = {"Operations", "Assets", "Debt", "Tax", "Cash Flow", "Balance Sheet",
                              "Equity Value", "Annual Statements", "Covenants", "Tax Vintages"}
        # Cached primitive assumptions and public dates are copied as supplied
        # values. Saving formula-only copies would erase those public caches.
        # No other entity supplies defaults or missing values.
        with tempfile.TemporaryDirectory(prefix="portfolio-public-", dir=destination.parent) as temporary:
            temporary = Path(temporary)
            for entity, mapping in mappings.items():
                raw, recovered = temporary / (entity + ".xlsx"), temporary / (entity + "-recovered.xlsx")
                sub = openpyxl.Workbook()
                sub.remove(sub.active)
                for original, full in mapping.items():
                    target = sub.create_sheet(original)
                    for row in public[full]:
                        for cell in row:
                            if cell.value is not None:
                                target.cell(cell.row, cell.column, cell.value)
                sub.save(raw)
                sub.close()
                result = _public_reconstruct(raw, recovered)
                results.append(result)
                restored = openpyxl.load_workbook(recovered, data_only=True, keep_links=False)
                try:
                    equity_rows = _public_rows(restored["Equity Value"])
                    funding = restored["Equity Value"].cell(equity_rows["owner cash flow"], 2).value
                    equity_funding.append(-_decimal(funding, "public owner equity funding"))
                    for original in calculated_modules & set(mapping):
                        target = book[mapping[original]]
                        for row in restored[original]:
                            for cell in row:
                                if (cell.column >= 2 and not isinstance(cell.value, bool)
                                        and isinstance(cell.value, (int, float, Decimal))):
                                    # The witness writes independently derived
                                    # values, while preserving all input modules,
                                    # row labels, sheet metadata and dimensions.
                                    target.cell(cell.row, cell.column, cell.value)
                finally:
                    restored.close()
        monthly = []
        for index in range(36):
            keys = set(results[0]["monthly"][index])
            if any(set(result["monthly"][index]) != keys for result in results):
                raise ValueError("Subsidiary journal schemas differ")
            monthly.append({key: sum((result["monthly"][index][key] for result in results), _ZERO)
                            for key in keys if key not in {"period", "year", "month", "date", "days"}
                            and isinstance(results[0]["monthly"][index][key], (Decimal, int))})
        monthly_rows = _public_rows(public["Group Statements"])
        check_labels = {"group balance check", "group cfo check", "group operating cash check",
                        "group total cash check", "group reserve check", "group retained check", "group income check"}
        for index, amounts in enumerate(monthly):
            column = index + 3
            checks = {
                "group balance check": amounts["assets"] - amounts["liabilities"] - amounts["equity"],
                "group cfo check": amounts["cfo_direct"] - amounts["cfo_indirect"],
                "group operating cash check": amounts["cash_open"] + amounts["cfo_direct"] + amounts["cfi"]
                    + amounts["cff"] + amounts["dsra_release"] + amounts["dsra_support"]
                    - amounts["dsra_funding"] - amounts["cash_close"],
                "group total cash check": amounts["cash_open"] + amounts["dsra_open"] + amounts["cfo_direct"]
                    + amounts["cfi"] + amounts["cff"] - amounts["total_cash_close"],
                "group reserve check": amounts["dsra_open"] + amounts["dsra_funding"]
                    - amounts["dsra_release"] - amounts["dsra_support"] - amounts["dsra_close"],
                "group retained check": amounts["retained_open"] + amounts["net_income"]
                    - amounts["dividend"] - amounts["retained_close"],
                "group income check": amounts["ebt"] - amounts["tax"] - amounts["net_income"],
            }
            if any(value != 0 for value in checks.values()):
                raise ArithmeticError("Independent public group journals do not reconcile")
            for label, row in monthly_rows.items():
                key = label.replace(" ", "_")
                if label in check_labels:
                    amount = checks[label]
                elif key in amounts:
                    amount = amounts[key]
                else:
                    raise ValueError("Unsupported public group monthly row: " + label)
                book["Group Statements"].cell(row, column, float(amount))
        closing = {"accumulated_depreciation", "asset_initial_gross", "asset_refresh_gross", "assets",
                   "balance_check", "cash_before_allocation", "equity", "liabilities", "net_ppe"}
        valuations = {key: sum((result["valuation"][key] for result in results), _ZERO)
                      for key in results[0]["valuation"] if all(
                          isinstance(result["valuation"][key], (Decimal, int)) for result in results)}
        annual_rows = _public_rows(public["Group Summary"])
        for label, row in annual_rows.items():
            if row <= 20:
                continue
            key = label.replace(" ", "_")
            if key == "initial_owner_equity":
                book["Group Summary"].cell(row, 3, float(sum(equity_funding, _ZERO)))
            elif key in valuations:
                book["Group Summary"].cell(row, 3, float(valuations[key]))
            elif key in monthly[0]:
                for year in range(3):
                    periods = monthly[year * 12:(year + 1) * 12]
                    if key.endswith("_open"):
                        amount = periods[0][key]
                    elif key.endswith("_close") or key in closing:
                        amount = periods[-1][key]
                    else:
                        amount = sum((period[key] for period in periods), _ZERO)
                    book["Group Summary"].cell(row, year + 3, float(amount))
            else:
                raise ValueError("Unsupported public group annual/value row: " + label)
        book.save(destination)
    finally:
        public.close()
        book.close()


if __name__ == "__main__":
    _portfolio_public_reconstruct("/workspace/input.xlsx", "/workspace/output.xlsx")
'''


def compile_public_portfolio_recovery() -> str:
    """Return a standalone program requiring only the actual public workbook."""
    tree = ast.parse(compile_public_project_recovery())
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__")]
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_public_reconstruct")
    function.args.args = [ast.arg(arg="source_path"), ast.arg(arg="destination_path")]
    if not (isinstance(function.body[0], ast.Assign) and isinstance(function.body[1], ast.Assign)
            and isinstance(function.body[-1], ast.Try)):
        raise ValueError("Public project adapter structure changed")
    function.body[0].value = ast.Call(func=ast.Name(id="Path", ctx=ast.Load()),
        args=[ast.Name(id="source_path", ctx=ast.Load())], keywords=[])
    function.body[1].value = ast.Call(func=ast.Name(id="Path", ctx=ast.Load()),
        args=[ast.Name(id="destination_path", ctx=ast.Load())], keywords=[])
    function.body[-1].body.append(ast.Return(value=ast.Name(id="result", ctx=ast.Load())))
    code = ast.unparse(ast.fix_missing_locations(tree)) + "\n" + _PORTFOLIO_REPLAY
    compile(code, "portfolio_public_recovery.py", "exec")
    return code
