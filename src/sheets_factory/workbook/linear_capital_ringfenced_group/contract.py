"""Fixed four-mandate public contract; metadata freezing performs no admission."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SETUP = ROOT / 'outputs/research/linear_scaled_N360_pass10_engineering_revision2_prepared_20261031T175200Z/setup.json'
SETUP_SHA256 = 'e935b754ebccbf72b2497fdf3f1e00530c1d45a1906716e48e47a600d66fbc7f'
PROFILE_ORDER = ('L360-P01', 'L360-P02', 'L360-P07', 'L360-P09')
MANDATE_ORDER = ('M01', 'M02', 'M03', 'M04')
SCENARIOS = ('S01', 'S02', 'S03')
YEARS = tuple(range(1, 21))
GROUP_FIELDS = ('new_lp_calls', 'year_end_debt', 'lp_distributions', 'net_lp_cashflow', 'asset_nbv')
KIND = 'synthetic_four_ringfenced_capital_mandates'
PROSPECTIVE_KIND = 'prospective_four_ringfenced_capital_certificate_composition'
POLICIES = {
    'currency': 'GBP', 'monetary_unit': 'integer posted pence',
    'fiscal_year_start': 2027, 'fiscal_year_end': 2046,
    'time_convention': 'Each unchanged local time zero precedes FY1; fiscal year index1 is2027 and index20 is2046.',
    'business_header': 'Four legally ringfenced investment mandates hold separate project portfolios. Each mandate retains its own provided budgets, resources, tax accounts and funding rules. Management reports consolidate their reported amounts.',
    'local_financial_rules': 'Preserve each whole local public contract, project cash flows, posting rules and three scenarios without change.',
    'capital_fungible_between_mandates': False, 'resources_fungible_between_mandates': False,
    'intermandate_lending': False, 'intermandate_tax_or_loss_netting': False,
    'cross_mandate_binding_constraints': [],
    'choice_scope': 'Each mandate independently chooses its complete360-project binary plan, common across its three scenarios.',
    'objective': 'Sum the selected individually posted S01 project NPVs over all mandates; do not rediscount or reround the sum.',
    'group_reports': 'For each aligned scenario and fiscal year, add the five local reported pence amounts field by field; do not net debt, recompute tax, or create a group waterfall.',
    'runner_definition': 'Highest objective among all feasible complete group choices different from the unique group winner.',
    'nonapplicable_values': 'Any future nonapplicable presentation cell must contain a supplied nonempty NA literal.',
}


def require(condition, message):
    if not condition: raise ValueError(message)


def reference(value):
    path = Path(value).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'An exact real artifact is required')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(1024 * 1024): digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked(record):
    require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
            and reference(record['path']) == record, 'A frozen artifact reference changed')
    return Path(record['path'])


def read(value):
    return json.loads((checked(value) if isinstance(value, dict) else Path(value)).read_text())


def write(path, value):
    path = Path(path)
    with path.open('x') as handle: json.dump(value, handle, indent=2, ensure_ascii=False); handle.write('\n')
    return reference(path)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def first_pilot_inventory():
    """Read only pre-existing selection metadata, before hydrating proof bodies."""
    require(reference(SETUP)['sha256'] == SETUP_SHA256, 'The original fixed pass10 setup changed')
    setup = read(SETUP); lookup = {row['profile_id']: row for row in setup['profiles']}
    result = []
    for mandate, profile in zip(MANDATE_ORDER, PROFILE_ORDER, strict=True):
        row = lookup[profile]
        worker_ref = reference(SETUP.parent / 'profiles' / profile / 'worker_terminal.json')
        worker = read(worker_ref)
        require(worker['profile_id'] == profile, 'Another local profile worker was substituted')
        result.append({'id': mandate, 'profile_id': profile, 'specification': row['specification'],
                       'reference': row['reference'], 'source_manifest': worker['records']['source_manifest'],
                       'engineering_worker': worker_ref})
    return result


def public_contract(contexts):
    require([row['id'] for row in contexts] == list(MANDATE_ORDER)
            and [row['profile_id'] for row in contexts] == list(PROFILE_ORDER),
            'The first pilot is the fixed complete P01/P02/P07/P09 quartet')
    return {'kind': KIND, 'version': 1, 'origin': 'independent synthetic local business contexts reused unchanged',
        'mandates': [{'id': row['id'], 'local_profile_id': row['profile_id'], 'display_name': 'Mandate ' + str(i),
            'sheet_prefix': row['profile_id'].removeprefix('L360-') + ' - ',
            'public_specification': deepcopy(row['specification'])} for i, row in enumerate(contexts, 1)],
        'policies': deepcopy(POLICIES), 'scenario_ids': list(SCENARIOS), 'years': list(YEARS),
        'group_fields': list(GROUP_FIELDS), 'local_projects': 360, 'local_integer_rows': 941,
        'group_projects': 1440, 'group_local_integer_rows': 3764,
        'coupled_1440_project_MIP_claimed': False, 'difficulty_claimed': False}


def validate_contract(value, contexts):
    require(value == public_contract(contexts), 'The frozen public ringfencing or quartet contract changed')
    return value


def recipes():
    folder = Path(__file__).parent
    return {str(path): reference(path) for path in (folder / 'contract.py', folder / 'composition.py',
        ROOT / 'src/sheets_factory/workbook/linear_capital_scaled/reference.py',
        ROOT / 'scripts/build_linear_capital_scaled_source.py')}


def freeze_first_pilot(output):
    """Freeze all four assignments and policies before full certificate reads."""
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(),
            'Use a fresh private prospective directory')
    contexts = first_pilot_inventory(); public = public_contract(contexts)
    for row in contexts:
        for name in ('specification', 'reference', 'source_manifest', 'engineering_worker'): checked(row[name])
    output.mkdir(parents=True)
    return write(output / 'prospective.json', {'kind': PROSPECTIVE_KIND, 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'contract': write(output / 'public_contract.json', public),
        'contexts': contexts, 'original_setup': reference(SETUP), 'recipe': recipes(),
        'all_assignments_fixed_before_full_reference_hydration': True,
        'reference_or_source_admission_performed': False, 'workbooks_written': 0,
        'new_financial_forwards': 0, 'solver_calls': 0, 'LO_calls': 0, 'model_calls': 0, 'qualified': False})


def validate_prospective(record):
    frozen = read(record)
    require(frozen['kind'] == PROSPECTIVE_KIND and frozen['version'] == 1
            and frozen['contexts'] == first_pilot_inventory() and frozen['original_setup'] == reference(SETUP)
            and frozen['recipe'] == recipes() and frozen['all_assignments_fixed_before_full_reference_hydration'] is True
            and frozen['reference_or_source_admission_performed'] is False and frozen['qualified'] is False
            and all(type(frozen[k]) is int and frozen[k] == 0 for k in
                    ('workbooks_written', 'new_financial_forwards', 'solver_calls', 'LO_calls', 'model_calls')),
            'A complete frozen unspent first-quartet prospective is required')
    validate_contract(read(frozen['contract']), frozen['contexts'])
    for row in frozen['contexts']:
        for name in ('specification', 'reference', 'source_manifest', 'engineering_worker'): checked(row[name])
    return frozen
