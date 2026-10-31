"""Real OOXML construction checks, with no engine or model calls."""
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.utils.cell import coordinate_from_string
import pytest

from sheets_factory.workbook.operating_metrics_regime import excel, spec, oracle_a


def load(ref):
    return json.loads(Path(ref["path"]).read_text())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    folder = tmp_path_factory.mktemp("operating_metrics") / "candidate"
    preparation = excel.build_views(folder)
    p = load(preparation); definition = load(p["bindings"])
    return folder, p, definition, {b["key"]: b for b in definition["bindings"]}


def grid(path):
    book = openpyxl.load_workbook(path, data_only=False)
    result = {(s.title, c.coordinate): c.value for s in book for row in s for c in row if c.value is not None}
    book.close(); return result


def formula_cells_and_cached_count(path):
    formulas, cached = {}, 0
    with ZipFile(path) as archive:
        for part in archive.namelist():
            if part.startswith("xl/worksheets/sheet") and part.endswith(".xml"):
                for cell in ET.fromstring(archive.read(part)).findall("{*}sheetData/{*}row/{*}c"):
                    node = cell.find("{*}f")
                    if node is not None:
                        formulas[part, cell.get("r")] = node.text
                        cached += cell.find("{*}v") is not None
    return formulas, cached


def typed(value):
    if type(value) is bool: return {"type": "boolean", "value": value}
    if type(value) is str: return {"type": "string", "value": value}
    return {"type": "number", "value": format(Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP), "f")}


def test_complete_field_census_unique_cells_and_oracle_seeded_typed_values(built):
    _, p, definition, lookup = built
    assert len(lookup) == len({(b["sheet"], b["cell"]) for b in lookup.values()}) == 2052
    assert set(lookup) == set(oracle_a.solve(spec.default_spec())["exact_values"])
    expected = load(p["independent_expected"])
    goal = openpyxl.load_workbook(p["goal"]["path"], data_only=True)
    assert len(goal.sheetnames) == 9
    for b in definition["bindings"]:
        assert typed(goal[b["sheet"]][b["cell"]].value) == expected[b["sheet"] + "!" + b["cell"]] == b["expected_typed"]
    goal.close()
    assert p["independent_oracle_values_crosschecked"] == 2052
    assert load(p["independent_crosscheck"])["passed"] is True


def test_eligibility_uses_logical_formula_and_general_format_without_numeric_coercion(built):
    _,p,_,lookup=built
    formulas=openpyxl.load_workbook(p['goal']['path'],data_only=False)
    values=openpyxl.load_workbook(p['goal']['path'],data_only=True)
    eligibility=[b for b in lookup.values() if b['metric']=='distribution_eligible']
    assert len(eligibility)==12
    for b in eligibility:
        cell=formulas[b['sheet']][b['cell']]
        assert cell.number_format=='General'
        assert cell.value.startswith('=AND('+b['period'][2:]+'=2027')
        assert type(values[b['sheet']][b['cell']].value) is bool
        assert b['expected_typed']['type']=='boolean'
    assert typed(0)!=typed(False) and typed(1)!=typed(True)
    formulas.close();values.close()


def test_natural_layouts_and_correct_zero_historical_template(built):
    _, p, _, lookup = built; cells = grid(p["goal"]["path"])
    for entity in ("ALDER", "CEDAR"):
        a,b=(lookup[f"{entity}/2025Q{q}/net_income"] for q in (1,2))
        assert coordinate_from_string(a["cell"])[1] == coordinate_from_string(b["cell"])[1]
        assert coordinate_from_string(a["cell"])[0] != coordinate_from_string(b["cell"])[0]
        old = lookup[f"{entity}/2025Q1/reported_associate_line"]
        new = lookup[f"{entity}/2026Q1/reported_associate_line"]
        old_label=(old["sheet"],"A"+str(coordinate_from_string(old["cell"])[1]))
        assert "expense basis" in cells[old_label]
        assert "profit / (loss)" in cells[new["sheet"],"A"+str(coordinate_from_string(new["cell"])[1])]
        old_ref=excel._qualified(old["sheet"],old["cell"])
        assert cells[a["sheet"],a["cell"]].endswith("-"+old_ref)
        ni=lookup[f"{entity}/2026Q1/net_income"]
        assert cells[ni["sheet"],ni["cell"]].endswith("+"+excel._qualified(new["sheet"],new["cell"]))
    for entity in ("BEACON", "DELTA"):
        a,b=(lookup[f"{entity}/2025Q{q}/net_income"] for q in (1,2))
        assert coordinate_from_string(a["cell"])[0] == coordinate_from_string(b["cell"])[0]
        assert coordinate_from_string(a["cell"])[1] != coordinate_from_string(b["cell"])[1]
        assert cells[a["sheet"],a["cell"]].startswith("=SUM(")


def test_full_forecast_fm_mask_preserves_history_formulas_and_all_facts(built):
    _, p, definition, lookup=built
    goal=grid(p["goal"]["path"]); fm=grid(p["views"]["financial_modeling"]["input"]["path"])
    mask={(x["sheet"],x["cell"]) for x in definition["FM_mask_points"]}
    assert len(mask)==p["FM_mask_count"]==1368
    assert {point for point in goal if goal.get(point)!=fm.get(point)}==mask
    for b in lookup.values():
        if "2025" in b["period"]: assert fm[b["sheet"],b["cell"]]==goal[b["sheet"],b["cell"]]
    assert formula_cells_and_cached_count(p["views"]["financial_modeling"]["input"]["path"])[1]==0
    for fact in definition["provided_facts"]:
        point=fact["sheet"],fact["cell"]
        assert goal[point]==fm[point]


def test_dbg_changes_only_four_declared_formulas_and_retains_every_literal(built):
    _,p,definition,_=built
    goal=grid(p["goal"]["path"]); dbg=grid(p["views"]["debugging"]["input"]["path"])
    changes={point for point in goal if goal.get(point)!=dbg.get(point)}
    assert changes=={(r["sheet"],r["cell"]) for r in definition["DBG_root_edits"]}
    assert len(changes)==p["DBG_root_count"]==4
    assert {r["mechanism"] for r in definition["DBG_root_edits"]}=={"associate_sign","growth_ratio_without_minus_one","money_unit","wrong_comparison_quarter"}
    for root in definition["DBG_root_edits"]:
        point=root["sheet"],root["cell"]
        assert goal[point]==root["before"] and dbg[point]==root["after"]
        assert root["before"].startswith("=") and root["after"].startswith("=")
    assert formula_cells_and_cached_count(p["views"]["debugging"]["input"]["path"])[1]==0


def test_yoy_regression_reaches_real_distribution_cash_and_equity(built):
    _,p,definition,lookup=built; cells=grid(p["goal"]["path"])
    q=lambda key:excel._qualified(lookup[key]["sheet"],lookup[key]["cell"])
    formula=lambda key:cells[lookup[key]["sheet"],lookup[key]["cell"]]
    root=next(r for r in definition["DBG_root_edits"] if r["mechanism"]=="growth_ratio_without_minus_one")
    assert root["key"]=="DELTA/2027Q4/yoy_percent" and "-1)" in root["before"] and "-1" not in root["after"]
    assert q(root["key"]) in formula("DELTA/FY2027/distribution_eligible")
    assert q("DELTA/FY2027/distribution_eligible") in formula("DELTA/2027Q4/dividend")
    for field in ("closing_cash","closing_retained_earnings"):
        assert q("DELTA/2027Q4/dividend") in formula("DELTA/2027Q4/"+field)
        assert q("DELTA/2027Q4/"+field)+"*1000" in formula("PORTFOLIO/2027Q4/"+field)
    assert "*10000>=" in formula("ALDER/FY2027/distribution_eligible")
    assert "^(1/2)" in formula("ALDER/FY2027/cagr_percent")


def test_portfolio_profit_has_independent_bridge_for_local_sign_regression(built):
    _,p,_,lookup=built; cells=grid(p["goal"]["path"])
    q=lambda key:excel._qualified(lookup[key]["sheet"],lookup[key]["cell"])
    formula=lambda key:cells[lookup[key]["sheet"],lookup[key]["cell"]]
    assert formula("PORTFOLIO/2026Q1/net_income")=="="+q("PORTFOLIO/2026Q1/core_net_income")+"+"+q("PORTFOLIO/2026Q1/associate_income")
    assert q("ALDER/2026Q1/core_net_income")+"*1000" in formula("PORTFOLIO/2026Q1/core_net_income")
    assert q("ALDER/2026Q1/associate_income")+"*1000" in formula("PORTFOLIO/2026Q1/associate_income")
    assert q("ALDER/2026Q1/net_income") not in formula("PORTFOLIO/2026Q1/net_income")


def test_all_source_formula_caches_cleared_before_first_native_input(built):
    _,p,_,_=built
    original,cached=formula_cells_and_cached_count(p["goal"]["path"])
    cold,remaining=formula_cells_and_cached_count(p["cold_source_input"]["path"])
    assert original==cold and len(cold)==p["formula_count"]==1967
    assert cached==1967 and remaining==0
    assert grid(p["goal"]["path"])==grid(p["cold_source_input"]["path"])
    proof=load(p["cold_source_cache_clearance"])
    assert proof["all_formula_caches_removed"] and proof["formula_count"]==1967
    assert p["oracle_seeded_goal_is_not_native_validation"] is True
    assert p["first_source_native_input_requires_all_formula_caches_cleared"] is True
    assert p["actual_LO_calls"]==p["model_calls"]==p["optimizer_calls"]==0
    assert p["engineering_or_difficulty_certified"] is p["qualified"] is False


def test_public_labels_use_business_language_and_short_objective(built):
    _,p,_,_=built; cells=grid(p["goal"]["path"])
    text="\n".join(v for (sheet,_),v in cells.items() if sheet in ("Read Me","Opening and terms") and type(v) is str)
    assert "Positive expense deductions" in text and "Signed account credits and debits" in text
    assert "GBP thousands" in text and "Sequential revenue multiple" in text
    assert not any(label in text for label in ("expense_columns","signed_rows","yoy_percent","qoq_multiple","GBP_thousands"))
    assert "already held" in text and "No acquisition" in text
    for view in p["views"].values():
        instruction=Path(view["instruction"]["path"]).read_text()
        assert len(instruction.split())<80
        assert "Read Me" in instruction and "synthetic" in instruction
        assert not any(hint in instruction for hint in ("minus one","associate sign","CAGR formula","root address"))


def test_provided_literals_match_explicit_typed_fact_manifest(built):
    _,p,definition,_=built;cells=grid(p["goal"]["path"])
    for fact in definition["provided_facts"]:
        value=cells[fact["sheet"],fact["cell"]]; expected=fact["expected_literal"]
        if expected["type"]=="number": assert Decimal(str(value))==Decimal(expected["value"])
        else: assert value==expected["value"]


def test_cold_copy_is_fresh_only_and_source_has_no_external_workbook_links(built,tmp_path):
    _,p,_,_=built
    destination=tmp_path/"cold.xlsx"
    proof=excel.clear_formula_caches(p["goal"]["path"],destination)
    assert proof["formula_count"]==1967
    with pytest.raises(FileExistsError): excel.clear_formula_caches(p["goal"]["path"],destination)
    with ZipFile(p["goal"]["path"]) as archive:
        assert not any("externalLinks" in name for name in archive.namelist())


def test_existing_output_and_mismatched_oracle_binding_rejected(built,tmp_path):
    folder,_,_,_=built
    with pytest.raises(FileExistsError): excel.build_views(folder)
    public=spec.default_spec(); result=oracle_a.solve(public)
    result["specification_sha256"]="0"*64
    with pytest.raises(ValueError):excel.emit_workbook(tmp_path/"bad.xlsx",public,result)
    assert not (tmp_path/"bad.xlsx").exists()
