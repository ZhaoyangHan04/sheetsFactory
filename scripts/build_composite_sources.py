#!/usr/bin/env python3
"""Plan, ledger-preflight, or explicitly build declared composite sources.

The default makes plans only. Independent ledger preflight never calls
LibreOffice. Only --build calls the complete four-audit, two-stability builder.
Profile selection uses declared order and ledger feasibility, never model scores.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.workbook.composite_finance.build import build as composite_build, RUNTIME, RUNTIME_ID
from sheets_factory.workbook.composite_finance.operating import checked_json
from sheets_factory.workbook.derived_gold.ledger import simulate as operating_simulate
from sheets_factory.workbook.derived_gold.validate import ledger_invariants_pass
from sheets_factory.workbook.derived_regulatory.ledger import simulate as regulatory_simulate, annual_bridge
from sheets_factory.workbook.derived_regulatory.source import prepare_spec
from sheets_factory.workbook.holding_treasury.ledger import simulate_parent
from sheets_factory.workbook.lease_finance.contract import validate_lease_spec
from sheets_factory.workbook.lease_finance.ledger import simulate_lease

REQUIRED_REGIMES = {'bank_draw', 'mandatory_margin', 'optional_repayment', 'lp_call',
                    'operating_acquisition', 'operating_exit', 'borrowing_base_binding'}
AUDIT_NAMES = {'lease', 'programme', 'operating', 'holding'}
PROFILE_FIELDS = {'id', 'operating_entity', 'mechanism', 'policy_changes', 'lease', 'programme', 'holding'}
LEASE_FIELDS = {'monthly_base_rent', 'initial_direct_cost', 'annual_discount_rate',
                'fixed_step_rate', 'fixed_step_months', 'index_floor_factor', 'index_cap_factor'}
EVENT_FIELDS = {'month', 'index_ratio', 'annual_discount_rate', 'new_end_month',
                'retention_fraction', 'cash_fee'}
PROGRAMME_FIELDS = {'long_run_inflation', 'long_run_real_wacc', 'tax_rate_before', 'tax_rate_after',
    'tax_rate_change_year', 'debt_rate', 'incremental_tariff_fraction', 'disallowance_real',
    'disallowance_year', 'general_rate', 'special_rate', 'general_transfer_fraction',
    'transfer_year', 'gearing', 'loss_carry_years', 'loss_use_cap', 'claim_lag_years', 'structures_tax_life'}
CATEGORY_FIELDS = {'share', 'commission_lag', 'regulatory_life', 'tax_pool'}
HOLDING_FIELDS = {'opening_cash', 'minimum_cash', 'facility_limit', 'additional_lp_commitment',
                  'rav_advance_rate', 'claim_advance_rate', 'operating_ownership', 'gbp_per_usd'}
ANNUAL_PRIMITIVES = {'bank_rate', 'management_fee', 'claim_haircut'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def write(path, value):
    """Every persisted result belongs to this new run; never replace a receipt."""
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def load(path):
    return json.loads(Path(path).read_text())


def absolute(path, root=ROOT):
    path = Path(path)
    return path if path.is_absolute() else Path(root) / path


def allowed(mapping, keys, label):
    if not isinstance(mapping, dict) or set(mapping) - keys:
        raise ValueError('Only public primitive patches are permitted for ' + label)


def finite(value, label):
    if isinstance(value, bool):
        raise ValueError('Finite explicit numeric primitive required: ' + label)
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Finite explicit numeric primitive required: ' + label)
    return result


def load_profiles(path):
    data = load(path)
    if data.get('schema_version') != 1 or not isinstance(data.get('profiles'), list):
        raise ValueError('Version 1 declared composite profiles are required')
    profiles = data['profiles']
    if not 10 <= len(profiles) <= 20:
        raise ValueError('Declare ten to twenty profiles before running the batch')
    identities = set()
    for profile in profiles:
        if set(profile) != PROFILE_FIELDS or not re.fullmatch(r'C[0-9]{2}-[a-z0-9-]+', profile['id']):
            raise ValueError('Explicit safe profile identity and complete public mechanism are required')
        if profile['id'] in identities:
            raise ValueError('Profile identities must be unique')
        identities.add(profile['id'])
        if not re.fullmatch(r'T(?:0[1-9]|10)', profile['operating_entity']):
            raise ValueError('Select an existing audited operating entity T01 through T10')
        if not profile['mechanism'] or not profile['policy_changes']:
            raise ValueError('Each profile must declare its financial mechanism and business policy changes')
    if not data.get('selection_policy'):
        raise ValueError('Predeclared selection policy is required')
    ancestor = data.get('regulatory_original_ancestor', {})
    if not ancestor.get('local_path') or not re.fullmatch(r'[a-f0-9]{64}', ancestor.get('sha256', '')) or not ancestor.get('url'):
        raise ValueError('Bind the original regulatory download separately from its normalized input')
    return data


def materialize_profile(profile, base_config, destination, root=ROOT):
    """Emit config inputs only; no computed annual amounts can enter a patch."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    base = deepcopy(base_config)
    if base.get('operating_contract_revision') != 2:
        raise ValueError('New composite scenarios require explicit operating_contract_revision=2')
    lease = load(absolute(base['lease_config'], root))
    programme = load(absolute(base['regulatory_config'], root))
    holding = load(absolute(base['holding_config'], root))
    by_id = {item['lease_id']: item for item in lease['leases']}
    allowed(profile['lease'], set(by_id), 'lease identities')
    for identity, patch in profile['lease'].items():
        allowed(patch, LEASE_FIELDS | {'events'}, 'lease ' + identity)
        record = by_id[identity]
        for key, value in patch.items():
            if key != 'events':
                record[key] = value
        events = {str(event['month']): event for event in record['events']}
        allowed(patch.get('events', {}), set(events), 'existing lease event identities')
        for month, changes in patch.get('events', {}).items():
            allowed(changes, EVENT_FIELDS, 'lease event')
            events[month].update(deepcopy(changes))
        # Preserve declared event order; validation rejects illegal moved dates.
    lease = validate_lease_spec(lease)
    reg_patch = profile['programme']
    allowed(reg_patch, PROGRAMME_FIELDS | {'categories', 'lease_allowable_fraction'}, 'programme')
    categories = {row['id']: row for row in programme['categories']}
    allowed(reg_patch.get('categories', {}), set(categories), 'programme categories')
    for identity, patch in reg_patch.get('categories', {}).items():
        allowed(patch, CATEGORY_FIELDS, 'programme category')
        categories[identity].update(deepcopy(patch))
    for key, value in reg_patch.items():
        if key not in {'categories', 'lease_allowable_fraction'}:
            programme[key] = value
    fraction = reg_patch.get('lease_allowable_fraction', base['lease_allowable_fraction'])
    if not Decimal('.75') <= finite(fraction, 'lease allowance') <= Decimal('.95'):
        raise ValueError('Public lease allowable fraction must remain between .75 and .95')
    for category in programme['categories']:
        if not 0 < finite(category['share'], 'programme share') <= 1:
            raise ValueError('Programme shares must be positive fractions')
        if type(category['commission_lag']) is not int or category['commission_lag'] < 0:
            raise ValueError('Commissioning lag must be a nonnegative integer')
        if type(category['regulatory_life']) is not int or category['regulatory_life'] < 1:
            raise ValueError('Regulatory asset life must be a positive integer')
        if category['tax_pool'] not in {'General', 'Special', 'Structures'}:
            raise ValueError('Unsupported public tax-pool policy')
    if sum(finite(c['share'], 'share') for c in programme['categories']) > 1:
        raise ValueError('Programme shares cannot exceed the available source spend')
    for key in ('disallowance_year', 'tax_rate_change_year', 'transfer_year'):
        if type(programme[key]) is not int or not programme['first_year'] <= programme[key] <= programme['last_year']:
            raise ValueError('Programme policy event falls outside the reporting horizon')
    if finite(programme['disallowance_real'], 'real disallowance') <= 0:
        raise ValueError('Every profile retains a real regulatory disallowance')
    allowed(profile['holding'], {'parameters', 'annual_defaults', 'annual_overrides'}, 'holding')
    hold_patch = profile['holding']
    allowed(hold_patch.get('parameters', {}), HOLDING_FIELDS, 'holding parameters')
    holding['parameters'].update(deepcopy(hold_patch.get('parameters', {})))
    allowed(hold_patch.get('annual_defaults', {}), ANNUAL_PRIMITIVES, 'holding annual primitive defaults')
    for row in holding['annual_inputs']:
        row.update(deepcopy(hold_patch.get('annual_defaults', {})))
    for changes in hold_patch.get('annual_overrides', []):
        allowed(changes, ANNUAL_PRIMITIVES | {'years'}, 'holding annual primitive overrides')
        years = changes.get('years')
        if not isinstance(years, list) or not years or any(type(y) is not int or y not in holding['years'] for y in years):
            raise ValueError('Explicit existing holding reporting years are required')
        for row in holding['annual_inputs']:
            if row['year'] in years:
                row.update({key: value for key, value in changes.items() if key != 'years'})
    for row in holding['annual_inputs']:
        if (finite(row['bank_rate'], 'bank rate') < 0 or finite(row['management_fee'], 'management fee') < 0
                or not 0 <= finite(row['claim_haircut'], 'claim haircut') <= 1):
            raise ValueError('Holding annual rates, fees and haircuts must be finite contractual primitives')
    p = holding['parameters']
    if not Decimal('.7') <= finite(p['gbp_per_usd'], 'GBP per USD') <= Decimal('.9'):
        raise ValueError('Declared GBP per USD must remain between .7 and .9')
    if finite(p['additional_lp_commitment'], 'finite LP commitment') <= 0:
        raise ValueError('A positive finite LP commitment is required')
    for key in ('rav_advance_rate', 'claim_advance_rate'):
        if not 0 <= finite(p[key], key) <= 1:
            raise ValueError('Collateral advance rates must be fractions')
    if not REQUIRED_REGIMES <= set(holding.get('required_observed_regimes', [])):
        raise ValueError('Every required parent financing and operating regime must remain required')
    holding['scenario_id'] = profile['id'] + '-holding'
    holding['credit_policy'] = (
        f"RAV advances are {p['rav_advance_rate']} of nominal closing RAV; claims advances are "
        f"{p['claim_advance_rate']} after the explicitly listed annual haircuts, net of senior "
        "programme debt and lease liabilities. The annual primitive input table states every "
        "bank rate, management fee and claim haircut. Additional LP commitments are finite.")
    programme['scenario_id'] = profile['id'] + '-programme'
    programme['source_path'] = str(absolute(programme['source_path'], root).resolve())
    files = {'lease_config': destination / 'lease.json', 'regulatory_config': destination / 'programme.json',
             'holding_config': destination / 'holding.json'}
    for key, value in [('lease_config', lease), ('regulatory_config', programme), ('holding_config', holding)]:
        write(files[key], value)
        base[key] = str(files[key].resolve())
    base['lease_allowable_fraction'] = fraction
    base['operating_manifest'] = str(absolute(base['operating_manifest'], root).resolve())
    base['operating_entity'] = profile['operating_entity']
    base['operating_contract_revision'] = 2
    config_path = destination / 'composite.json'
    write(config_path, base)
    write(destination / 'declared_profile.json', profile)
    return {'id': profile['id'], 'operating_entity': profile['operating_entity'],
            'operating_contract_revision': 2,
            'mechanism': profile['mechanism'], 'policy_changes': profile['policy_changes'],
            'config': ref(config_path), 'inputs': {key: ref(value) for key, value in files.items()}}


def operating_inputs(manifest_path, entity_id):
    manifest = load(manifest_path)
    if manifest.get('financial_audit_passed') is not True:
        raise ValueError('Operating source lacks actual financial audit evidence')
    if sha(manifest['local_path']) != manifest['derived_workbook_sha256']:
        raise ValueError('Operating source workbook differs from its verified identity')
    entities = [entity for entity in manifest['entities'] if entity['id'] == entity_id]
    if len(entities) != 1:
        raise ValueError('Operating entity must uniquely exist in the audited source')
    entity = entities[0]
    spec, bound = checked_json(entity['public_scenario']), checked_json(entity['ledger'])
    ledger = operating_simulate(spec)
    if json.loads(json.dumps(ledger, default=str)) != bound or not ledger_invariants_pass(ledger['checks']):
        raise ValueError('Independent operating ledger no longer reproduces its bound audited source')
    if spec['parameters']['start_date'] != '2027-01-01' or spec['parameters'].get('currency', 'USD') != 'USD':
        raise ValueError('Keep the original operating dates and USD reporting currency')
    return manifest, spec, ledger


def validate_ledgers(lease, programme, operating, holding, required):
    for name, ledger in [('lease', lease), ('programme', programme), ('holding', holding)]:
        if not ledger.get('checks') or not all(value is True for value in ledger['checks'].values()):
            raise ValueError('Independent ledger checks failed: ' + name)
    if not ledger_invariants_pass(operating['checks']):
        raise ValueError('Independent ledger checks failed: operating')
    missing = sorted(set(required) - {key for key, years in holding['observed_regimes'].items() if years})
    if missing:
        raise ValueError('Required holding regimes not activated: ' + ', '.join(missing))


def preflight_case(record, destination):
    """Only independent arithmetic and input provenance; no workbook emitter or LO."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    config = load(record['config']['path'])
    lease_spec = validate_lease_spec(load(config['lease_config']))
    reg_config = load(config['regulatory_config'])
    programme_spec = prepare_spec(reg_config['source_path'], reg_config)
    programme_spec['parameters']['lease_allowable_fraction'] = config['lease_allowable_fraction']
    parent_spec = load(config['holding_config'])
    manifest, op_spec, op = operating_inputs(config['operating_manifest'], config['operating_entity'])
    lease = simulate_lease(lease_spec)
    programme = regulatory_simulate(programme_spec, external_lease_annual=lease['annual'])
    parent = simulate_parent(parent_spec, annual_bridge(programme_spec, programme), op, op_spec)
    journals = {}
    for name, ledger in [('lease', lease), ('programme', programme), ('operating', op), ('holding', parent)]:
        path = destination / (name + '_ledger.json')
        write(path, ledger)
        journals[name] = ref(path)
    # Preserve independent journals even when a declared regime is absent.
    validate_ledgers(lease, programme, op, parent, parent_spec['required_observed_regimes'])
    original_reg = record['regulatory_original_ancestor']
    if sha(original_reg['local_path']) != original_reg['sha256'] or original_reg['url'] != reg_config['official_url']:
        raise ValueError('Original regulatory ancestor differs from the declared public download')
    original_op = manifest['source_ancestor']
    if (original_op['sha256'] != op_spec['source_lineage']['sha256']
            or sha(absolute(original_op['local_path'])) != original_op['sha256']):
        raise ValueError('Original operating ancestor differs from the bound public benchmark')
    report = {'schema_version': 1, 'status': 'independent_ledger_preflight_passed', 'profile_id': record['id'],
        'operating_contract_revision': config['operating_contract_revision'],
        'libreoffice_calls': 0, 'source_financial_audit_claimed': False, 'model_calls': 0,
        'ledger_refs': journals, 'required_holding_regimes': parent_spec['required_observed_regimes'],
        'observed_holding_regimes': parent['observed_regimes'],
        'observed_programme_regimes': programme['observed_regimes'],
        'lp_commitment': parent_spec['parameters']['additional_lp_commitment'],
        'lp_called_total': str(parent['annual'][-1]['lp_called_close']),
        'lp_remaining': str(parent['annual'][-1]['lp_remaining']),
        'source_ancestors': [
            {'sha256': original_reg['sha256'], 'kind': 'original_published_regulatory_workbook',
             'url': original_reg['url'], 'normalized_upstream_sha256': reg_config['source_sha256']},
            {'sha256': op_spec['source_lineage']['sha256'], 'kind': 'published_operating_benchmark_workbook',
             'url': op_spec['source_lineage'].get('download_url')}],
        'upstream_workbook_sha256': [reg_config['source_sha256'], manifest['derived_workbook_sha256']],
        'operating_entity': config['operating_entity'], 'original_operating_dates_preserved': True,
        'original_operating_currency': 'USD'}
    write(destination / 'preflight.json', report)
    return report


def recipe_hashes(root=ROOT, scenario_path=None):
    root = Path(root)
    paths = [root / 'scripts/build_composite_sources.py', root / 'config/derived_composite_finance_v1.json',
             root / 'config/derived_composite_finance_v2.json',
             root / 'config/derived_lease_contract_v1.json', root / 'config/derived_regulatory_reopener_v1.json',
             root / 'config/derived_holding_treasury_v2.json']
    paths += list((root / 'runtime/lo24.2-iterative-openpyxl315-v1').glob('*'))
    for folder in ('composite_finance', 'derived_gold', 'derived_regulatory', 'lease_finance', 'holding_treasury'):
        paths += list((root / 'src/sheets_factory/workbook' / folder).glob('*.py'))
    paths += [root / 'src/sheets_factory/workbook' / name for name in ('engine.py', 'compare.py', 'uno_recalculate.py')]
    if scenario_path is not None:
        paths.append(Path(scenario_path).resolve())
    return {str(p.resolve().relative_to(root.resolve())) if p.resolve().is_relative_to(root.resolve()) else str(p.resolve()): sha(p)
            for p in sorted(set(paths)) if p.is_file()}


def verify_built_source(manifest, output):
    """A prepared file or a preflight pass cannot enter selected."""
    output = Path(output)
    if manifest.get('financial_audit_passed') is not True or set(manifest.get('financial_audits', {})) != AUDIT_NAMES:
        raise ValueError('Four actual financial audit results are required')
    goal = ref(manifest['local_path'])
    if len(manifest.get('selected', [])) != 1 or manifest['selected'][0]['sha256'] != goal['sha256']:
        raise ValueError('Exactly one selected workbook must match the actual verified source')
    if goal['sha256'] != manifest['derived_workbook_sha256'] or manifest['runtime']['image_id'] != RUNTIME_ID:
        raise ValueError('Built workbook or runtime identity differs from the verified manifest')
    proofs = {}
    for name in sorted(AUDIT_NAMES):
        if manifest['financial_audits'][name].get('passed') is not True:
            raise ValueError('Actual component financial audit failed: ' + name)
        path = output / 'private' / (name + '_financial_audit.json')
        report = load(path)
        if report.get('passed') is not True or report.get('checked_cells', 0) <= 0 or report['workbook']['sha256'] != goal['sha256']:
            raise ValueError('Actual component financial audit receipt is invalid: ' + name)
        proofs[name] = ref(path)
    stable_ref = manifest['stability']
    if sha(stable_ref['path']) != stable_ref['sha256']:
        raise ValueError('Changed actual stability receipt')
    stable = load(stable_ref['path'])
    if (stable.get('stable') is not True or stable.get('comparison', {}).get('reward') != 1
            or stable.get('first_against_goal', {}).get('reward') != 1
            or stable.get('second_against_goal', {}).get('reward') != 1):
        raise ValueError('Two actual stable calculations must both match the frozen goal')
    calculations = [Path(stable[name]).resolve() for name in ('first', 'second')]
    if len(set(calculations + [Path(manifest['local_path']).resolve()])) != 3:
        raise ValueError('Two distinct actual recalculation artifacts are required')
    return {'workbook': goal, 'four_audits': proofs,
            'stability': ref(stable_ref['path']), 'actual_stability_workbooks': [ref(p) for p in calculations]}


def run_batch(scenario_path, output, *, mode='plan_only', limit=10, max_attempts=20, workers=1, root=ROOT):
    if mode not in {'plan_only', 'preflight', 'build'}:
        raise ValueError('Unknown composite batch mode')
    if type(workers) is not int or not 1 <= workers <= 2:
        raise ValueError('At most two workers are permitted')
    if type(limit) is not int or type(max_attempts) is not int or limit < 1 or not 1 <= max_attempts <= 20:
        raise ValueError('Positive limit and one to twenty maximum attempts are required')
    scenario_path, output, root = Path(scenario_path).resolve(), Path(output).resolve(), Path(root).resolve()
    declared = load_profiles(scenario_path)
    output.mkdir(parents=True, exist_ok=False)
    before_recipe = recipe_hashes(root, scenario_path)
    base = load(absolute(declared['base_config'], root))
    audit = AuditStore(output / 'audit', {'id': output.name, 'kind': 'composite_source_batch', 'status': 'planning',
        'target_count': limit, 'mode': mode, 'producer_active': True, 'llm_calls_permitted': False})
    server = DashboardServer(audit.snapshot, audit.events, port=0)
    url = server.start()
    audit.update_run(dashboard_url=url)
    print(json.dumps({'output': str(output), 'mode': mode, 'dashboard_url': url}), flush=True)
    manifest = {'schema_version': 1, 'dataset': declared['dataset'], 'mode': mode, 'created_at': utcnow(),
        'status': 'planning', 'qualified': False, 'task_count': 0, 'selected': [], 'attempts': [],
        'selection_policy': declared['selection_policy'], 'model_scores_consulted': False,
        'declared_profile_count': len(declared['profiles']), 'target_derived_workbook_count': limit,
        'max_attempts': max_attempts, 'workers': workers, 'verified_derived_workbook_count': 0,
        'source_ancestor_unique_count': None, 'upstream_workbook_unique_count': None,
        'api_calls': 0, 'llm_tokens': 0, 'recipe_sha256': before_recipe, 'scenario_config': ref(scenario_path),
        'runtime': {'image': RUNTIME, 'required_image_id': RUNTIME_ID}, 'started_at': utcnow()}
    began = time.monotonic()

    def node(record, name, action):
        start = time.monotonic()
        payload = {'task_id': record['id'], 'node': name, 'node_id': name, 'status': 'running', 'started_at': utcnow()}
        record_id = audit.record('nodes', payload)
        audit.emit('node.started', **payload)
        audit.task(record['id'], status='source_' + name, node=name, operating_entity=record['operating_entity'])
        status, error = 'failed', None
        try:
            result = action()
            status, error = 'completed', None
            return {'id': record['id'], 'passed': True, 'result': result}
        except Exception as exc:
            status, error = 'failed', {'type': type(exc).__name__, 'reason': str(exc)}
            return {'id': record['id'], 'passed': False, 'error': error}
        finally:
            values = {**payload, 'status': status, 'duration_ms': round((time.monotonic() - start) * 1000), 'error': error}
            audit.update_record('nodes', record_id, values)
            audit.emit('node.' + status, **values)
            audit.export()

    try:
        records = []
        for profile in declared['profiles'][:max_attempts]:
            result = node(profile, 'materialize', lambda p=profile: materialize_profile(p, base, output / 'configs' / p['id'], root))
            if result['passed']:
                record = result['result']
                record['regulatory_original_ancestor'] = deepcopy(declared['regulatory_original_ancestor'])
                record['regulatory_original_ancestor']['local_path'] = str(absolute(record['regulatory_original_ancestor']['local_path'], root).resolve())
                records.append(record)
            else:
                manifest['attempts'].append({**result, 'stage': 'materialize'})
        plan = {'declared_order': [p['id'] for p in declared['profiles']], 'attempted_order': [p['id'] for p in declared['profiles'][:max_attempts]],
                'selection_policy': declared['selection_policy'], 'limit': limit, 'profiles': records,
                'model_results_consulted': False, 'recipe_sha256': before_recipe}
        write(output / 'plan.json', plan)
        manifest['plan'] = ref(output / 'plan.json')
        preflights = []
        chosen = []
        if mode == 'plan_only':
            manifest['attempts'] += [{'id': r['id'], 'stage': 'plan_only', 'status': 'planned', 'config': r['config']} for r in records]
            manifest['status'] = 'planned_only'
        else:
            audit.update_run(status='preflighting')
            def preflight(record):
                return node(record, 'preflight', lambda: preflight_case(record, output / 'preflight' / record['id']))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                outcomes = list(pool.map(preflight, records))
            for record, outcome in zip(records, outcomes):
                item = {'id': record['id'], 'stage': 'preflight', 'status': 'preflight_passed' if outcome['passed'] else 'rejected', 'config': record['config']}
                if outcome['passed']:
                    report = outcome['result']
                    item['preflight'] = ref(output / 'preflight' / record['id'] / 'preflight.json')
                    preflights.append(report)
                    if len(chosen) < limit:
                        chosen.append(record)
                    audit.task(record['id'], status='source_preflight_passed', node='preflight')
                else:
                    item['error'] = outcome['error']
                    write(output / 'preflight' / record['id'] / 'failure.json', outcome['error'])
                    audit.task(record['id'], status='source_rejected', node='preflight', error=outcome['error'])
                manifest['attempts'].append(item)
            selection = {'profiles': [r['id'] for r in chosen], 'frozen_at': utcnow(),
                         'criterion': 'first declared profiles with passing independent ledger preflight',
                         'model_results_consulted': False, 'plan': manifest['plan']}
            write(output / 'source_selection.json', selection)
            manifest['source_selection'] = ref(output / 'source_selection.json')
            manifest['status'] = 'preflight_complete'
            if mode == 'build':
                if recipe_hashes(root, scenario_path) != before_recipe:
                    raise ValueError('Recipe changed before actual builds; use a fresh output and freeze it again')
                audit.update_run(status='building')
                def build_one(record):
                    destination = output / 'sources' / record['id']
                    def action():
                        result = composite_build(record['config']['path'], destination, root)
                        proof = verify_built_source(result, destination)
                        return {'manifest': result, 'verification': proof}
                    return node(record, 'four_audits_two_stability', action)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    outcomes = list(pool.map(build_one, chosen))
                seen = set()
                for record, outcome in zip(chosen, outcomes):
                    item = {'id': record['id'], 'stage': 'build', 'status': 'verified' if outcome['passed'] else 'rejected'}
                    if outcome['passed']:
                        source = outcome['result']['manifest']
                        identity = source['derived_workbook_sha256']
                        if identity in seen:
                            item.update(status='rejected', error={'reason': 'Duplicate derived workbook identity'})
                        else:
                            seen.add(identity)
                            item['verification'] = outcome['result']['verification']
                            item['source_manifest'] = ref(output / 'sources' / record['id'] / 'seed_manifest.json')
                            selected = deepcopy(source['selected'][0])
                            selected.update(profile_id=record['id'], operating_entity=record['operating_entity'],
                                            source_manifest=item['source_manifest'], source_ancestors=source['source_ancestors'])
                            manifest['selected'].append(selected)
                    else:
                        item['error'] = outcome['error']
                    manifest['attempts'].append(item)
                    audit.task(record['id'], status='source_verified' if item['status'] == 'verified' else 'source_rejected',
                               node='complete', error=item.get('error'))
                manifest['status'] = 'independently_verified_composed_financial_seed_batch' if len(manifest['selected']) == limit else 'partial_source_batch'
        ancestors = {item['sha256']: item for report in preflights for item in report['source_ancestors']}
        upstream = {value for report in preflights for value in report['upstream_workbook_sha256']}
        manifest.update(source_ancestors=list(ancestors.values()), source_ancestor_unique_count=len(ancestors) if preflights else None,
            upstream_workbook_unique_count=len(upstream) if preflights else None,
            derived_scenarios_are_independent_observed_companies=False,
            attempted_profile_count=len(declared['profiles'][:max_attempts]),
            preflight_passed_count=len(preflights),
            preflight_rejected_count=sum(a['stage'] in {'materialize', 'preflight'} and a.get('status') != 'preflight_passed' and a.get('passed') is not True
                                         for a in manifest['attempts'] if a['stage'] != 'plan_only'),
            verified_derived_workbook_count=len(manifest['selected']),
            build_rejected_count=sum(a['stage'] == 'build' and a['status'] == 'rejected' for a in manifest['attempts']),
            elapsed_seconds=round(time.monotonic() - began, 3))
        manifest['recipe_unchanged'] = recipe_hashes(root, scenario_path) == before_recipe
        if mode == 'build' and manifest['recipe_unchanged'] is not True:
            manifest['selected'] = []
            manifest['verified_derived_workbook_count'] = 0
            manifest['status'] = 'recipe_changed_not_verified'
        write(output / 'seed_manifest.json', manifest)
        audit.update_run(status=manifest['status'], verified_sources=len(manifest['selected']), qualified=0,
                         preflight_passed=len(preflights), elapsed_seconds=manifest['elapsed_seconds'])
        audit.emit('source_batch.completed', mode=mode, verified_sources=len(manifest['selected']),
                   preflight_passed=len(preflights), rejected=manifest['preflight_rejected_count'], llm_tokens=0)
        return manifest
    except BaseException as exc:
        write(output / 'batch_failure.json', {'type': type(exc).__name__, 'reason': str(exc)})
        audit.update_run(status='failed', error=str(exc), qualified=0)
        raise
    finally:
        audit.update_run(producer_active=False)
        audit.export()
        server.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/derived_composite_scenarios_v1.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--max-attempts', type=int, default=20)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--plan-only', action='store_const', dest='mode', const='plan_only')
    modes.add_argument('--preflight', action='store_const', dest='mode', const='preflight')
    modes.add_argument('--build', action='store_const', dest='mode', const='build')
    parser.set_defaults(mode='plan_only')
    args = parser.parse_args(argv)
    result = run_batch(args.config, args.output, mode=args.mode, limit=args.limit,
                       max_attempts=args.max_attempts, workers=args.workers)
    print(json.dumps({'manifest': str(args.output / 'seed_manifest.json'), 'status': result['status'],
        'preflight_passed': result['preflight_passed_count'], 'verified_sources': result['verified_derived_workbook_count'],
        'source_ancestors': result['source_ancestor_unique_count'], 'elapsed_seconds': result['elapsed_seconds']}), flush=True)


if __name__ == '__main__':
    main()
