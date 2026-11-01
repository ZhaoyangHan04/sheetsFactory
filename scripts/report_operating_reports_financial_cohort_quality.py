#!/usr/bin/env python3
"""Report an actual cohort run using its hash-bound native goal reference."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'scripts/run_operating_reports_financial_cohort_quality_revision2.py'
ENTRY_SHA = 'db8179ad29f392c283f01e1472047bdfa413b23bb8f8aa3e2c7777a3dbb037dd'


def _load():
    # Freeze the full existing entry, including its original scoped reporter.
    if hashlib.sha256(ENTRY.read_bytes()).hexdigest() != ENTRY_SHA:
        raise ValueError('The frozen cohort normal entry changed')
    spec = importlib.util.spec_from_file_location('_cohort_native_goal_report_ancestor', ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ancestor = _load()


def _current_native_goal(native, binding, base):
    """Check the actual goal file; a digest-shaped string is insufficient."""
    record = native.get('goal')
    if type(record) is not dict or set(record) != {'path', 'sha256', 'bytes'}:
        raise ValueError('Require the complete native-probe goal reference')
    path = Path(base) / 'private/goal.xlsx'
    if record['path'] != str(path.resolve()) or type(record['bytes']) is not int:
        raise ValueError('The native goal must be the current revision goal')
    raw = ancestor.reporting._reference_file(path, base)
    if record != {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}:
        raise ValueError('The native goal reference differs from its actual file')
    if record['sha256'] != binding['goal_sha256']:
        raise ValueError('The native goal differs from the diagnostic binding')
    if 'goal_sha256' in native and native['goal_sha256'] != record['sha256']:
        raise ValueError('Conflicting native goal identities')
    return True


def _reporter():
    original = ancestor._reporting
    namespace = {**original, '_current_native_goal': _current_native_goal}
    for name, value in original.items():
        if isinstance(value, FunctionType) and value.__globals__ is original:
            namespace[name] = ancestor._clone(value, namespace)
    # Preserve the already checked full-artifact/compact-context adaptation.
    source = ast.parse(Path(ancestor.reporting.__file__).read_bytes())
    function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == '_reference_review')
    targets = {
        ast.dump(ast.parse("native.get('goal_sha256') == binding['goal_sha256']", mode='eval').body, include_attributes=False): '_current_native_goal(native, binding, base)',
        ast.dump(ast.parse("private.get('reference_review_context') == context", mode='eval').body, include_attributes=False): '_bound_audited_context(evidence, private, context)',
    }
    counts = dict.fromkeys(targets, 0)

    class ExactSeams(ast.NodeTransformer):
        def visit_Compare(self, node):
            key = ast.dump(node, include_attributes=False)
            if key in targets:
                counts[key] += 1
                return ast.copy_location(ast.parse(targets[key], mode='eval').body, node)
            return self.generic_visit(node)

    function = ExactSeams().visit(function)
    if list(counts.values()) != [1, 1]:
        raise ValueError('The exact native-goal or context reporter seams changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), __file__, 'exec'), namespace)
    return namespace


_namespace = _reporter()
generate_report = _namespace['generate_report']
write_reports = _namespace['write_reports']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve earlier reports; use a fresh report directory')
    result = write_reports(args.run_dir, args.output)
    print(json.dumps({'paths': result['paths'], 'yield': result['report']['yield'],
                      'consistency_warnings': result['report']['consistency_warnings']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
