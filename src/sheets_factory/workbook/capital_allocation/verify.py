"""Independent integer interpretation of every plan in a search CSV.

Only the public schema is shared. This module imports neither the Decimal
journal nor the C++ search/wire implementation and reads no compiled cash-flow
cache. Its own project schedules, taxes, funding and path hashes come from the
raw public primitives.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import time

from .spec import ANNUAL_FIELDS, PROJECT_IDS, SCENARIO_IDS, YEARS, load_spec

DENOMINATOR = 1_000_000_000_000
PROJECT_COLUMNS = ('revenue', 'opex', 'capex', 'depreciation', 'sale_proceeds',
                   'sale_carrying', 'sale_gain', 'book', 'nav')
CSV_FIELDS = ['mask', 'full_mask']
for _scenario_id in SCENARIO_IDS:
    CSV_FIELDS.extend((_scenario_id + '_feasible', _scenario_id + '_npv_pence',
        _scenario_id + '_path_sha256', _scenario_id + '_first_violation_year',
        _scenario_id + '_violation_mask'))
CSV_FIELDS.extend(('feasible', 'objective_pence'))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def _round_ratio(numerator, denominator):
    """Exact signed nearest integer; a half tie always moves away from zero."""
    _require(type(numerator) is int and type(denominator) is int and denominator > 0,
             'Invalid integer rational posting')
    magnitude = (2 * abs(numerator) + denominator) // (2 * denominator)
    return -magnitude if numerator < 0 else magnitude


def _project_schedules(raw):
    schedules = []
    for scenario in raw['scenarios']:
        projects = []
        for project in raw['projects']:
            book = 0
            rows = []
            for year in YEARS:
                key = str(year)
                capex = project['acquisition_cost_pence'] if year == project['commission_year'] else 0
                book += capex
                depreciation = 0
                age = year - project['commission_year']
                if 1 <= age <= project['depreciation_years'] and year <= project['sale_year']:
                    scheduled = (book if age == project['depreciation_years'] else
                        _round_ratio(project['acquisition_cost_pence'], project['depreciation_years']))
                    depreciation = min(book, max(0, scheduled))
                    book -= depreciation
                proceeds = carrying = 0
                if year == project['sale_year']:
                    proceeds = _round_ratio(project['sale_proceeds_pence'] * scenario['sale_factors_p12'][key], DENOMINATOR)
                    carrying, book = book, 0
                revenue = _round_ratio(project['annual_revenue_pence'][key] * scenario['revenue_factors_p12'][key], DENOMINATOR)
                expense = _round_ratio(project['annual_opex_pence'][key] * scenario['opex_factors_p12'][key], DENOMINATOR)
                nav = _round_ratio(book * scenario['nav_factors_p12'][key], DENOMINATOR)
                rows.extend((revenue, expense, capex, depreciation, proceeds, carrying,
                             proceeds - carrying, book, nav))
            projects.append(rows)
        schedules.append(projects)
    return schedules


class _Interpreter:
    def __init__(self, public_spec):
        self.spec = public_spec
        self.projects = _project_schedules(public_spec)
        self.total = [[0] * (len(YEARS) * len(PROJECT_COLUMNS)) for _ in SCENARIO_IDS]
        self.previous_mask = 0

    def _select(self, full_mask):
        changed = self.previous_mask ^ full_mask
        for index in range(18):
            if not changed & (1 << index):
                continue
            direction = 1 if full_mask & (1 << index) else -1
            for scenario_index in range(3):
                target = self.total[scenario_index]
                project = self.projects[scenario_index][index]
                for position, amount in enumerate(project):
                    target[position] += direction * amount
        self.previous_mask = full_mask

    def evaluate(self, full_mask, *, details=False):
        _require(type(full_mask) is int and 0 <= full_mask < 2**18, 'Invalid full investment mask')
        self._select(full_mask)
        scenarios = []
        for index, scenario in enumerate(self.spec['scenarios']):
            scenarios.append(self._scenario(scenario, self.total[index], details))
        feasible = all(row['feasible'] for row in scenarios)
        return {'full_mask': full_mask, 'feasible': feasible, 'scenarios': scenarios,
                'objective_pence': min(row['npv_pence'] for row in scenarios) if feasible else None}

    def _scenario(self, scenario, totals, details):
        public = self.spec
        cash = capital = public['opening_cash_pence']
        debt = retained = calls = nav = 0
        loss = [0] * 20
        discounted_net = -public['opening_cash_pence'] * DENOMINATOR
        flags = 0
        first = None
        path = hashlib.sha256()
        annual = []
        for offset, year in enumerate(YEARS):
            key = str(year)
            start = offset * len(PROJECT_COLUMNS)
            revenue, expense, capex, depreciation, sale, carrying, gain, book, current_nav = totals[start:start + 9]
            interest = _round_ratio(debt * scenario['bank_rates_p12'][key], DENOMINATOR)
            profit = revenue + gain - expense - depreciation - interest
            opening_losses = sum(loss)
            expire_index = offset - public['tax_loss_carry_years'] - 1
            expired = 0
            if expire_index >= 0:
                expired, loss[expire_index] = loss[expire_index], 0
            taxable = max(0, profit)
            used = 0
            for origin in range(offset):
                available = loss[origin]
                taken = min(available, taxable)
                loss[origin] = available - taken
                used += taken
                taxable -= taken
            created = max(0, -profit)
            loss[offset] = created
            tax = _round_ratio(taxable * public['tax_rate_p12'], DENOMINATOR)
            income = profit - tax
            limit = min(public['facility_limit_pence'], _round_ratio(
                nav * public['advance_rate_p12'] * (DENOMINATOR - scenario['haircuts_p12'][key]),
                DENOMINATOR * DENOMINATOR)) if year != 2043 else 0
            floor = public['minimum_cash_pence'] if year != 2043 else 0
            settlement_cash = cash + revenue + sale - expense - capex - interest - tax
            compulsory = max(0, debt - limit)
            after_compulsory = settlement_cash - compulsory
            voluntary = min(debt - compulsory, max(0, after_compulsory - floor))
            after_voluntary = after_compulsory - voluntary
            debt_left = debt - compulsory - voluntary
            advance = min(max(0, limit - debt_left), max(0, floor - after_voluntary))
            needed = max(0, floor - after_voluntary - advance)
            called = min(needed, max(0, public['lp_commitment_pence'] - calls))
            missing = needed - called
            available_cash = after_voluntary + advance + called
            available_equity = capital + called + retained + income
            paid = min(max(0, available_cash - floor), max(0, available_equity))
            capital_return = min(paid, capital + called)
            profit_return = paid - capital_return
            new_cash = available_cash - paid
            new_debt = debt_left + advance
            new_capital = capital + called - capital_return
            new_retained = retained + income - profit_return
            row = {'year': year, 'cash_open': cash, 'bank_open': debt, 'capital_open': capital,
                'retained_open': retained, 'lp_called_open': calls, 'prior_certified_nav': nav,
                'revenue': revenue, 'opex': expense, 'capex': capex, 'depreciation': depreciation,
                'sale_proceeds': sale, 'sale_carrying': carrying, 'sale_gain': gain,
                'bank_interest': interest, 'taxable_before_losses': profit,
                'loss_open': opening_losses, 'loss_expired': expired, 'loss_used': used,
                'loss_created': created, 'loss_close': sum(loss), 'taxable_after_losses': taxable,
                'current_tax': tax, 'net_income': income, 'borrowing_base': limit,
                'cash_before_financing': settlement_cash, 'mandatory_margin': compulsory,
                'cash_after_margin': after_compulsory, 'optional_repayment': voluntary,
                'cash_after_optional': after_voluntary, 'bank_draw': advance,
                'lp_required': needed, 'lp_call': called, 'funding_gap': missing,
                'cash_before_distribution': available_cash, 'equity_before_distribution': available_equity,
                'distribution': paid, 'return_of_capital': capital_return,
                'profit_distribution': profit_return, 'net_lp_cashflow': paid - called,
                'lp_called_close': calls + called, 'lp_remaining': public['lp_commitment_pence'] - calls - called,
                'cash_close': new_cash, 'bank_close': new_debt, 'capital_close': new_capital,
                'retained_close': new_retained, 'project_book_value': book, 'certified_nav': current_nav,
                'total_assets': new_cash + book, 'total_liabilities': new_debt,
                'total_equity': new_capital + new_retained,
                'balance_check': new_cash + book - new_debt - new_capital - new_retained,
                'cash_check': new_cash - (cash + revenue - expense - capex + sale - interest - tax
                    - compulsory - voluntary + advance + called - paid),
                'bank_check': new_debt - debt + compulsory + voluntary - advance,
                'capital_check': new_capital - capital - called + capital_return,
                'loss_check': sum(loss) - opening_losses + expired + used - created}
            _require(all(row[name] == 0 for name in ('balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check')),
                     'Independent integer financial conservation failed')
            values = (year, *(row[name] for name in ANNUAL_FIELDS), *loss)
            path.update(struct.pack('<' + 'q' * len(values), *values))
            if details:
                annual.append({**row, 'closing_loss_vintages': list(loss)})
            new_flags = (1 if missing else 0)
            if year == 2043:
                new_flags |= (2 if new_debt else 0) | (4 if book else 0) | (8 if new_cash else 0)
            flags |= new_flags
            if new_flags and first is None:
                first = year
            discounted_net += (paid - called) * public['discount_factors_p12'][key]
            cash, debt, capital, retained, calls, nav = new_cash, new_debt, new_capital, new_retained, calls + called, current_nav
        return {'id': scenario['id'], 'feasible': flags == 0,
            'npv_pence': _round_ratio(discounted_net, DENOMINATOR) if not flags else None,
            'net_npv_numerator': str(discounted_net), 'path_sha256': path.hexdigest(),
            'first_violation_year': first, 'violation_mask': flags, **({'annual': annual} if details else {})}


def evaluate_plan(spec, full_mask, *, details=False):
    """Interpret one plan independently; this does not prove global optimality."""
    return _Interpreter(load_spec(spec)).evaluate(full_mask, details=details)


def csv_record(mask, full_mask, result):
    record = {'mask': str(mask), 'full_mask': str(full_mask)}
    for scenario in result['scenarios']:
        prefix = scenario['id'] + '_'
        record.update({prefix + 'feasible': str(int(scenario['feasible'])),
            prefix + 'npv_pence': '' if scenario['npv_pence'] is None else str(scenario['npv_pence']),
            prefix + 'path_sha256': scenario['path_sha256'],
            prefix + 'first_violation_year': '' if scenario['first_violation_year'] is None else str(scenario['first_violation_year']),
            prefix + 'violation_mask': str(scenario['violation_mask'])})
    record.update(feasible=str(int(result['feasible'])),
        objective_pence='' if result['objective_pence'] is None else str(result['objective_pence']))
    return record


def verify_search(spec, plans_csv, output, *, active_project_ids=None):
    """Check every plan, including every infeasible twenty-year path.

    Production requires the full eighteen choices. An explicit smaller active
    set is only a toy experiment and cannot produce a production admission.
    """
    public = load_spec(spec)
    active = list(PROJECT_IDS if active_project_ids is None else active_project_ids)
    _require(len(set(active)) == len(active) and all(identifier in PROJECT_IDS for identifier in active)
             and 0 <= len(active) <= 18, 'Invalid active project IDs')
    indices = [PROJECT_IDS.index(identifier) for identifier in active]
    count = 1 << len(active)
    output = Path(output).resolve()
    _require(not output.exists(), 'Use a fresh independent verification directory')
    original_csv = _ref(plans_csv)
    output.mkdir(parents=True)
    if isinstance(spec, (str, Path)):
        public_ref = _ref(spec)
    else:
        _write(output / 'public_spec.json', public)
        public_ref = _ref(output / 'public_spec.json')
    implementation = _ref(__file__)
    schema_implementation = _ref(Path(__file__).with_name('spec.py'))
    interpreter = _Interpreter(public)
    started = time.monotonic()
    verified = evaluations = feasible_count = 0
    best = runnerup = best_mask = best_full_mask = runnerup_mask = None
    best_count = 0
    error = None
    try:
        with Path(plans_csv).open(newline='') as source, (output / 'python_plans.csv').open('x', newline='') as destination:
            reader = csv.DictReader(source)
            _require(reader.fieldnames == CSV_FIELDS, 'The complete search CSV column contract differs')
            writer = csv.DictWriter(destination, fieldnames=CSV_FIELDS, lineterminator='\n')
            writer.writeheader()
            for ordinal, actual in enumerate(reader):
                _require(ordinal < count, 'Search CSV contains undeclared extra plans')
                full_mask = sum((1 << index) for bit, index in enumerate(indices) if ordinal & (1 << bit))
                result = interpreter.evaluate(full_mask)
                evaluations += 60
                expected = csv_record(ordinal, full_mask, result)
                differing = [field for field in CSV_FIELDS if actual.get(field) != expected[field]]
                _require(None not in actual and not differing,
                         f'Plan {ordinal} differs from the raw-spec independent interpreter: {differing}')
                writer.writerow(expected)
                verified += 1
                value = result['objective_pence']
                if value is None:
                    continue
                feasible_count += 1
                if best is None or value > best:
                    runnerup, runnerup_mask = best, best_mask
                    best, best_mask, best_full_mask, best_count = value, ordinal, full_mask, 1
                elif value == best:
                    if best_count == 1:
                        runnerup, runnerup_mask = best, ordinal
                    best_count += 1
                elif runnerup is None or value > runnerup:
                    runnerup, runnerup_mask = value, ordinal
            _require(verified == count, 'Search CSV omits predeclared plans')
        _require(_ref(plans_csv) == original_csv and _ref(public_ref['path']) == public_ref
                 and _ref(__file__) == implementation
                 and _ref(schema_implementation['path']) == schema_implementation,
                 'An input or verifier changed during independent verification')
        _require(_ref(output / 'python_plans.csv')['sha256'] == original_csv['sha256'],
                 'The independent complete plan CSV bytes differ from the search CSV')
    except Exception as exception:
        error = {'error_type': type(exception).__name__, 'reason': str(exception)}
    full = active == list(PROJECT_IDS)
    unique = error is None and best is not None and best_count == 1
    gap = None if best is None or runnerup is None else best - runnerup
    chosen = {identifier: int(bool(best_full_mask & (1 << bit))) for bit, identifier in enumerate(PROJECT_IDS)} if unique else None
    receipt = {'kind': 'capital_allocation_independent_integer_verification', 'version': 1,
        'passed': error is None, 'full_enumeration': full and error is None,
        'toy_only': not full, 'active_project_ids': active, 'expected_plan_count': count,
        'plan_count': verified, 'scenario_year_evaluations': evaluations,
        'public_spec': public_ref, 'spec_sha256': _canonical(public),
        'cpp_plans': original_csv, 'python_plans': _ref(output / 'python_plans.csv'),
        'implementation': implementation, 'schema_implementation': schema_implementation,
        'feasible_count': feasible_count, 'best_count': best_count,
        'best_mask': best_mask, 'best_full_mask': best_full_mask, 'best_plan': chosen,
        'objective_pence': best, 'runnerup_mask': runnerup_mask, 'runnerup_objective_pence': runnerup,
        'gap_pence': gap, 'unique_best': unique,
        'source_admissible_unique_optimum': error is None and full and unique and gap is not None and gap >= 1,
        'elapsed_seconds': time.monotonic() - started, 'error': error,
        'all_scenario_year_states_checked': error is None,
        'shared_financial_calculation_helper': False,
        'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0}
    _write(output / 'verification_receipt.json', receipt)
    _require(error is None, 'Independent full-plan verification failed: ' + str(error))
    return _ref(output / 'verification_receipt.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--plans-csv', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--active-projects', nargs='*', default=None)
    arguments = parser.parse_args(argv)
    print(json.dumps(verify_search(arguments.spec, arguments.plans_csv, arguments.output,
                                  active_project_ids=arguments.active_projects)))


if __name__ == '__main__':
    main()
