"""Explicit, unverified native FM/DBG views of one privately audited source.

The functions below do no financial forward, search, workbook recalculation or
grading. Source admission and all actual task validation remain separate gates.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import json

import openpyxl

from . import excel
from .spec import canonical_sha256, load_spec, require, validate_plan
from .formula_identity import formula_signature

VERSION = 1
FAMILIES = ('closing_debt_interest', 'early_loss_expiry', 'scenario_base_feedback')
FM_INSTRUCTION = (
    'Complete the investment model and choose one common project portfolio that maximises the sum of posted S01 LP NPVs, '
    'subject to all stated capacities and relationships in every scenario. Complete all existing financial, tax-loss, '
    'NPV, capacity and portfolio schedules for every candidate and all three scenarios. Candidate forecasts are standalone; '
    'portfolio totals use the common project choices. Amounts are integer GBP pence. Preserve supplied assumptions, labels, '
    'worksheet names and worksheet order. Do not add, remove or move cells, add helper calculations, or add worksheets. '
    'Keep the stated non-applicable loss-vintage slots blank. Save the completed workbook to /app/output.xlsx.\n'
)
DBG_INSTRUCTION = (
    'Review and correct the investment model, then choose one common project portfolio that maximises the sum of posted '
    'S01 LP NPVs, subject to all stated capacities and relationships in every scenario. The existing project choices are '
    'provisional. Review all existing financial, tax-loss, NPV, capacity and portfolio schedules for every candidate and all '
    'three scenarios. Candidate forecasts are standalone; portfolio totals use the common project choices. Amounts are '
    'integer GBP pence. Preserve supplied assumptions, labels, worksheet names and worksheet order. Do not add, remove or '
    'move cells, add helper calculations, or add worksheets. Keep the stated non-applicable loss-vintage slots blank. '
    'Save the corrected and completed workbook to /app/output.xlsx.\n'
)


def _reference(path):
    path=Path(path).resolve();digest=hashlib.sha256();size=0
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block);size+=len(block)
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':size}


def _recipe():
    from ...task_adapters import heterogeneous_formula_identity
    from . import spec, formula_identity
    return [_reference(p) for p in (__file__,excel.__file__,spec.__file__,formula_identity.__file__,heterogeneous_formula_identity.__file__)]


def _read_bindings(value):
    if isinstance(value,(str,Path)):
        path=Path(value);return json.loads(path.read_text()),_reference(path)
    require(isinstance(value,dict),'A complete private source binding is required')
    return value,{'canonical_sha256':canonical_sha256(value)}


def _coordinate(row):return row['sheet'],row['cell']


def _index(rows,label):
    require(isinstance(rows,list),'A complete '+label+' list is required')
    indexed={_coordinate(row):row for row in rows}
    require(len(indexed)==len(rows),'A physical '+label+' identity is duplicated')
    return indexed


def _identity(actual,expected):
    return type(actual) is type(expected) and actual==expected


def _source(source,public,bindings):
    require(bindings.get('binding_version')==VERSION and type(bindings.get('binding_version')) is int
        and bindings.get('kind')=='linear_capital_portfolio_native_excel_bindings'
        and bindings.get('specification_sha256')==canonical_sha256(public),'The complete native source identity differs')
    require(bindings.get('plan_supplied') is True,'A source with a complete explicit private plan is required')
    domains={name:_index(bindings[name],name) for name in ('input_bindings','literal_bindings','decision_bindings','arithmetic_bindings','financial_bindings')}
    financial=domains['financial_bindings'];arith=domains['arithmetic_bindings']
    require(set(arith)-set(financial)=={('Portfolio','B3')},'A source formula lacks an independent financial or plan-completion locator')
    require(type(bindings.get('formula_count')) is int and bindings['formula_count']==len(arith),'The physical source formula count differs')
    require(set(domains['input_bindings']).isdisjoint(financial),'A financial target overlaps a provided primitive')
    physical=[set(domains[name]) for name in ('input_bindings','literal_bindings','decision_bindings','arithmetic_bindings')]
    require(len(set.union(*physical))==sum(map(len,physical)),'The physical source binding domains overlap')
    book=openpyxl.load_workbook(source,data_only=False)
    try:
        require(book.sheetnames==bindings['sheetnames'],'The native source worksheet order differs')
        current={(sheet.title,cell.coordinate):cell.value for sheet in book for row in sheet for cell in row if cell.value is not None}
        require(set(current)==set.union(*physical),'The complete physical source binding scope differs')
        formula={key:value for key,value in current.items() if type(value) is str and book[key[0]][key[1]].data_type=='f'}
        require(set(formula)==set(arith),'The complete source formula coordinate set differs')
        for key,row in arith.items():
            require(formula_signature(formula[key])==formula_signature(row['formula']),'A source formula differs from its bound definition')
        for key,row in domains['input_bindings'].items():
            value=public
            for part in row['path']:value=value[part]
            require(_identity(current[key],value),'A provided source primitive differs')
        for key,row in domains['literal_bindings'].items():require(_identity(current[key],row['value']),'A provided source literal differs')
        decision=domains['decision_bindings']
        require(len(decision)==len(public['project_ids']) and {r['project_id'] for r in decision.values()}==set(public['project_ids']),
                'Every common project choice is required')
        for key,row in decision.items():require(type(current[key]) is int and current[key] in (0,1) and current[key]==row['value'],
                'The source private plan is incomplete or differs from its binding')
        for key,row in financial.items():
            if row['formula'] is None:
                require(key in domains['literal_bindings'] and type(row['expression']) is int and _identity(current[key],row['expression']),
                        'A financial identity literal differs from its independent locator')
            else:require(key in arith and arith[key]==row,'A financial formula binding differs from its physical definition')
        return domains,current
    finally:book.close()


def _point(row):
    return "'"+row['sheet'].replace("'","''")+"'!"+openpyxl.utils.absolute_coordinate(row['cell'])


def _replace(expr,before,after):
    if expr==before:return after,1
    if not isinstance(expr,(tuple,list)):return expr,0
    values=[];count=0
    for value in expr:
        replaced,n=_replace(value,before,after);values.append(replaced);count+=n
    return values,count


def _faults(public,financial,current):
    annual={};vintages={};projects={p['id']:p for p in public['projects']};scenarios={s['id']:s for s in public['scenarios']}
    for key,row in financial.items():
        role=row.get('semantic_role',{});path=row['expected_path']
        if role.get('schedule')=='annual':
            # Canonical source path: projects/pid/scenarios/sid/annual/index/field.
            require(len(path)==7 and path[0]=='projects' and path[2]=='scenarios' and path[4]=='annual',
                    'A primary annual source locator differs')
            annual[path[1],path[3],path[5]+1,path[6]]=row
        elif role.get('schedule')=='tax_vintages':
            vintages[role['project_id'],role['scenario_id'],row['vintage_year'],row['origin_year'],row['vintage_field']]=row
    edits=[]
    def edit(family,row,expr):
        key=_coordinate(row);before=current[key];after='='+excel._expression(expr)
        require(row['formula'] is not None or (type(before) is int and before==0),
                'Only formulas and private-bound financial identity zeroes may be faulted')
        require(before!=after,'A syntactically unchanged mutation is not an edit')
        edits.append({'family':family,'sheet':key[0],'cell':key[1],'before':before,'after':after,
            'before_kind':'formula' if row['formula'] is not None else 'financial_identity_literal_zero',
            'after_kind':'formula','semantic_role':deepcopy(row['semantic_role']),
            'financial_locator':{k:deepcopy(row[k]) for k in ('expected_path','vintage_year','origin_year','vintage_field') if k in row},
            'individual_activity_claimed':False})
    for (pid,sid,year,field),row in sorted(annual.items()):
        project=projects[pid];scenario=scenarios[sid]
        if field=='bank_interest' and year<=project['debt_maturity_year'] and project['bank_rate_bp']+scenario['interest_spread_bp'][str(year)]>0:
            old=_point(annual[pid,sid,year,'debt_open']);new=_point(annual[pid,sid,year,'debt_close'])
            expr,count=_replace(row['expression'],old,new);require(count==1,'The opening-debt interest shape differs')
            edit(FAMILIES[0],row,expr)
        if field=='revenue_base' and year>project['operating_start_year']:
            old=_point(annual[pid,sid,year-1,'revenue_base']);new=_point(annual[pid,sid,year-1,'revenue'])
            expr,count=_replace(row['expression'],old,new);require(count==1,'The unshocked-base growth shape differs')
            edit(FAMILIES[2],row,expr)
    for (pid,sid,year,origin,field),row in sorted(vintages.items()):
        if year-origin!=3 or field!='opening':continue
        opening=_point(row)
        # This coherent wrong policy expires the account in its final legal FY.
        # Selection is purely calendar/policy based, never chosen after an effect.
        for part,expr in [('expired',opening),('used',0),('closing',0)]:
            edit(FAMILIES[1],vintages[pid,sid,year,origin,part],expr)
    require(len({_coordinate(e) for e in edits})==len(edits),'Two fault families overlap a physical cell')
    return edits


def plan_task_view(source_path,specification,bindings,*,mode,temporary_plan=None):
    """Bind complete scope and deterministic faults; no materialization or finance."""
    require(mode in ('financial_modeling','debugging'),'An explicit task mode is required')
    public=load_spec(specification);binding,binding_ref=_read_bindings(bindings)
    before=_reference(source_path);domains,current=_source(before['path'],public,binding)
    require(_reference(before['path'])==before,'The source changed during task planning')
    require(temporary_plan is None or mode=='debugging','A temporary choice vector is only a debugging input')
    temporary=validate_plan(public,{pid:0 for pid in public['project_ids']} if temporary_plan is None else temporary_plan) if mode=='debugging' else None
    mask=sorted(set(domains['financial_bindings'])|set(domains['arithmetic_bindings'])|set(domains['decision_bindings'])) if mode=='financial_modeling' else []
    provided=sorted(set(domains['input_bindings'])|(set(domains['literal_bindings'])-set(domains['financial_bindings'])))
    edits=_faults(public,domains['financial_bindings'],current) if mode=='debugging' else []
    require(set(mask).isdisjoint(provided) and {_coordinate(e) for e in edits}.isdisjoint(provided),'A task change touches a provided primitive or label')
    choice_edits=[]
    if mode=='debugging':
        for key,row in sorted(domains['decision_bindings'].items()):
            choice_edits.append({'sheet':key[0],'cell':key[1],'project_id':row['project_id'],'before':current[key],
                'after':temporary[row['project_id']],'kind':'declared_provisional_choice'})
    result={'kind':'planned_unverified_linear_capital_task_view','version':VERSION,'mode':mode,'source':before,
        'specification_sha256':canonical_sha256(public),'bindings':binding_ref,'bindings_canonical_sha256':canonical_sha256(binding),
        'recipe':_recipe(),'sheetnames':list(binding['sheetnames']),'project_ids':list(public['project_ids']),
        'masked_targets':[{'sheet':s,'cell':c,'before':current[s,c]} for s,c in mask],
        'provided_cells':[{'sheet':s,'cell':c,'value':current[s,c]} for s,c in provided],
        'all_source_physical_cells':[{'sheet':s,'cell':c} for s,c in sorted(current)],
        'formula_edits':edits,'choice_edits':choice_edits,'temporary_plan':temporary,
        'family_selection_policy':{'version':1,'families':list(FAMILIES),'basis':'Public contract calendars, rates, loan policy and semantic primary-node identities only; no observed activity or optimal answer selection'},
        'family_physical_edit_counts':{f:sum(e['family']==f for e in edits) for f in FAMILIES},
        'instruction':FM_INSTRUCTION if mode=='financial_modeling' else DBG_INSTRUCTION,
        'actual_family_effects_verified':False,'actual_joint_full_D_verified':False,'actual_input_stability_verified':False,
        'source_financial_admission_claimed':False,'quality_recovery_Harbor_difficulty_certified':False}
    result['plan_sha256']=canonical_sha256(result)
    return result


def _check_plan(plan):
    require(isinstance(plan,dict) and plan.get('kind')=='planned_unverified_linear_capital_task_view'
        and type(plan.get('version')) is int and plan['version']==VERSION,'A bound task plan is required')
    require(plan['plan_sha256']==canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'}),'The frozen task plan changed')
    require(plan['recipe']==_recipe(),'The task-view implementation recipe changed')
    require(_reference(plan['source']['path'])==plan['source'],'The source workbook changed')


def materialize_variant(plan,path,*,families=(),apply_temporary_plan=True):
    """Write a fresh uncalculated masked or selected-family validation workbook.

    In DBG, families=() gives the same provisional-plan baseline. Family names
    never select individual effects after observation; every planned edit in a
    selected family is retained. All variants remain unverified private evidence.
    """
    _check_plan(plan)
    require(type(apply_temporary_plan) is bool,'The choice-plan application setting must be Boolean')
    require(isinstance(families,(tuple,list)) and len(set(families))==len(families)
        and set(families)<=set(FAMILIES),'The selected mutation families differ')
    if plan['mode']=='financial_modeling':require(not families,'A modeling variant cannot contain faults')
    destination=Path(path).resolve();require(not destination.exists(),'Preserve existing task artifacts; use a fresh workbook path')
    require(destination.suffix.lower()=='.xlsx','A native XLSX variant is required')
    book=openpyxl.load_workbook(plan['source']['path'],data_only=False)
    try:
        require(book.sheetnames==plan['sheetnames'],'The source worksheet order changed')
        before={(s.title,c.coordinate):c.value for s in book for row in s for c in row if c.value is not None}
        for row in plan['provided_cells']:require(_identity(before[_coordinate(row)],row['value']),'A supplied assumption or label changed')
        allowed=set()
        if plan['mode']=='financial_modeling':
            require(not plan['formula_edits'] and not plan['choice_edits'],'A modeling plan contains debugging edits')
            for row in plan['masked_targets']:
                key=_coordinate(row);require(_identity(before[key],row['before']),'A modeling target changed')
                book[key[0]][key[1]]=None;allowed.add(key)
        else:
            require(not plan['masked_targets'] and plan['mode']=='debugging','A debugging plan contains masks')
            selected=[row for row in plan['formula_edits'] if row['family'] in families]
            if apply_temporary_plan:selected+=plan['choice_edits']
            for row in selected:
                key=_coordinate(row);require(_identity(before[key],row['before']),'A debugging source value changed')
                book[key[0]][key[1]]=row['after'];allowed.add(key)
        after={(s.title,c.coordinate):c.value for s in book for row in s for c in row if c.value is not None}
        changed={key for key in set(before)|set(after) if not _identity(before.get(key),after.get(key))}
        require(changed<=allowed and set(after)<=set(before),'A task view changed outside its exact approved physical scope')
        require(all(_identity(after[_coordinate(row)],row['value']) for row in plan['provided_cells']),'A provided input or label was modified')
        if plan['mode']=='financial_modeling':require(not any(c.data_type=='f' for s in book for row in s for c in row),'A modeling view retained a source formula or answer alias')
        destination.parent.mkdir(parents=True,exist_ok=True);book.save(destination)
    finally:book.close()
    require(_reference(plan['source']['path'])==plan['source'],'The source changed during variant materialization')
    return _reference(destination)


def materialize_view(plan,fresh_directory):
    """Write an unverified task plus same-plan baseline and family counterfactuals."""
    _check_plan(plan)
    destination=Path(fresh_directory).resolve();require(not destination.exists(),'Preserve existing task artifacts; use a fresh directory')
    destination.mkdir(parents=True,exist_ok=False);public=destination/'public';private=destination/'private'
    public.mkdir();private.mkdir();input_path=public/'input.xlsx'
    materialize_variant(plan,input_path,families=FAMILIES if plan['mode']=='debugging' else ())
    temporary_plan_only=None;family_inputs={}
    if plan['mode']=='debugging':
        validation=private/'validation';validation.mkdir()
        temporary_plan_only=materialize_variant(plan,validation/'temporary_plan_only.xlsx')
        family_inputs={family:materialize_variant(plan,validation/(family+'.xlsx'),families=(family,)) for family in FAMILIES}
    goal=private/'goal.xlsx';shutil.copyfile(plan['source']['path'],goal)
    require(_reference(goal)['sha256']==plan['source']['sha256'] and _reference(goal)['bytes']==plan['source']['bytes'],'The private goal is not an exact source copy')
    instruction=public/'instruction.md';instruction.write_text(plan['instruction'],encoding='utf-8')
    plan_path=private/'view_plan.json';plan_path.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+'\n')
    require(_reference(plan['source']['path'])==plan['source'],'The source changed during materialization')
    result={'kind':'materialized_unverified_linear_capital_task_view','version':VERSION,'mode':plan['mode'],
        'source':plan['source'],'specification_sha256':plan['specification_sha256'],'plan':_reference(plan_path),
        'plan_sha256':plan['plan_sha256'],'input':_reference(input_path),'goal':_reference(goal),'instruction':_reference(instruction),
        'temporary_plan_only':temporary_plan_only,'family_inputs':family_inputs,
        'sheetnames':plan['sheetnames'],'masked_target_count':len(plan['masked_targets']),
        'formula_edit_count':len(plan['formula_edits']),'choice_cell_count':len(plan['choice_edits']),
        'family_physical_edit_counts':plan['family_physical_edit_counts'],'recipe':plan['recipe'],
        'provided_inputs_labels_and_sheet_order_preserved':True,'goal_is_byte_exact_source_copy':True,
        'input_caches_are_not_certified':True,'actual_family_effects_verified':False,'actual_joint_full_D_verified':False,
        'actual_input_stability_verified':False,'actual_controls_verified':False,'source_financial_admission_claimed':False,
        'quality_recovery_Harbor_difficulty_certified':False,'new_financial_forwards_optimizer_LO_models':0}
    path=private/'view_manifest.json';path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return result
