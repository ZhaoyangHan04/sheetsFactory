"""Live admission for the fixed SG4000 debugging material, without prior QA."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType
import weakref

from . import heterogeneous_native_quality as base
from .linear_capital_quality import References, ROOT, reference, require

SETTING = 'operating_reports_debug_classes_quality'
REGISTRY = ROOT/'config/task_adapters/operating_reports_debug_classes_quality_nodes.yaml'
CONFIG = ROOT/'config/pipelines/operating_reports_debug_classes_quality_v1.yaml'
PROFILE = base.PROFILE
BOUNDARY = ROOT/'scripts/validate_operating_reports_debug_classes_tasks.py'
BOUNDARY_SHA = '9021c1613f41efb13be3f300016886eed2cbd41a76e07a20015cb6efb9325f09'
BASE_SHA = 'ac87f3544c1e14f42827b93e895e59015554d93fc6c59b054f54084beeff1b86'
NORMAL_SOURCE_KIND = 'fixed_operating_reports_SG4000_actual_debugging_view'
SPECIFICATION_SHA = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
TERMINAL_SHA = '0fb7ae14553b56d588012ac96c30e4b41d8b3eb37494240f213f842df0e24116'
DEV_PROBE = ROOT/'outputs/difficulty/operating_reports_debug_SG4000_first_development_v6_20261101T023000Z/prepared/probe_manifest.json'
DEV_PROBE_SHA = '0b7c9932d17bc15bdf403302b16d5b60d6d6a48791c68de5bbf632fd17dcb644'
FIRST_MATERIAL = 'b8f2c49e2b17693e19278612d0dc02f6a2a4f0897a9533ec6473c44c05d4ff85'
ENVELOPE_SHA = 'de584267929f5d9f3d7abd71efb566a97b69aa191f7814266f6fd7a6eee5b95b'
PLAN_SHA = '0e64c7c9f86c804f4a99f02d86118e548bddb1db0af8b85c08709e69cc57384c'
IMPACT_SHA = '40dbcae1c1f28b775422ac8e37ad10ae9f56c04fa5df3605cc97a09713e72c1c'
SOURCE_SHA = 'beee954067fa061616a65b045ff176bc3e052726931f5788c93ea71deb032fca'
INPUT_SHA = '705b43e8607bb56fd1890a43836ac377395c600f03632f1f3ab1fa8eb513c65b'
GOAL_SHA = '5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'
BUSINESS_SHA = '4568f6f210af964e46949158f0d0ae96093abb6ea3c581772117577852787c5d'
INSTRUCTION_SHA = '9d7d8838a04d16f9d25302d297bb467201376994864b820c5fef72371cbb71d6'
IO_APPENDIX = b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
REWARDS = {'oracle':1, 'nop':0, 'equivalent':1, 'missed_root':0, 'extra_change':0}
_LIVE = weakref.WeakSet()


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def setting():
    return {'version':1, 'scope':'fixed_SG4000_complete_debugging_business_outputs',
        'pipeline':reference(__file__), 'nodes':reference(ROOT/'src/sheets_factory/task_adapters/operating_reports_debug_classes_quality.py'),
        'registry':reference(REGISTRY), 'runtime_profile':reference(PROFILE), 'actual_task_boundary':reference(BOUNDARY)}


def boundary():
    require(reference(BOUNDARY)['sha256']==BOUNDARY_SHA, 'The exact SG4000 task5 validator changed')
    loader=importlib.util.spec_from_file_location('_SG4000_normal_task5', BOUNDARY)
    helper=importlib.util.module_from_spec(loader);loader.loader.exec_module(helper);return helper


def _scope(refs, actual_ref, actual, prepared, development_ref, development):
    """Bind interpreted current artifacts; historical envelopes remain byte witnesses.

    walk checks direct REF leaves, not JSON bodies recursively. The genuine task
    validator already replays its complete current source/task proof. Historical
    global selections inside the spent snapshot are not current code providers.
    """
    refs.check(actual_ref);refs.walk(actual);refs.walk(prepared)
    interpreted={key:prepared[key] for key in ('definition','source_definition','expected','bindings','specification',
        'candidate_preparation','source_manifest','source_preparation','variant_envelope')}
    interpreted.update(prepared['variant_plans'])
    for row in interpreted.values():refs.check(row)
    candidate=refs.read(prepared['candidate_preparation']);refs.walk(candidate)
    for key in ('retained_A','retained_B','raw_generation','emission_receipt'):
        require(key in candidate, 'The complete original financial/raw ancestry is required')
        refs.check(candidate[key])
    refs.check(development_ref)
    consumed={key:development[key] for key in ('input','goal','original_instruction','rendered_instruction')}
    refs.walk(consumed)
    return {'policy':'current_interpreted_artifacts_and_direct_leaves_only', 'version':1,
        'interpreted_artifacts':interpreted, 'historical_snapshot':development_ref,
        'historical_snapshot_is_current_code_inventory':False, 'consumed_historical_material':consumed,
        'all_current_task_recipe_files_checked':True, 'historical_global_selection_code_reinterpreted':False}


class DebugClassesAdmission:
    def __init__(self, validation_terminal):
        self.references=References();self.helper=boundary()
        actual_ref=reference(validation_terminal['path'] if isinstance(validation_terminal,dict) else validation_terminal)
        if isinstance(validation_terminal,dict):self.references.check(validation_terminal)
        require(actual_ref['sha256']==TERMINAL_SHA, 'Select the one retained SG4000 task5 terminal')
        actual=self.helper.validate_completed(actual_ref)
        require(actual['kind']=='complete_operating_reports_200_debug_classes_task_engineering' and actual['version']==1
            and actual['passed'] is True and actual.get('failure') is None
            and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==5
            and actual['normal_all12_QA_passed'] is actual['qualified'] is False,
            'Only genuine complete five-call SG4000 engineering enters normal quality')
        prepared=self.helper.read(actual['preparation'])
        require(prepared['kind']=='prepared_operating_reports_200_debug_classes_task_engineering'
            and prepared['version']==1 and prepared['variant_id']=='SG4000'
            and prepared['mode_order']==['debugging'] and prepared['financial_target_count']==93510
            and prepared['independent_business_field_count']==93510 and prepared['DBG_formula_root_count']==4000
            and prepared['formula_count']==88676 and prepared['report_NA_count']==4834
            and prepared['variant_envelope']['sha256']==ENVELOPE_SHA
            and prepared['variant_plans']['view_plans']['sha256']==PLAN_SHA
            and prepared['variant_plans']['proof']['sha256']==IMPACT_SHA
            and prepared['source_manifest']['sha256']==SOURCE_SHA
            and self.helper.source.schema.canonical_sha256(self.helper.read(prepared['specification']))==SPECIFICATION_SHA,
            'The exact complete SG4000 plan, independent business scope or source changed')
        require(set(actual['records']['modes'])=={'debugging'}, 'This route admits debugging only')
        material=actual['records']['modes']['debugging']
        require(material['complete_D_count']==4000 and material['controls']==REWARDS
            and material['goal']==prepared['genuine_goal'] and actual['source_manifest']==prepared['source_manifest']
            and material['input']['sha256']==INPUT_SHA and material['goal']['sha256']==GOAL_SHA
            and material['instruction']['sha256']==BUSINESS_SHA and material['instruction']['bytes']==411
            and prepared['runtime_profile']==reference(PROFILE), 'The exact task bytes, full D or five controls changed')
        dev_ref=reference(DEV_PROBE)
        require(dev_ref['sha256']==DEV_PROBE_SHA, 'The spent first-development snapshot changed')
        development=self.helper.read(dev_ref)['modes']['debugging']
        business=self.references.check(material['instruction']).read_bytes()
        rendered=self.references.check(development['rendered_instruction']).read_bytes()
        require(development['input']==material['input'] and development['goal']==material['goal']
            and development['original_instruction']==material['instruction']
            and development['material_task_version']['sha256']==FIRST_MATERIAL
            and development['rendered_instruction']['sha256']==INSTRUCTION_SHA
            and rendered==business+IO_APPENDIX and len(rendered)==502,
            'Preserve the original 411-byte brief, 91-byte IO appendix and spent material exactly')
        impact=self.helper.read(prepared['variant_plans']['proof']);plan=self.helper.read(prepared['variant_plans']['view_plans'])
        faults=plan['DBG_faults'];witnesses=impact['witnesses']
        require(len(faults)==len(witnesses)==4000 and len({(r['sheet'],r['cell']) for r in faults.values()})==4000
            and set(faults)=={r['key'] for r in witnesses}
            and impact['roots_by_family']=={'associate_presentation_sign':800,'ratio_as_quarterly_change':3200}
            and impact['all_roots_exact_nonzero_primary_impact'] is True
            and impact['outside_root_formula_dependents']==[] and impact['exact_arithmetic_predicted_D_count']==4000
            and all(r['healthy_primary']!=r['wrong_primary'] for r in witnesses),
            'All 4000 independently covered nonzero roots and complete scope are required')
        self.recipe={}
        for path,row in self.helper.recipes().items():
            self.references.check(row);self.recipe[path]=row['sha256']
        for path in (BOUNDARY,Path(__file__),Path(base.__file__)):
            row=reference(path);self.references.check(row);self.recipe[row['path']]=row['sha256']
        scope=_scope(self.references,actual_ref,actual,prepared,dev_ref,development)
        self.evidence={'actual_ref':actual_ref,'actual':actual,'preparation':prepared,'material':material,
            'development_snapshot':dev_ref,'development_material':development,'dependency_scope':scope,
            'plan':plan,'impact':impact}
        self.proof={'kind':'opaque_operating_reports_SG4000_debugging_reference_admission','version':1,
            'mode':'debugging','variant_id':'SG4000','workbook':material['goal'],'input':material['input'],'goal':material['goal'],
            'instruction':development['rendered_instruction'],'original_business_instruction':material['instruction'],
            'actual_validation':actual_ref,'source_manifest':actual['source_manifest'],'specification':prepared['specification'],
            'independent_expected':prepared['expected'],'independent_scope':prepared['expected'],'definition':prepared['definition'],
            'full_D_controls':material['full_D_controls'],'independent_scope_count':93510,'complete_D_count':4000,
            'variant_envelope':prepared['variant_envelope'],'variant_plans':prepared['variant_plans'],
            'first_development_material_identity':FIRST_MATERIAL,'runtime_profile':prepared['runtime_profile'],
            'original_dev_and_normal_scores_transferred':False,'qualified':False}
        self.identity=deepcopy(self.proof);self.evidence_sha=_canonical(self.evidence);_LIVE.add(self);self.guard()

    def guard(self):
        require(type(self) is DebugClassesAdmission and self in _LIVE and self.proof==self.identity,
            'A live exact SG4000 opaque admission is required')
        self.references.guard()
        require(_canonical(self.evidence)==self.evidence_sha,'The admitted SG4000 evidence changed in memory')
        current={path:row['sha256'] for path,row in self.helper.recipes().items()}
        require(all(current.get(path,reference(path)['sha256'])==digest for path,digest in self.recipe.items()),
            'The current genuine task/source/normal recipe changed')
        return deepcopy(self.proof)


NativeScopeAdmission=DebugClassesAdmission


def admission(value):
    require(type(value) is DebugClassesAdmission and value in _LIVE,
        'JSON, fabricated objects and other task families cannot admit SG4000')
    return value.guard()


def validate_seed(seed, admissions):
    require(seed.get('source_kind')==NORMAL_SOURCE_KIND and seed.get('variant')==0 and seed.get('modes')==['debugging'],
        'Only the exact SG4000 debugging view is selected')
    source=reference(seed['local_path']);proof=admission(admissions.get((source['sha256'],'debugging')))
    require(seed['sha256']==source['sha256'] and proof['workbook']==source
        and seed['finance_evidence']['scoped_task_admissions']['debugging']==proof,
        'The seed differs from its genuine current SG4000 proof')


require(reference(base.__file__)['sha256']==BASE_SHA,'The frozen generic normal lifecycle changed')
_namespace={**vars(base),**globals()}
_configuration=FunctionType(base.validate_configuration.__code__,_namespace,'validate_configuration')


def validate_configuration(config):
    profile=_configuration(config)
    require(config['agents']['model']=='gpt-6-sol' and config['agents']['reasoning_effort']=='high'
        and config['run']['targets']=={'financial_modeling':0,'debugging':1}
        and config['run']['max_sources']==config['run']['max_parallel_sources']==1,
        'Keep one fixed SG4000 debugging review with the ordinary quality model')
    return profile


class NativeQualityFactory(base.NativeQualityFactory):pass


_namespace.update(globals())
for name in ('__init__','load_seeds','run_phase','_claim_targets'):
    old=getattr(base.NativeQualityFactory,name)
    new=FunctionType(old.__code__,_namespace,old.__name__,old.__defaults__,old.__closure__)
    new.__kwdefaults__=deepcopy(old.__kwdefaults__);setattr(NativeQualityFactory,name,new)
