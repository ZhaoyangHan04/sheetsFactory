"""Independent rational business oracle; no workbook or Decimal-A calculations.

Every financial state is an unrounded Fraction. The two-year CAGR stays
symbolic; its displayed rounding and distribution gate use exact integer tests.
"""
from fractions import Fraction
from math import isqrt

from .spec import NA, canonical_sha256, validate_spec


FLOW_FIELDS = ("revenue", "direct_cost", "operating_expense", "operating_profit",
    "interest", "pretax_before_associate", "current_tax", "core_net_income",
    "associate_income", "net_income", "dividend", "operating_cash_flow")
STOCK_FIELDS = ("closing_cash", "closing_investment", "closing_retained_earnings",
    "debt", "contributed_capital", "total_assets", "total_liabilities_equity")


def _number(value):
    if type(value) not in (str, int, Fraction):
        raise ValueError("Exact decimal strings, integers or Fractions are required")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("Invalid rational value") from error


def display(value):
    """Two decimal places, exact half away from zero, including negative zero."""
    value = _number(value)
    magnitude = abs(value) * 100
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    cents = whole + (2 * remainder >= magnitude.denominator)
    return ("-" if value < 0 else "") + f"{cents // 100}.{cents % 100:02d}"


def cagr_display(ratio):
    """Round 100*(sqrt(ratio)-1) with an exact half-cent comparison.

    The integer square root certifies floor(10000*sqrt(ratio)). Comparing
    squares at its halfway point determines rounding without an approximation.
    """
    ratio = _number(ratio)
    if ratio <= 0:
        raise ValueError("CAGR endpoints must be positive")
    numerator, denominator = ratio.numerator, ratio.denominator
    scaled_floor = isqrt(numerator * 100_000_000 // denominator)
    assert scaled_floor ** 2 * denominator <= numerator * 100_000_000
    assert (scaled_floor + 1) ** 2 * denominator > numerator * 100_000_000
    comparison = 4 * numerator * 100_000_000 - denominator * (2 * scaled_floor + 1) ** 2
    # At an exact negative halfway point, rounding selects the lower integer.
    increment = comparison >= 0 if ratio >= 1 else comparison > 0
    cents = scaled_floor - 10000 + int(increment)
    absolute = abs(cents)
    text = ("-" if ratio < 1 else "") + f"{absolute // 100}.{absolute % 100:02d}"
    return text, {
        "method": "exact_integer_square_root_and_halfway_square_comparison",
        "endpoint_ratio": str(ratio), "root_lower": str(Fraction(scaled_floor,10000)),
        "root_upper_exclusive": str(Fraction(scaled_floor+1,10000)),
        "scaled_root_floor": scaled_floor,
        "halfway_comparison_sign": (comparison > 0) - (comparison < 0),
        "negative_halfway_uses_away_from_zero": True,
        "display": text,
    }


def _quarter_metrics(revenues, incomes, index):
    revenue = revenues[index]
    prior_year = revenues[index-4] if index >= 4 else None
    previous = revenues[index-1] if index else None
    return {
        "net_margin_percent": 100 * incomes[index] / revenue,
        "yoy_percent": 100 * (revenue / prior_year - 1) if prior_year is not None else NA,
        "qoq_percent": 100 * (revenue / previous - 1) if previous is not None else NA,
        "prior_year_multiple": revenue / prior_year if prior_year is not None else NA,
        "prior_year_index": 100 * revenue / prior_year if prior_year is not None else NA,
    }


def _annual_metrics(revenues, incomes, index):
    revenue = revenues[index]
    prior = revenues[index-1] if index else None
    cagr = NA if index == 0 else (100 * (revenue/revenues[0]-1) if index == 1
        else ("cagr_percent", revenue/revenues[0], 2))
    return {
        "net_margin_percent": 100 * incomes[index] / revenue,
        "yoy_percent": 100 * (revenue/prior-1) if prior is not None else NA,
        "prior_year_multiple": revenue/prior if prior is not None else NA,
        "prior_year_index": 100 * revenue/prior if prior is not None else NA,
        "cagr_percent": cagr,
    }


def _entity_quarters(entity, distribution):
    revenues = list(map(_number, entity["actual_revenue"]))
    for index, assumption in enumerate(map(_number, entity["forecast_sales_assumptions"]),4):
        revenue = (revenues[index-4] * (1+assumption/100) if entity["sales_basis"] == "yoy_percent"
            else revenues[index-1] * assumption)
        if revenue <= 0:
            raise ValueError("Revenue comparison bases must remain positive")
        revenues.append(revenue)
    opening = {key:_number(value) for key,value in entity["opening"].items()}
    interest = opening["debt"] * _number(entity["annual_interest_percent"]) / 400
    cost_fraction = _number(entity["direct_cost_percent"]) / 100
    tax_fraction = _number(entity["tax_percent"]) / 100
    quarters = []
    for index,revenue in enumerate(revenues):
        costs = revenue * cost_fraction
        expense = _number(entity["quarterly_fixed_opex"][index])
        operating = revenue-costs-expense
        pretax = operating-interest
        tax = max(pretax,Fraction(0))*tax_fraction
        associate = _number(entity["associate_results"][index])
        core = pretax-tax
        quarters.append({"revenue":revenue,"direct_cost":costs,"operating_expense":expense,
            "operating_profit":operating,"interest":interest,"pretax_before_associate":pretax,
            "current_tax":tax,"core_net_income":core,"associate_income":associate,
            "net_income":core+associate,"dividend":Fraction(0),"operating_cash_flow":core})
    annual_revenue = [sum(revenues[i:i+4],Fraction(0)) for i in (0,4,8)]
    annual_income = sum((q["net_income"] for q in quarters[8:12]),Fraction(0))
    cagr_threshold = 1+_number(distribution["cagr_percent"])/100
    q4_threshold = 1+_number(distribution["q4_yoy_percent"])/100
    eligible = (annual_income > 0 and annual_revenue[2] >= annual_revenue[0]*cagr_threshold**2
        and revenues[11] >= revenues[7]*q4_threshold)
    if eligible:
        quarters[11]["dividend"] = annual_income*_number(distribution["profit_percent"])/100
    cash,investment,retained = opening["cash"],opening["investment"],opening["retained_earnings"]
    expense_sign = -1 if entity["layout"] == "signed_rows" else 1
    for index,row in enumerate(quarters):
        cash += row["operating_cash_flow"]-row["dividend"]
        investment += row["associate_income"]
        retained += row["net_income"]-row["dividend"]
        if cash < 0 or investment < 0:
            raise ValueError(f"Negative closing cash or investment: {entity['id']} quarter {index+1}")
        assets = cash+investment
        liabilities_equity = opening["debt"]+opening["capital"]+retained
        if assets != liabilities_equity:
            raise ValueError("The independent financial balance bridge does not reconcile")
        row.update(closing_cash=cash,closing_investment=investment,closing_retained_earnings=retained,
            debt=opening["debt"],contributed_capital=opening["capital"],total_assets=assets,
            total_liabilities_equity=liabilities_equity)
        for expense in ("direct_cost","operating_expense","interest","current_tax"):
            row["reported_"+expense] = expense_sign*row[expense]
        row["reported_associate_line"] = (-row["associate_income"] if index < 4
            and entity["layout"] == "expense_columns" else row["associate_income"])
    return quarters,eligible


def solve(public):
    """Compute every quarterly/annual entity and management-portfolio value."""
    public = validate_spec(public)
    exact,shown,proofs = {},{},{}
    def emit(prefix,row):
        for field,value in row.items():
            key = prefix+"/"+field
            if key in exact:
                raise ValueError("Duplicate financial output key")
            exact[key] = value
            if type(value) is bool:
                shown[key] = {"type":"boolean","value":value}
            elif type(value) is str:
                if value != NA:
                    raise ValueError("Unknown unavailable-comparison marker")
                shown[key] = {"type":"string","value":value}
            elif type(value) is tuple:
                if value[0] != "cagr_percent" or value[2] != 2:
                    raise ValueError("Unknown symbolic financial value")
                text,proof = cagr_display(value[1]);proofs[key] = proof
                shown[key] = {"type":"number","value":text}
            else:
                if type(value) is not Fraction:
                    raise ValueError("Financial state must remain an exact Fraction")
                shown[key] = {"type":"number","value":display(value)}
    all_entities=[]
    for entity in public["entities"]:
        quarters,eligible = _entity_quarters(entity,public["distribution"])
        factor = Fraction(1000 if entity["money_unit"] == "GBP_thousands" else 1)
        all_entities.append((quarters,factor))
        _emit_periods(entity["id"],quarters,eligible,emit)
    combined = [{field:sum((rows[index][field]*factor for rows,factor in all_entities),Fraction(0))
        for field in FLOW_FIELDS+STOCK_FIELDS} for index in range(12)]
    _emit_periods("PORTFOLIO",combined,None,emit)
    return {"kind":"operating_metrics_regime_oracle_values","version":1,"implementation":"B",
        "specification_sha256":canonical_sha256(public),
        "exact_values":exact,"display_values":shown,"cagr_proofs":proofs}


def _emit_periods(identity,quarters,eligible,emit):
    revenues = [q["revenue"] for q in quarters]
    incomes = [q["net_income"] for q in quarters]
    for index,row in enumerate(quarters):
        period = str(2025+index//4)+"Q"+str(1+index%4)
        emit(identity+"/"+period,{**row,**_quarter_metrics(revenues,incomes,index)})
    annual = []
    for index in range(3):
        group = quarters[index*4:index*4+4]
        annual.append({**{field:sum((q[field] for q in group),Fraction(0)) for field in FLOW_FIELDS},
            **{field:group[-1][field] for field in STOCK_FIELDS}})
    annual_revenue = [r["revenue"] for r in annual]
    annual_income = [r["net_income"] for r in annual]
    for index,row in enumerate(annual):
        extra = {} if eligible is None else {"distribution_eligible":eligible if index==2 else False}
        emit(identity+"/FY"+str(2025+index),{**row,**_annual_metrics(annual_revenue,annual_income,index),**extra})
