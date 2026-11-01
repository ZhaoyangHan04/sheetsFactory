#!/usr/bin/env python3
"""Run fresh business-revision development materials with the frozen native v6 protocol."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
BASE = ROOT / 'scripts/run_operating_reports_factory_frontier.py'
BASE_SHA = '5d2389b2382082b299fc601e31865cec551f8369656bb46d6320adc2d00b1620'
BATCH_KIND = 'individually_engineered_business_revision_batch'
KIND = 'prepared_business_revision_native_frontier_v1'
SOURCE_KIND = 'business_revision_native_source_v1'
TERMINAL_KIND = 'business_revision_native_frontier_terminal_v1'
REPLACEMENTS = {
    'prepared_operating_reports_factory_frontier_v6': KIND,
    'operating_reports_factory_frontier_terminal_v6': TERMINAL_KIND,
    'operating_reports_factory_native_source_v6': SOURCE_KIND,
    'individually_engineered_operating_report_batch': BATCH_KIND,
    'permanent_factory_native_material_phase_reservation': 'permanent_business_revision_native_phase_reservation',
}


def _base_guard():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen native development base changed')


def _namespace():
    _base_guard()
    tree = ast.parse(BASE.read_text(), filename=str(BASE))
    counts = Counter()
    class Identity(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in REPLACEMENTS:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(REPLACEMENTS[node.value]), node)
            return node
    tree = Identity().visit(tree)
    if counts != Counter({key: 1 for key in REPLACEMENTS}):
        raise ValueError('The exact five native identity seams changed')
    namespace = {'__name__': '_business_revision_frozen_native_v6', '__file__': __file__}
    exec(compile(ast.fix_missing_locations(tree), str(BASE), 'exec'), namespace)
    return namespace


_N = _namespace()
_BASE_RECIPES = _N['recipes']
_BASE_PREPARE = _N['prepare']
_BASE_VALIDATE = _N['validate_prepared']
_BASE_RUN = _N['run']
for _name in ('BUDGET', 'PROFILE', 'MODES', 'runner', 'require', 'ref', 'read', 'write',
              'checked', 'canonical', 'check_task', 'material_identity', 'effective_score',
              'inspect_resource_export'):
    globals()[_name] = _N[_name]


def recipes():
    _base_guard()
    return {**_BASE_RECIPES(), 'frozen_generic_base': ref(BASE),
        'business_revision_development_contract': {
            'kind': BATCH_KIND, 'candidate_minimum': 10, 'candidate_maximum': 20,
            'phase': 'development', 'source_goal_identity': 'each task declares its exact goal SHA256',
            'reservation_registry': str(_N['RESERVATIONS']),
            'new_namespace_does_not_reset_existing_material_history': True}}


_N['recipes'] = recipes


def prepare(batches, output, *, port=0):
    """Freeze all declared 10–20 candidates; never select using later scores."""
    records = [checked(value) for value in batches]
    count = 0
    for record in records:
        batch = read(record)
        require(batch.get('kind') == BATCH_KIND and batch.get('version') == 1
            and batch.get('count') == len(batch['tasks'])
            and batch.get('selected_task_ids') == [t['task_id'] for t in batch['tasks']],
            'Use complete new business-revision engineering batches')
        count += batch['count']
    require(10 <= count <= 20, 'Predeclare ten through twenty fresh development candidates')
    return _BASE_PREPARE(records, output, phase='development', port=port)


def validate_prepared(output):
    prepared = _BASE_VALIDATE(output)
    require(prepared['phase'] == 'development' and prepared['development'] is None
        and 10 <= len(prepared['tasks']) <= 20,
        'This entry admits the fixed small development phase only')
    require(read(prepared['source']).get('kind') == SOURCE_KIND,
            'Require the distinct business-revision native source identity')
    return prepared


_N['validate_prepared'] = validate_prepared


def run(output, *, concurrency=10, port=0):
    # The original run calls validate_prepared once before permanent reservations.
    # It retains every original model, timing, actual-resource and retry check.
    return _BASE_RUN(output, concurrency=concurrency, port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--batch', action='append', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--concurrency', default=10, type=int)
    p.add_argument('--port', default=0, type=int)
    p = sub.add_parser('run')
    p.add_argument('--prepared', required=True, type=Path)
    p.add_argument('--concurrency', default=10, type=int)
    p.add_argument('--port', default=0, type=int)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.batch, args.output, port=args.port)
        if args.run:
            result = run(args.output, concurrency=args.concurrency, port=args.port)
    else:
        result = run(args.prepared, concurrency=args.concurrency, port=args.port)
    print(_N['json'].dumps(result))


if __name__ == '__main__':
    main()
