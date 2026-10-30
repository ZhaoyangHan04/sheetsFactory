"""Compile an expert journal reconstruction that reads only the public workbook.

The replay program embeds the independently implemented Decimal journal, never
the formula emitter, a goal workbook, task edits or per-task reference answers.
It is a programmatic recovery witness, not a scored LLM attempt.
"""

from __future__ import annotations

import ast
from pathlib import Path
import textwrap


_REPLAY = r'''

# Public-only workbook adapter for the independent journal above.
import re
from pathlib import Path
import openpyxl


def _public_label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _public_rows(sheet):
    result = {}
    for row in sheet.iter_rows(min_col=1, max_col=1):
        cell = row[0]
        label = _public_label(cell.value)
        if label:
            if label in result:
                raise ValueError("Ambiguous public row label: " + sheet.title + "/" + label)
            result[label] = cell.row
    return result


def _public_reconstruct():
    source = Path("/workspace/input.xlsx")
    destination = Path("/workspace/output.xlsx")
    book = openpyxl.load_workbook(source, keep_links=False)
    values = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    try:
        needed = {"Read Me", "Source Inputs", "Scenario", "Calendar", "Operations", "Assets",
                  "Debt", "Tax", "Cash Flow", "Balance Sheet", "Equity Value", "Annual Statements"}
        if not needed.issubset(book.sheetnames):
            raise ValueError("Unrecognized public project workbook")
        public_policies = [cell.value for row in values["Read Me"] for cell in row
                           if isinstance(cell.value, str) and len(cell.value) >= 60]
        policy = " ".join(public_policies).lower()
        if len(public_policies) < 5 or not all(word in policy for word in
                                             ("hypothetical", "month", "nol", "debt", "round")):
            raise ValueError("The public project business contract is missing")
        rows = {name: _public_rows(book[name]) for name in book.sheetnames if name != "Read Me"}
        parameter_rows = rows["Scenario"]
        cyclic = "DebtSizing" in book
        if cyclic and not all(word in policy for word in (
                "underwriting", "capacity", "tranche", "equity",
                "twelve times the unrounded monthly unit-annuity", "round capacity to cents",
                "rounded down to a tranche")):
            raise ValueError("The explicit public debt-underwriting policy is missing")
        def assumption(name):
            if cyclic and name in {"loan_a_principal", "equity_paid_in"}:
                # Financing quantities are independently solved outputs. Never
                # reuse their possibly masked or mutated cached values.
                return _ZERO
            label = name.replace("_", " ")
            if label not in parameter_rows:
                raise ValueError("Missing public project assumption: " + name)
            value = values["Scenario"].cell(parameter_rows[label], 2).value
            if name == "start_date":
                if hasattr(value, "date"):
                    return value.date().isoformat()
                if hasattr(value, "isoformat"):
                    return value.isoformat()
                return str(value)
            return _decimal(value, name)
        # All scalar values, including normally defaulted assumptions, must be
        # present publicly.  The embedded ledger has no numerical defaults.
        parameters = {name: assumption(name) for name in
                      set(_DEFAULTS) | set(_REQUIRED_RESOLVED)
                      if name not in {"ramp_factors", "residual"}}
        if "residual" in parameter_rows:
            parameters["residual"] = assumption("residual")
        elif re.search(r"cost\s*/\s*life", policy) or "zero residual" in policy:
            # The public cost/life charge with a remaining-cost cap specifies
            # a zero-residual policy even when it has no separate input row.
            parameters["residual"] = _ZERO
        else:
            raise ValueError("The public book-depreciation residual policy is missing")
        ramp_labels = sorted((label for label in parameter_rows if re.fullmatch(r"ramp [1-9][0-9]*", label)),
                             key=lambda label: int(label.split()[-1]))
        if not ramp_labels or [int(label.split()[-1]) for label in ramp_labels] != list(range(1, len(ramp_labels) + 1)):
            raise ValueError("Public ramp assumptions must be a complete ordered sequence")
        parameters["ramp_factors"] = [assumption(label.replace(" ", "_")) for label in ramp_labels]
        specification = {"parameters": parameters}
        if cyclic:
            parameters["equity_paid_in"] = (parameters["initial_asset_cost"]
                + parameters["opening_cash"] - parameters["loan_b_principal"])
            specification["cyclic_financing_parameters"] = {
                key: assumption("cyclic_" + key) for key in
                ("enabled", "bankcap", "target_dscr", "tranche")}
            if specification["cyclic_financing_parameters"]["enabled"] != _ONE:
                raise ValueError("The public cyclic underwriting contract must be explicitly enabled")
        covenant_names = ("covenant_enabled", "covenant_first_test_month", "covenant_dscr_threshold",
                          "dsra_normal_payment_months", "dsra_trap_payment_months")
        if "covenant enabled" in parameter_rows:
            specification["covenant_parameters"] = {name: assumption(name) for name in covenant_names}
        tax_names = ("advanced_tax_enabled", "initial_tax_rate_y1", "initial_tax_rate_y2",
                     "initial_tax_rate_y3", "refresh_tax_rate_y1", "refresh_tax_rate_y2",
                     "refresh_tax_rate_y3", "interest_deduction_ebitda_fraction", "nol_carryforward_years")
        if "advanced tax enabled" in parameter_rows:
            if not all(word in policy for word in ("deferred", "vintage", "expire", "fifo")):
                raise ValueError("The advanced public tax contract is missing")
            specification["advanced_tax_parameters"] = {name: assumption(name) for name in tax_names}
        result = simulate(specification)
        period_row = rows["Calendar"].get("period")
        if period_row is None:
            raise ValueError("Missing public monthly calendar")
        columns = []
        for period in range(1, 37):
            matching = [cell.column for cell in values["Calendar"][period_row]
                        if not isinstance(cell.value, bool) and cell.value == period and cell.column >= 3]
            if len(matching) != 1:
                raise ValueError("The public calendar does not identify each monthly period uniquely")
            columns.append(matching[0])
        if columns != list(range(columns[0], columns[0] + 36)):
            raise ValueError("The public monthly calendar is not contiguous")
        monthly_sheets = ("Operations", "Assets", "Debt", "Tax", "Cash Flow", "Balance Sheet", "Covenants")
        def write(sheet, label, column, amount):
            row = rows[sheet].get(_public_label(label))
            if row is None:
                raise ValueError("Unrecognized public calculation row: " + sheet + "/" + label)
            if isinstance(amount, Decimal):
                if not amount.is_finite():
                    raise ValueError("The independent journal produced a nonfinite value")
                amount = float(amount)
            book[sheet].cell(row, column, amount)
        if cyclic:
            sizing = result["debt_sizing"]
            parameters["loan_a_principal"] = sizing["sized_principal"]
            parameters["equity_paid_in"] = sizing["equity_paid_in"]
            for key in ("loan_a_principal", "equity_paid_in"):
                write("Scenario", key, 2, parameters[key])
            for key, amount in sizing.items():
                write("DebtSizing", key, 2, amount)
        p = _parameters(specification)
        cov = p["covenant"] is not None
        advanced = p["advanced_tax"] is not None
        # Row labels and field names are metadata. Financial amounts come only
        # from the independent journal and the supplied public assumptions.
        aliases = {
            "Operations": {"total book income tax expense signed": "tax"},
            "Assets": {"initial asset depreciation": "depreciation_initial",
                       "refresh depreciation": "depreciation_refresh", "total depreciation": "depreciation"},
            "Debt": {"total cash interest": "interest"},
            "Tax": {"year end cash tax": "current_tax" if advanced else "tax"},
            "Cash Flow": {"scheduled loan a principal": "loan_a_scheduled_principal",
                          "loan b principal": "loan_b_principal",
                          "dsra net transfer to operating cash": "dsra_net_transfer",
                          "total cash including dsra": "total_cash_close",
                          "deferred tax adjustment signed": "deferred_tax_expense"},
            "Balance Sheet": {"cash": "cash_close", "operating cash": "cash_close",
                              "receivables": "ar_close", "inventory": "inventory_close",
                              "initial asset cost including cip": "asset_initial_gross",
                              "refresh asset cost": "asset_refresh_gross",
                              "accumulated depreciation": "accumulated_depreciation",
                              "net fixed assets including cip": "net_ppe", "payables": "ap_close",
                              "loan a": "loan_a_close", "loan b": "loan_b_close", "revolver": "revolver_close",
                              "dsra restricted cash": "dsra_close", "gross deferred tax asset": "dta_close",
                              "gross deferred tax liability": "dtl_close"},
        }
        for index, (column, monthly) in enumerate(zip(columns, result["monthly"])):
            direct = {_public_label(key): key for key in monthly}
            helpers = {
                "Assets": {}, "Debt": {"original level payment": result["valuation"]["loan_a_payment"]},
                "Tax": {"year to date pretax income": sum((row["ebt"] for row in
                          result["monthly"][(index // 12) * 12:index + 1]), _ZERO)},
                "Cash Flow": {
                    "excess after revolver": monthly["allocation_excess"] if cov else max(
                        _ZERO, monthly["cash_before_allocation"] + monthly["revolver_draw"]
                        - monthly["revolver_repayment"] - p["minimum_cash"]),
                    "optional allocation allowed": int(monthly["period"] >= p["cash_allocation_start"]),
                    "cash reconciliation": (monthly["cash_open"] + monthly["cfo_direct"] + monthly["cfi"]
                        + monthly["cff"] + monthly.get("dsra_net_transfer", _ZERO) - monthly["cash_close"]),
                },
                "Balance Sheet": {"paid in equity": p["equity_paid_in"]},
            }
            if cov:
                helpers["Cash Flow"]["total cash reconciliation"] = (
                    monthly["cash_open"] + monthly["dsra_open"] + monthly["cfo_direct"]
                    + monthly["cfi"] + monthly["cff"] - monthly["total_cash_close"])
            for sheet in monthly_sheets:
                if sheet not in book:
                    continue
                for label, row in rows[sheet].items():
                    if row <= 1:
                        continue
                    key = aliases.get(sheet, {}).get(label, direct.get(label))
                    if key is not None:
                        if key not in monthly:
                            raise ValueError("Public row requires unavailable journal field: " + key)
                        write(sheet, label, column, monthly[key])
                    elif label in helpers.get(sheet, {}):
                        write(sheet, label, column, helpers[sheet][label])
                    else:
                        raise ValueError("Unrecognized public financial calculation row: " + sheet + "/" + label)
        valuation = result["valuation"]
        for key, amount in valuation.items():
            label = _public_label(key)
            if label in rows["Equity Value"]:
                write("Equity Value", label, 2, amount)
        write("Equity Value", "owner cash flow", 2, -p["equity_paid_in"])
        with localcontext() as context:
            context.prec = 60
            for column, monthly in zip(columns, result["monthly"]):
                write("Equity Value", "owner cash flow", column, monthly["owner_cashflow"])
                write("Equity Value", "dividend", column, monthly["dividend"])
                pv = monthly["owner_cashflow"] / (_ONE + valuation["monthly_discount_rate"]) ** monthly["period"]
                write("Equity Value", "pv of owner cash flow", column, _q(pv))
        # Annual columns are identified by their public year row, not by private
        # targets, a task plan, a baseline workbook or any hidden answer file.
        for year, annual in enumerate(result["annual"], 1):
            year_row = rows["Annual Statements"]["year"]
            candidates = [cell.column for cell in values["Annual Statements"][year_row]
                          if cell.column >= 3 and cell.value == year]
            if len(candidates) != 1:
                raise ValueError("Ambiguous public annual-summary columns")
            column = candidates[0]
            direct = {_public_label(key): key for key in annual}
            for label, row in rows["Annual Statements"].items():
                if label in {"year", "periods", "start date", "end date"} or row <= 1:
                    continue
                if label not in direct:
                    raise ValueError("Unrecognized public annual financial row: " + label)
                write("Annual Statements", label, column, annual[direct[label]])
        if advanced:
            if "Tax Vintages" not in book:
                raise ValueError("The public advanced tax schedule is missing")
            year_row = rows["Tax Vintages"]["model year"]
            for annual in result["tax_annual"]:
                candidates = [cell.column for cell in values["Tax Vintages"][year_row]
                              if cell.column >= 3 and cell.value == annual["year"]]
                if len(candidates) != 1:
                    raise ValueError("Ambiguous public tax-vintage columns")
                for key, amount in annual.items():
                    if key != "year":
                        write("Tax Vintages", key, candidates[0], amount)
        if not result["checks"]["all_balanced"] or any(
                result["checks"][key] != 0 for key in ("max_cfo_reconciliation_error",
                "max_cash_reconciliation_error", "max_income_reconciliation_error", "max_journal_error")):
            raise ArithmeticError("The independent public reconstruction did not reconcile")
        destination.parent.mkdir(parents=True, exist_ok=True)
        book.save(destination)
    finally:
        values.close()
        book.close()


if __name__ == "__main__":
    _public_reconstruct()
'''


def compile_public_project_recovery() -> str:
    """Return standalone Python for a public-only expert recovery replay.

    Numeric scenario defaults are removed from the embedded journal. Every
    primitive assumption must be present in the replay's public Scenario worksheet.
    """
    source = Path(__file__).with_name("ledger.py").read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_DEFAULTS":
            if not isinstance(node.value, ast.Dict):
                raise ValueError("Independent ledger default schema changed")
            node.value.values = [ast.Constant(None) for _ in node.value.keys]
            break
    else:
        raise ValueError("Independent ledger assumption schema is unavailable")
    code = ast.unparse(ast.fix_missing_locations(tree))
    return code + "\n" + textwrap.dedent(_REPLAY).lstrip()
