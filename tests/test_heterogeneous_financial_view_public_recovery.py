"""Public-only hand fixtures; no real source, isolated replay, LO or models."""
from copy import deepcopy
from datetime import datetime, date
from decimal import Decimal
import ast
import calendar
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import heterogeneous_financial_view_public_recovery as recovery
from sheets_factory.workbook.heterogeneous_contracts import spec, ledger


def public_spec():
    months = ['2027-01-01', '2027-02-01', '2027-03-01']
    return {'schema_version': 1, 'dimension_mode': 'toy', 'currency': 'GBP', 'rate_scale': spec.SCALE,
        'start_month': months[0], 'months': months, 'scenario_ids': ['S01'],
        'entities': [{'id': 'E01', 'name': 'Hand fixture business', 'functional_currency': 'GBP',
            'tax_policy': 'CASH_COUPON_QUARTERLY', 'tax_rate_p12': spec.SCALE // 4,
            'interest_cap_fraction_p12': 3 * spec.SCALE // 10, 'interest_carry_months': 1,
            'loss_carry_months': 1, 'dscr_policy': 'QUARTERLY_LAGGED', 'dscr_threshold_p12': spec.SCALE,
            'minimum_cash_pence': 2000, 'reserve_target_pence': 0, 'additional_lp_commitment_pence': 10000,
            'opening_trap': False, 'opening_cure_count': 0, 'opening_cash_pence': 2000,
            'opening_restricted_cash_pence': 0, 'opening_paid_in_capital_pence': 1800,
            'opening_retained_earnings_pence': 0, 'opening_tax_payable_pence': 0,
            'opening_interest_carry': [{'origin_month': '2026-11-01', 'amount_pence': 10},
                {'origin_month': '2026-12-01', 'amount_pence': 20}],
            'opening_tax_losses': [{'origin_month': '2026-12-01', 'amount_pence': 30}]}],
        'loans': [{'id': 'L01', 'entity_id': 'E01', 'type': 'BULLET_QUARTERLY_ACCRUAL',
            'opening_principal_pence': 1200, 'opening_accrued_interest_pence': 0,
            'terms': [{'id': 'L01@2027-01-01', 'effective_month': months[0], 'annual_rate_p12': spec.SCALE,
                'day_count': 'ACT_360', 'local_limit_pence': 1200, 'maturity_date': '2028-12-31',
                'draw_cutoff_month': months[-1], 'optional_repayment_fraction_p12': 0,
                'next_coupon_month': months[-1]}]}],
        'assets': [{'id': 'A01', 'entity_id': 'E01', 'description': 'Hand fixture opening equipment',
            'commission_month': '2026-01-01', 'original_cost_pence': 1000,
            'opening_accumulated_depreciation_pence': 0, 'useful_life_months': 100, 'capex_category': 'GROWTH'},
            {'id': 'A02', 'entity_id': 'E01', 'description': 'Hand fixture renewal',
                'commission_month': months[1], 'original_cost_pence': 100,
                'opening_accumulated_depreciation_pence': 0, 'useful_life_months': 3, 'capex_category': 'MAINTENANCE'}],
        'operating_inputs': {'E01': [{'month': m, 'base_cash_revenue_pence': 100, 'base_cash_opex_pence': 10} for m in months]},
        'scenarios': [{'id': 'S01', 'monthly_schedule': [{'month': m, 'revenue_factor_p12': spec.SCALE,
            'opex_factor_p12': spec.SCALE, 'annual_rate_spread_p12': 0} for m in months]}],
        'group': {'additional_lp_commitment_pence': 10000,
            'shared_bank_limit_schedule': [{'effective_month': months[0], 'limit_pence': 10000}],
            'shared_margin_priority': ['E01'], 'bank_funding_priority': ['E01'], 'lp_funding_priority': ['E01']}}


def _date(value):
    return datetime.fromisoformat(value) if value is not None else None


def _gbp(value):
    return float(Decimal(value) / 100)


def _rate(value):
    return float(Decimal(value) / spec.SCALE)


def public_book(s=None):
    """Hand table serializer, not a source emitter or source certificate."""
    s = deepcopy(s or public_spec())
    book = openpyxl.Workbook(); book.remove(book.active)
    for name in recovery.PUBLIC_SHEETS:
        book.create_sheet(name)
    for sid in s['scenario_ids']:
        for name in recovery.FORECAST_VIEWS:
            book.create_sheet(sid + ' ' + name)
    notes = book['Contract Notes']
    notes.append(['Heterogeneous debt and tax contracts', 'Public policy'])
    for i, text in enumerate((*spec.RULES, recovery.CLOSED_POLICY), 1):
        notes.append(['Policy ' + str(i), text])
    notes.append([])
    for phase in spec.PHASES:
        notes.append(['Close phase', phase])
    notes.append(['Asset depreciation', recovery.ASSET_POLICY])
    for title, headers in recovery.HEADERS.items():
        book[title].append(headers)
    for m in s['months']:
        d = datetime.fromisoformat(m); days = calendar.monthrange(d.year, d.month)[1]
        book['Calendar'].append([d, d.replace(day=days), days, int(d.month % 3 == 0)])
    for e in s['entities']:
        book['Entity Policies'].append([e['id'], e['name'], e['tax_policy'], _rate(e['tax_rate_p12']),
            _rate(e['interest_cap_fraction_p12']), e['interest_carry_months'], e['loss_carry_months'],
            e['dscr_policy'], _rate(e['dscr_threshold_p12']), _gbp(e['minimum_cash_pence']),
            _gbp(e['reserve_target_pence']), _gbp(e['additional_lp_commitment_pence']), int(e['opening_trap']), e['opening_cure_count']])
        book['Opening Balances'].append([e['id'], *[_gbp(e[f]) for f in ['opening_cash_pence',
            'opening_restricted_cash_pence', 'opening_paid_in_capital_pence', 'opening_retained_earnings_pence', 'opening_tax_payable_pence']]])
        for attr, label in [('opening_interest_carry', 'Denied interest'), ('opening_tax_losses', 'Tax loss')]:
            for v in e[attr]:
                book['Opening Tax Attributes'].append([e['id'], label, _date(v['origin_month']), _gbp(v['amount_pence'])])
    for loan in s['loans']:
        book['Facilities'].append([loan['id'], loan['entity_id'], loan['type'], _gbp(loan['opening_principal_pence']), _gbp(loan['opening_accrued_interest_pence'])])
        for t in loan['terms']:
            book['Facility Terms'].append([t['id'], loan['id'], _date(t['effective_month']), _rate(t['annual_rate_p12']),
                t['day_count'], _gbp(t['local_limit_pence']), _date(t['maturity_date']), _date(t['draw_cutoff_month']),
                _rate(t['optional_repayment_fraction_p12']), _date(t['next_coupon_month'])])
    for a in s['assets']:
        book['Asset Register'].append([a['id'], a['entity_id'], a['description'], _date(a['commission_month']),
            _gbp(a['original_cost_pence']), _gbp(a['opening_accumulated_depreciation_pence']), a['useful_life_months'], a['capex_category']])
    for eid, rows in s['operating_inputs'].items():
        for r in rows:
            book['Operating Forecast'].append([eid, _date(r['month']), _gbp(r['base_cash_revenue_pence']), _gbp(r['base_cash_opex_pence'])])
    for scenario in s['scenarios']:
        for r in scenario['monthly_schedule']:
            book['Scenario Assumptions'].append([scenario['id'], _date(r['month']), _rate(r['revenue_factor_p12']),
                _rate(r['opex_factor_p12']), _rate(r['annual_rate_spread_p12'])])
    g = s['group']; book['Portfolio Funding'].append(['Additional LP commitment', None, _gbp(g['additional_lp_commitment_pence'])])
    for r in g['shared_bank_limit_schedule']:
        book['Portfolio Funding'].append(['Shared bank limit', _date(r['effective_month']), _gbp(r['limit_pence'])])
    for attr, label in [('shared_margin_priority', 'Shared margin'), ('bank_funding_priority', 'Bank funding'), ('lp_funding_priority', 'LP funding')]:
        for rank, eid in enumerate(g[attr], 1):
            book['Allocation Priorities'].append([label, rank, eid])

    definitions = [('entities', s['entities'], [f for f in spec.ENTITY_FIELDS if f not in
        ('month', 'term_id', 'tax_policy', 'dscr_policy', 'cure_open', 'cure_next')]),
        ('loans', s['loans'], [f for f in spec.LOAN_FIELDS if f not in ('month', 'term_id')]),
        ('assets', s['assets'], [f for f in spec.ASSET_FIELDS if f != 'month']),
        ('group', [{'id': 'Group'}], [f for f in spec.GROUP_FIELDS if f != 'month'])]
    for sid in s['scenario_ids']:
        for view in recovery.FORECAST_VIEWS:
            ws = book[sid + ' ' + view]
            ws.append([ws.title + ' — monthly business forecast']); ws.append([])
            ws.append(['Entity', 'Origin month', 'Forecast month', 'Opening GBP', 'Expired GBP', 'Used GBP', 'Created GBP', 'Closing GBP']
                if view in ('Interest Carry', 'Loss Carry') else ['Entity / facility / asset', 'Statement / schedule', 'Account', 'Unit', *map(_date, s['months'])])
        for domain, identities, fields in definitions:
            for identity in identities:
                # Reverse row order so fixed private coordinates cannot work.
                for field in reversed(fields):
                    book[sid + ' ' + recovery._field_sheet(domain, field)].append([identity['id'],
                        recovery._category(domain, field), recovery._label(field), recovery._field_contract(domain, field)[1]])
        for name, attr, carry in [('Interest Carry', 'opening_interest_carry', 'interest_carry_months'),
                ('Loss Carry', 'opening_tax_losses', 'loss_carry_months')]:
            for e in s['entities']:
                for t, m in enumerate(s['months']):
                    origins = sorted({v['origin_month'] for v in e[attr]} | set(s['months'][:t + 1]))
                    for origin in origins:
                        age = spec.month_index(m) - spec.month_index(origin)
                        if t == 0 or age <= e[carry] + 1:
                            book[sid + ' ' + name].append([e['id'], _date(origin), _date(m)])
    return book


def save_book(tmp_path, s=None):
    book = public_book(s); path = tmp_path / 'public_input.xlsx'
    try: book.save(path)
    finally: book.close()
    return path


def test_complete_public_primitive_round_trip_and_no_private_metadata(tmp_path):
    s = public_spec(); path = save_book(tmp_path, s)
    result = recovery.parse_public_workbook(path)
    assert result == s
    assert 'source_manifest' not in result and 'provenance' not in result
    assert result['assets'][1]['commission_month'] == '2027-02-01'
    assert result['entities'][0]['opening_trap'] is False


def test_writer_matches_hand_interest_asset_timing_and_policy_na(tmp_path):
    source = save_book(tmp_path); destination = tmp_path / 'recovered.xlsx'
    report = recovery.recover_public(source, destination)
    public = recovery.parse_public_workbook(source)
    book = openpyxl.load_workbook(destination)
    try:
        def account(sheet, identity, label, month):
            row = next(r for r in book[sheet].iter_rows() if r[0].value == identity and r[2].value == label)
            return row[4 + month].value
        assert account('S01 Debt', 'L01', 'Interest accrual', 0) == 1.03
        assert account('S01 Assets', 'A02', 'Capex', 1) == 1
        assert account('S01 Assets', 'A02', 'Depreciation', 1) == 0
        assert account('S01 Assets', 'A02', 'Depreciation', 2) == .33
        assert account('S01 Covenants', 'E01', 'Covenant test passed', 0) is None
        assert account('S01 Covenants', 'E01', 'Debt-service coverage ratio', 0) is None
        assert report['intentional_policy_blank_results'] == 4
        assert not any('cure passes' in str(c.value).lower() for s in book for row in s for c in row)
        assert report['declared_business_slots'] == len(recovery.public_forecast_slots(book, public, require_masked=False))
    finally: book.close()
    assert report['independent_from_native_Excel_formulas'] is True
    assert report['shared_Decimal_source_audit_implementation'] is True
    assert report['third_independent_financial_implementation'] is False
    assert report['public_policy_sufficiency_independently_certified'] is False
    assert report['actual_isolated_replay_executed'] is False and report['actual_LO_calls'] == 0


def test_multi_scenario_resets_from_public_factors_without_hardcoded_source_values(tmp_path):
    s = public_spec()
    second = deepcopy(s['scenarios'][0]); second['id'] = 'S02'
    for r in second['monthly_schedule']: r['revenue_factor_p12'] = spec.SCALE // 2
    s['scenario_ids'].append('S02'); s['scenarios'].append(second)
    source = save_book(tmp_path, s); destination = tmp_path / 'recovered.xlsx'
    report = recovery.recover_public(source, destination)
    assert recovery.parse_public_workbook(source) == s
    book = openpyxl.load_workbook(destination)
    try:
        def revenue(sid):
            return next(r[4].value for r in book[sid + ' Statements'].iter_rows() if r[2].value == 'Revenue')
        assert revenue('S01') == 1 and revenue('S02') == .5
    finally: book.close()
    assert report['numeric_results_written'] > 0


def test_distinct_public_numeric_primitives_and_term_amendment_round_trip(tmp_path):
    s = public_spec(); e = s['entities'][0]
    e.update(tax_rate_p12=271234000000, interest_cap_fraction_p12=312345000000,
        dscr_threshold_p12=1234567000000, minimum_cash_pence=1901, reserve_target_pence=802,
        additional_lp_commitment_pence=12345, opening_cash_pence=2001,
        opening_restricted_cash_pence=302, opening_paid_in_capital_pence=1803,
        opening_retained_earnings_pence=-104, opening_tax_payable_pence=205,
        opening_trap=True, opening_cure_count=1)
    loan = s['loans'][0]
    loan['opening_accrued_interest_pence'] = 306
    first = loan['terms'][0]
    first.update(annual_rate_p12=876543000000, optional_repayment_fraction_p12=123456000000)
    second = deepcopy(first)
    second.update(id='L01@2027-02-01', effective_month='2027-02-01', day_count='ACT_365F',
        annual_rate_p12=765432000000, local_limit_pence=1123, next_coupon_month='2027-02-01')
    loan['terms'].append(second)
    s['operating_inputs']['E01'][0].update(base_cash_revenue_pence=501, base_cash_opex_pence=102)
    s['scenarios'][0]['monthly_schedule'][1].update(revenue_factor_p12=1234567000000,
        opex_factor_p12=987654000000, annual_rate_spread_p12=-1234000000)
    s['group']['additional_lp_commitment_pence'] = 23456
    s['group']['shared_bank_limit_schedule'].append({'effective_month': '2027-02-01', 'limit_pence': 34567})
    assert recovery.parse_public_workbook(save_book(tmp_path, s)) == s


@pytest.mark.parametrize('positive', [True, False])
def test_applicable_zero_service_has_blank_ratio_and_real_cash_based_pass(tmp_path, positive):
    s = public_spec(); s['entities'][0]['dscr_policy'] = 'MONTHLY_CURRENT'
    s['entities'][0]['opening_paid_in_capital_pence'] = 3000
    s['loans'][0].update(type='BULLET_MONTHLY', opening_principal_pence=0)
    s['loans'][0]['terms'][0].update(annual_rate_p12=0, next_coupon_month=None)
    for r in s['operating_inputs']['E01']:
        r.update(base_cash_revenue_pence=100 if positive else 0, base_cash_opex_pence=0 if positive else 100)
    source = save_book(tmp_path, s); destination = tmp_path / 'output.xlsx'
    recovery.recover_public(source, destination)
    book = openpyxl.load_workbook(destination)
    try:
        rows = {row[2].value: row for row in book['S01 Covenants'].iter_rows() if row[0].value == 'E01'}
        assert rows['Covenant test applies'][4].value == 1
        assert rows['Debt-service coverage ratio'][4].value is None
        assert rows['Covenant test passed'][4].value == int(positive)
    finally: book.close()


@pytest.mark.parametrize('tamper', ['missing_asset_policy', 'asset_policy_drift', 'raw_formula', 'raw_bool',
    'half_penny_input', 'calendar_days', 'duplicate_operating', 'missing_operating', 'duplicate_vintage',
    'unknown_funding', 'priority_rank', 'term_facility', 'extra_sheet', 'extra_input_cell',
    'missing_forecast', 'wrong_unit', 'duplicate_forecast', 'prefilled_answer', 'cure_counter', 'missing_fifo',
    'title_helper', 'hidden_forecast'])
def test_public_tamper_rejected_before_financial_forward(tmp_path, monkeypatch, tamper):
    book = public_book()
    if tamper == 'missing_asset_policy': book['Contract Notes'].delete_rows(book['Contract Notes'].max_row)
    elif tamper == 'asset_policy_drift': book['Contract Notes'].cell(book['Contract Notes'].max_row, 2, 'Use commissioning-month depreciation.')
    elif tamper == 'raw_formula': book['Opening Balances']['B2'] = '=20'
    elif tamper == 'raw_bool': book['Entity Policies']['M2'] = False
    elif tamper == 'half_penny_input': book['Opening Balances']['B2'] = 20.001
    elif tamper == 'calendar_days': book['Calendar']['C2'] = 30
    elif tamper == 'duplicate_operating': book['Operating Forecast'].append([c.value for c in book['Operating Forecast'][2]])
    elif tamper == 'missing_operating': book['Operating Forecast'].delete_rows(2)
    elif tamper == 'duplicate_vintage': book['Opening Tax Attributes'].append([c.value for c in book['Opening Tax Attributes'][2]])
    elif tamper == 'unknown_funding': book['Portfolio Funding']['A2'] = 'Unlimited LP'
    elif tamper == 'priority_rank': book['Allocation Priorities']['B2'] = 2
    elif tamper == 'term_facility': book['Facility Terms']['B2'] = 'Unknown'
    elif tamper == 'extra_sheet': book.create_sheet('Hidden answer').sheet_state = 'hidden'
    elif tamper == 'extra_input_cell': book['Asset Register']['Z3'] = 42
    elif tamper == 'missing_forecast': book['S01 Statements'].delete_rows(4)
    elif tamper == 'wrong_unit': book['S01 Statements']['D4'] = 'pence'
    elif tamper == 'duplicate_forecast': book['S01 Statements'].append([c.value for c in book['S01 Statements'][4]])
    elif tamper == 'prefilled_answer': book['S01 Statements']['E4'] = 0
    elif tamper == 'cure_counter': book['S01 Covenants'].append(['E01', 'Covenants', 'Observed cure passes at opening', 'count'])
    elif tamper == 'title_helper': book['S01 Statements']['Z1'] = 42
    elif tamper == 'hidden_forecast': book['S01 Statements'].sheet_state = 'hidden'
    else: book['S01 Loss Carry'].delete_rows(4)
    source = tmp_path / 'tampered.xlsx'; book.save(source); book.close()
    monkeypatch.setattr(ledger, 'simulate', lambda *a: pytest.fail('Financial forward started before validation'))
    with pytest.raises(recovery.PublicRecoveryError): recovery.recover_public(source, tmp_path / 'forbidden.xlsx')
    assert not (tmp_path / 'forbidden.xlsx').exists()


def test_first_expired_fifo_display_is_present_but_later_padding_is_not_required():
    public = public_spec(); entity = public['entities'][0]
    assert '2026-11-01' in recovery._fifo_origins(public, entity, 'opening_interest_carry', 0)
    assert '2026-11-01' not in recovery._fifo_origins(public, entity, 'opening_interest_carry', 1)
    assert '2026-12-01' in recovery._fifo_origins(public, entity, 'opening_interest_carry', 1)
    assert '2026-12-01' not in recovery._fifo_origins(public, entity, 'opening_interest_carry', 2)


@pytest.mark.parametrize('args', [(True, 1), (float('nan'), 1), (float('inf'), 1), (1.001, 100)])
def test_exact_public_numeric_units_fail_closed(args):
    with pytest.raises(recovery.PublicRecoveryError): recovery._integer(*args)


def test_ledger_report_binding_must_match_public_primitive_values():
    s = public_spec(); book = public_book(s); forward = ledger.simulate(s)
    forward['specification_sha256'] = '0' * 64
    try:
        with pytest.raises(recovery.PublicRecoveryError): recovery.write_public_results(book, s, forward)
    finally: book.close()


def test_fresh_output_and_immutable_public_input(tmp_path):
    source = save_book(tmp_path); before = source.read_bytes()
    instruction = tmp_path / 'instruction.md'; instruction.write_text('Complete the labelled business template.')
    destination = tmp_path / 'output.xlsx'; report_path = tmp_path / 'report.json'
    report = recovery.recover_public(source, destination, report_path, instruction_path=instruction)
    assert source.read_bytes() == before and report['instruction']['sha256']
    assert json.loads(report_path.read_text()) == report
    with pytest.raises(recovery.PublicRecoveryError): recovery.recover_public(source, destination)
    with pytest.raises(recovery.PublicRecoveryError): recovery.recover_public(source, source)


def test_saved_output_audit_streams_instead_of_quadratic_readonly_cell_queries(tmp_path, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    source = save_book(tmp_path)
    monkeypatch.setattr(ReadOnlyWorksheet, 'cell', lambda *a, **k: pytest.fail('Random readonly cell query'))
    recovery.recover_public(source, tmp_path / 'output.xlsx')


def test_recovery_does_not_import_private_source_projection_or_excel_code():
    source = Path(recovery.__file__).read_text(); tree = ast.parse(source)
    imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(s in module for module in imports for s in ('validate', 'excel', 'task_adapters', 'builder', 'admission'))
    assert 'heterogeneous_contracts' in imports
    assert 'private_specification' not in source and 'source_manifest' not in source
    args = list(__import__('inspect').signature(recovery.recover_public).parameters)
    assert args == ['source', 'destination', 'report_path', 'instruction_path']


def test_asset_business_note_is_exact_frozen_v2_policy():
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'config/task_adapters/heterogeneous_financial_view_v2.json').read_text())
    assert recovery.ASSET_POLICY == policy['asset_policy_note']
