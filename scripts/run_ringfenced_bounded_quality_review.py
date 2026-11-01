#!/usr/bin/env python3
"""Review hash-bound policy projections and exhaustive program evidence."""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from openpyxl import load_workbook
BASE=ROOT/'scripts/run_associate_bridge_shared_review.py'
BASE_SHA='1d9b46db226014ecab53916ac1b5e5bd1d2a2e21dcaf07eb2a5ba9dd515af003'
PRIOR=ROOT/'scripts/run_ringfenced_shared_quality_review.py'
PRIOR_SHA='ffd81d0d48ba76c6d4ec699e0b7f05c24b0401c44d9c3f551592a31b099e6d66'
PRIOR_PREPARED=ROOT/'outputs/research/ringfenced_fixed5_shared_quality_actual_20261101T083400Z/prepared.json'
PRIOR_TERMINAL=ROOT/'outputs/research/ringfenced_fixed5_shared_quality_actual_20261101T083400Z/terminal.json'
PRIOR_TERMINAL_SHA='a9d7054d3f6b139afb3d06b16f35d5c9ca361c040fd4ef3c37973bcf7352477c'
PROFILE=ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
KIND='actual_five_ringfenced_pairs_bounded_quality_review_v2'
PREPARED_KIND='prepared_five_ringfenced_pairs_bounded_quality_review_v2'
IDENTITIES={
 'prepared_associate_bridge_shared_semantic_review':PREPARED_KIND,
 'actual_associate_bridge_shared_semantic_review':KIND,
 'associate_bridge_shared_semantic_review':'five_ringfenced_pairs_bounded_quality_review_v2',
 'New associate bridge shared semantic review':'Five capital pairs bounded evidence review',
}


def namespace():
    if hashlib.sha256(BASE.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('The original isolated-review lifecycle changed')
    tree=ast.parse(BASE.read_text());counts=Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in IDENTITIES:
                counts[node.value]+=1;return ast.copy_location(ast.Constant(IDENTITIES[node.value]),node)
            return node
    tree=Adapt().visit(tree)
    if counts!=Counter({k:1 for k in IDENTITIES}):raise ValueError('The four bounded-review identity seams changed')
    n={'__name__':'_isolated_bounded_five_pair_review','__file__':__file__}
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),n);n['PROFILE']=PROFILE;return n


_N=namespace();ref,read,write,require=(_N[k] for k in ('ref','read','write','require'))


def module():
    require(ref(PRIOR)['sha256']==PRIOR_SHA,'The original five-pair admission changed')
    s=importlib.util.spec_from_file_location('_bounded_review_previous_material_admission',PRIOR)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def projection(path,*,reference=False):
    """Copy actual bounded cell values/definitions; never invent assumptions."""
    before=ref(path);wb=load_workbook(path,read_only=True,data_only=reference,keep_links=False)
    sections={};categories=Counter()
    ranges={'ContractNotes':(400,16),'Projects':(5,40),'Scenarios':(5,80),'ResourceUse':(4,16),
            'Limits':(5,16),'Sites':(4,8),'Prerequisites':(4,8),'Portfolio':(5,6),'P001':(45,12),'Group reporting':(10,12)}
    try:
        for name in wb.sheetnames:
            suffix=name.split(' - ',1)[-1];categories['candidate' if re.fullmatch(r'P\d{3}',suffix) else suffix]+=1
            if suffix not in ranges:continue
            rows,cols=ranges[suffix];sheet=wb[name]
            if reference and suffix=='P001':rows,cols=120,18
            require(suffix!='ContractNotes' or sheet.max_row<=rows and sheet.max_column<=cols,
                'The public policy projection must include the complete policy sheet')
            cells=[{'cell':c.coordinate,'type':c.data_type,'value':c.value} for row in sheet.iter_rows(max_row=rows,max_col=cols) for c in row if c.value is not None]
            # JSON must represent supplied dates without changing their meaning.
            for c in cells:
                if hasattr(c['value'],'isoformat'):c['value']=c['value'].isoformat()
            sections[name]={'cells':cells,'max_row':sheet.max_row,'max_column':sheet.max_column,
                'full_policy_sheet':suffix=='ContractNotes','sample_rows':rows,'sample_columns':cols}
        result={'workbook':{'sha256':before['sha256'],'bytes':before['bytes']},'sheet_count':len(wb.sheetnames),
            'sheet_names_sha256':hashlib.sha256(json.dumps(wb.sheetnames,ensure_ascii=False).encode()).hexdigest(),
            'sheet_categories':dict(categories),'sections':sections,'visibility':'reference_cached_values' if reference else 'public_input_definitions',
            'coverage':'All policy notes; bounded labelled examples elsewhere. Exhaustive cell checks are separate program evidence.'}
    finally:wb.close()
    require(ref(path)==before,'The projected original workbook changed')
    return result


def prompt(mode,role):
    ids=_N['PUBLIC'] if role=='public' else _N['PRIVATE']
    text=f'''Review the actual {mode} cases R2-01 through R2-05 using packet.json.
The packet copies every public policy-note cell from each actual input and provides
labelled schema examples from all five cases. It does not supply an alternative
business contract. Other ranges are explicitly bounded examples, not full tables.
Do not request a full-cell rescan: immutable exhaustive financial, formula, fact,
structure and source-stability checks are separately recorded by the program.
Read all policy notes and briefs, then inspect the bounded example sections as
needed. Use Python to read selected JSON keys and compact aggregates; do not print
the whole packet or entire maps. This is a semantic evidence review, not a solving
attempt. Do not start a solver, LibreOffice, Harbor, another model, containers or
networking. Do not modify data or submit a workbook.
Each case has two ringfenced 360-project investment mandates and one group report.
The common portfolio in each mandate maximises posted S01 LP NPVs under every
scenario's supplied constraints. Amounts are integer GBP pence. Review assumptions,
business coherence, public recoverability, requested scope and answer exposure.
Report a concrete contradiction or missing required business input. Distinguish
ordinary financial conventions from extra tutorial instructions. Record any
case-specific issue using its case ID and packet cell coordinates.
All twelve checks remain assigned across public/reference roles. Every assigned ID
must appear exactly once. Do not treat the previous incomplete review as a task
defect or as a positive finding. Its calls and unknown usage are retained separately.
'''
    if role=='public':
        text+='''Public-only packet contains only public input definitions and actual briefs.
No reference, expected financial values, private winner or strongest-model result is
provided. Q08 addresses an observable answer-exposure shortcut; use not_applicable
when none is established and note that independent frozen difficulty is separate.
'''
    else:
        text+='''Reference packet additionally contains cached healthy examples, exhaustive new
source/input audits, exact best/runner composition certificates and original complete
A/B proof identities. financial_implementations/ contains the independent business
calculations. Inspect the policy-to-calculation consistency without recomputing every
cell. Different arithmetic proof metadata does not imply different business values.
Q10 can use all three new native source audits and complete raw/typed stability.
Use reference_review; no independent public solver is claimed. Actual final-root
oracle/nop and the strongest-model confirmation are pending and absent here.
Q05/Q11/Q12 must explicitly retain missing final evidence as unknown. The downstream
join will use actual controls rather than inheriting an executed pass from this call.
'''
    return _N['PROMPT'].read_text()+'\n\n'+text+'\nassigned_check_ids='+json.dumps(ids)


_N['prompt']=prompt


def previous_material(previous):
    dispatch=read(previous['dispatch'])
    require(dispatch['prepared']==ref(PRIOR_PREPARED),
        'The original dispatched material preparation changed')
    return read(PRIOR_PREPARED)


def prepare(output):
    out=Path(output).absolute();require(out==out.resolve() and not out.exists(),'Use a fresh bounded-review namespace')
    prior=module();entry=prior.load(prior.ENTRY,prior.ENTRY_SHA,'_bounded_review_fixed_cohort')
    with entry.p._N['monitor'](Path(str(out)+'_preparation_monitor'),'bounded_policy_projection') as audit:
        require(ref(PRIOR_TERMINAL)['sha256']==PRIOR_TERMINAL_SHA,'The original incomplete review changed')
        previous=read(PRIOR_TERMINAL);old=previous_material(previous)
        require(previous['shared_semantic_passed'] is False and len(previous['failures'])==4
            and not previous['review_results'] and old['implementation']==ref(PRIOR),
            'This recovery cannot replace a completed valid review judgment')
        batchrefs,tasks,retained=entry.cohort_tasks(old['batch'])
        require({t['task_id'] for t in tasks}=={t['task_id'] for t in old['tasks']},'The fixed five cases changed')
        source_by_pair={r['pair_id']:r for r in old['source']};packets={}
        for mode in _N['MODES']:
            public=[];private=[]
            for task in [t for t in old['tasks'] if t['mode']==mode]:
                pair=task['pair_id'];public.append({'case_id':pair,'task_id':task['task_id'],
                    'instruction':Path(task['instruction']['path']).read_text(),
                    'public_projection':projection(task['input']['path'])})
                require(ref(task['instruction']['path'])==task['instruction'] and ref(task['input']['path'])==task['input'],
                    'An actual public input or brief changed')
                source=read(source_by_pair[pair]['source']);sf=read(source['preparation']);eng=read(task['individual_engineering'])
                eng={k:v for k,v in eng.items() if k!='complete_primary_difference'}
                private.append({'case_id':pair,'reference_projection':projection(task['goal']['path'],reference=True),
                    'source':source_by_pair[pair]['source'],'certificate':read(sf['certificate']),
                    'source_audits':{k:read(v) for k,v in source['records'].items()},'individual_input_audit':eng})
                require(ref(task['goal']['path'])==task['goal'],'An exact healthy reference changed')
                audit.update_run(stage='bounded_policy_projection',current_case=pair,current_mode=mode);audit.export()
            for role in ('public','reference'):
                workspace=out/'workspaces'/mode/role;payload={'mode':mode,'public_cases':public,
                    'projection_method':ref(__file__),'no_strongest_model_results_provided':True}
                if role=='reference':
                    payload['reference_cases']=private
                    for name,record in old['workspace_inventory'].items():
                        marker='workspaces/'+mode+'/reference/financial_implementations/'
                        if name.startswith(marker) and Path(name).name in ('candidate_a.py','ledger.py','spec.py'):
                            value=Path(record['path']);require(ref(value)==record,'An independent financial implementation changed')
                            target=workspace/'financial_implementations'/Path(name).relative_to(marker)
                            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value.read_bytes())
                packets[mode+'/'+role]=write(workspace/'packet.json',payload)
        inventory={str(p.relative_to(out)):ref(p) for p in sorted((out/'workspaces').rglob('*')) if p.is_file()}
        result=write(out/'prepared.json',{'kind':PREPARED_KIND,'version':2,'tasks':old['tasks'],'source':old['source'],
            'batch':batchrefs,'workspace_inventory':inventory,'implementation':ref(__file__),'prompt':ref(_N['PROMPT']),
            'runtime_profile':ref(PROFILE),'model':'gpt-6-sol','reasoning_effort':'high','outer_retries':0,
            'model_calls_permitted':4,'model_calls_started':0,'all_enabled_check_ids':_N['ALL'],
            'all_five_pairs_in_both_role_views':True,'bounded_packets':packets,'prior_incomplete_review':ref(PRIOR_TERMINAL),
            'prior_preparation':ref(PRIOR_PREPARED),'incomplete_review_calls_preserved':4,'previous_valid_judgments_replaced':False,
            'independent_public_solver_executed':False,'whole_family_qualified':False,'frozen_review_base':ref(BASE),
            'original_five_pair_admission':ref(PRIOR),'cohort_entry':ref(prior.ENTRY)})
        audit.update_run(status='completed',stage='bounded_review_prepared');return result


def run(prepared):
    p=read(prepared);require(p['kind']==PREPARED_KIND and p['previous_valid_judgments_replaced'] is False
        and p['original_five_pair_admission']==ref(PRIOR) and p['prior_incomplete_review']==ref(PRIOR_TERMINAL),
        'The bounded recovery dispatch or preserved incomplete review changed')
    return _N['run'](prepared)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run',action='store_true');a=p.parse_args()
    prepared=prepare(a.output);print(json.dumps(prepared),flush=True)
    if a.run:run(prepared['path'])


if __name__=='__main__':main()
