"""Live, content-bound FM admissions for the nine frozen new report cases."""
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
from ..workbook.operating_reports_financial_cohort_v1 import schema

SETTING='operating_reports_financial_cohort_quality'
REGISTRY=ROOT/'config/task_adapters/operating_reports_financial_cohort_quality_nodes.yaml'
CONFIG=ROOT/'config/pipelines/operating_reports_financial_cohort_quality_v1.yaml'
PROFILE=base.PROFILE
BOUNDARY=ROOT/'scripts/validate_operating_reports_financial_cohort_tasks.py'
BOUNDARY_SHA='8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91'
NORMAL_SOURCE_KIND='operating_reports_financial_cohort_actual_FM_view'
BASE_SHA='ac87f3544c1e14f42827b93e895e59015554d93fc6c59b054f54084beeff1b86'
IO_APPENDIX=b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
_LIVE=weakref.WeakSet()


def setting():
    return {'version':1,'scope':'complete_independent_financial_cohort_FM_reports',
        'pipeline':reference(__file__),'nodes':reference(ROOT/'src/sheets_factory/task_adapters/operating_reports_financial_cohort_quality.py'),
        'registry':reference(REGISTRY),'runtime_profile':reference(PROFILE),'actual_task_boundary':reference(BOUNDARY),
        'cohort_contract':reference(schema.CONTRACT)}


def boundary():
    require(reference(BOUNDARY)['sha256']==BOUNDARY_SHA,'The genuine FM cohort task5 validator changed')
    loader=importlib.util.spec_from_file_location('_normal_financial_cohort_task5',BOUNDARY)
    helper=importlib.util.module_from_spec(loader);loader.loader.exec_module(helper);return helper


def _canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def _material(artifact_directory,case_id,original,input_ref,goal,specification,*,create):
    directory=Path(artifact_directory).absolute()
    require(directory==directory.resolve() and directory.is_relative_to(ROOT/'outputs'),
        'Normal admission artifacts must remain in a real private output directory')
    folder=directory/case_id;instruction=folder/'instruction.md';material=folder/'material.json'
    business=Path(original['path']).read_bytes()
    require(len(business)==403 and len(IO_APPENDIX)==91,'Keep the exact original business brief and fixed IO appendix')
    rendered=business+IO_APPENDIX
    identity={'version':1,'mode':'financial_modeling','case_id':case_id,'input_sha256':input_ref['sha256'],
        'goal_sha256':goal['sha256'],'instruction_sha256':hashlib.sha256(rendered).hexdigest(),
        'specification_sha256':specification}
    digest=_canonical(identity)
    if create:
        folder.mkdir(parents=True,exist_ok=False)
        with instruction.open('xb') as stream:stream.write(rendered)
    require(instruction.is_file() and instruction.read_bytes()==rendered,'The immutable current rendered business brief changed')
    value={'kind':'immutable_financial_cohort_FM_normal_material','version':1,'case_id':case_id,
        'input':input_ref,'goal':goal,'original_instruction':original,'rendered_instruction':reference(instruction),
        'identity_components':identity,'material_identity':digest,'normal_quality_or_development_score_inherited':False}
    if create:
        with material.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')
    require(material.is_file() and json.loads(material.read_text())==value,'The immutable normal material proof changed')
    return reference(instruction),reference(material),digest


class FinancialCohortAdmission:
    def __init__(self,validation_terminal,*,artifact_directory,create=False):
        self.references=References();self.helper=boundary()
        actual_ref=reference(validation_terminal['path'] if isinstance(validation_terminal,dict) else validation_terminal)
        if isinstance(validation_terminal,dict):self.references.check(validation_terminal)
        actual=self.helper.validate_completed(actual_ref)
        require(actual['kind']=='complete_operating_reports_financial_cohort_FM_task_engineering'
            and actual['version']==1 and actual['passed'] is True
            and actual['actual_LO_calls_started']==actual['actual_LO_calls_completed']==5
            and actual['normal_all12_QA_passed'] is actual['qualified'] is False,
            'Only genuine completed five-call FM cohort engineering enters normal review')
        prepared=self.helper.read(actual['preparation']);public=self.helper.read(prepared['specification']);schema.validate_spec(public)
        case_id=schema.candidate(public['seed'])['candidate_id']
        require(public['dimension_mode']=='production' and prepared['case_id']==case_id
            and prepared['kind']=='prepared_operating_reports_financial_cohort_FM_task_engineering'
            and prepared['mode_order']==['financial_modeling'] and prepared['financial_target_count']==62322
            and prepared['independent_business_field_count']==93510 and prepared['formula_count']==88676
            and prepared['report_NA_count']==4834,'The original frozen raw case or full report scope changed')
        require(set(actual['records']['modes'])=={'financial_modeling'},'No debugging task may enter this FM-only cohort')
        material=actual['records']['modes']['financial_modeling']
        require(material['complete_D_count']==62322 and material['goal']==prepared['genuine_goal']
            and material['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},
            'The exact FM full-D and all five original engineering controls are required')
        require(prepared['runtime_profile']==reference(PROFILE),'The exact task/source runtime profile changed')
        original=self.references.check(material['instruction']);original_ref=reference(original)
        rendered,material_ref,identity=_material(artifact_directory,case_id,original_ref,material['input'],material['goal'],
            schema.canonical_sha256(public),create=create)
        self.recipe={}
        for path,row in self.helper.recipes().items():self.references.check(row);self.recipe[path]=row['sha256']
        for path in (BOUNDARY,Path(__file__),Path(base.__file__),REGISTRY,CONFIG,
            ROOT/'src/sheets_factory/task_adapters/operating_reports_financial_cohort_quality.py'):
            row=reference(path);self.references.check(row);self.recipe[row['path']]=row['sha256']
        self.references.discover(actual_ref)
        for key in ('definition','source_definition','expected','bindings','specification','candidate_preparation','raw_inventory'):
            self.references.check(prepared[key])
        for row in (rendered,material_ref):self.references.check(row)
        self.evidence={'actual_ref':actual_ref,'actual':actual,'preparation':prepared,'material':material,
            'normal_material':material_ref,'case_id':case_id}
        self.proof={'kind':'opaque_operating_reports_financial_cohort_FM_admission','version':1,
            'mode':'financial_modeling','case_id':case_id,'workbook':material['goal'],'input':material['input'],'goal':material['goal'],
            'instruction':rendered,'original_business_instruction':original_ref,'material':material_ref,'material_identity':identity,
            'actual_validation':actual_ref,'source_manifest':actual['source_manifest'],'specification':prepared['specification'],
            'full_nine_raw_inventory':prepared['raw_inventory'],'independent_expected':prepared['expected'],'independent_scope':prepared['expected'],
            'definition':prepared['definition'],'full_D_controls':material['full_D_controls'],'independent_scope_count':93510,
            'forecast_mask_count':62322,'complete_D_count':62322,'runtime_profile':prepared['runtime_profile'],
            'original_dev_and_normal_scores_transferred':False,'qualified':False}
        self.identity=deepcopy(self.proof);self.evidence_sha=_canonical(self.evidence);_LIVE.add(self);self.guard()

    def guard(self):
        require(type(self) is FinancialCohortAdmission and self in _LIVE and self.proof==self.identity,
            'A genuine live exact financial-cohort admission is required')
        self.references.guard();require(_canonical(self.evidence)==self.evidence_sha,'The admitted evidence changed in memory')
        current={path:row['sha256'] for path,row in self.helper.recipes().items()}
        require(all(current.get(path,reference(path)['sha256'])==digest for path,digest in self.recipe.items()),
            'The complete current source/task/normal code recipe changed')
        return deepcopy(self.proof)


NativeScopeAdmission=FinancialCohortAdmission


def admission(value):
    require(type(value) is FinancialCohortAdmission and value in _LIVE,
        'JSON, fabricated admissions and other task families cannot enter this cohort')
    return value.guard()


def validate_seed(seed,admissions):
    require(seed.get('source_kind')==NORMAL_SOURCE_KIND and seed.get('variant')==0
        and seed.get('modes')==['financial_modeling'],'Only one genuine new FM case may enter each source')
    source=reference(seed['local_path']);proof=admission(admissions.get((source['sha256'],'financial_modeling')))
    require(seed['sha256']==source['sha256'] and proof['workbook']==source
        and seed['finance_evidence']['scoped_task_admissions']['financial_modeling']==proof,
        'The seed differs from its current opaque case/source proof')


require(reference(base.__file__)['sha256']==BASE_SHA,'The generic normal factory changed')
_namespace={**vars(base),**globals()}
_configuration=FunctionType(base.validate_configuration.__code__,_namespace,'validate_configuration')


def validate_configuration(config):
    profile=_configuration(config);targets=config['run']['targets']
    require(config['agents']['model']=='gpt-6-sol' and config['agents']['reasoning_effort']=='high'
        and type(targets.get('financial_modeling')) is int and 1<=targets['financial_modeling']<=9
        and targets.get('debugging')==0 and 1<=config['run']['max_parallel_sources']<=2,
        'Keep one through nine fixed new FM cases, at most two sources and the ordinary quality model')
    return profile


class NativeQualityFactory(base.NativeQualityFactory):pass


_namespace.update(globals())
for name in ('__init__','load_seeds','run_phase','_claim_targets'):
    old=getattr(base.NativeQualityFactory,name);new=FunctionType(old.__code__,_namespace,old.__name__,old.__defaults__,old.__closure__)
    new.__kwdefaults__=deepcopy(old.__kwdefaults__);setattr(NativeQualityFactory,name,new)
