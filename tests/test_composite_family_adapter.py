from copy import copy
from decimal import Decimal
from pathlib import Path
import json

import openpyxl
import pytest

from sheets_factory.task_adapters.composite_family import (
    FAMILIES, validate_policy, mutate_composite_cell, discover_composite_families,
)
from sheets_factory.task_adapters.composite_presentation_source import audited_zero_coverage


def test_all_six_algorithms_and_complete_declared_families_are_mandatory():
    assert len(FAMILIES) == 9
    assert len({name.split('.')[0] for name in FAMILIES}) == 6
    validate_policy({'families': list(FAMILIES), 'max_roots': 100000})
    for names in [list(FAMILIES[:-1]), list(FAMILIES) + [FAMILIES[0]], ['unknown']]:
        with pytest.raises(ValueError, match='every declared'):
            validate_policy({'families': names})
    for bound in [True, 0, 100001, 1.5]:
        with pytest.raises(ValueError, match='bound'):
            validate_policy({'max_roots': bound})


def test_nominal_loan_interest_fault_replaces_rate_subexpression():
    w = openpyxl.Workbook()
    c = w.active['D8']
    before = "=ROUND(ROUND(D7*'Operating Scenario'!$B$48/12,2),2)"
    c.value = before
    after, reason = mutate_composite_cell({'family': 'operating.loan_interest'}, c, w, None)
    assert "((1+'Operating Scenario'!$B$48)^(1/12)-1)" in after
    assert before[1:] not in after
    rate, principal = .075, 10000000
    assert round(principal * rate / 12, 2) != round(principal * ((1 + rate)**(1/12) - 1), 2)
    assert 'nominal' in reason
    w.close()


def test_regulatory_return_fault_uses_opening_not_average_without_copying_answer_formula():
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Reopener Statements'
    s['A4'], s['A10'] = 'opening rav real', 'closing rav real'
    c = s['C11']
    before = "=ROUND(('Reopener Statements'!C4+'Reopener Statements'!C10)/2*'Reopener Inputs'!C4,2)"
    c.value = before
    after, _ = mutate_composite_cell({'family': 'regulatory.real_return', 'sheet': s.title}, c, w, None)
    assert after == "=ROUND('Reopener Statements'!C4*'Reopener Inputs'!C4,2)"
    assert before[1:] not in after
    w.close()


def test_collateral_haircut_is_a_field_specific_loss_vs_discount_error():
    w = openpyxl.Workbook()
    c = w.active['E26']
    c.value = "=ROUND((ROUND('Reopener Statements'!E31*(1-'Holding Inputs'!E18),2)),2)"
    after, _ = mutate_composite_cell({'family': 'holding.claims_haircut'}, c, w, None)
    assert "'Reopener Statements'!E31/(1+'Holding Inputs'!E18)" in after
    assert round(100 * (1 - .2), 2) != round(100/(1 + .2), 2)
    w.close()


def test_contingent_fault_changes_rent_measurement_base_inside_the_cycle():
    w = openpyxl.Workbook()
    c = w.active['C4']
    c.value = "=IF('Contingent Inputs'!C7,MIN('Contingent Inputs'!C10,ROUND('Contingent Inputs'!C8*MAX(0,C3-'Contingent Inputs'!C9)/'Contingent Inputs'!C11,0)*'Contingent Inputs'!C11),0)"
    after, _ = mutate_composite_cell({'family': 'contingent.variable_rent'}, c, w, None)
    assert "(C3*'Contingent Inputs'!C4)-'Contingent Inputs'!C9" in after
    assert c.value[1:] not in after
    w.close()


def test_waterfall_preference_base_adds_gp_capital_instead_of_wrapping_correct_pref():
    w = openpyxl.Workbook()
    s = w.active
    s.title = 'Partner Waterfall'
    s['A7'], s['A8'] = 'lp_capital_open', 'gp_capital_open'
    c = s['C10']
    c.value = "=ROUND((ROUND(C7*'Partner Inputs'!$B$6,2)),2)"
    after, _ = mutate_composite_cell({'family': 'waterfall.preference_accrual', 'sheet': s.title}, c, w, None)
    assert "ROUND((C7+C8)*'Partner Inputs'!$B$6,2)" in after
    assert c.value[1:] not in after
    w.close()


def test_unknown_financial_templates_fail_closed_instead_of_fabricating_edits():
    w = openpyxl.Workbook()
    c = w.active['C8']
    c.value = '=ROUND(C7*.01,2)'
    with pytest.raises(ValueError, match='Unsupported'):
        mutate_composite_cell({'family': 'operating.loan_interest'}, c, w, None)
    w.close()


def test_zero_presentation_coverage_requires_successful_independent_exact_zero():
    conversions = [{'sheet': 'Operating Debt', 'cell': 'C12'}]
    audits = {'operating': {'cell_checks': [{'address': 'Debt!C12', 'expected_independent': '0', 'passed': True}]}}
    assert audited_zero_coverage(conversions, audits)[0]['source_independent_modules'] == ['operating']
    audits['operating']['cell_checks'][0]['expected_independent'] = '0.001'
    with pytest.raises(ValueError, match='not covered'):
        audited_zero_coverage(conversions, audits)
    audits['operating']['cell_checks'][0].update(expected_independent='0', passed=False)
    with pytest.raises(ValueError, match='failed'):
        audited_zero_coverage(conversions, audits)


def test_failed_contingent_match_is_never_treated_as_transitive_coverage():
    with pytest.raises(ValueError, match='failed'):
        audited_zero_coverage([{'sheet': 'Contingent Annual', 'cell': 'C4'}], {
            'contingent': {'cell_checks': [{'address': 'Contingent Annual!C4', 'expected_independent': 0, 'matched': False}]}})
