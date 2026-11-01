#!/usr/bin/env python3
"""Review all five fixed pairs in four isolated public/reference calls."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
BASE=ROOT/'scripts/run_associate_bridge_shared_review.py'
BASE_SHA='1d9b46db226014ecab53916ac1b5e5bd1d2a2e21dcaf07eb2a5ba9dd515af003'
ENTRY=ROOT/'scripts/run_ringfenced_replacement_confirmation.py'
ENTRY_SHA='bde7c4963159ddeb5c7e11b3bd62dde992753d9c447b2e61583755dd6feaa04f'
PROFILE=ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
IDENTITIES={
 'prepared_associate_bridge_shared_semantic_review':'prepared_five_ringfenced_pairs_shared_quality_review_v1',
 'actual_associate_bridge_shared_semantic_review':'actual_five_ringfenced_pairs_shared_quality_review_v1',
 'associate_bridge_shared_semantic_review':'five_ringfenced_pairs_shared_quality_review_v1',
 'New associate bridge shared semantic review':'Five ringfenced pairs shared semantic review',
}


def load(path,digest,name):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('A frozen review dependency changed')
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def namespace():
    if hashlib.sha256(BASE.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('The frozen ordinary-review lifecycle changed')
    tree=ast.parse(BASE.read_text());counts=Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in IDENTITIES:
                counts[node.value]+=1;return ast.copy_location(ast.Constant(IDENTITIES[node.value]),node)
            return node
    tree=Adapt().visit(tree)
    if counts!=Counter({k:1 for k in IDENTITIES}):raise ValueError('The four shared-review identity seams changed')
    n={'__name__':'_isolated_five_pair_shared_review','__file__':__file__}
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),n);n['PROFILE']=PROFILE;return n


_N=namespace();ref,read,write,require=(_N[k] for k in ('ref','read','write','require'))


def prompt(mode,role):
    ids=_N['PUBLIC'] if role=='public' else _N['PRIVATE']
    common=f'''Review the five actual {mode} tasks under cases/R2-01 through cases/R2-05.
Each case has two legally ringfenced investment mandates and a group report. Use
its actual instruction.md and input.xlsx. The task is to complete or repair all
existing financial schedules and choose feasible portfolios that maximise their
posted S01 LP NPVs in integer GBP pence. Each common selection must satisfy the
mandate's supplied constraints in every scenario. The two mandates are independent;
the group report consolidates them. Do not invent a coupled optimisation problem.
Inspect all five cases for public assumptions, business coherence, conflicting
interpretations, scope and answer exposure. Review shared construction rules and
record any case-specific issue using its case ID. Do not solve or submit. Do not
ask for a tutorial, explicit formula recipe or the private winning choices.
All twelve checks are enabled across the two roles. Return each assigned ID once.
Keep issues caused by missing final evidence distinct from actual task defects.
Do not start LibreOffice, Harbor, a solver, another model, containers or networking.
Use read-only Python and compact aggregates; do not print entire maps or cell arrays.
The two-decimal, full modified-set primary reward is unchanged. This review does
not establish strongest-model difficulty, actual final oracle/nop or publication.
'''
    if role=='public':
        common+='''Public-only visibility contains exactly the five public inputs and briefs.
Q08 addresses an observable answer-exposure shortcut; use not_applicable if none is
established and note that separate frozen strongest-model confirmation is pending.
'''
    else:
        common+='''Reference visibility additionally provides each exact goal, composition and
source audits, original independent local financial maps and mathematical proofs.
The local unique optima and excluded-winner optima have retained solver certificates
and two independently formed complete integer matrices. The new source audits check
all financial values, formulas, facts and group expectations; inspect the evidence
and reference meaning, not only a passed flag. Independent exact-arithmetic proof
metadata may differ; compare posted business fields rather than JSON byte identity.
Native source stability has three
actual calls for every new pair. Each current input has its own full union audit.
Retained local evidence and new whole-pair evidence have distinct scopes. Neither
copying the oracle nor shared source correctness proves public solvability. Use the
reference_review route; no independent public solver is claimed. Q05, Q11 and Q12
must state missing final actual controls. Do not demand new local optimisers or cold
financial forwards when complete immutable local proofs and new composition checks
are present. Strongest-model attempts and rewards are absent from this review.
'''
    return _N['PROMPT'].read_text()+'\n\n'+common+'\nassigned_check_ids='+_N['json'].dumps(ids)


_N['prompt']=prompt


def _prepare(batches,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh shared-review preparation')
    entry=load(ENTRY,ENTRY_SHA,'_ring_shared_quality_fixed_cohort')
    batchrefs,tasks,retained=entry.cohort_tasks(batches)
    bindings=[];source_rows=[]
    def copy(record,target):
        value=ref(record) if isinstance(record,(str,Path)) else record
        require(ref(value['path'])==value,'A copied review artifact changed')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(value['path'],target)
        actual=ref(target);require((actual['sha256'],actual['bytes'])==(value['sha256'],value['bytes']),'A review copy changed bytes')
    for task in tasks:
        entry.p._N['check_task'](task)
        pair=task['variant_id'][:5];td=Path(task['task_directory']);engineering=read(task['individual_engineering'])
        binding={'task_id':task['task_id'],'mode':task['mode'],'pair_id':pair,'input':ref(td/'environment/input.xlsx'),
            'instruction':ref(td/'instruction.md'),'goal':ref(td/'tests/reference.xlsx'),
            'individual_engineering':task['individual_engineering'],'plan_freeze':task['plan_freeze']}
        bindings.append(binding)
        batch=next(read(v) for v in batchrefs if task['task_id'] in read(v)['selected_task_ids'])
        source=read(batch['source']);sf=read(source['preparation']);certificate=read(sf['certificate'])
        source_rows.append({'pair_id':pair,'source':batch['source'],'preparation':source['preparation'],'certificate':sf['certificate']})
        for role in ('public','reference'):
            workspace=output/'workspaces'/task['mode']/role;case=workspace/'cases'/pair
            copy(binding['input'],case/'input.xlsx');copy(binding['instruction'],case/'instruction.md')
            if role=='reference':
                copy(binding['goal'],case/'reference.xlsx');copy(task['individual_engineering'],case/'engineering.private.json')
                copy(task['plan_freeze'],case/'plan_freeze.private.json');copy(batch['source'],case/'source.private.json')
                copy(source['preparation'],case/'source_preparation.private.json');copy(sf['certificate'],case/'certificate.private.json')
                for key in ('local_composition','report_plan','report_expected','cold_audit'):
                    copy(sf[key],case/(key+'.private.json'))
                for key,value in source['records'].items():
                    copy(value,case/'new_native_evidence'/(key+'.private.json'))
                for donor,mandate in zip(sf['donors'],read(sf['public_contract'])['mandates'],strict=True):
                    local=read(donor['source_manifest']);profile=mandate['local_profile_id']
                    require(Path(profile).name==profile,'Use a safe retained donor ID')
                    donor_dir=workspace/'retained_local_proofs'/profile
                    if donor_dir.exists():continue
                    copy(donor['source_manifest'],donor_dir/'source.private.json');copy(donor['reference'],donor_dir/'reference.private.json')
                    reference=read(donor['reference'])
                    for key in ('model_A','model_B','financial_crosscheck'):
                        if key in reference:copy(reference[key],donor_dir/(key+'.private.json'))
                    for family in ('solver_validations','solver_receipts'):
                        for stage,record in reference.get(family,{}).items():
                            copy(record,donor_dir/(family+'_'+stage+'.private.json'))
                    for path,digest in local.get('source_recipe_sha256',{}).items():
                        path=Path(path)
                        if path.is_relative_to(ROOT/'src/sheets_factory/workbook') and path.suffix=='.py':
                            record=ref(path);require(record['sha256']==digest,'A retained financial implementation changed')
                            target=workspace/'financial_implementations'/path.relative_to(ROOT/'src')
                            if target.exists():require(ref(target)['sha256']==digest,'Two donors disagree on the immutable financial recipe')
                            else:copy(record,target)
                    for key in ('independent_A_expected','independent_B_expected','geometry','stability'):
                        copy(local[key],donor_dir/(key+'.private.json'))
                    for i,value in enumerate(local['financial_audits'],1):copy(value,donor_dir/(f'audit{i}.private.json'))
    inventory={str(p.relative_to(output)):ref(p) for p in sorted((output/'workspaces').rglob('*')) if p.is_file()}
    return write(output/'prepared.json',{'kind':IDENTITIES['prepared_associate_bridge_shared_semantic_review'],'version':1,
        'batch':batchrefs,'source':source_rows,'tasks':bindings,'retained_results_not_reviewed_again':retained,
        'workspace_inventory':inventory,'implementation':ref(__file__),'prompt':ref(_N['PROMPT']),
        'runtime_profile':ref(PROFILE),'model':'gpt-6-sol','reasoning_effort':'high','outer_retries':0,
        'model_calls_permitted':4,'model_calls_started':0,'all_enabled_check_ids':_N['ALL'],
        'all_five_pairs_in_both_role_views':True,'individual_controls_and_business_difficulty_pending':True,
        'whole_family_qualified':False,'frozen_review_base':ref(BASE),'cohort_entry':ref(ENTRY)})


def prepare(batches,output):
    entry=load(ENTRY,ENTRY_SHA,'_ring_review_early_panel')
    with entry.p._N['monitor'](Path(str(Path(output).absolute())+'_preparation_monitor'),'five_pair_review_admission') as audit:
        result=_prepare(batches,output)
        audit.update_run(status='completed',stage='review_prepared',task_count=10)
        return result


def run(prepared):
    require(read(prepared)['cohort_entry']==ref(ENTRY) and read(prepared)['frozen_review_base']==ref(BASE),
        'The frozen review admission changed')
    return _N['run'](prepared)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',action='append',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--run',action='store_true');a=p.parse_args()
    prepared=prepare(a.batch,a.output);print(_N['json'].dumps(prepared),flush=True)
    if a.run:run(prepared['path'])


if __name__=='__main__':main()
