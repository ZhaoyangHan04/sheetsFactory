#!/usr/bin/env python3
"""Source3 revision2: exact rendering provenance, with the original failure retained."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
import importlib.util as _importlib
from pathlib import Path as _Path
import re as _re

_ROOT = _Path(__file__).resolve().parents[1]
_UPSTREAM = _ROOT/'scripts/build_operating_reports_200_source.py'
_UPSTREAM_SHA = '1e8319d0ba6975348b4c188e92a04d2eb2d730c21e9022a1accd885b05406ef1'
_RENDERER = _ROOT/'src/sheets_factory/workbook/operating_reports_200/excel_revision2.py'
_RENDERER_SHA = 'b4fb12d296b5c8b5457fc6d8bbf8a1a412ed0587267beb8e81d996f7e6432e97'
_OLD_FAILURE = {
    'path': str(_ROOT/'outputs/research/operating_reports_200_source3_prepared_20261031T214800Z/prepared/source_manifest.json'),
    'sha256': '153d5b2d5d9c55acf1eca13091d10025fbcc679acd2b7bf6f0491f767e65e306', 'bytes': 6674,
}
_MISMATCHES = [
    {'point':'E057 Glenmere Facilities!M68','expected':{'type':'number','value':'0.05'},'actual':{'type':'number','value':'0.04'}},
    {'point':'E097 Valecrest Analytics!H30','expected':{'type':'number','value':'0.03'},'actual':{'type':'number','value':'0.02'}},
]


def _adapted_ast():
    data = _UPSTREAM.read_bytes()
    if _hashlib.sha256(data).hexdigest() != _UPSTREAM_SHA:
        raise ValueError('The original fixed200 source3 lifecycle changed')
    replacements = {
        'prepared_fixed_operating_reports_200_cold_source': 'prepared_fixed_operating_reports_200_cold_source_revision2',
        'independently_checked_fixed_operating_reports_200_source': 'independently_checked_fixed_operating_reports_200_source_revision2',
        'pure_operating_reports_200_emission': 'pure_operating_reports_200_emission_rendering_v2',
    }
    counts = {key:0 for key in replacements}; counts['main'] = 0
    class Adapt(_ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in replacements:
                counts[node.value] += 1; node.value = replacements[node.value]
            return node
        def visit_If(self,node):
            if _ast.unparse(node.test) == "__name__ == '__main__'":
                counts['main'] += 1; return None
            return self.generic_visit(node)
    tree = Adapt().visit(_ast.parse(data))
    if any(value != 1 for value in counts.values()):
        raise ValueError('The narrow revision2 source identity adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


_source_namespace = {'__name__':'_isolated_fixed200_source_revision2','__file__':__file__}
exec(compile(_adapted_ast(),__file__,'exec'),_source_namespace)
for _name,_value in _source_namespace.items():
    if not _name.startswith('__'): globals().setdefault(_name,_value)
_source_recipes = _source_namespace['recipes']
_original_prepare = _source_namespace['prepare']
_original_validate_prepared = _source_namespace['validate_prepared']
_original_execute = _source_namespace['execute_prepared']
_original_validate_source = _source_namespace['validate_source']
validate_call = _ns['validate_call']
__doc__ = 'Source3 revision2: exact rendering provenance, with the original failure retained.'


def _renderer():
    require(len(_RENDERER_SHA) == 64 and reference(_RENDERER)['sha256'] == _RENDERER_SHA,
            'The final exact finite-decimal renderer is not frozen or changed')
    spec = _importlib.spec_from_file_location('sheets_factory.workbook.operating_reports_200._frozen_source_renderer_revision2',_RENDERER)
    module = _importlib.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def recipes():
    require(reference(_UPSTREAM)['sha256'] == _UPSTREAM_SHA,'The original failed-source implementation changed')
    _renderer()
    return {**_source_recipes(), **{str(path.resolve()):reference(path) for path in (_UPSTREAM,_RENDERER,_Path(__file__))}}


def _old_failure_proof():
    old = read(_OLD_FAILURE)
    require(old['kind'] == 'independently_checked_fixed_operating_reports_200_source' and old['version'] == 1
            and old['passed'] is False and old['qualified'] is False
            and old['actual_LO_calls_started'] == old['actual_LO_calls_completed'] == 1
            and len(old['actual_calls']) == 1 and old['cold_start_is_unseeded'] is True
            and old['specification_sha256'] == SPECIFICATION_SHA256
            and old['failure'] == {'type':'ValueError','message':'Complete independent financial/type/literal audit failed'}
            and old['model_calls'] == old['solver_calls'] == old['Harbor_calls'] == old['task_count'] == old['retry'] == 0,
            'Retain the genuine one-call numerical-rendering failure; it is never admitted as a source')
    prepared = read(old['preparation']); candidate = read(prepared['candidate_manifest']); call = old['actual_calls'][0]
    require(prepared['kind'] == 'prepared_fixed_operating_reports_200_cold_source'
            and prepared['specification'] == old['specification'] and prepared['specification_sha256'] == SPECIFICATION_SHA256
            and call['index'] == 1 and call['role'] == 'source1' and call['completed'] is True
            and call['input'] == prepared['cold_start'] and call['output'] == old['source']
            and read(call['terminal_receipt']) == {key:value for key,value in call.items() if key != 'terminal_receipt'},
            'The original source1 input, output or call chain changed')
    evidence = validate_call(call,call['actual_resource_evidence']['terminal'],prepared)
    require(evidence == call['actual_resource_evidence'],'The original actual source1 resource proof changed')
    report = read(old['records']['source1_audit'])
    require(report['kind'] == 'full_fixed_operating_reports_200_native_audit' and report['passed'] is False
            and report['workbook'] == call['output'] and report['all_financial_fields_checked'] == 93510
            and report['all_derived_values_checked'] == 93510 and report['physical_formulas_checked'] == 88676
            and report['mismatches'] == _MISMATCHES and report['native_errors'] == [],
            'The retained failure must have exactly the two original halfway rendering differences')
    cleanup = read(old['records']['failure_cleanup']); cid = evidence['container_id']
    require(cleanup['all_owned_containers_absent'] is True and cleanup['daemon_reachable'] is True
            and len(cleanup['owned']) == 1 and cleanup['owned'][0]['full_id'] == cid,
            'Retain the complete original owned-container cleanup proof')
    owned = cleanup['owned'][0]
    require(owned['absent'] is True and owned['returncode'] == 1 and not owned['stdout'].strip()
            and _re.fullmatch(r'(?i:(?:error:\s*)?no such (?:object|container):\s*)'+_re.escape(cid),owned['stderr'].strip()) is not None,
            'The original cleanup observation is not an exact full-ID absence')
    return {'failed_source':_OLD_FAILURE,'preparation':old['preparation'],'candidate':prepared['candidate_manifest'],
            'audit':old['records']['source1_audit'],'cleanup':old['records']['failure_cleanup'],
            'actual_resource_evidence':evidence,'base_emission_receipt':candidate['emission_receipt'],
            'base_emission_directory':str(checked(candidate['source']).parent)}


def _rendering_proof(specification,emission,left,right):
    renderer = _renderer(); old = _old_failure_proof(); emission = _Path(emission).absolute()
    public = read(specification); require(schema.canonical_sha256(public) == SPECIFICATION_SHA256,'The fixed200 public facts changed')
    receipt = read(emission/'receipt.json'); proof = read(receipt['rendering_proof'])
    base = receipt['base_emission_receipt']; original = old['base_emission_receipt']
    require(receipt['kind'] == 'pure_operating_reports_200_emission_rendering_v2' and receipt['version'] == 2
            and receipt['matching_growth_formulas'] == 1600 and base['sha256'] == original['sha256']
            and base['bytes'] == original['bytes'] and checked(base).read_bytes() == checked(original).read_bytes(),
            'The new renderer must retain the exact original base emission receipt and all1600 replacements')
    require(proof['kind'] == 'exact_finite_decimal_matching_growth_rendering' and proof['version'] == 2
            and proof['renderer'] == reference(_RENDERER) and proof['specification_sha256'] == SPECIFICATION_SHA256
            and proof['matching_growth_fields'] == 1600 and len(proof['rules']) == 1600
            and proof['public_policy_and_facts_changed'] is False and proof['financial_intermediate_rounding'] is False
            and proof['hidden_epsilon'] is False and proof['native_calculations'] == 0 and proof['actual_D_unknown'] is True,
            'Require the exact public finite-decimal rendering proof, without changed policy or epsilon')
    fresh = renderer.prove(public,read(left),read(right),old['base_emission_directory'],emission)
    require(fresh['kind'] == 'complete_exact_finite_decimal_rendering_equivalence' and fresh['version'] == 2
            and fresh['passed'] is True and fresh['specification_sha256'] == SPECIFICATION_SHA256
            and fresh['matching_growth_exact_and_primary_checked'] == 1600
            and fresh['complete_original_A_B_points_unchanged'] == 93510
            and fresh['all_provided_facts_context_and_NA_unchanged'] is True
            and fresh['all_other_formulas_unchanged'] is True and fresh['original_DBG_fault_definitions_retained'] == 200
            and fresh['original_DBG_roots_primary_impact_proved'] == 200
            and fresh['native_calls'] == 0 and fresh['actual_D_unknown'] is True
            and fresh['original_emission_receipt'] == original and fresh['base_emission_receipt'] == base
            and fresh['rendering_proof'] == receipt['rendering_proof'],
            'The complete pure rendering, context, fault and independent-value proof failed')
    return {'kind':'fixed200_source_revision2_rendering_lineage','version':2,'old_failure':old,
            'renderer':reference(_RENDERER),'emission_receipt':reference(emission/'receipt.json'),
            'rendering_proof':receipt['rendering_proof'],'complete_rendering_equivalence':fresh,
            'new_source_qualified':False,'normal_quality_inherited':False,'actual_LO_calls':0}


def prepare(specification,emission,left,right,output,*,profile=PROFILE):
    output = _Path(output).absolute()
    require(not output.exists(),'Use a fresh revision2 source preparation; retain the original failure')
    lineage = _rendering_proof(specification,emission,left,right)
    preparation = _original_prepare(specification,emission,left,right,output,profile=profile)
    write(output/'revision2_provenance.json',{'kind':'fixed200_source_revision2_preparation_provenance','version':2,
        'preparation':preparation,'lineage':lineage,'original_failed_source':_OLD_FAILURE,
        'renderer':reference(_RENDERER),'old_implementation':reference(_UPSTREAM),'implementation':reference(__file__),
        'does_not_relabel_original_failure':True,'normal_quality_inherited':False})
    validate_prepared(output)
    return preparation


def validate_prepared(output):
    f = _original_validate_prepared(output); candidate = read(f['candidate_manifest'])
    lineage = _rendering_proof(checked(f['specification']),checked(candidate['source']).parent,
                               checked(candidate['retained_A']),checked(candidate['retained_B']))
    provenance = _Path(output)/'revision2_provenance.json'
    require(read(provenance) == {'kind':'fixed200_source_revision2_preparation_provenance','version':2,
        'preparation':reference(_Path(output)/'preparation.json'),'lineage':lineage,'original_failed_source':_OLD_FAILURE,
        'renderer':reference(_RENDERER),'old_implementation':reference(_UPSTREAM),'implementation':reference(__file__),
        'does_not_relabel_original_failure':True,'normal_quality_inherited':False},
        'The exact revision2 rendering or original-failure lineage changed')
    return {**f,'revision2_provenance':reference(provenance)}


def execute_prepared(output): return _original_execute(output)


def validate_source(value): return _original_validate_source(value)


validate_completed = validate_source
for _namespace in (_source_namespace,_ns):
    _namespace.update(recipes=recipes,prepare=prepare,validate_prepared=validate_prepared,
                      execute_prepared=execute_prepared,validate_source=validate_source,validate_completed=validate_source)


def main(argv=None): return _source_namespace['main'](argv)


if __name__ == '__main__': raise SystemExit(main())
