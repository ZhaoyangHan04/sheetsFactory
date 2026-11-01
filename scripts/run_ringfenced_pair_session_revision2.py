#!/usr/bin/env python3
"""Same frozen pair lifecycle, with exact recorded CP-SAT host artifacts."""
from __future__ import annotations

from contextvars import ContextVar
from copy import deepcopy
import hashlib
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
FROZEN=ROOT/'scripts/run_ringfenced_pair_session.py'
FROZEN_SHA='c600139d90e4d23edcc665de847be2c713d3d342abf104f267aa314b1d0b9f14'
if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:raise ValueError('The frozen complete pair session changed')
# Execute in a private namespace: no old module/global/cache mutation.
_N={'__file__':str(FROZEN),'__name__':'_private_pair_session_host_artifacts_v2'}
exec(compile(FROZEN.read_bytes(),str(FROZEN),'exec'),_N)
c=_N['c'];_CONTEXT=ContextVar('selected_pair_CP_SAT_host_artifacts',default=None)
NAMES={'log_reference':'solver.log','model_reference':'native_model.pbtxt',
    'parameters_reference':'native_model.pbtxt.parameters.pbtxt'}
IMAGE='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'


def _job_aliases(reference_root,phase):
    """Read only retained descriptors, inventories and before/after receipts."""
    terminal_ref=reference_root['solver_receipts'][phase];terminal=c.read(terminal_ref)
    descriptor_ref=reference_root['solver_validations'][phase];descriptor=c.read(descriptor_ref)
    required={'preparation','terminal','host_before','host_after','cleanup','solver_result','runtime_result',
        'checked_optimal','solver','matrix_result_check'}
    c.require(set(descriptor)==required and descriptor['checked_optimal'] is True and descriptor['terminal']==terminal_ref,
        'Use the exact selected completed native-job descriptor')
    prep_ref=descriptor['preparation'];prep=c.read(prep_ref);bundle=Path(prep['bundle'])
    c.require(prep['kind']=='prepared_private_linear_capital_scaled_producer16_solver' and prep['version']==2
        and terminal['kind']=='private_linear_capital_scaled_producer16_solver_execution' and terminal['version']==2
        and terminal['status']=='reference_optimal_checked' and terminal['preparation']==prep_ref
        and terminal['actual_resources_verified'] is True and type(terminal['exit_code'])is int
        and terminal['exit_code']==0 and terminal['oom_killed'] is False
        and all(terminal[k]==descriptor[k] for k in ('solver_result','runtime_result','cleanup','matrix_result_check'))
        and prep['request']['backend']=='cp_sat' and prep['request']['threads']==16
        and prep['resources']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256}
        and prep['image_id']==terminal['image_id']==IMAGE
        and bundle.is_absolute() and bundle==bundle.resolve() and bundle==Path(prep_ref['path']).parent/'job_bundle',
        'The selected original CP16 job identity/resource/bundle changed')
    cid=terminal['container_id'];c.require(type(cid)is str and re.fullmatch('[0-9a-f]{64}',cid),'Use one full owned container identity')
    for record,status in ((descriptor['host_before'],'created'),(descriptor['host_after'],'exited')):
        actual=c.read(record);mounts=actual['Mounts'];state=actual['State']
        c.require(actual['Id']==cid and actual['Image']==IMAGE and actual['NanoCpus']==16*10**9
            and actual['Memory']==32*1024**3 and actual['PidsLimit']==256 and actual['NetworkMode']=='none'
            and len(mounts)==1 and mounts[0]['Type']=='bind' and mounts[0]['RW'] is True
            and mounts[0]['Source']==str(bundle) and mounts[0]['Destination']=='/app'
            and state['Status']==status and state['Running'] is False and state['OOMKilled'] is False
            and type(state['ExitCode'])is int and state['ExitCode']==0,
            'The recorded exact host mount or normal container lifecycle changed')
    solver=c.read(descriptor['solver_result']);inventory=terminal['retained_job_inventory']
    c.require(solver==descriptor['solver'] and solver['checked_optimal'] is True
        and solver['backend']=='ortools_cp_sat' and solver['solver_version']=='9.14.6206'
        and inventory==terminal['complete_job_inventory'] and inventory['solver_result.json']==descriptor['solver_result']
        and descriptor['solver_result']['path']==str(bundle/'solver_result.json'),
        'The complete selected native result or retained host inventory changed')
    rows=[]
    for field,name in NAMES.items():
        local=solver[field];host=inventory[name]
        c.require(set(local)=={'path','sha256','bytes'} and local['path']=='/app/'+name
            and host['path']==str(bundle/name) and type(local['bytes'])is int
            and (local['sha256'],local['bytes'])==(host['sha256'],host['bytes']),
            'A fixed container descriptor differs from its exact inventoried host file')
        c.checked(host)
        rows.append({'container_descriptor':deepcopy(local),'host':deepcopy(host),
            'allowed_parent_JSONs':[deepcopy(descriptor['solver_result']),deepcopy(descriptor_ref)],
            'native_preparation':deepcopy(prep_ref),'native_terminal':deepcopy(terminal_ref),
            'native_validation':deepcopy(descriptor_ref)})
    return rows


def selected_metadata(prospective,pair_id):
    frozen=c.validate_prospective(prospective);rows=[]
    for context in c.pair_contexts(frozen['contexts'],pair_id):
        source=c.read(context['source_manifest']);reference=c.read(context['reference'])
        c.require(source['kind']=='independently_verified_linear_capital_scaled_native_source' and source['version']==1
            and source['status']=='source_verified_not_task_or_difficulty_qualified'
            and source['source_financially_verified'] is True and source['independent_reference']==context['reference']
            and source['workbook']==context['workbook'] and reference['passed'] is True
            and reference['kind']=='linear_capital_scaled_producer16_best_runner_dual_financial_reference'
            and reference['version']==2,'The selected source/reference physical lineage changed')
        for phase in ('best','runner'):rows.extend(_job_aliases(reference,phase))
    return rows


_OldArtifacts=_N['_Artifacts'];_old_add=_OldArtifacts.add
class _Artifacts(_OldArtifacts):
    def __init__(self):
        super().__init__();self._parents=[];self.container_descriptor_bindings=[]
        self._aliases=deepcopy(_CONTEXT.get())
        c.require(self._aliases is not None,'Selected immutable native metadata must precede artifact expansion')
        _old_add(self,c.reference(FROZEN));_old_add(self,c.reference(__file__))

    def add(self,record,*,expand=False):
        path=record.get('path') if isinstance(record,dict) else None
        if type(path)is str and path.startswith('/app/'):
            matches=[r for r in self._aliases if r['container_descriptor']==record
                and self._parents and self._parents[-1] in r['allowed_parent_JSONs']]
            c.require(len(matches)==1,'An unbound or unknown container-local artifact is not a host file')
            row=matches[0];parent=self._parents[-1];_old_add(self,parent,expand=False)
            _old_add(self,row['host'],expand=False)
            binding={**deepcopy(row),'actual_parent_JSON':deepcopy(parent)}
            if binding not in self.container_descriptor_bindings:self.container_descriptor_bindings.append(binding)
            return
        if expand:self._parents.append(deepcopy(record))
        try:return _old_add(self,record,expand=expand)
        finally:
            if expand:self._parents.pop()


_N['_Artifacts']=_Artifacts;_original_mint=_N['_mint'];_original_source=_N['_source']
def _mint(prospective,pair_id,*,parse_cache=None,expected_cache_sha256=None):
    token=_CONTEXT.set(selected_metadata(prospective,pair_id))
    try:return _original_mint(prospective,pair_id,parse_cache=parse_cache,expected_cache_sha256=expected_cache_sha256)
    finally:_CONTEXT.reset(token)


def _source(admission,pilot):
    namespace=_original_source(admission,pilot);old=namespace['recipes']
    namespace['recipes']=lambda:{**old(),str(FROZEN):c.reference(FROZEN),str(Path(__file__).resolve()):c.reference(__file__)}
    return namespace


_N.update(_mint=_mint,_source=_source);_original_prepare=_N['prepare']
def prepare(prospective,output,*,pair_id='R2-01',parse_cache=None,expected_cache_sha256=None):
    admission=_original_prepare(prospective,output,pair_id=pair_id,parse_cache=parse_cache,
        expected_cache_sha256=expected_cache_sha256)
    data=_N['_LIVE'][admission]
    receipt=c.write(Path(output)/'container_descriptor_transport.json',{'kind':'selected_CP_SAT_container_descriptor_transport',
        'version':2,'implementation':c.reference(__file__),'frozen_session':c.reference(FROZEN),
        'bindings':data['artifacts'].container_descriptor_bindings,'does_not_replace_genuine_cold_proofs':True,
        'native_calls':0,'qualified':False})
    data['artifacts'].add(receipt);admission.guard();return admission


_N['prepare']=prepare
execute_prepared=_N['execute_prepared'];validate_completed=_N['validate_completed'];main=_N['main']
if __name__=='__main__':raise SystemExit(main())
