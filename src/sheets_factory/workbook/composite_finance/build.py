"""Build and verify a genuinely connected multi-contract financial source."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import openpyxl

from ..derived_regulatory.source import prepare_spec
from ..derived_regulatory.ledger import simulate as regulatory_simulate, annual_bridge
from ..derived_regulatory.excel import create_workbook
from ..derived_regulatory.policy import public_policy
from ..derived_regulatory.validate import audit_workbook as regulatory_audit
from ..derived_gold.validate import audit_workbook as operating_audit
from ..lease_finance.contract import load_lease_spec
from ..lease_finance.ledger import simulate_lease
from ..lease_finance.excel import emit_lease_workbook
from ..lease_finance.validate import audit_lease_workbook
from ..holding_treasury.ledger import simulate_parent
from ..holding_treasury.excel import emit_parent
from ..holding_treasury.validate import audit_workbook as holding_audit
from ..engine import LibreOfficeEngine
from ..compare import compare_workbooks, workbook_values
from .operating import append_operating_entity


RUNTIME = 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
RUNTIME_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
PUBLIC_SHEET = 'Model Input Contracts'


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str, ensure_ascii=False) + '\n')


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def _public_spec(value):
    """Remove local provenance locations; retain every explicit business input."""
    if isinstance(value, list):
        return [_public_spec(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_spec(item) for key, item in value.items()
                if key not in {'path', 'local_path', 'private_path'}}
    return value


def emit_public_specs(book, specs):
    sheet = book.create_sheet(PUBLIC_SHEET)
    sheet['A1'] = 'Machine-readable copies of provided contractual inputs'
    sheet['A2'] = ('These JSON records contain supplied assumptions and policies only. '
                   'They contain no calculated forecast or reference answers. '
                   'The matching labelled input sheets carry the same contractual values.')
    for row, (name, spec) in enumerate(specs.items(), 4):
        payload = json.dumps(_public_spec(spec), ensure_ascii=False, separators=(',', ':'))
        if len(payload) > 32000:
            raise ValueError('Public input contract exceeds safe Excel cell length')
        sheet.cell(row, 1, name)
        sheet.cell(row, 2, payload)
    sheet.column_dimensions['A'].width = 30
    sheet.column_dimensions['B'].width = 115


def audit_provided_context(source, goal, adapters):
    """The provided forecast must not become a balancing input for new modules."""
    original, source_sheets = workbook_values(source)
    completed, goal_sheets = workbook_values(goal)
    permitted = {(item['sheet'], item['cell']) for item in adapters}
    if permitted - {('Cover', 'G4')}:
        raise ValueError('Only the declared nonfinancial cover identifier may be adapted')
    missing_sheets = set(source_sheets) - set(goal_sheets)
    keys = set(original) | {key for key in completed if key[0] in source_sheets}
    mismatches = [{'address': sn + '!' + cell, 'before': original.get((sn, cell)),
                   'after': completed.get((sn, cell))}
                  for sn, cell in sorted(keys - permitted)
                  if original.get((sn, cell), ('empty', '')) != completed.get((sn, cell), ('empty', ''))]
    return {'passed': not mismatches and not missing_sheets, 'checked_cells': len(keys - permitted),
            'missing_sheets': sorted(missing_sheets), 'mismatches': mismatches,
            'metadata_adapters': adapters, 'source': ref(source), 'completed': ref(goal),
            'scope': 'All provided upstream typed values, except the explicitly declared cover display identifier.'}


def recipe_references(config_path, config):
    """Capture actual calculation and input bytes before building any outputs."""
    modules = ('composite_finance/build.py', 'composite_finance/operating.py',
        'derived_gold/ledger.py', 'derived_gold/validate.py',
        'derived_regulatory/source.py', 'derived_regulatory/ledger.py',
        'derived_regulatory/excel.py', 'derived_regulatory/schema.py',
        'derived_regulatory/policy.py', 'derived_regulatory/POLICY.md', 'derived_regulatory/validate.py',
        'lease_finance/contract.py', 'lease_finance/ledger.py', 'lease_finance/excel.py',
        'lease_finance/validate.py', 'lease_finance/CONTRACT.md',
        'holding_treasury/ledger.py', 'holding_treasury/schema.py',
        'holding_treasury/excel.py', 'holding_treasury/validate.py')
    paths = [Path(__file__).parent.parent / name for name in modules]
    paths.extend(Path(config[key]) for key in ('regulatory_config', 'lease_config', 'holding_config', 'operating_manifest'))
    paths.append(Path(config_path))
    return {str(path.resolve()): ref(path) for path in paths}


def build(config_path, output, project_root):
    started = time.monotonic()
    project_root, config_path, output = Path(project_root), Path(config_path), Path(output)
    config = json.loads(config_path.read_text())
    recipe = recipe_references(config_path, config)
    output.mkdir(parents=True, exist_ok=False)
    private = output / 'private'
    private.mkdir()
    reg_config = json.loads(Path(config['regulatory_config']).read_text())
    reg_spec = prepare_spec(reg_config['source_path'], reg_config)
    reg_spec['parameters']['lease_allowable_fraction'] = config['lease_allowable_fraction']
    lease_spec = load_lease_spec(config['lease_config'])
    parent_spec = json.loads(Path(config['holding_config']).read_text())
    lease = simulate_lease(lease_spec)
    programme = regulatory_simulate(reg_spec, external_lease_annual=lease['annual'])
    book = openpyxl.load_workbook(reg_config['source_path'], keep_links=False)
    lease_binding = emit_lease_workbook(lease_spec, workbook=book)
    book.save(private / 'provided_and_leases.xlsx')
    book.close()
    reg_binding = create_workbook(private / 'provided_and_leases.xlsx', reg_spec,
        private / 'with_programme.xlsx', public_policy(include_leases=True),
        external_annual_refs=lease_binding['annual_refs'])
    book = openpyxl.load_workbook(private / 'with_programme.xlsx', keep_links=False)
    operating = append_operating_entity(book, config['operating_manifest'],
        entity_id=config.get('operating_entity', 'T01'),
        contract_revision=config.get('operating_contract_revision', 1))
    parent = simulate_parent(parent_spec, annual_bridge(reg_spec, programme),
                             operating['ledger'], operating['public_scenario'])
    if not all(parent['observed_regimes'].get(key) for key in parent_spec['required_observed_regimes']):
        raise ValueError('Holding case does not activate every requested actual financial regime')
    holding_binding = emit_parent(book, parent_spec, reg_binding['annual_refs'], operating['operating_refs'])
    specs = {'lease': lease_spec, 'programme': reg_spec,
             'operating': operating['public_scenario'], 'holding': parent_spec}
    emit_public_specs(book, specs)
    raw = private / 'unrecalculated.xlsx'
    book.save(raw)
    book.close()
    for name, value in [('lease_ledger', lease), ('programme_ledger', programme),
                        ('holding_ledger', parent), ('operating', operating),
                        ('lease_bindings', lease_binding), ('programme_bindings', reg_binding),
                        ('holding_bindings', holding_binding)]:
        write(private / (name + '.json'), value)
    write(output / 'public_scenarios.json', _public_spec(specs))
    engine = LibreOfficeEngine(project_root, RUNTIME, config.get('engine_timeout_seconds', 300))
    runtime = engine.metadata()
    if runtime['image_id'] != RUNTIME_ID:
        raise ValueError('Unexpected composed-source calculation runtime')
    goal = engine.recalculate(raw, output / 'composite_model.xlsx')
    context_audit = audit_provided_context(reg_config['source_path'], goal, reg_binding['metadata_adapter'])
    write(private / 'provided_context_audit.json', context_audit)
    if not context_audit['passed']:
        raise ValueError('Provided upstream context changed: ' + str(context_audit['mismatches'][:3]))
    audits = {
        'lease': audit_lease_workbook(goal, lease_spec, lease, lease_binding),
        'programme': regulatory_audit(goal, reg_spec, programme),
        'operating': operating_audit(goal, operating['public_scenario'], operating['ledger'],
                                     operating['bindings'], sheet_mapping=operating['sheet_mapping']),
        'holding': holding_audit(goal, parent, holding_binding['bindings'], spec=parent_spec)}
    for name, audit in audits.items():
        write(private / (name + '_financial_audit.json'), {'workbook': ref(goal), **audit})
    summary = {name: {'passed': audit['passed'], 'checked_cells': audit['checked_cells'],
                     'mismatch_count': len(audit.get('mismatches', []))}
               for name, audit in audits.items()}
    write(private / 'financial_audit_summary.json', summary)
    if not all(audit['passed'] is True for audit in audits.values()):
        raise ValueError('Composed financial source audit failed: ' + json.dumps(summary))
    # Compare the first frozen goal against BOTH later real calculations.
    stable = engine.check_stable(goal, private / 'stability')
    stable['first_against_goal'] = compare_workbooks(goal, goal, Path(stable['first']))
    stable['second_against_goal'] = compare_workbooks(goal, goal, Path(stable['second']))
    stable['stable'] = (stable['stable'] and stable['first_against_goal']['reward'] == 1
                        and stable['second_against_goal']['reward'] == 1)
    write(private / 'stability.json', stable)
    if not stable['stable']:
        raise ValueError('Composed source caches change under ordinary subsequent recalculation')
    if any(ref(path)['sha256'] != binding['sha256'] for path, binding in recipe.items()):
        raise ValueError('A calculation implementation or scenario input changed while building the source')
    manifest = {'schema_version': 1, 'status': 'independently_verified_composed_financial_seed',
        'qualified': False, 'task_count': 0, 'created_at': datetime.now(timezone.utc).isoformat(),
        'local_path': str(goal.resolve()), 'derived_workbook_sha256': ref(goal)['sha256'],
        'source_ancestors': [ref(reg_config['source_path']), operating['lineage']],
        'public_scenarios': ref(output / 'public_scenarios.json'),
        'financial_audit_passed': True, 'financial_audits': summary,
        'financial_audit': ref(private / 'financial_audit_summary.json'),
        'stability': ref(private / 'stability.json'), 'runtime': runtime,
        'config': ref(config_path), 'calculation_implementations': recipe,
        'provided_context_audit': ref(private / 'provided_context_audit.json'),
        'api_calls': 0, 'elapsed_seconds': time.monotonic() - started,
        'observed_holding_regimes': parent['observed_regimes'],
        'formula_count': sum(a.get('formula_count', a.get('new_formula_count', 0)) for a in audits.values()),
        'independently_checked_cells': sum(a['checked_cells'] for a in audits.values())}
    manifest['selected'] = [{'sha256': manifest['derived_workbook_sha256'],
        'source_sha256': manifest['derived_workbook_sha256'], 'local_path': manifest['local_path'],
        'source_kind': 'derived_composed_financial_model', 'modes': ['financial_modeling', 'debugging'],
        'financial_modeling_eligible': True, 'finance_eligible': True,
        'finance_evidence': {'financial_seed_verified': True, 'source_business_issues': [],
                             'audit_proofs': manifest['financial_audits'],
                             'qualification': 'Independent source audit only; no task or difficulty qualification.'}}]
    write(output / 'seed_manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.config, args.output, Path.cwd())
    print(json.dumps({'manifest': str(args.output / 'seed_manifest.json'),
                      'checked_cells': result['independently_checked_cells'],
                      'elapsed_seconds': result['elapsed_seconds']}))
