#!/usr/bin/env python3
"""Diagnose saved tax-vintage submissions; only O needs a new native calculation."""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
import re
import sys
from types import FunctionType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.evaluation import business_failure_evidence as original
from sheets_factory.evaluation import business_failure_evidence_revision2 as currencies
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec

BASE = ROOT/'scripts/diagnose_associate_bridge_business_attempts.py'
BASE_SHA = '6deae634290bbd76d571704d70faa8d1bf1a56f6a2b1e0c72d959ec413eacf5d'
CURRENCY_SHA = '5d8bd5e3e7401296da96eeb11d1cecf62ad88fdc360d134894e3df8f6873243a'
SPEC_FILE = Path(spec.__file__)
SPEC_SHA = 'c62468e5a8ab4e2d0329a448599ad86097aa7d91f9f2a5c14c31c65d90f40857'
ADDITIONAL_CORE_FIELDS = {'cash_tax_paid': 'noncash_cashbridge',
    'tax_payable_close': 'rollforward', 'tax_ordinary_after_losses': 'tax',
    'tax_investment_after_losses': 'tax'}
reference, read = original.reference, original._read
require = original._require


def _guard():
    currencies.verify_dependencies()
    for path, digest in ((BASE, BASE_SHA), (Path(currencies.__file__), CURRENCY_SHA), (SPEC_FILE, SPEC_SHA)):
        require(reference(path)['sha256'] == digest, 'A frozen tax diagnosis dependency changed')


def _receipt(record, call, previous):
    """Check all three source calls, including their actual owned resource identity."""
    receipt = read(record)
    require(receipt.get('kind') == 'resource_bound_libreoffice_call'
        and receipt.get('status') == 'completed' and receipt.get('role') == 'source'
        and receipt.get('actual_resources_verified') is True and receipt.get('thread_cap_verified') is True
        and receipt.get('started_at') and receipt.get('finished_at')
        and re.fullmatch(r'[0-9a-f]{64}', receipt.get('container_id', '')),
        'A complete actual native source receipt is required')
    require(receipt['output'] == call['workbook'] and reference(call['workbook']['path']) == call['workbook']
        and reference(receipt['source']['path']) == receipt['source']
        and (previous is None or receipt['source'] == previous), 'The three native source calculations are not chained')
    for name, digest in original.ENGINE_PINS.items():
        require(receipt[name]['sha256'] == digest and reference(receipt[name]['path']) == receipt[name],
                'The native source used another calculation implementation')
    require(receipt.get('actual_resources') == {'cpus_nanoseconds': 2_000_000_000,
        'memory_bytes': 32*1024**3, 'pids_limit': 256}, 'The actual source resource bounds changed')
    for stage in ('before', 'after'):
        cap = receipt.get('thread_cap_'+stage, {})
        require(cap.get('container_id') == receipt['container_id'] and cap.get('values') == ['MAX_CONCURRENCY=2'],
                'The actual source worker identity is incomplete')
    require(receipt['thread_cap_after'].get('exit_code_observed') == '0', 'A source call did not exit normally')
    return receipt


def _source_scope(source):
    """Derive N from the public inventory and every complete independent map."""
    _guard()
    require(source.get('kind') == 'independently_verified_tax_vintage_bridge_business_source_v2'
        and source.get('passed') is True and source.get('case_id') in spec.CASE_IDS,
        'Require the independently checked tax-vintage source family')
    public = spec.validate(read(source['specification']))
    require(public['case_id'] == source['case_id'], 'The source belongs to another public case')
    inventory = list(spec.points(public))
    semantic = {key for key, _ in inventory}
    require(semantic and len(semantic) == len(inventory), 'The public semantic inventory is incomplete or duplicated')
    bindings = read(source['bindings'])
    require(set(bindings['financial']) == semantic, 'Physical bindings omit or add public financial fields')
    for key, binding in bindings['financial'].items():
        require(binding.get('field', key.rsplit('/', 1)[-1]) == key.rsplit('/', 1)[-1]
            and binding.get('entity_id', key.split('/', 1)[0]) == key.split('/', 1)[0],
            'A physical binding relabels its public economic field or entity')
    physical = [b['sheet']+'!'+b['cell'] for b in bindings['financial'].values()]
    require(len(set(physical)) == len(physical), 'Financial fields share a physical cell')
    entity_scales = {e['id']: currencies.UNITS[e['money_unit']] for e in public['bridge']['base']['entities']}
    require(len(entity_scales) == len(public['bridge']['base']['entities']), 'Duplicate public entity identity')
    currencies.complete_money_scales(bindings, entity_scales)
    require(source['recipe'] and reference(SPEC_FILE) in source['recipe'], 'The source did not bind this public vocabulary')
    for record in source['recipe']:
        require(reference(record['path']) == record, 'An actual source recipe changed')
    cohort = read(source['raw_cohort'])
    rows = cohort['cases']
    require(cohort.get('kind') == 'frozen_raw_tax_vintage_bridge_business_cases_v2'
        and cohort.get('fixed_before_financial_oracle_and_model') is True
        and cohort.get('count') == len(rows) == len(spec.CASE_IDS)
        and [r['case_id'] for r in rows] == list(spec.CASE_IDS)
        and cohort.get('spec_implementation') == reference(SPEC_FILE), 'The original fixed eight-case raw contract changed')
    for row in rows:
        read(row['specification'])
    raw_case = next(r for r in rows if r['case_id'] == source['case_id'])
    require(raw_case['specification'] == source['specification']
        and raw_case['canonical_sha256'] == spec.canonical_sha256(public), 'The actual source raw case differs from its frozen contract')
    independent = source['independent_records']
    require(set(independent) == {'A', 'B', 'independent_comparison'}, 'Both complete independent ledgers are required')
    A, B = read(independent['A']), read(independent['B'])
    for value in (A, B):
        require(value.get('kind') == spec.RESULT_KIND
            and value.get('specification_sha256') == spec.canonical_sha256(public), 'An independent ledger belongs to another public source')
        for name in ('economic_exact_values', 'raw_cell_exact_values', 'typed_2dp_values'):
            require(isinstance(value[name], dict) and set(value[name]) == semantic,
                    'An independent ledger does not cover the complete semantic scope: '+name)
        require(value['reconciliation_checks'].get('passed') is True, 'An independent business ledger does not reconcile')
    for name in ('economic_exact_values', 'raw_cell_exact_values', 'typed_2dp_values'):
        require(A[name] == B[name], 'The complete independent ledgers disagree: '+name)
    count = len(semantic)
    comparison = read(independent['independent_comparison'])
    require(source.get('complete_AB_financial_fields') == count and comparison.get('passed') is True
        and comparison.get('full_financial_fields') == count
        and comparison.get('complete_economic_raw_and_primary_values_equal') is True,
        'The retained independent comparison does not cover the derived scope')
    calls = source['actual_LO_calls']
    require(source.get('actual_LO_calls_completed') == len(calls) == 3
        and [c['index'] for c in calls] == [1, 2, 3], 'Require all three original native source calculations')
    previous = None
    for call in calls:
        audit = read(call['audit'])
        require(audit.get('passed') is True and audit.get('all_financial_fields_checked') == count
            and audit.get('unresolved_mismatches') == audit.get('native_errors') == [],
            'An original native source audit does not cover the complete financial scope')
        receipts = call['native_metadata']['actual_resource_receipts']
        require(len(receipts) == 1, 'A source call has an ambiguous actual receipt')
        _receipt(receipts[0], call, previous)
        previous = call['workbook']
    require(source['goal'] == previous, 'The healthy goal is not the third actual source output')
    return count


def _business():
    """Extend affected-field labels without changing thresholds or the primary score."""
    namespace = dict(original.analyze.__globals__)
    namespace.update(CORE_FIELDS={**original.CORE_FIELDS, **ADDITIONAL_CORE_FIELDS}, __file__=__file__)
    analyze = FunctionType(original.analyze.__code__, namespace, original.analyze.__name__, original.analyze.__defaults__)
    analyze.__kwdefaults__ = deepcopy(original.analyze.__kwdefaults__)
    return SimpleNamespace(**{**vars(original), 'analyze': analyze})


def _final_source_guard(source, batch):
    require(read(batch['source']) == source, 'The original source changed during diagnosis')
    return _source_scope(source)


def _namespace():
    _guard()
    counts = Counter()
    replacements = {
        'independently_verified_associate_bridge_business_source_v1': 'independently_verified_tax_vintage_bridge_business_source_v2',
        'associate_bridge_business_spec_v1': 'tax_vintage_bridge_business_spec_v2',
        'fixed_associate_bridge_saved_submission_diagnosis': 'fixed_tax_vintage_saved_submission_diagnosis_v2',
        'complete_associate_bridge_auxiliary_business_diagnosis': 'complete_tax_vintage_auxiliary_business_diagnosis_v2'}
    class Revision(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in replacements:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(replacements[node.value]), node)
            if type(node.value) is int and node.value == 93510:
                counts['scope'] += 1
                return ast.copy_location(ast.Name('_scope_size', ast.Load()), node)
            return node
        def visit_Subscript(self, node):
            node = self.generic_visit(node)
            if isinstance(node.value, ast.Name) and node.value.id == 'public' and isinstance(node.slice, ast.Constant) and node.slice.value == 'base':
                counts['entity_path'] += 1
                node.value = ast.Subscript(ast.Name('public', ast.Load()), ast.Constant('bridge'), ast.Load())
            return node
        def visit_Assign(self, node):
            node = self.generic_visit(node)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == 'source':
                    counts['source_admission'] += 1
                    return [node, ast.Assign([ast.Name('_scope_size', ast.Store())],
                        ast.Call(ast.Name('_source_scope', ast.Load()), [ast.Name('source', ast.Load())], []))]
            return node
        def visit_Expr(self, node):
            node = self.generic_visit(node)
            if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == 'require' and len(node.value.args) == 2
                and isinstance(node.value.args[1], ast.Constant)
                and node.value.args[1].value == 'Entity identities must be unique'):
                counts['aggregate_scales'] += 1
                return [node, ast.Assign([ast.Name('scales', ast.Store())],
                    ast.Call(ast.Name('_complete_money_scales', ast.Load()),
                        [ast.Name('bindings', ast.Load()), ast.Name('scales', ast.Load())], []))]
            if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                and node.value.func.id == 'require' and len(node.value.args) == 2
                and isinstance(node.value.args[1], ast.Constant)
                and node.value.args[1].value == 'The original batch, terminal or diagnosis code changed'):
                counts['final_source_guard'] += 1
                return [ast.Expr(ast.Call(ast.Name('_final_source_guard', ast.Load()),
                    [ast.Name('source', ast.Load()), ast.Name('batch', ast.Load())], [])), node]
            return node
    tree = Revision().visit(ast.parse(BASE.read_text(), filename=str(BASE)))
    expected = Counter({**{name: 1 for name in replacements}, 'scope': 3, 'entity_path': 2,
                        'source_admission': 1, 'aggregate_scales': 1, 'final_source_guard': 1})
    require(counts == expected, 'The exact tax diagnosis adaptation seams changed: '+str(counts))
    namespace = {'__name__': '_tax_vintage_saved_submission_diagnosis', '__file__': __file__,
        '_source_scope': _source_scope, '_final_source_guard': _final_source_guard,
        '_complete_money_scales': currencies.complete_money_scales}
    exec(compile(ast.fix_missing_locations(tree), str(BASE), 'exec'), namespace)
    namespace['business'] = _business()
    original_recipes = namespace['recipes']
    def recipes():
        _guard()
        return [*original_recipes(), reference(BASE), reference(currencies.__file__), reference(SPEC_FILE)]
    namespace['recipes'] = recipes
    return namespace


_N = _namespace()
run, main = _N['run'], _N['main']
if __name__ == '__main__': main()
