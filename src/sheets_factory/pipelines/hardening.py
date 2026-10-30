"""Progressive structural hardening driven by immutable, fully scored measurements.

A contract is planned until actual constructed tasks pass the structural audit.
Cell count and source/prompt retries are never evidence of applied hardening.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import openpyxl
import yaml

from ..workbook.profile import formula_references
from ..workbook.static_references import expand_static_formula, static_formula_text, StaticReferenceError

MODES = ('financial_modeling', 'debugging')
CYCLE_CHECKS = ('cyclic_financing_unique_fixed_point', 'cyclic_financing_endpoint_convergence',
                'cyclic_financing_grid_feasible', 'cyclic_financing_tax_feedback',
                'cyclic_financing_projection_matches')


class HardeningError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, data):
    path=Path(path)
    if path.exists():
        raise HardeningError('Hardening evidence already exists; use a fresh round/run')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')
    return {'path':str(path.resolve()), 'sha256':sha(path)}


def bound_json(proof):
    if not isinstance(proof,dict) or not proof.get('path') or not proof.get('sha256'):
        raise HardeningError('Missing hash-bound evidence')
    path=Path(proof['path'])
    if not path.is_file() or sha(path)!=proof['sha256']:
        raise HardeningError('Evidence hash mismatch: '+str(path))
    return json.loads(path.read_text())


def scored_measurement(path, label=None):
    """A complete one-task pilot is valid directionally; an incomplete cohort is not."""
    path=Path(path); evaluation=json.loads(path.read_text())
    selection=bound_json(evaluation.get('selection_manifest'))
    for record in (evaluation,selection):
        if (record.get('model'),record.get('reasoning_effort'),record.get('timeout_seconds')) != ('gpt-6.1-sol','xhigh',1800):
            raise HardeningError('Hardening requires the strongest model and the unchanged full budget')
        if record.get('n_attempts',1)!=1:
            raise HardeningError('Only valid first attempts can drive hardening')
    if evaluation.get('status')!='completed':
        raise HardeningError('Incomplete/infrastructure measurement cannot drive hardening')
    tasks=selection.get('tasks',[]); attempts=evaluation.get('attempts',[])
    ids=[x.get('task_id') for x in tasks]
    if not ids or len(set(ids))!=len(ids) or set(ids)!=set(selection.get('selected_task_ids',[])):
        raise HardeningError('Invalid frozen cohort')
    if len(attempts)!=len(tasks) or {x.get('task_id') for x in attempts}!=set(ids):
        raise HardeningError('Incomplete scored cohort')
    frozen={x['task_id']:x for x in tasks}; successes=0
    for attempt in attempts:
        if attempt.get('status')!='scored' or type(attempt.get('reward')) not in (int,float) or attempt['reward'] not in (0,1):
            raise HardeningError('Unknown or infrastructure outcomes are not scored failures')
        task=frozen[attempt['task_id']]
        if attempt.get('mode')!=task.get('mode') or attempt.get('task_checksum')!=task.get('task_checksum'):
            raise HardeningError('Scored task differs from frozen cohort')
        if task.get('timeout_seconds',1800)!=1800 or task.get('mode') not in MODES:
            raise HardeningError('Invalid scored task mode or budget')
        if attempt.get('result_file'):
            if not attempt.get('result_sha256') or sha(attempt['result_file'])!=attempt['result_sha256']:
                raise HardeningError('Scored result evidence changed')
        successes+=int(attempt['reward'])
    score=evaluation.get('score',{})
    if (score.get('total_tasks'),score.get('scored_tasks'),score.get('infrastructure_errors')) != (len(tasks),len(tasks),0):
        raise HardeningError('Score counts disagree with frozen scored cohort')
    rate=successes/len(tasks)
    if not isinstance(score.get('overall_pass_at_1'),(int,float)) or not math.isclose(score['overall_pass_at_1'],rate,abs_tol=1e-12):
        raise HardeningError('Pass rate disagrees with binary rewards')
    mode_counts={mode:sum(t['mode']==mode for t in tasks) for mode in MODES}
    return {'evaluation':{'path':str(path.resolve()),'sha256':sha(path)},
            'selection':evaluation['selection_manifest'],'measurement_label':label or evaluation.get('phase'),
            'scope':'full_delivery_cohort' if min(mode_counts.values())>=10 else 'directional_pilot',
            'task_count':len(tasks),'successes':successes,'overall_pass_at_1':rate,
            'mode_counts':mode_counts,'exceeds_threshold':successes*5>len(tasks),
            'cohort_fingerprint':hashlib.sha256(json.dumps(sorted((t['task_id'],t.get('task_checksum'),t.get('revision_hash'),t['mode']) for t in tasks)).encode()).hexdigest(),
            'qualification_inferred':False}


def workbook_inventory(path, *, max_dependency_closure_cells=20000, max_profile_cells=200000,
                       per_formula_reference_cells=5000):
    """Actual scalar financial row families and static formula dependencies."""
    from ..nodes.construction import construction_contract
    construction_contract(config={'construction': {'analysis_limits': {
        'max_dependency_closure_cells': max_dependency_closure_cells,
        'max_profile_cells': max_profile_cells,
        'per_formula_reference_cells': per_formula_reference_cells}}})
    book=openpyxl.load_workbook(path,data_only=False,keep_links=False)
    values=openpyxl.load_workbook(path,data_only=True,keep_links=False)
    families=defaultdict(set);graph={};unsupported={};profile_cells=0
    try:
        for sheet in book:
            for cell in sheet._cells.values():
                if cell.value is not None:
                    profile_cells+=1
                    if profile_cells>max_profile_cells:
                        raise HardeningError('Hardening profile exceeds configured analysis limit')
                if cell.data_type!='f':continue
                key=(sheet.title,cell.coordinate)
                cached=values[sheet.title][cell.coordinate];value=cached.value
                if type(value) in (int,float) and math.isfinite(value) and not cell.is_date and not cached.is_date:
                    families[(sheet.title,cell.row)].add(key)
                try:
                    text=expand_static_formula(static_formula_text(cell),sheet.title,book,max_expansion=per_formula_reference_cells)
                    refs=formula_references(text,sheet.title,max_expansion=per_formula_reference_cells)
                    if not refs['fully_supported']:raise StaticReferenceError(str(refs['unsupported']))
                    graph[key]={(r['sheet'],r['cell']) for r in refs['references']}
                except (StaticReferenceError,ValueError,TypeError) as exc:
                    graph[key]=set();unsupported[key]=str(exc)
        descriptions=[];scalar_outputs=[]
        for (sn,row),cells in families.items():
            ordered=sorted(cells,key=lambda k:book[k[0]][k[1]].column)
            label=' '.join(str(c.value) for c in book[sn][row][:2] if c.value is not None and c.data_type!='f')[:180]
            description={'sheet':sn,'row':row,'label':label,'cells':ordered,'formula_count':len(cells),
                         'range':ordered[0][1]+':'+ordered[-1][1]}
            (scalar_outputs if len(cells)==1 else descriptions).append(description)
        return {'families':descriptions,'scalar_financial_outputs':scalar_outputs,'graph':graph,'unsupported':unsupported,
                'source_sha256':sha(path),'formula_count':len(graph),
                'analysis_limits':{'max_dependency_closure_cells':max_dependency_closure_cells,
                    'max_profile_cells':max_profile_cells,'per_formula_reference_cells':per_formula_reference_cells}}
    finally:book.close();values.close()


def closure(targets,inventory):
    maximum=inventory.get('analysis_limits',{}).get('max_dependency_closure_cells',20000)
    seen=set(targets);queue=deque(targets);edges=set()
    while queue:
        key=queue.popleft()
        if key in inventory['unsupported']:
            raise HardeningError('Unsupported target dependency: '+str(key))
        if len(seen)>maximum:raise HardeningError('Hardening closure exceeds configured analysis limit')
        for parent in inventory['graph'].get(key,()):
            if parent[0]!=key[0]:edges.add((key[0],parent[0]))
            if parent not in seen:seen.add(parent);queue.append(parent)
    return seen,edges


def _positive(value):
    try:return Decimal(str(value))>0
    except Exception:return False


def _source_binding(seed, proofs, canonical):
    """Bind financial receipts to these source bytes, including current bundles."""
    source=Path(seed['local_path']).resolve()
    direct=proofs.get('project_model.xlsx') or proofs.get('source_workbook')
    if direct:
        if (not isinstance(direct,dict) or direct.get('sha256')!=seed['sha256']
                or Path(direct.get('path','')).resolve()!=source or sha(source)!=direct['sha256']):
            raise HardeningError('Source proofs do not bind this financial workbook')
        return [direct]
    # New portfolio/cashpool manifests bind the actual normalized workbook at
    # their root, and bind each audit file by hash. A loose *_path is not proof.
    manifest_path=source.parent/'manifest.json'
    if not manifest_path.is_file():
        raise HardeningError('Source financial proofs lack a hash-bound workbook binding')
    manifest=json.loads(manifest_path.read_text())
    selected=[x for x in manifest.get('selected',[]) if x.get('sha256')==seed['sha256']
              and Path(x.get('local_path','')).resolve()==source]
    if (len(selected)!=1 or manifest.get('derived_workbook_sha256')!=seed['sha256']
            or Path(manifest.get('local_path','')).resolve()!=source):
        raise HardeningError('Current source manifest does not bind this workbook')
    for name, proof in canonical.items():
        candidate=manifest.get(name) or (manifest.get('group_ledger') if name=='ledger' else None)
        if (not isinstance(candidate,dict) or candidate.get('sha256')!=proof.get('sha256')
                or Path(candidate.get('path','')).resolve()!=Path(proof.get('path','')).resolve()):
            raise HardeningError('Financial receipt differs from bound source manifest: '+name)
    return [{'path':str(manifest_path.resolve()),'sha256':sha(manifest_path)},
            {'path':str(source),'sha256':seed['sha256']}]


def _financial_invariants_passed(audit, ledger):
    if audit.get('all_ledger_invariants_passed') is True:
        return True
    checks=ledger.get('checks',{})
    if audit.get('all_entity_ledger_invariants_passed') is True:
        return (checks.get('all_group_identities_passed') is True
                and checks.get('group_balance_plug_used') is False
                and audit.get('group_independent_checks')==checks)
    cashpool=('all_double_entry_balanced','all_subsidiary_balances','all_treasury_balances',
              'all_group_balances','all_group_cash_balances','all_group_income_eliminations','no_balance_plug')
    observed=audit.get('independent_ledger_checks',{})
    return all(checks.get(key) is True and observed.get(key) is True for key in cashpool)


def _stable_receipt(stable, audit):
    if stable.get('stable') is True:
        return True
    return (audit.get('two_recalculations_typed_stable') is True
            and stable.get('reward')==1 and stable.get('structure_ok') is True
            and stable.get('expected_change_count')==0 and stable.get('actual_change_count')==0
            and all(stable.get(key)==[] for key in ('wrong_values','missing_changes','extra_changes')))


def _cashpool_events(ledger, public):
    members=public.get('parameters',{}).get('members',[])
    if not members:return []
    events=[]
    for period, rows in enumerate(ledger.get('monthly',[]),1):
        for member in members:
            identity=member.get('id');row=rows.get(identity,{})
            if (member.get('contract')=='term_depositor' and _positive(row.get('deposit_open',0))
                    and Decimal(str(row.get('term_return',0)))==0 and _positive(row.get('loan_advance',0))):
                events.append({'kind':'locked_deposit_and_new_member_borrowing','period':period,
                               'sheets':[identity+' Holding','Treasury']})
            if (member.get('contract')=='nav_borrower' and _positive(row.get('margin_paid',0))
                    and _positive(row.get('capital_margin',0))):
                events.append({'kind':'nav_margin_call_and_limited_partner_capital','period':period,
                               'sheets':[identity+' Holding','Treasury','Pool Scenario']})
        if (any(_positive(row.get('new_deposit',0)) for row in rows.values())
                and any(_positive(row.get('loan_advance',0)) for row in rows.values())):
            events.append({'kind':'cross_member_deposits_fund_limited_advances','period':period,
                           'sheets':['Treasury','Group Statements']})
    return events


def seed_mechanisms(seed):
    """Resolve existing production source proofs; no metadata-only capability assertion."""
    path=Path(seed['local_path'])
    if not path.is_file() or sha(path)!=seed['sha256']:
        raise HardeningError('Source bytes do not match seed manifest')
    evidence=seed.get('finance_evidence',{});proofs=evidence.get('audit_proofs',{})
    bundle_ref=evidence.get('source_proof_bundle')
    origin_ref=None
    if bundle_ref:
        bundle=bound_json(bundle_ref)
        origin_ref=bundle.get('source_manifest')
        original=bound_json(origin_ref)
        matching=[entry for entry in original.get('selected',[])
                  if entry.get('sha256')==seed['sha256']
                  and Path(entry.get('local_path','')).resolve()==path.resolve()
                  and entry.get('finance_evidence',{}).get('financial_seed_verified') is True]
        if len(matching)!=1:
            raise HardeningError('Source proof bundle lacks an original verified manifest binding')
        proofs={**bundle.get('audit_proofs',{}),'source_workbook':bundle.get('source_workbook')}
    result={'nested_events':[],'verified_economic_cycle':False,'evidence':[]}
    canonical={name:proofs.get(old) or proofs.get(name) for name,old in (
        ('ledger','private/ledger.json'),('financial_audit','private/financial_audit.json'),
        ('stability','private/stability.json'),('public_scenario','public_scenario.json'))}
    canonical['ledger']=canonical['ledger'] or proofs.get('group_ledger')
    if all(canonical.values()):
        source_bindings=_source_binding(seed,proofs,canonical)
        ledger=bound_json(canonical['ledger']);audit=bound_json(canonical['financial_audit'])
        stable=bound_json(canonical['stability']);public=bound_json(canonical['public_scenario'])
        if not (audit.get('passed') is True and audit.get('all_formula_cells_independently_covered') is True
                and _financial_invariants_passed(audit,ledger) and _stable_receipt(stable,audit)):
            raise HardeningError('Source financial/runtime proof is not passing')
        result['evidence']=[*source_bindings,*canonical.values(),*([origin_ref,bundle_ref] if bundle_ref else [])]
        annual={int(x['year'])*12:x for x in ledger.get('tax_annual',[])}
        checks=ledger.get('checks',{})
        advanced=public.get('advanced_tax_parameters') or {}
        if advanced.get('advanced_tax_enabled') in (1,'1'):
            for period,tax in annual.items():
                if (checks.get('tax_nol_fifo_ok') is True and _positive(tax.get('nol_expired',0))
                        and _positive(tax.get('current_tax',0))):
                    result['nested_events'].append({'kind':'nol_expiry_with_cash_tax','period':period,
                        'sheets':['Tax Vintages','Tax','Cash Flow']})
                if checks.get('tax_interest_fifo_ok') is True and _positive(tax.get('interest_cf_used',0)):
                    result['nested_events'].append({'kind':'interest_carry_fifo_utilization','period':period,
                        'sheets':['Tax Vintages','Tax','Debt']})
        for month in ledger.get('monthly',[]):
            if 'period' not in month:continue
            period=int(month['period']);tax=annual.get(period,{})
            if (_positive(tax.get('nol_expired',0)) or _positive(tax.get('interest_cf_used',0))) and (
                    _positive(month.get('dsra_support',0)) or _positive(month.get('dsra_funding',0))):
                result['nested_events'].append({'kind':'annual_tax_and_reserve_cash_priority','period':period,
                                                'sheets':['Tax Vintages','Tax','Cash Flow','Covenants']})
            if (month.get('lock_open')==1 and month.get('lock_close')==0 and month.get('passes_close')==2
                    and _positive(month.get('dsra_release',0))):
                result['nested_events'].append({'kind':'second_pass_cure_and_reserve_release','period':period,
                                                'sheets':['Covenants','Cash Flow','Debt']})
        result['nested_events']+=_cashpool_events(ledger,public)
        cycle=ledger.get('cyclic_financing_proof',{})
        enabled=public.get('cyclic_financing_parameters',{}).get('enabled')
        if enabled in (1,'1') and all(checks.get(k) is True for k in CYCLE_CHECKS):
            if (len(cycle.get('fixed_points',[]))!=1 or cycle.get('grid_points_checked',0)<2
                    or cycle.get('mapping_monotone') is not True or cycle.get('all_tranches_feasible') is not True):
                raise HardeningError('Cyclic source lacks complete unique fixed-point proof')
            result['verified_economic_cycle']=True
            result['cycle_kind']='independently_verified_debt_interest_tax_fixed_point'
            result['nested_events'].append({'kind':'debt_interest_tax_capacity_feedback','sheets':['DebtSizing','Debt','Tax']})
            result['cycle_proof_metadata']={'kind':'finite_tranche_grid_unique_fixed_point',
                'grid_points_checked':cycle['grid_points_checked'],'fixed_points':cycle['fixed_points'],
                'business_boundary_count_contribution':0}
    elif evidence.get('compatibility_proof'):
        proof=evidence['compatibility_proof'];receipt=bound_json(proof)
        if not (receipt.get('stability',{}).get('stable') is True
                and receipt.get('raw_sha256')==seed['sha256']
                and receipt.get('profiles',{}).get('normalized',{}).get('errors')==[]):
            raise HardeningError('Professional source compatibility proof is not clean/stable/bound')
        result['evidence']=[proof]
    else:
        raise HardeningError('No supported hash-bound source compatibility/financial proof')
    return result


class HardeningPolicy:
    def __init__(self,root,settings):
        self.root=Path(root);self.settings=deepcopy(settings)
        self.enabled=settings.get('enabled',False) is True
        self.policy={}
        if self.enabled:
            path=Path(settings.get('policy_path','config/difficulty_hardening.yaml'))
            if not path.is_absolute():path=self.root/path
            self.policy=yaml.safe_load(path.read_text())
            if self.policy.get('threshold')!=.2 or [t['tier'] for t in self.policy['tiers']]!=list(range(4)):
                raise HardeningError('Invalid progressive hardening policy')
            self.provenance={'path':str(path.resolve()),'sha256':sha(path)}

    def initial_state(self):
        return {'tier':0,'status':'baseline','measurements':[],'policy':getattr(self,'provenance',None)}

    def observe(self,state,evaluation_path,*,label=None):
        state=deepcopy(state);measurement=scored_measurement(evaluation_path,label)
        digest=measurement['evaluation']['sha256']
        if any(x['evaluation']['sha256']==digest for x in state['measurements']):
            return state,{'status':'already_recorded','measurement':measurement}
        if any(x.get('cohort_fingerprint')==measurement['cohort_fingerprint'] and x['exceeds_threshold'] for x in state['measurements']):
            state['measurements'].append(measurement)
            return state,{'status':'unchanged_task_versions_not_escalated','measurement':measurement}
        previous=state['tier'];event={'status':'retained','measurement':measurement,'from_tier':previous,'to_tier':previous}
        if measurement['exceeds_threshold']:
            if previous>=3:
                state['status']='structural_policy_exhausted';state['measurements'].append(measurement)
                return state,{'status':'structural_policy_exhausted','measurement':measurement,'from_tier':previous,'to_tier':previous}
            state['tier']=previous+1;state['status']='structural_upgrade_required';event.update(status='upgrade_required',to_tier=state['tier'])
        state['measurements'].append(measurement)
        return state,event

    def prepare_round(self,config,seeds,state,directory):
        config=deepcopy(config);directory=Path(directory);tier=state['tier']
        if state.get('status')=='structural_policy_exhausted':raise HardeningError('Highest structural tier remains too easy; add a verified source mechanism and policy revision')
        from ..nodes.construction import construction_contract
        configured=construction_contract(config=config)
        analysis={'max_dependency_closure_cells':configured['dependency_requirements']['max_dependency_closure_cells'],
                  'max_profile_cells':configured['source_requirements']['max_profile_cells'],
                  'per_formula_reference_cells':configured['dependency_requirements']['per_formula_reference_cells']}
        contract={**deepcopy(self.policy['tiers'][tier]),'analysis_limits':analysis,'status':'planned','model':'gpt-6.1-sol',
                  'reasoning_effort':'xhigh','timeout_seconds':1800,'policy':self.provenance,
                  'new_revision_and_fresh_run_required':True,'measurement_count':len(state['measurements'])}
        if tier==0:
            write_new(directory/'hardening_contract.json',contract)
            return config,seeds,contract
        accepted=[];rejected=[];summaries=[]
        for seed in seeds:
            try:
                mechanisms=seed_mechanisms(seed);inventory=workbook_inventory(seed['local_path'],**analysis)
                if len({f['sheet'] for f in inventory['families']})<contract['min_target_sheets']:
                    raise HardeningError('Source lacks enough complete financial formula families')
                if tier>=2 and len({x['kind'] for x in mechanisms['nested_events']})<2:
                    raise HardeningError('Source lacks two actually triggered interacting edge mechanisms')
                if tier>=3 and not mechanisms['verified_economic_cycle']:
                    raise HardeningError('No compatible independently verified economic cyclic source')
                accepted.append(seed)
                summaries.append({'source_sha256':seed['sha256'],'mechanisms':mechanisms,
                    'family_candidates':[{k:v for k,v in family.items() if k!='cells'} for family in inventory['families'][:80]]})
            except (HardeningError,OSError,ValueError,KeyError) as exc:
                rejected.append({'source_sha256':seed.get('sha256'),'reason':str(exc)})
        source_receipt=write_new(directory/'hardening_sources.json',{'status':'planned','tier':tier,'accepted':summaries,'rejected':rejected})
        if not accepted:raise HardeningError('No compatible source for structural tier '+str(tier))
        construction=config.setdefault('construction',{})
        construction.update(authoring_backend='llm',planning_scope='per_mode')
        limits=construction.setdefault('max_edit_count',{})
        for mode in MODES:limits[mode]=max(limits.get(mode,80),contract['max_edit_count'][mode])
        base_name=config.get('prompt_overrides',{}).get('planning.md','planning.md')
        base=Path(base_name) if Path(base_name).is_absolute() else self.root/'prompts'/base_name
        prompt=(base.read_text()+'\n\nACTIVE STRUCTURAL HARDENING CONTRACT\n'
            'This contract overrides soft edit-count preferences. Select whole financial row families, including '
            'first/final periods and zero-valued members where masking changes an observable value. Do not leave '
            'a correct adjacent formula donor within a selected family. Debugging must choose fully effective '
            'complete families; do not insert zero-impact mutations. Use connected target families on at least '
            f"{contract['min_target_sheets']} worksheets. Preserve every public assumption and independent recovery. "
            'Explain the actual nested mechanisms selected. A certified economic fixed point must be included '
            'when required, with its public policy and independently proven unique solution. Already certified real '
            'circular formulas are permitted only with actual iterative-runtime stability evidence; reject '
            'unproven or runtime-unsupported cycles. '
            'If the source cannot support the contract, reject it. No added filler, missing assumptions, '
            'target answers, shortened timeouts or disabled checks are permitted.\n'+json.dumps(contract,ensure_ascii=False)+'\nRead the source-selection evidence locally and match the current immutable source SHA: '+json.dumps(source_receipt)+'\n')
        prompt_path=directory/'hardening_planning.md'
        if prompt_path.exists():raise HardeningError('Hardening prompt already exists')
        prompt_path.parent.mkdir(parents=True,exist_ok=True);prompt_path.write_text(prompt)
        config.setdefault('prompt_overrides',{})['planning.md']=str(prompt_path.resolve())
        feedback=config.setdefault('generation_feedback',{})
        feedback['structural_hardening']={**contract,'source_selection_evidence':source_receipt}
        write_new(directory/'hardening_contract.json',contract)
        return config,accepted,contract

    def verify_task(self,goal,plan,mode,contract,seed,public_input):
        inventory=workbook_inventory(goal,**contract.get('analysis_limits',{}));targets={(e['sheet'],e['cell']) for e in plan.get('edits',[])}
        if not targets:raise HardeningError('No compiled construction edits for hardening verification')
        if mode not in MODES:raise HardeningError('Unknown hardening task mode')
        public=openpyxl.load_workbook(public_input,data_only=False,keep_links=False)
        try:
            for edit in plan['edits']:
                actual=public[edit['sheet']][edit['cell']]
                if mode=='financial_modeling' and (edit.get('after') is not None or actual.value is not None):
                    raise HardeningError('Planned whole-family mask was not applied to public workbook')
                if mode=='debugging' and (actual.data_type!='f' or actual.value!=edit.get('after') or actual.value==edit.get('before')):
                    raise HardeningError('Planned whole-family bug was not applied to public workbook')
        finally:public.close()
        touched=[]
        for family in inventory['families']:
            members=set(family['cells'])
            if not members&targets:continue
            if not members<=targets:
                raise HardeningError('Incomplete formula family: '+family['sheet']+'/'+str(family['row']))
            touched.append({k:v for k,v in family.items() if k!='cells'})
        if not touched:raise HardeningError('No whole-family structural operation was applied')
        target_sheets={x['sheet'] for x in touched}
        if len(target_sheets)<contract['min_target_sheets']:
            raise HardeningError('Insufficient connected target worksheets')
        # The underwriting outputs are genuine scalar calculations, so they
        # have no adjacent formula-family member. They may certify participation
        # in the cycle, but cannot inflate the whole-family worksheet minimum.
        cycle_targets=[]
        for scalar in inventory['scalar_financial_outputs']:
            label=''.join(character for character in scalar['label'].casefold() if character.isalnum())
            if (scalar['sheet']=='DebtSizing' and label in {'year3cfads','debtcapacity','sizedprincipal'}
                    and set(scalar['cells']) & targets):
                cycle_targets.append({'label':scalar['label'],'sheet':scalar['sheet'],
                                      'cell':scalar['cells'][0][1]})
        if contract['tier']>=3 and not cycle_targets:
            raise HardeningError('No actual core DebtSizing business output was changed')
        mechanism_sheets=target_sheets|{target['sheet'] for target in cycle_targets}
        visited,edges=closure(targets,inventory)
        if not any(a in mechanism_sheets and b in mechanism_sheets for a,b in edges):
            raise HardeningError('Targets lack a real cross-sheet dependency chain')
        mechanisms=seed_mechanisms(seed)
        if contract['tier']>=2:
            events=[e for e in mechanisms['nested_events'] if len(mechanism_sheets&set(e['sheets']))>=2]
            if len({e['kind'] for e in events})<2:
                raise HardeningError('Actual targets do not cover the verified nested edge mechanisms')
        if contract['tier']>=3 and not (mechanisms['verified_economic_cycle'] and cycle_targets):
            raise HardeningError('Verified cyclic mechanism was not included in actual task targets')
        return {'status':'applied','tier':contract['tier'],'mode':mode,'goal_sha256':sha(goal),
                'targets_sha256':hashlib.sha256(json.dumps(sorted(targets)).encode()).hexdigest(),
                'whole_families':touched,'whole_family_target_sheets':sorted(target_sheets),
                'target_sheets':sorted(mechanism_sheets),'cyclic_business_targets':cycle_targets,
                'cross_sheet_edges':sorted(edges),'dependency_closure_cells':len(visited),
                'mechanisms':mechanisms,'difficulty_proven':False}

    def verify_release(self,quality,packaged,seeds,contract,directory):
        if contract['tier']==0:return {'status':'baseline','tier':0}
        manifest=json.loads(Path(packaged['manifest']).read_text());sources={s['sha256']:s for s in seeds};receipts=[]
        for task in manifest['tasks']:
            private=Path(quality)/'tasks'/task['task_id']/'revisions'/f"{int(task['revision']):03d}"/'private'
            plan=json.loads((private/'plan.json').read_text())
            if task['source_id'] not in sources:raise HardeningError('Constructed task uses a source outside hardening selection')
            receipts.append({'task_id':task['task_id'],**self.verify_task(private/'goal.xlsx',plan,task['mode'],contract,sources[task['source_id']],private.parent/'public/input.xlsx')})
        return write_new(Path(directory)/'hardening_applied.json',{'status':'applied','tier':contract['tier'],'tasks':receipts,'difficulty_proven':False})
