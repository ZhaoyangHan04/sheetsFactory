"""Live admission for the unchanged C00 debugging material, without inherited QA."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType
import weakref

from . import heterogeneous_native_quality as base
from .linear_capital_quality import References, ROOT, reference, require

SETTING='operating_reports_200_debug_quality'
REGISTRY=ROOT/'config/task_adapters/operating_reports_200_debug_quality_nodes.yaml'
CONFIG=ROOT/'config/pipelines/operating_reports_200_debug_quality_v1.yaml'
PROFILE=base.PROFILE
BOUNDARY=ROOT/'scripts/validate_operating_reports_200_tasks_revision2.py'
BOUNDARY_SHA='9b09e434e0cbe0dfbb7b97d825bb8b457167558fc8f72be50234a2a9010763ee'
BASE_SHA='ac87f3544c1e14f42827b93e895e59015554d93fc6c59b054f54084beeff1b86'
NORMAL_SOURCE_KIND='fixed_operating_reports_C00_actual_debugging_view'
SPECIFICATION_SHA='4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
TERMINAL_SHA='fba1c365aeead7902953dd1b8c6877ece8687fd35e757ec3e5286a53e3cf67aa'
DEV_PROBE=ROOT/'outputs/difficulty/operating-reports-200-first-development-v6-revision2-20261031T224700Z/prepared/probe_manifest.json'
DEV_PROBE_SHA='f66c469070426d9c80058aade5836c7546e1b577d334b796bb4ccb2675f5b01d'
FIRST_MATERIAL='188da52442f26097d2a60b63ad47989df3b82b9347c9a8648208c0f9cf8c5166'
SOURCE_SHA='beee954067fa061616a65b045ff176bc3e052726931f5788c93ea71deb032fca'
LINEAGE_SHA='66fb3a8baaff2752835720a96c48c66a631812bacc6bfe46dd143f3041fc5729'
PLAN_SHA='f5ecfde9df384df7215d15901aaacdd15d4c4fee2685a2bfb312c1cd8b99c289'
IMPACT_SHA='28011e89b3123ac87ffb7fa18cf67b7d87222cfbb4839ddbbb26f4f4e3f0e8c1'
INPUT_SHA='1b11d49cc0046472a8813da2ac83f51a425f7c356b43515d6d9c3565ef2605e0'
GOAL_SHA='5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'
BUSINESS_SHA='4568f6f210af964e46949158f0d0ae96093abb6ea3c581772117577852787c5d'
INSTRUCTION_SHA='9d7d8838a04d16f9d25302d297bb467201376994864b820c5fef72371cbb71d6'
IO_APPENDIX=b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
REWARDS={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
FAMILIES={name:50 for name in ('associate_sign','ratio_as_change','money_scale','wrong_reference_quarter')}
_LIVE=weakref.WeakSet()


def _canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def setting():
    return {'version':1,'scope':'fixed_C00_complete_debugging_business_outputs',
        'pipeline':reference(__file__),'nodes':reference(ROOT/'src/sheets_factory/task_adapters/operating_reports_200_debug_quality.py'),
        'registry':reference(REGISTRY),'runtime_profile':reference(PROFILE),'actual_task_boundary':reference(BOUNDARY)}


def boundary():
    require(reference(BOUNDARY)['sha256']==BOUNDARY_SHA,'The exact C00 revised task8 validator changed')
    loader=importlib.util.spec_from_file_location('_C00_debug_normal_task8',BOUNDARY)
    helper=importlib.util.module_from_spec(loader);loader.loader.exec_module(helper);return helper


def _scope(refs,actual_ref,actual,prepared,development_ref,development,lineage):
    """Keep current interpreted task/source refs and consumed historical leaves."""
    refs.check(actual_ref);refs.walk(actual);refs.walk(prepared);refs.walk(lineage)
    interpreted={key:prepared[key] for key in ('definition','source_definition','DBG_definition','expected','bindings',
        'specification','candidate_preparation','source_manifest','source_preparation','task_fault_lineage')}
    interpreted.update({key:lineage[key] for key in ('fault_design','revised_view_plans','pure_design_proof')})
    refs.walk(interpreted)
    candidate=refs.read(prepared['candidate_preparation']);refs.walk(candidate)
    for key in ('retained_A','retained_B','raw_generation','emission_receipt'):
        require(key in candidate,'Keep the entire original independent financial/raw ancestry');refs.check(candidate[key])
    refs.check(development_ref)
    consumed={key:development[key] for key in ('input','goal','original_instruction','rendered_instruction')};refs.walk(consumed)
    return {'policy':'current_interpreted_artifacts_and_direct_leaves_only','version':1,
        'interpreted_artifacts':interpreted,'historical_snapshot':development_ref,
        'historical_snapshot_is_current_code_inventory':False,'consumed_historical_material':consumed,
        'all_current_task_recipe_files_checked':True,'historical_global_selection_code_reinterpreted':False}


class OperatingReportsDebugAdmission:
    def __init__(self,validation_terminal):
        self.references=References();self.helper=boundary()
        actual_ref=reference(validation_terminal['path'] if isinstance(validation_terminal,dict) else validation_terminal)
        if isinstance(validation_terminal,dict):self.references.check(validation_terminal)
        require(actual_ref['sha256']==TERMINAL_SHA,'Select the one retained C00 task8 revision2 terminal')
        actual=self.helper.validate_completed(actual_ref)
        require(actual['kind']=='complete_fixed_operating_reports_200_task_engineering_revision2' and actual['version']==1
            and actual['passed'] is True and actual.get('failure') is None
            and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==8
            and actual['source_LO_calls_reused']==3 and actual['task_fault_lineage']['sha256']==LINEAGE_SHA
            and actual['normal_all12_QA_passed'] is actual['qualified'] is False,
            'Only genuine complete eight-call C00 engineering enters normal debugging quality')
        prepared=self.helper.read(actual['preparation']);lineage=self.helper.read(prepared['task_fault_lineage'])
        require(prepared['kind']=='prepared_fixed_operating_reports_200_task_engineering_revision2' and prepared['version']==1
            and prepared['mode_order']==['financial_modeling','debugging'] and prepared['financial_target_count']==62322
            and prepared['independent_business_field_count']==93510 and prepared['DBG_formula_root_count']==200
            and prepared['task_fault_lineage']==actual['task_fault_lineage']
            and prepared['source_manifest']['sha256']==SOURCE_SHA
            and lineage['revised_view_plans']['sha256']==PLAN_SHA and lineage['pure_design_proof']['sha256']==IMPACT_SHA
            and self.helper.source.schema.canonical_sha256(self.helper.read(prepared['specification']))==SPECIFICATION_SHA,
            'The exact C00 independent business scope, revised fault plan or source changed')
        require(set(actual['records']['modes'])=={'financial_modeling','debugging'},'Keep the genuine paired task8 provenance')
        material=actual['records']['modes']['debugging']
        require(material['complete_D_count']==18240 and material['controls']==REWARDS
            and material['goal']==prepared['genuine_goal'] and actual['source_manifest']==prepared['source_manifest']
            and material['input']['sha256']==INPUT_SHA and material['goal']['sha256']==GOAL_SHA
            and material['instruction']['sha256']==BUSINESS_SHA and material['instruction']['bytes']==411
            and prepared['runtime_profile']==reference(PROFILE),'The original C00 bytes, full D or five controls changed')
        dev_ref=reference(DEV_PROBE);require(dev_ref['sha256']==DEV_PROBE_SHA,'The spent paired development snapshot changed')
        development=self.helper.read(dev_ref)['modes']['debugging']
        business=self.references.check(material['instruction']).read_bytes()
        rendered=self.references.check(development['rendered_instruction']).read_bytes()
        require(development['input']==material['input'] and development['goal']==material['goal']
            and development['original_instruction']['sha256']==material['instruction']['sha256']
            and development['original_instruction']['bytes']==material['instruction']['bytes']
            and development['material_task_version']['sha256']==FIRST_MATERIAL
            and development['rendered_instruction']['sha256']==INSTRUCTION_SHA
            and rendered==business+IO_APPENDIX and len(rendered)==502,
            'Preserve the exact original C00 input, goal and 411+91-byte brief')
        plan=self.helper.read(lineage['revised_view_plans']);impact=self.helper.read(lineage['pure_design_proof'])
        faults=plan['DBG_faults'];witnesses=impact['witnesses'];definition=self.helper.read(prepared['definition'])
        roots=[row['sheet']+'!'+row['cell'] for row in faults.values()]
        require(len(faults)==len(witnesses)==len(set(roots))==200 and set(roots)==set(definition['DBG_root_points'])
            and set(faults)=={row['key'] for row in witnesses}
            and Counter(row['family'] for row in faults.values())==FAMILIES
            and Counter(row['family'] for row in witnesses)==FAMILIES
            and impact['passed'] is True and impact['total_roots_primary_impact_proved']==200
            and impact['all93510_original_A_B_points_unchanged'] is True
            and impact['healthy_source_formulas_and_values_unchanged'] is True
            and impact['public_facts_and_policies_unchanged'] is True
            and all(row['expected_primary']['value']!=row['wrong_root_primary'] for row in witnesses),
            'All200 distinct independently nonzero roots and four complete families are required')
        full=self.helper.read(material['full_D_controls']['nop'])['comparison']
        labels=full['missing_changes']
        require(full['reward']==0 and full['expected_change_count']==18240 and full['actual_change_count']==0
            and len(labels)==len(set(labels))==18240 and not full['extra_changes'] and set(roots)<=set(labels),
            'Keep the entire actual18240 changed-value closure, including200 roots')
        self.recipe={}
        for path,row in self.helper.recipes().items():self.references.check(row);self.recipe[path]=row['sha256']
        for path in (BOUNDARY,Path(__file__),Path(base.__file__)):
            row=reference(path);self.references.check(row);self.recipe[row['path']]=row['sha256']
        scope=_scope(self.references,actual_ref,actual,prepared,dev_ref,development,lineage)
        self.evidence={'actual_ref':actual_ref,'actual':actual,'preparation':prepared,'material':material,
            'development_snapshot':dev_ref,'development_material':development,'dependency_scope':scope,
            'lineage':lineage,'plan':plan,'impact':impact,'full_D':sorted(labels)}
        self.proof={'kind':'opaque_operating_reports_C00_debugging_reference_admission','version':1,
            'mode':'debugging','variant_id':'C00','workbook':material['goal'],'input':material['input'],'goal':material['goal'],
            'instruction':development['rendered_instruction'],'original_business_instruction':material['instruction'],
            'actual_validation':actual_ref,'source_manifest':actual['source_manifest'],'specification':prepared['specification'],
            'independent_expected':prepared['expected'],'independent_scope':prepared['expected'],'definition':prepared['definition'],
            'full_D_controls':material['full_D_controls'],'independent_scope_count':93510,'complete_D_count':18240,
            'physical_root_count':200,'task_fault_lineage':prepared['task_fault_lineage'],
            'first_development_material_identity':FIRST_MATERIAL,'runtime_profile':prepared['runtime_profile'],
            'original_dev_and_normal_scores_transferred':False,'qualified':False}
        self.identity=deepcopy(self.proof);self.evidence_sha=_canonical(self.evidence);_LIVE.add(self);self.guard()

    def guard(self):
        require(type(self) is OperatingReportsDebugAdmission and self in _LIVE and self.proof==self.identity,
            'A live exact C00 debugging opaque admission is required')
        self.references.guard()
        require(_canonical(self.evidence)==self.evidence_sha,'The admitted C00 evidence changed in memory')
        current={path:row['sha256'] for path,row in self.helper.recipes().items()}
        require(all(current.get(path,reference(path)['sha256'])==digest for path,digest in self.recipe.items()),
            'The genuine current task/source/normal recipe changed')
        return deepcopy(self.proof)


NativeScopeAdmission=OperatingReportsDebugAdmission


def admission(value):
    require(type(value) is OperatingReportsDebugAdmission and value in _LIVE,
        'JSON, fabricated objects and other task families cannot admit C00 debugging')
    return value.guard()


def validate_seed(seed,admissions):
    require(seed.get('source_kind')==NORMAL_SOURCE_KIND and seed.get('variant')==0 and seed.get('modes')==['debugging'],
        'Only the original exact C00 debugging view is selected')
    source=reference(seed['local_path']);proof=admission(admissions.get((source['sha256'],'debugging')))
    require(seed['sha256']==source['sha256'] and proof['workbook']==source
        and seed['finance_evidence']['scoped_task_admissions']['debugging']==proof,
        'The seed differs from its genuine current C00 debugging proof')


require(reference(base.__file__)['sha256']==BASE_SHA,'The frozen generic normal lifecycle changed')
_namespace={**vars(base),**globals()}
_configuration=FunctionType(base.validate_configuration.__code__,_namespace,'validate_configuration')


def validate_configuration(config):
    profile=_configuration(config)
    require(config['agents']['model']=='gpt-6-sol' and config['agents']['reasoning_effort']=='high'
        and config['run']['targets']=={'financial_modeling':0,'debugging':1}
        and config['run']['max_sources']==config['run']['max_parallel_sources']==1,
        'Keep one fixed C00 debugging review with the ordinary quality model')
    return profile


class NativeQualityFactory(base.NativeQualityFactory):pass


_namespace.update(globals())
for name in ('__init__','load_seeds','run_phase','_claim_targets'):
    old=getattr(base.NativeQualityFactory,name)
    new=FunctionType(old.__code__,_namespace,old.__name__,old.__defaults__,old.__closure__)
    new.__kwdefaults__=deepcopy(old.__kwdefaults__);setattr(NativeQualityFactory,name,new)
