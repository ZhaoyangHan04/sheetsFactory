"""Independent Decimal journal for the disclosed heterogeneous contracts.

Only raw schema primitives are consumed. No Excel emitter, prior model, answer,
optimizer, or arithmetic helper from another financial model is imported.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext

from .spec import (ASSET_FIELDS, ENTITY_FIELDS, GROUP_FIELDS, GROUP_SUM_FIELDS,
                   LOAN_FIELDS, MAX_INTEGER, MONEY_FIELDS, SCALE,
                   canonical_sha256, load_spec, month_index)


def _r(numerator: int, denominator: int = 1) -> int:
    with localcontext() as c:
        c.prec = 80
        value = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    result = int(value)
    if abs(result) >= MAX_INTEGER:
        raise OverflowError("computed financial/display integer exceeds the exact worksheet contract")
    return result


def _bounded(values):
    for value in values:
        if type(value) is int and abs(value) >= MAX_INTEGER:
            raise OverflowError("computed account exceeds the exact worksheet contract")


def _queue(opening, offset, window, capacity, creation):
    """Return an independently posted FIFO queue and an origin-level bridge."""
    eligible = {}
    entries = {}
    for origin, amount in sorted(opening.items()):
        entry = {"origin_month": origin, "opening": amount, "expired": 0, "used": 0, "created": 0, "closing": 0}
        if offset - month_index(origin) > window:
            entry["expired"] = amount
        else:
            eligible[origin] = amount
        entries[origin] = entry
    remaining = capacity
    for origin, amount in sorted(eligible.items()):
        used = min(amount, remaining)
        remaining -= used
        eligible[origin] -= used
        entries[origin]["used"] = used
        entries[origin]["closing"] = amount - used
    if creation:
        # The caller supplies a month string for creation separately.
        raise ValueError("current queue creation must be posted after old-vintage use")
    out = {origin: amount for origin, amount in eligible.items() if amount}
    return out, entries, remaining


def _queue_close(opening, entries, current_month, creation):
    out = {o: e["closing"] for o, e in entries.items() if e["closing"]}
    if creation:
        if current_month in entries:
            raise ArithmeticError("current vintage was available before its creation")
        entries[current_month] = {"origin_month": current_month, "opening": 0, "expired": 0, "used": 0, "created": creation, "closing": creation}
        out[current_month] = creation
    totals = {k: sum(e[k] for e in entries.values()) for k in ("opening", "expired", "used", "created", "closing")}
    if totals["opening"] != sum(opening.values()) or totals["closing"] != totals["opening"] - totals["expired"] - totals["used"] + totals["created"]:
        raise ArithmeticError("FIFO origin bridge failed")
    return out, {"month": current_month, **totals, "entries": list(entries.values())}


def _scenario(spec, scenario):
    entities = {e["id"]: e for e in spec["entities"]}
    loans = {l["entity_id"]: l for l in spec["loans"]}
    asset_specs = {a["id"]: a for a in spec["assets"]}
    months = spec["months"]
    outputs = {e: {"monthly": []} for e in entities}
    loan_outputs = {l["id"]: {"monthly": []} for l in loans.values()}
    asset_outputs = {a: {"monthly": []} for a in asset_specs}
    interest_outputs = {e: {"monthly": []} for e in entities}
    loss_outputs = {e: {"monthly": []} for e in entities}
    groups, journals, checks = [], [], []
    activation = defaultdict(list)
    asset_state = {}
    states, accounts = {}, {}
    for aid, a in asset_specs.items():
        exists = a["commission_month"] < months[0]
        asset_state[aid] = {"cost": a["original_cost_pence"] if exists else 0,
                            "accum": a["opening_accumulated_depreciation_pence"] if exists else 0}
    for eid, e in entities.items():
        l = loans[eid]
        states[eid] = {"cash": e["opening_cash_pence"], "reserve": e["opening_restricted_cash_pence"],
                       "principal": l["opening_principal_pence"], "interest": l["opening_accrued_interest_pence"],
                       "tax": e["opening_tax_payable_pence"], "capital": e["opening_paid_in_capital_pence"],
                       "retained": e["opening_retained_earnings_pence"], "called": 0,
                       "trap": e["opening_trap"], "cure": e["opening_cure_count"], "closed": False,
                       "instalment": 0, "term": None,
                       "iq": {v["origin_month"]: v["amount_pence"] for v in e["opening_interest_carry"]},
                       "tq": {v["origin_month"]: v["amount_pence"] for v in e["opening_tax_losses"]}}
        cost = sum(v["cost"] for aid, v in asset_state.items() if asset_specs[aid]["entity_id"] == eid)
        accum = sum(v["accum"] for aid, v in asset_state.items() if asset_specs[aid]["entity_id"] == eid)
        # Debit-positive trial balances. Explicit opening capital is verified,
        # never inferred as a residual to repair an inconsistent opening.
        accounts[eid] = {"Cash": states[eid]["cash"], "Restricted cash": states[eid]["reserve"],
                         "Asset cost": cost, "Accumulated depreciation": -accum,
                         "Bank": -states[eid]["principal"], "Accrued interest": -states[eid]["interest"],
                         "Income tax payable": -states[eid]["tax"], "Paid-in capital": -states[eid]["capital"],
                         "Retained earnings": -states[eid]["retained"]}
        if sum(accounts[eid].values()):
            raise ArithmeticError(f"unbalanced explicit opening trial balance: {eid}")

    def witness(name, month, entity=None, **amounts):
        activation[name].append({"month": month, **({"entity_id": entity} if entity else {}), **amounts})

    def post(eid, month, debit, credit, amount, description):
        if type(amount) is not int or amount < 0:
            raise ArithmeticError("journal entry is not a nonnegative integer posting")
        if not amount:
            return
        accounts[eid][debit] = accounts[eid].get(debit, 0) + amount
        accounts[eid][credit] = accounts[eid].get(credit, 0) - amount
        journals.append({"month": month, "entity_id": eid, "debit": debit, "credit": credit,
                         "amount_pence": amount, "description": description})

    for mi, month in enumerate(months):
        factors = scenario["monthly_schedule"][mi]
        offset = month_index(month)
        year, mon = map(int, month[:7].split("-"))
        days = calendar.monthrange(year, mon)[1]
        month_end = f"{year:04d}-{mon:02d}-{days:02d}"
        limit = max((v for v in spec["group"]["shared_bank_limit_schedule"] if v["effective_month"] <= month), key=lambda v: v["effective_month"])["limit_pence"]
        rows, lr, selected = {}, {}, {}
        cash, debt, reserve = {}, {}, {}
        capex_by_entity = defaultdict(lambda: {"MAINTENANCE": 0, "GROWTH": 0})
        depreciation_by_entity = defaultdict(int)
        nbv_open_by_entity, nbv_close_by_entity = defaultdict(int), defaultdict(int)
        for aid, a in asset_specs.items():
            st = asset_state[aid]
            capex = a["original_cost_pence"] if a["commission_month"] == month else 0
            nbv_open = st["cost"] - st["accum"]
            age = offset - month_index(a["commission_month"])
            depreciation = 0
            if age > 0 and nbv_open > 0:
                depreciation = nbv_open if age >= a["useful_life_months"] else min(nbv_open, _r(a["original_cost_pence"], a["useful_life_months"]))
            ar = {"month": month, "cost_open": st["cost"], "accumulated_depreciation_open": st["accum"],
                  "nbv_open": nbv_open, "capex": capex, "depreciation": depreciation,
                  "cost_close": st["cost"] + capex, "accumulated_depreciation_close": st["accum"] + depreciation,
                  "nbv_close": nbv_open + capex - depreciation}
            if set(ar) != set(ASSET_FIELDS):
                raise ArithmeticError("asset interface incomplete")
            asset_outputs[aid]["monthly"].append(ar)
            asset_state[aid] = {"cost": ar["cost_close"], "accum": ar["accumulated_depreciation_close"]}
            eid = a["entity_id"]
            capex_by_entity[eid][a["capex_category"]] += capex
            depreciation_by_entity[eid] += depreciation
            nbv_open_by_entity[eid] += nbv_open
            nbv_close_by_entity[eid] += ar["nbv_close"]
        # Local cash obligations and opening-principal interest are independent
        # of the later group financing allocation.
        for eid, e in entities.items():
            st, loan = states[eid], loans[eid]
            term = max((t for t in loan["terms"] if t["effective_month"] <= month), key=lambda t: t["effective_month"])
            selected[eid] = term
            maturity = not st["closed"] and month_end >= term["maturity_date"]
            active = not st["closed"]
            basis = 365 if term["day_count"] == "ACT_365F" else 360
            rate = term["annual_rate_p12"] + factors["annual_rate_spread_p12"]
            interest = _r(st["principal"] * rate * days, SCALE * basis) if active else 0
            is_quarter = loan["type"] == "BULLET_QUARTERLY_ACCRUAL"
            regular_coupon = active and (not is_quarter or (month >= term["next_coupon_month"] and (offset - month_index(term["next_coupon_month"])) % 3 == 0))
            coupon_due = regular_coupon or maturity
            coupon = st["interest"] + interest if coupon_due else 0
            recast = active and loan["type"] == "LEVEL_PRINCIPAL_MONTHLY" and st["term"] != term["id"]
            instalment = st["instalment"]
            if recast:
                last = month_index(term["maturity_date"][:7] + "-01")
                instalment = _r(st["principal"], last - offset + 1)
            if not active:
                instalment = 0
            scheduled = st["principal"] if maturity else min(st["principal"], instalment) if loan["type"] == "LEVEL_PRINCIPAL_MONTHLY" and active else 0
            local_margin = max(0, st["principal"] - scheduled - term["local_limit_pence"]) if active else 0
            revenue = _r(spec["operating_inputs"][eid][mi]["base_cash_revenue_pence"] * factors["revenue_factor_p12"], SCALE)
            opex = _r(spec["operating_inputs"][eid][mi]["base_cash_opex_pence"] * factors["opex_factor_p12"], SCALE)
            cap = capex_by_entity[eid]
            r = {k: 0 for k in MONEY_FIELDS}
            r.update(month=month, term_id=term["id"], tax_policy=e["tax_policy"], dscr_policy=e["dscr_policy"],
                     revenue=revenue, cash_opex=opex, ebitda=revenue-opex, capex_maintenance=cap["MAINTENANCE"],
                     capex_growth=cap["GROWTH"], depreciation=depreciation_by_entity[eid],
                     ebit=revenue-opex-depreciation_by_entity[eid], interest_accrual=interest, cash_coupon=coupon,
                     cash_open=st["cash"], reserve_open=st["reserve"], asset_nbv_open=nbv_open_by_entity[eid],
                     asset_nbv_close=nbv_close_by_entity[eid], principal_open=st["principal"],
                     scheduled_principal=scheduled, local_margin_principal=local_margin,
                     interest_payable_open=st["interest"], interest_payable_close=st["interest"]+interest-coupon,
                     tax_payable_open=st["tax"], paid_in_open=st["capital"], retained_open=st["retained"],
                     trap_open=int(st["trap"]), cure_open=st["cure"], facility_closed_open=int(st["closed"]))
            reserve[eid] = st["reserve"]
            early_release = st["reserve"] if st["closed"] or maturity else 0
            r["reserve_released"] = early_release
            reserve[eid] -= early_release
            cash[eid] = st["cash"] + revenue - opex - cap["MAINTENANCE"] - cap["GROWTH"] - coupon - scheduled - local_margin + early_release
            debt[eid] = st["principal"] - scheduled - local_margin
            rows[eid] = r
            lr[eid] = {"month": month, "term_id": term["id"], "principal_open": st["principal"],
                       "annual_rate_p12": rate, "day_basis": basis, "days": days, "interest_accrual": interest,
                       "interest_payable_open": st["interest"], "coupon_due": int(coupon_due), "cash_coupon": coupon,
                       "recast_due": int(recast), "recast_instalment": instalment,
                       "scheduled_principal": scheduled, "local_margin_principal": local_margin,
                       "shared_margin_principal": 0, "voluntary_principal": 0, "bank_draw": 0,
                       "principal_close": 0, "interest_payable_close": r["interest_payable_close"],
                       "facility_closed_open": int(st["closed"]), "facility_closed_next": 0}
            if interest:
                witness("loan_"+loan["type"], month, eid, interest_pence=interest)
            if is_quarter and interest and not coupon:
                witness("quarterly_unpaid_accrual", month, eid, amount_pence=interest)
            if is_quarter and coupon:
                witness("quarterly_cash_coupon", month, eid, amount_pence=coupon)
            if is_quarter and st["term"] is not None and st["term"] != term["id"] and st["interest"]:
                witness("coupon_reset_preserves_accrual", month, eid, opening_accrued_pence=st["interest"])
            if is_quarter and maturity and not regular_coupon and coupon:
                witness("off_cycle_maturity_stub", month, eid, cash_coupon_pence=coupon)
            if recast and mi:
                witness("amendment_principal_recast", month, eid, instalment_pence=instalment)
            if mon == 2 and days == 29 and interest:
                witness("leap_day_"+term["day_count"], month, eid, interest_pence=interest)

        excess = max(0, sum(debt.values()) - limit)
        for eid in spec["group"]["shared_margin_priority"]:
            payment = min(debt[eid], excess)
            excess -= payment
            debt[eid] -= payment
            cash[eid] -= payment
            rows[eid]["shared_margin_principal"] = payment
            lr[eid]["shared_margin_principal"] = payment
            if payment:
                witness("shared_bank_margin", month, eid, amount_pence=payment)

        next_iq, next_tq = {}, {}
        for eid, e in entities.items():
            st, r, term = states[eid], rows[eid], selected[eid]
            active = not st["closed"]
            maturity = active and month_end >= term["maturity_date"]
            eligible = r["interest_accrual"] if e["tax_policy"] == "ACCRUAL_MONTHLY" else r["cash_coupon"]
            capacity = _r(max(0, r["ebitda"]) * e["interest_cap_fraction_p12"], SCALE)
            _, ie, unused = _queue(st["iq"], offset, e["interest_carry_months"], capacity, 0)
            current_allowed = min(eligible, unused)
            denied = eligible - current_allowed
            iq, ib = _queue_close(st["iq"], ie, month, denied)
            before_losses = r["ebit"] - ib["used"] - current_allowed
            _, te, _ = _queue(st["tq"], offset, e["loss_carry_months"], max(0, before_losses), 0)
            tq, tb = _queue_close(st["tq"], te, month, max(0, -before_losses))
            after_losses = max(0, before_losses - tb["used"])
            tax = _r(after_losses * e["tax_rate_p12"], SCALE)
            tax_cash = st["tax"] + tax if e["tax_policy"] == "ACCRUAL_MONTHLY" or mon % 3 == 0 else 0
            cash[eid] -= tax_cash
            r.update(eligible_current_interest=eligible, interest_capacity=capacity,
                     interest_carry_open=ib["opening"], interest_expired=ib["expired"], interest_old_used=ib["used"],
                     interest_current_allowed=current_allowed, interest_denied_created=denied, interest_carry_close=ib["closing"],
                     taxable_before_losses=before_losses, loss_open=tb["opening"], loss_expired=tb["expired"],
                     loss_used=tb["used"], loss_created=tb["created"], loss_close=tb["closing"], taxable_after_losses=after_losses,
                     current_tax_expense=tax, cash_tax=tax_cash, tax_payable_close=st["tax"]+tax-tax_cash,
                     net_income=r["ebit"]-r["interest_accrual"]-tax,
                     cfads=r["revenue"]-r["cash_opex"]-tax_cash-r["capex_maintenance"],
                     mandatory_debt_service=r["cash_coupon"]+r["scheduled_principal"]+r["local_margin_principal"]+r["shared_margin_principal"])
            next_iq[eid], next_tq[eid] = iq, tq
            interest_outputs[eid]["monthly"].append(ib)
            loss_outputs[eid]["monthly"].append(tb)
            for name, val in (("interest_carry_creation",denied),("interest_carry_use",ib["used"]),("interest_carry_expiry",ib["expired"]),("tax_loss_creation",tb["created"]),("tax_loss_use",tb["used"]),("tax_loss_expiry",tb["expired"])):
                if val:
                    witness(name, month, eid, amount_pence=val)
            tested = active and (e["dscr_policy"] == "MONTHLY_CURRENT" or mon % 3 == 0)
            window = [r] if e["dscr_policy"] == "MONTHLY_CURRENT" else outputs[eid]["monthly"][-2:] + [r]
            wcf = sum(x["cfads"] for x in window)
            wds = sum(x["mandatory_debt_service"] for x in window)
            passed = int(wcf >= 0 if not wds else wcf * SCALE >= e["dscr_threshold_p12"] * wds) if tested else None
            ratio = _r(wcf * 10**6, wds) if tested and wds else None
            failed = tested and not passed
            trap = bool(st["trap"] or failed) if e["dscr_policy"] == "MONTHLY_CURRENT" else bool(st["trap"])
            if not active or maturity:
                trap, next_trap, cure = False, False, 0
            elif failed:
                next_trap, cure = True, 0
            elif tested and passed:
                cure = min(2, st["cure"]+1) if st["trap"] else 0
                next_trap = bool(st["trap"] and cure < 2)
            else:
                next_trap, cure = bool(st["trap"]), st["cure"]
            r.update(test_applicable=int(tested), test_pass=passed, dscr_ratio_millionths=ratio,
                     dscr_window_cfads=wcf, dscr_window_debt_service=wds,
                     trap_operative=int(trap), trap_next=int(next_trap), cure_next=cure)
            if failed and e["dscr_policy"] == "MONTHLY_CURRENT" and not st["trap"] and not maturity:
                witness("monthly_current_breach", month, eid, cfads_pence=wcf, debt_service_pence=wds)
            if failed and e["dscr_policy"] == "QUARTERLY_LAGGED" and not st["trap"] and not maturity:
                witness("quarterly_next_month_breach", month, eid, cfads_pence=wcf, debt_service_pence=wds)
            if active and not maturity and st["trap"] and tested and passed and not next_trap:
                witness("two_observed_pass_cure", month, eid, counter=cure)
            if active and not tested and st["cure"] and next_trap:
                witness("non_test_cure_carry", month, eid, counter=cure)
            if active and not maturity:
                if trap:
                    lock = min(max(0,cash[eid]-e["minimum_cash_pence"]), max(0,e["reserve_target_pence"]-reserve[eid]))
                    r["reserve_locked"] = lock
                    reserve[eid] += lock
                    cash[eid] -= lock
                else:
                    release = reserve[eid]
                    r["reserve_released"] += release
                    reserve[eid] = 0
                    cash[eid] += release
            fraction = SCALE if trap else term["optional_repayment_fraction_p12"]
            voluntary = min(debt[eid], _r(max(0,cash[eid]-e["minimum_cash_pence"])*fraction,SCALE))
            debt[eid] -= voluntary
            cash[eid] -= voluntary
            r["voluntary_principal"] = lr[eid]["voluntary_principal"] = voluntary
            r["cash_before_financing"] = cash[eid]
            if r["reserve_locked"]:
                witness("reserve_lock", month, eid, amount_pence=r["reserve_locked"])
            if r["reserve_released"]:
                witness("reserve_release", month, eid, amount_pence=r["reserve_released"])

        for eid in spec["group"]["bank_funding_priority"]:
            e, st, term, loan = entities[eid], states[eid], selected[eid], loans[eid]
            headroom = max(0, limit-sum(debt.values()))
            gap = max(0,e["minimum_cash_pence"]-cash[eid])
            available = (not st["closed"] and month_end < term["maturity_date"] and loan["type"] != "LEVEL_PRINCIPAL_MONTHLY" and month <= term["draw_cutoff_month"])
            amount = min(gap,max(0,term["local_limit_pence"]-debt[eid]),headroom) if available else 0
            debt[eid] += amount
            cash[eid] += amount
            rows[eid]["bank_draw"] = lr[eid]["bank_draw"] = amount
            if amount:
                witness("new_draw_no_current_interest", month, eid, draw_pence=amount, opening_principal_pence=st["principal"], interest_pence=rows[eid]["interest_accrual"])
            if available and gap and headroom < min(gap,max(0,term["local_limit_pence"]-(debt[eid]-amount))):
                witness("shared_bank_draw_competition", month, eid, headroom_pence=headroom, requested_pence=gap, draw_pence=amount)
        group_remaining = spec["group"]["additional_lp_commitment_pence"] - sum(st["called"] for st in states.values())
        for eid in spec["group"]["lp_funding_priority"]:
            e, st = entities[eid], states[eid]
            amount = min(max(0,e["minimum_cash_pence"]-cash[eid]),max(0,e["additional_lp_commitment_pence"]-st["called"]),max(0,group_remaining))
            cash[eid] += amount
            group_remaining -= amount
            rows[eid]["lp_call"] = amount
            if amount:
                witness("finite_lp_calls", month, eid, amount_pence=amount, entity_unused_after_pence=e["additional_lp_commitment_pence"]-st["called"]-amount, group_unused_after_pence=group_remaining)

        for eid, e in entities.items():
            st, r, loan = states[eid], rows[eid], loans[eid]
            equity = st["capital"] + st["retained"] + r["lp_call"] + r["net_income"]
            distribution = 0 if r["trap_operative"] else min(max(0,cash[eid]-e["minimum_cash_pence"]),max(0,equity))
            roc = min(distribution,st["capital"]+r["lp_call"])
            profit = distribution-roc
            cash[eid] -= distribution
            r.update(distribution=distribution, return_of_capital=roc, profit_distribution=profit,
                     cash_close=cash[eid], reserve_close=reserve[eid], principal_close=debt[eid],
                     lp_called_cumulative=st["called"]+r["lp_call"], paid_in_close=st["capital"]+r["lp_call"]-roc,
                     retained_close=st["retained"]+r["net_income"]-profit,
                     funding_gap=max(0,e["minimum_cash_pence"]-cash[eid]))
            closed = st["closed"] or month_end >= selected[eid]["maturity_date"] or (loan["type"] == "LEVEL_PRINCIPAL_MONTHLY" and not debt[eid] and not r["interest_payable_close"] and not r["funding_gap"])
            r["facility_closed_next"] = int(closed)
            if closed:
                r["trap_next"], r["cure_next"] = 0, 0
            r["feasible"] = not bool(r["funding_gap"])
            r["total_assets"] = r["cash_close"] + r["reserve_close"] + r["asset_nbv_close"]
            r["total_liabilities"] = r["principal_close"] + r["interest_payable_close"] + r["tax_payable_close"]
            r["total_equity"] = r["paid_in_close"] + r["retained_close"]
            r["cfo"] = r["revenue"]-r["cash_opex"]-r["cash_coupon"]-r["cash_tax"]
            r["cfi"] = -r["capex_maintenance"]-r["capex_growth"]
            mandatory = r["scheduled_principal"]+r["local_margin_principal"]+r["shared_margin_principal"]
            r["cff"] = r["bank_draw"]-mandatory-r["voluntary_principal"]+r["lp_call"]-distribution
            r["cash_delta"] = r["cash_close"]+r["reserve_close"]-r["cash_open"]-r["reserve_open"]
            r["cash_check"] = r["cash_delta"]-r["cfo"]-r["cfi"]-r["cff"]
            r["restricted_cash_check"] = r["reserve_close"]-r["reserve_open"]-r["reserve_locked"]+r["reserve_released"]
            r["principal_check"] = debt[eid]-st["principal"]+mandatory+r["voluntary_principal"]-r["bank_draw"]
            r["interest_payable_check"] = r["interest_payable_close"]-st["interest"]-r["interest_accrual"]+r["cash_coupon"]
            r["tax_payable_check"] = r["tax_payable_close"]-st["tax"]-r["current_tax_expense"]+r["cash_tax"]
            r["interest_queue_check"] = r["interest_carry_close"]-r["interest_carry_open"]+r["interest_expired"]+r["interest_old_used"]-r["interest_denied_created"]
            r["loss_queue_check"] = r["loss_close"]-r["loss_open"]+r["loss_expired"]+r["loss_used"]-r["loss_created"]
            r["capital_check"] = r["paid_in_close"]-st["capital"]-r["lp_call"]+roc
            r["retained_check"] = r["retained_close"]-st["retained"]-r["net_income"]+profit
            r["balance_sheet_check"] = r["total_assets"]-r["total_liabilities"]-r["total_equity"]
            if set(r) != set(ENTITY_FIELDS):
                raise ArithmeticError(f"entity interface mismatch: {set(r)^set(ENTITY_FIELDS)}")
            _bounded(r.values())
            if any(v for k,v in r.items() if k.endswith("_check")):
                raise ArithmeticError(f"financial account bridge failed {scenario['id']} {eid} {month}")
            # Record the finance receipts before cash obligations. These are
            # exactly the computed fixed-policy flows, not an injected plug.
            post(eid,month,"Cash","Bank",r["bank_draw"],"Shared bank drawing")
            post(eid,month,"Cash","Paid-in capital",r["lp_call"],"Limited LP contribution")
            post(eid,month,"Cash","Revenue",r["revenue"],"Operating revenue")
            post(eid,month,"Cash","Restricted cash",r["reserve_released"],"Reserve release")
            post(eid,month,"Operating expense","Cash",r["cash_opex"],"Operating cost")
            post(eid,month,"Asset cost","Cash",r["capex_maintenance"]+r["capex_growth"],"Commissioned capex")
            post(eid,month,"Depreciation expense","Accumulated depreciation",r["depreciation"],"Book depreciation")
            post(eid,month,"Interest expense","Accrued interest",r["interest_accrual"],"Opening-principal accrual")
            post(eid,month,"Accrued interest","Cash",r["cash_coupon"],"Coupon cash settlement")
            post(eid,month,"Bank","Cash",mandatory+r["voluntary_principal"],"Principal settlement")
            post(eid,month,"Tax expense","Income tax payable",r["current_tax_expense"],"Current tax assessment")
            post(eid,month,"Income tax payable","Cash",r["cash_tax"],"Tax cash settlement")
            post(eid,month,"Restricted cash","Cash",r["reserve_locked"],"Reserve lock")
            post(eid,month,"Paid-in capital","Cash",roc,"Return of capital")
            post(eid,month,"Retained earnings","Cash",profit,"Profit distribution")
            post(eid,month,"Revenue","Retained earnings",r["revenue"],"Close income")
            for account, amount in (("Operating expense",r["cash_opex"]),("Depreciation expense",r["depreciation"]),("Interest expense",r["interest_accrual"]),("Tax expense",r["current_tax_expense"])):
                post(eid,month,"Retained earnings",account,amount,"Close expense")
            expected_accounts = {"Cash":r["cash_close"],"Restricted cash":r["reserve_close"],
                                 "Asset cost":sum(v["cost"] for aid,v in asset_state.items() if asset_specs[aid]["entity_id"]==eid),
                                 "Accumulated depreciation":-sum(v["accum"] for aid,v in asset_state.items() if asset_specs[aid]["entity_id"]==eid),
                                 "Bank":-r["principal_close"],"Accrued interest":-r["interest_payable_close"],
                                 "Income tax payable":-r["tax_payable_close"],"Paid-in capital":-r["paid_in_close"],"Retained earnings":-r["retained_close"]}
            if any(accounts[eid].get(k,0) != v for k,v in expected_accounts.items()) or sum(accounts[eid].values()):
                raise ArithmeticError("independent journal does not match closing financial accounts")
            checks.append({"month":month,"entity_id":eid,"bridges_zero":True,"journal_balanced":True,"journal_matches_accounts":True})
            outputs[eid]["monthly"].append(r)
            lr[eid].update(principal_close=r["principal_close"],facility_closed_next=r["facility_closed_next"])
            if set(lr[eid]) != set(LOAN_FIELDS):
                raise ArithmeticError("loan interface mismatch")
            loan_outputs[loan["id"]]["monthly"].append(lr[eid])
            states[eid] = {"cash":r["cash_close"],"reserve":r["reserve_close"],"principal":r["principal_close"],
                           "interest":r["interest_payable_close"],"tax":r["tax_payable_close"],"capital":r["paid_in_close"],
                           "retained":r["retained_close"],"called":r["lp_called_cumulative"],"trap":bool(r["trap_next"]),
                           "cure":r["cure_next"],"closed":bool(closed),"instalment":lr[eid]["recast_instalment"],
                           "term":r["term_id"],"iq":next_iq[eid],"tq":next_tq[eid]}
        g = {k:sum(r[k] for r in rows.values()) for k in GROUP_SUM_FIELDS}
        g.update(month=month,shared_bank_limit=limit,bank_used=sum(debt.values()),bank_headroom=limit-sum(debt.values()),
                 lp_commitment=spec["group"]["additional_lp_commitment_pence"],lp_calls_cumulative=sum(st["called"] for st in states.values()),
                 lp_unused=group_remaining,feasible=all(r["feasible"] for r in rows.values()))
        g["group_cash_check"] = g["cash_delta"]-g["cfo"]-g["cfi"]-g["cff"]
        g["group_bank_check"] = g["principal_close"]-g["principal_open"]-g["bank_draw"]+g["scheduled_principal"]+g["local_margin_principal"]+g["shared_margin_principal"]+g["voluntary_principal"]
        g["group_equity_check"] = g["total_equity"]-g["paid_in_open"]-g["retained_open"]-g["lp_call"]-g["net_income"]+g["distribution"]
        g["group_balance_sheet_check"] = g["total_assets"]-g["total_liabilities"]-g["total_equity"]
        if set(g) != set(GROUP_FIELDS) or any(v for k,v in g.items() if k.startswith("group_") and k.endswith("_check")) or g["bank_headroom"] < 0:
            raise ArithmeticError("group funding or accounting conservation failed")
        _bounded(g.values())
        groups.append(g)
    return {"feasible":all(g["feasible"] for g in groups),"entities":outputs,"loans":loan_outputs,"assets":asset_outputs,
            "interest_vintages":interest_outputs,"loss_vintages":loss_outputs,"group_monthly":groups,
            "journal_entries":journals,"checks":checks,"mechanism_activation":dict(activation)}


def simulate(specification: dict) -> dict:
    spec = load_spec(specification)
    scenarios = {z["id"]:_scenario(spec,z) for z in spec["scenarios"]}
    return {"schema_version":1,"specification_sha256":canonical_sha256(spec),
            "feasible":all(z["feasible"] for z in scenarios.values()),"scenarios":scenarios,
            "checks":{"all_journals_and_financial_bridges_verified":True,
                      "all_scenarios_independently_reset":True,"no_balancing_plug":True},
            "mechanism_activation":{s:z["mechanism_activation"] for s,z in scenarios.items()}}
