"""Opt-in, uncalculated compound debugging construction only.

The provisional decisions use public project positions, never an optimum.
The complete frozen forward model is emitted before two financial policies are
mutated. The returned bindings describe the correct policy definitions; faults
are the exact overlay in the input. No source admission, numerical audit,
optimisation, activity proof, recalculation, or quality claim is made here.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from ..workbook.capital_allocation_sparse import excel, spec

ADAPTER_ID = 'sparse_capital_compound_debugging_v1'
SETTING = 'sparse_compound_debugging'
DEFAULT_TEMPLATE = Path(__file__).resolve().parents[3] / 'config/task_adapters/sparse_compound_debugging_v1.json'
_TEMPLATE = {
    'adapter': ADAPTER_ID, 'version': 1, 'enabled': False,
    'provisional_plan': {'rule': 'zero_based_public_project_index_modulo', 'modulus': 4,
                         'selected_remainder': 0, 'uses_gold': False},
    'policy_families': [
        {'id': 'lp_commitment_reuse', 'annual_field': 'lp_call',
         'mutation': 'minimum_required_and_total_commitment'},
        {'id': 'bank_interest_omitted', 'annual_field': 'bank_interest', 'mutation': 'constant_zero'}],
    'scope': 'every_scenario_and_financial_year', 'individual_root_activity_claimed': False,
    'optimisation_performed': False, 'LO_calls_authorized': False,
    'model_calls_authorized': False, 'qualified': False,
}
PENDING = (
    'provisional_plan_financial_feasibility', 'joint_policy_economic_effect',
    'optimisation_policy_coupling', 'two_by_two_necessity', 'actual_input_recalculation',
    'two_pass_complete_typed_stability', 'complete_required_D', 'five_controls',
    'independent_public_recovery', 'twelve_diagnostics', 'Harbor_oracle_nop', 'model_difficulty',
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'A real recipe file is required')
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    _require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
             == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
             'Recipe changed while hashing')
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def load_template(value=DEFAULT_TEMPLATE):
    """Accept only this disabled, prospectively fixed mechanism catalogue."""
    actual = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _require(spec.canonical_sha(actual) == spec.canonical_sha(_TEMPLATE), 'The fixed disabled template differs')
    return actual


def provisional_plan(public):
    """Select P01, P05, ... by public position; make no feasibility claim."""
    public = spec.load_spec(public)
    return {project['id']: int(index % 4 == 0) for index, project in enumerate(public['projects'])}


def public_brief():
    """State the business boundary without revealing private fault locations."""
    return (
        'Audit and repair this existing capital-allocation model against its supplied financial policies. '
        'The current common investment choices are provisional results, not fixed assumptions. '
        'Update them to the unique feasible binary plan that maximises the lowest LP net present value '
        'across all three scenarios, and update the connected financial schedules. '
        'Keep all raw project and scenario assumptions, approved financing channels, tax policies and '
        'posting and discount rules unchanged. Do not introduce new funding or forecast assumptions. '
        'Each candidate project schedule remains a standalone schedule even when not selected; '
        'selections apply to the scenario Annual aggregates. '
        'Keep the original worksheet names and order. Repair only existing model cells needed for this '
        'task; preserve unrelated formulas and supplied literals. Do not add helpers or populate '
        'otherwise unlabelled blanks. Allow dependent results to recalculate. '
        'Read /app/input.xlsx and save /app/output.xlsx. Values are checked after LibreOffice recalculation.'
    )


def _recipe():
    return {'adapter': _reference(__file__), 'template': _reference(DEFAULT_TEMPLATE),
            'schema': _reference(spec.__file__), 'emitter': _reference(excel.__file__),
            'frozen_emitter_dependencies': excel.assert_upstream_recipe()}


def _cell_reference(row):
    return "'" + row['sheet'].replace("'", "''") + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', row['cell'])


def _faults(bindings):
    """Derive the complete fixed overlay from financial identities, not values."""
    inputs = [row for row in bindings['input_bindings'] if row['path'] == ['lp_commitment_pence']]
    _require(len(inputs) == 1, 'The supplied total LP commitment must be unique')
    commitment = _cell_reference(inputs[0])
    rows = {tuple(row['expected_path']): row for row in bindings['financial_bindings']}
    _require(len(rows) == len(bindings['financial_bindings']), 'Duplicate financial identity')
    result = []
    for sid in spec.SCENARIO_IDS:
        for index, year in enumerate(spec.YEARS):
            annual = bindings['annual_refs'][sid][year]
            for family in _TEMPLATE['policy_families']:
                path = ('scenarios', sid, 'annual', index, family['annual_field'])
                row = rows[path]
                if family['annual_field'] == 'lp_call':
                    correct = '=' + excel.expression_formula(('min', annual['lp_required'],
                        ('max', 0, ('sub', commitment, annual['lp_called_open']))))
                    _require(row['formula'] == correct, 'The original cumulative commitment policy changed')
                    after = '=' + excel.expression_formula(('min', annual['lp_required'], commitment))
                else:
                    after = '=0'
                _require(row['formula'].startswith('=') and row['formula'] != after, 'A physical formula mutation is required')
                result.append({'policy_family': family['id'], 'scenario': sid, 'year': year,
                    'annual_field': family['annual_field'], 'sheet': row['sheet'], 'cell': row['cell'],
                    'before': row['formula'], 'after': after, 'individual_activity_claimed': False})
    return result


def emit_input(book, public, *, enabled=False, template=DEFAULT_TEMPLATE):
    """Emit a complete uncalculated model only with explicit opt-in.

    Neither an optimum, a reference workbook, nor a proof is an argument.
    Existing emitter metadata named ``gold_plan_supplied`` merely tests whether
    a plan argument exists; this builder corrects that label for its public-only
    provisional plan. Financial definitions and values are not changed by this
    metadata correction.
    """
    _require(type(enabled) is bool and enabled, 'Compound debugging construction is disabled by default')
    frozen = load_template(template)
    public = spec.load_spec(public)
    _require(not book.sheetnames, 'Use an empty workbook')
    recipe = _recipe()
    choices = provisional_plan(public)
    bindings = excel.emit_capital_allocation_workbook(book, public, choices)
    _require(bindings['gold_plan_supplied'] is True, 'The complete supplied-plan emitter contract changed')
    bindings['gold_plan_supplied'] = False
    bindings['provisional_plan_supplied'] = True
    faults = _faults(bindings)
    for fault in faults:
        cell = book[fault['sheet']][fault['cell']]
        _require(cell.value == fault['before'], 'The emitted financial definition differs')
        cell.value = fault['after']
    construction = {'kind': 'uncalculated_sparse_compound_debugging_input', 'version': 1,
        'adapter': ADAPTER_ID, 'template': frozen, 'public_spec_sha256': spec.canonical_sha(public),
        'recipe': recipe, 'bindings': bindings, 'provisional_plan': choices, 'faults': faults,
        'policy_family_count': len(frozen['policy_families']), 'physical_edit_count': len(faults),
        'public_instruction': public_brief(), 'individual_root_activity_claimed': False,
        'gold_or_optimum_supplied': False, 'optimisation_performed': False,
        'financial_cells_masked': 0, 'plan_dependent_caches_must_be_recalculated': True,
        'pending': {name: True for name in PENDING}, 'qualified': False, 'task_count': 0}
    construction['mechanical_validation'] = verify_input(book, public, construction)
    _require(recipe == _recipe(), 'Construction recipe changed during emission')
    return construction


def verify_input(book, public, construction):
    """Check the entire definition/literal overlay, without judging caches."""
    public = spec.load_spec(public)
    _require(construction.get('kind') == 'uncalculated_sparse_compound_debugging_input'
        and type(construction.get('version')) is int and construction['version'] == 1
        and construction.get('adapter') == ADAPTER_ID, 'Wrong compound construction')
    load_template(construction['template'])
    _require(construction['recipe'] == _recipe() and construction['public_spec_sha256'] == spec.canonical_sha(public)
        and construction['provisional_plan'] == provisional_plan(public), 'Public source, provisional choices or recipe changed')
    _require(construction['public_instruction'] == public_brief() and construction['pending'] == {name: True for name in PENDING}
        and construction['qualified'] is False and type(construction['task_count']) is int and construction['task_count'] == 0
        and construction['individual_root_activity_claimed'] is False and construction['gold_or_optimum_supplied'] is False
        and construction['optimisation_performed'] is False
        and type(construction['financial_cells_masked']) is int and construction['financial_cells_masked'] == 0
        and construction['plan_dependent_caches_must_be_recalculated'] is True, 'Unsupported construction claim')
    binding = construction['bindings']
    n = len(public['projects'])
    _require(binding['public_spec'] == public and binding['gold_plan_supplied'] is False
        and binding['provisional_plan_supplied'] is True and binding['optimisation_performed'] is False
        and binding['formula_count'] == 1981*n + 18083
        and len(binding['financial_bindings']) == 540*n + 9311
        and len(binding['arithmetic_bindings']) == 1440*n + 8772
        and len(binding['decision_bindings']) == n, 'Complete financial model scope differs')
    faults = _faults(binding)
    _require(construction['faults'] == faults and construction['physical_edit_count'] == len(faults) == 120
        and construction['policy_family_count'] == 2, 'Exact two-policy physical overlay differs')
    formulas = {(row['sheet'], row['cell']): row['formula']
                for row in binding['financial_bindings'] + binding['arithmetic_bindings']}
    for row in binding['decision_bindings']:
        formulas[row['sheet'], row['cell']] = '=' + str(construction['provisional_plan'][row['project_id']])
    _require(len(formulas) == binding['formula_count'], 'Duplicate physical formula binding')
    for row in faults:
        _require(formulas[row['sheet'], row['cell']] == row['before'], 'Original mutation definition differs')
        formulas[row['sheet'], row['cell']] = row['after']
    literals = {(row['sheet'], row['cell']): row for row in binding['literal_bindings']}
    _require(len(literals) == len(binding['literal_bindings']) and not set(formulas) & set(literals)
        and book.sheetnames == binding['sheet_names'], 'Complete literal or worksheet scope differs')
    seen_formulas, seen_literals = set(), set()
    for sheet in book:
        for cell in sheet._cells.values():
            if cell.value is None:
                continue
            key = sheet.title, cell.coordinate
            if cell.data_type == 'f':
                _require(key in formulas and cell.value == formulas[key], 'Unexpected input formula definition')
                seen_formulas.add(key)
            else:
                _require(key in literals, 'An unlabelled blank or unbound literal was populated')
                row = literals[key]
                _require((isinstance(cell.value, date) and cell.value.isoformat() == row['value']) if row['kind'] == 'date'
                    else type(cell.value).__name__ == row['kind'] and cell.value == row['value'], 'Supplied literal type or value changed')
                seen_literals.add(key)
    _require(seen_formulas == set(formulas) and seen_literals == set(literals), 'Missing financial formula or supplied literal')
    return {'complete_definition_and_literal_overlay_verified': True,
        'physical_formula_count': len(seen_formulas), 'physical_edit_count': len(faults),
        'policy_family_count': 2, 'individual_root_activity_claimed': False,
        'financial_audit_performed': False, 'cache_values_verified': False,
        'recalculation_performed': False, 'optimisation_performed': False, 'qualified': False}
