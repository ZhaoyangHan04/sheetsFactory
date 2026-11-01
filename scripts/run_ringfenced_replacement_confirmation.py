#!/usr/bin/env python3
"""Freeze the five predeclared pairs and confirm all ten new materials once."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
ENTRY = ROOT/'scripts/run_ringfenced_business_frontier.py'
ENTRY_SHA = 'a674ee4f4a9b928fecea7945c87ae5de3c64fa1398fcc358f311cc9c222fcac3'
DESIGN = ROOT/'outputs/research/ringfenced_first5_retained10_design_20261101T074000Z/freeze.json'
DESIGN_SHA = 'fa8ec5498c45d561570e4c1ba41f3fa9687b969386af74b5cfb1fe3a45326312'
KIND = 'prepared_ringfenced_predeclared_replacement_confirmation_v1'
TERMINAL_KIND = 'ringfenced_predeclared_replacement_confirmation_terminal_v1'
SOURCE_KIND = 'ringfenced_predeclared_replacement_confirmation_source_v1'
BATCH_KIND = 'individually_engineered_business_revision_batch'
PAIRS = tuple('R2-'+str(i).zfill(2) for i in range(1, 6))
COUNTS = Counter({'financial_modeling': 5, 'debugging': 5})


def guard():
    if hashlib.sha256(ENTRY.read_bytes()).hexdigest() != ENTRY_SHA:
        raise ValueError('The frozen development entry changed')


guard()
loader = importlib.util.spec_from_file_location('_replacement_confirmation_ring_entry', ENTRY)
entry = importlib.util.module_from_spec(loader); loader.loader.exec_module(entry)
p = entry.protocol
from sheets_factory.evaluation import ringfenced_confirmation_frontier_v6 as runner
from sheets_factory.evaluation import ringfenced_resource_harbor as resources
from sheets_factory.evaluation import mixed_business_resource_observer as observer
for _key, _value in {'runner': runner, 'KIND': KIND, 'TERMINAL_KIND': TERMINAL_KIND,
                     'resource_observer': observer, 'ResourceObserver': observer.ResourceObserver,
                     'validate_observation_receipt': observer.validate_observation_receipt}.items():
    p._N[_key] = _value
p.runner = runner
require, ref, read, write, checked = p.require, p.ref, p.read, p.write, p.checked
_BASE_RECIPES = entry.recipes


def recipes():
    guard(); old = _BASE_RECIPES()
    old.pop('business_revision_development_contract', None)
    return {**old, 'replacement_confirmation_entry': ref(__file__),
            'replacement_native_cardinality_adapter': ref(runner.__file__),
            'mixed_profile_inspector': ref(ROOT/'src/sheets_factory/evaluation/mixed_business_resources.py'),
            'replacement_contract': {'new_modes': dict(COUNTS), 'phase': 'confirmation',
                'retained_modes': dict(COUNTS), 'retained_results_are_historical': True,
                'all_new_materials_frozen_before_first_confirmation': True,
                'permanent_registry_unchanged': str(p._N['RESERVATIONS']), 'retries': 0}}


def cohort_tasks(batches):
    require(ref(DESIGN)['sha256'] == DESIGN_SHA, 'The first-five design changed')
    design = read(DESIGN)
    require(tuple(r['id'] for r in design['new_pairs']) == PAIRS
            and design['R2_model_results_observed_at_design_freeze'] == 0
            and design['model'] == 'gpt-6.1-sol' and design['reasoning_effort'] == 'xhigh'
            and design['outer_retries'] == 0, 'Use the prospective unchanged five-pair design')
    retained = read(design['retained_ten'])
    require(len(retained['tasks']) == 10 and Counter(t['mode'] for t in retained['tasks']) == COUNTS,
            'Preserve the ten predeclared retained materials')
    records = [checked(value) for value in batches]; tasks = []
    for record in records:
        batch = read(record)
        require(batch.get('kind') == BATCH_KIND and batch.get('version') == 1
                and batch.get('count') == len(batch['tasks']) == 2
                and batch.get('selected_task_ids') == [t['task_id'] for t in batch['tasks']],
                'Each complete engineered pair supplies its two fixed tasks')
        source = read(batch['source']); preparation = read(source['preparation']); certificate = read(preparation['certificate'])
        pair = certificate['pair_id']
        require(source['passed'] is True and source['LO_calls'] == 3 and pair in PAIRS
                and certificate['prospective'] == design['original_whole_pair_pool']
                and all(t['source_id'] == source['source']['sha256'] and t['variant_id'].startswith(pair+'-') for t in batch['tasks']),
                'Bind every fixed pair to its actual healthy source and original prospective certificate')
        tasks.extend(deepcopy(batch['tasks']))
    expected = {pair+'-'+suffix for pair in PAIRS for suffix in ('FM', 'DBG')}
    require(len(tasks) == len({t['task_id'] for t in tasks}) == 10
            and {t['variant_id'] for t in tasks} == expected
            and Counter(t['mode'] for t in tasks) == COUNTS,
            'Freeze exactly the first five pairs, once in each mode')
    for task in tasks:
        require(task['variant_id'].endswith('-FM' if task['mode'] == 'financial_modeling' else '-DBG'),
                'The task mode and fixed variant differ')
    return records, sorted(tasks, key=lambda t: (t['variant_id'][:5], t['mode'])), design['retained_ten']


def inspect_pair(tasks):
    """Use the original complete identity algorithm; share only this pair's goal."""
    before = recipes(); cache, inventories, materials = {}, {}, {}; tick = time.monotonic()
    for task in tasks:
        inventories[task['task_id']] = p._N['check_task'](task)
        materials[task['task_id']] = p.material_identity(task, cache)
    for task in tasks:
        require(p._N['check_task'](task) == inventories[task['task_id']], 'A pair changed during full logical inspection')
    require(recipes() == before, 'An identity recipe changed during full inspection')
    return {'kind': 'completed_replacement_pair_logical_identity_v1', 'tasks': [t['task_id'] for t in tasks],
            'recipe': before, 'export_files': inventories, 'materials': materials,
            'shared_goal_cache_entries': len(cache), 'elapsed_seconds': time.monotonic()-tick,
            'original_full_identity_algorithm': True, 'model_LO_solver_calls': 0}


def _development_records(locations, materials):
    records = [checked(value) for value in locations]; seen = set()
    for record in records:
        old = read(record)
        require(old.get('phase') == 'development' and old.get('kind') == 'business_revision_native_frontier_terminal_v1',
                'Keep actual development provenance separate from confirmation')
        checked(old['selection']); checked(old['evaluation'])
        for row in old['results']:
            if row.get('actual_attempt'):
                key = row['material_identity']['sha256']
                require(key in {v['sha256'] for v in materials.values()}, 'A development result belongs to another replacement cohort')
                seen.add(key)
    return records, sorted(seen)


def prepare(batches, output, *, development=(), workers=5, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real confirmation preparation')
    require(type(workers) is int and 1 <= workers <= 5, 'Use one through five identity workers')
    with p._N['monitor'](output/'preparation_monitor', 'freeze_replacement_cohort', port) as audit:
        before = recipes(); records, tasks, retained = cohort_tasks(batches)
        inventory, materials, witnesses = {}, {}, []
        pairs = [[t for t in tasks if t['variant_id'].startswith(pair+'-')] for pair in PAIRS]
        for task in tasks:
            audit.task(task['task_id'], mode=task['mode'], status='running', stage='full_logical_identity')
        audit.export()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(inspect_pair, pair): pair for pair in pairs}
            for future in as_completed(futures):
                result = future.result(); pair = futures[future]
                proof = write(output/'logical_proofs'/(pair[0]['variant_id'][:5]+'.json'), result)
                witnesses.append(proof); inventory.update(result['export_files']); materials.update(result['materials'])
                for task in pair:
                    audit.task(task['task_id'], status='ready', stage='frozen_material')
                audit.export()
        require(len({v['sha256'] for v in materials.values()}) == 10, 'Aliases do not form distinct replacement candidates')
        development_refs, developed = _development_records(development, materials)
        require(recipes() == before, 'The replacement protocol changed during preparation')
        source = write(output/'source_manifest.json', {'kind': SOURCE_KIND, 'version': 1, 'tasks': tasks,
            'selected_task_ids': [t['task_id'] for t in tasks], 'execution_budget': p.BUDGET,
            'tool_time_policy_version': 6, 'tool_time_policy': dict(runner.POLICY_V6),
            'native_transport_profile': runner.transport_profile(), 'qualified': False,
            'retained_results': retained, 'retained_results_retested': False, 'design': ref(DESIGN)})
        frozen = {'kind': KIND, 'version': 1, 'phase': 'confirmation', 'batches': records,
            'source': source, 'tasks': tasks, 'materials': materials, 'export_files': inventory, 'recipe': before,
            'development': None, 'development_provenance': development_refs,
            'developed_material_identities': developed,
            'first_attempt_holdout_material_identities': sorted(v['sha256'] for v in materials.values() if v['sha256'] not in developed),
            'logical_proofs': sorted(witnesses, key=lambda r: r['path']), 'design': ref(DESIGN), 'retained_results': retained,
            'retained_results_retested': False, 'selection_frozen_before_model': True, 'attempts_per_task': 1,
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'outer_retries': 0,
            'qualified': False, 'model_calls': 0, 'LO_calls': 0}
        result = write(output/'prepared.json', frozen)
        audit.update_run(status='completed', stage='prepared', task_count=10)
        return result


def validate_prepared(output):
    frozen = read(Path(output)/'prepared.json')
    require(frozen['kind'] == KIND and frozen['version'] == 1 and frozen['phase'] == 'confirmation'
            and frozen['recipe'] == recipes() and frozen['design'] == ref(DESIGN)
            and frozen['retained_results_retested'] is False, 'The frozen prospective replacement protocol changed')
    _, tasks, retained = cohort_tasks(frozen['batches'])
    require(tasks == frozen['tasks'] and retained == frozen['retained_results'], 'The complete fixed cohort changed')
    checked(retained)
    source = read(frozen['source'])
    require(source['kind'] == SOURCE_KIND and source['tasks'] == tasks
            and source['selected_task_ids'] == [t['task_id'] for t in tasks]
            and source['execution_budget'] == p.BUDGET and source['tool_time_policy_version'] == 6
            and source['tool_time_policy'] == dict(runner.POLICY_V6)
            and source['native_transport_profile'] == runner.transport_profile(), 'The native source contract changed')
    inventories, materials, seen = {}, {}, []
    for proof_ref in frozen['logical_proofs']:
        proof = read(proof_ref)
        require(proof['kind'] == 'completed_replacement_pair_logical_identity_v1' and proof['recipe'] == frozen['recipe']
                and proof['original_full_identity_algorithm'] is True and proof['model_LO_solver_calls'] == 0,
                'A completed original full-identity witness changed')
        inventories.update(proof['export_files']); materials.update(proof['materials']); seen.extend(proof['tasks'])
    require(len(seen) == len(set(seen)) == 10 and inventories == frozen['export_files'] and materials == frozen['materials'],
            'The complete witnessed logical identities differ from the freeze')
    for task in tasks:
        require(p._N['check_task'](task) == inventories[task['task_id']], 'An exact payload or engineering binding changed after inspection')
        core = {k: v for k, v in materials[task['task_id']].items() if k != 'sha256'}
        require(p.canonical(core) == materials[task['task_id']]['sha256'], 'A canonical logical identity changed')
    refs, developed = _development_records(frozen['development_provenance'], materials)
    require(refs == frozen['development_provenance'] and developed == frozen['developed_material_identities'],
            'The original development provenance changed')
    return frozen


p._N['recipes'] = recipes
p._N['validate_prepared'] = validate_prepared


def run(output, *, concurrency=10, port=0):
    return p._BASE_RUN(output, concurrency=concurrency, port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('prepare'); a.add_argument('--batch', action='append', type=Path, required=True)
    a.add_argument('--output', type=Path, required=True); a.add_argument('--development', action='append', type=Path, default=[])
    a.add_argument('--workers', type=int, default=5); a.add_argument('--run', action='store_true'); a.add_argument('--concurrency', type=int, default=10)
    a = sub.add_parser('run'); a.add_argument('--prepared', type=Path, required=True); a.add_argument('--concurrency', type=int, default=10)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.batch, args.output, development=args.development, workers=args.workers)
        if args.run: result = run(args.output, concurrency=args.concurrency)
    else: result = run(args.prepared, concurrency=args.concurrency)
    print(p._N['json'].dumps(result))


if __name__ == '__main__': main()
