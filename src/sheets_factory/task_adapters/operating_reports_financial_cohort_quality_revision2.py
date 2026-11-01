"""Current causal admissions; three exact design blobs retain opaque ancestry.

This is a scope correction for reference discovery, not a cached admission.
The original full source/task validators still run on every cold admission.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import FunctionType, ModuleType
import weakref

from ..pipelines import operating_reports_financial_cohort_quality as old_pipeline
from . import operating_reports_financial_cohort_quality as old_nodes

ROOT=old_pipeline.ROOT
reference,require=old_pipeline.reference,old_pipeline.require
REGISTRY=ROOT/'config/task_adapters/operating_reports_financial_cohort_quality_revision2_nodes.yaml'
ANCESTORS={str(Path(old_pipeline.__file__)):'2e9e8bbdb9935afbd3251c5350e4dba43ac7a38ba4867d7ba117cc441571a871',
    str(Path(old_nodes.__file__)):'92dcf6813572b7b519dd2210511d16e6227fa913406619df5d11243be49ccc0f'}
DESIGN_LEAVES={str(ROOT/'config'/name):{'path':str(ROOT/'config'/name),'sha256':sha,'bytes':size}
    for name,sha,size in (
        ('operating_reports_financial_cohort_v1.json','a31cf82e6273c17c287dbb842f84904cdffa35a5b0a9835e0b4821ec1ef2c4e4',12613),
        ('operating_reports_200_frozen_design_v1.json','d29f83905e32845a0856a7df0377e2ed6b8cf912869ebcaf059a70d0ef21fd04',190429),
        ('waterfall_transfer_frozen_contract_v1.json','64da7a85b93bda660490ef4c10d7085acc798cffc487475ce44029fcb3d10599',15174))}
for path,sha in ANCESTORS.items():require(reference(path)['sha256']==sha,'The original normal route changed')


class CausalReferences(old_pipeline.References):
    """Only these three exact code/design documents stop recursive discovery."""
    def __init__(self):
        super().__init__();self.design_blob_leaves={}

    def discover(self,record):
        path=record.get('path') if type(record) is dict else None
        if type(path) is str and path in DESIGN_LEAVES:
            require(record==DESIGN_LEAVES[path],'The complete original design-blob binding changed')
            self.check(record);self.design_blob_leaves[path]=deepcopy(record);return
        return super().discover(record)


def setting():
    return {**old_pipeline.setting(),'version':2,'pipeline':reference(__file__),'nodes':reference(__file__),
        'registry':reference(REGISTRY),'dependency_protocol':'current_causal_graph_with_exact_three_complete_design_blobs',
        'complete_design_blobs':deepcopy(DESIGN_LEAVES)}


def _clone(function,namespace):
    value=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    value.__kwdefaults__=deepcopy(function.__kwdefaults__);return value


pipeline=ModuleType(__name__+'._pipeline');_pipe_ns=pipeline.__dict__
_pipe_ns.update({**vars(old_pipeline),'__file__':__file__,'__name__':pipeline.__name__,
    'References':CausalReferences,'REGISTRY':REGISTRY,'_LIVE':weakref.WeakSet(),'setting':setting})
for name,value in vars(old_pipeline).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(old_pipeline):_pipe_ns[name]=_clone(value,_pipe_ns)
_pipe_ns['_configuration']=_clone(old_pipeline._configuration,_pipe_ns)
_pipe_ns['setting']=setting
class FinancialCohortAdmission(old_pipeline.FinancialCohortAdmission):pass


_pipe_ns['FinancialCohortAdmission']=FinancialCohortAdmission
for name in ('__init__','guard'):
    setattr(FinancialCohortAdmission,name,_clone(getattr(old_pipeline.FinancialCohortAdmission,name),_pipe_ns))
_original_init=FinancialCohortAdmission.__init__


def _initialize(self,*args,**kwargs):
    _original_init(self,*args,**kwargs)
    for row in DESIGN_LEAVES.values():self.references.check(row)
    for path in (*ANCESTORS,str(Path(__file__)),str(REGISTRY)):
        row=reference(path);self.references.check(row);self.recipe[row['path']]=row['sha256']
    scope={'protocol':'current_causal_graph_with_exact_three_complete_design_blobs',
        'complete_design_blobs':deepcopy(DESIGN_LEAVES),'whole_blob_SHA_stat_guards':True,
        'embedded_documentary_runtime_references_are_not_current_providers':True,
        'current_full_source_task_and_nine_raw_validation_unchanged':True,
        'current_other_reference_discovery_unchanged':True,'prior_normal_qualification_inherited':False}
    self.evidence['dependency_scope']=scope
    self.proof.update(kind='opaque_financial_cohort_FM_causal_admission_revision2',version=2,dependency_scope=scope)
    self.identity=deepcopy(self.proof);self.evidence_sha=_pipe_ns['_canonical'](self.evidence);self.guard()


FinancialCohortAdmission.__init__=_initialize
_pipe_ns['NativeScopeAdmission']=FinancialCohortAdmission


class NativeQualityFactory(old_pipeline.NativeQualityFactory):pass


for name in ('__init__','load_seeds','run_phase','_claim_targets'):
    setattr(NativeQualityFactory,name,_clone(getattr(old_pipeline.NativeQualityFactory,name),_pipe_ns))
_pipe_ns['NativeQualityFactory']=NativeQualityFactory

_node_ns={**old_nodes._namespace,**vars(old_nodes),'pipeline':pipeline,'REGISTRY':REGISTRY,
    'setting':setting,'admission':_pipe_ns['admission']}
for name in ('context','canonical_plan','independent_evidence','_export'):
    _node_ns[name]=_clone(getattr(old_nodes,name),_node_ns);globals()[name]=_node_ns[name]
for name in ('NormalizeNode','ProfileNode','PlanNode','ConstructNode','InstructionNode','ControlsNode','DiagnoseNode','RepairNode','ExportNode'):
    old=getattr(old_nodes,name);globals()[name]=type(name,(old,),{'__module__':__name__,'execute':_clone(old.execute,_node_ns)})
base,frozen,receipt=old_nodes.base,old_nodes.frozen,old_nodes.receipt
REWARDS,TaskRejected=old_nodes.REWARDS,old_nodes.TaskRejected
validate_reference_export=old_nodes.validate_reference_export
