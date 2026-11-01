"""Unverified whole-pair views, preserving the original local task contracts.

This module performs no financial forward, native calculation or admission.
The full fixed pool is declared before any task material is emitted.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as X
from xml.sax.saxutils import quoteattr
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
from openpyxl.utils import get_column_letter

from . import contract as c, stream_composition as stream, group_report
from ...evaluation import streaming_verifier as sparse
from ..linear_capital_portfolio.formula_identity import formula_signature

POOL_KIND='prospective_complete_ten_ringfenced_pair_task_views'
PLAN_KIND='complete_unverified_ringfenced_pair_task_view_plan'
COUNTS={'sheets':741,'formulas':2494958,'targets':3044678,'nonempty':3547571,
        'choices':720,'completion_gates':2,'DBG_formula_roots':172800}
MODES=('financial_modeling','debugging')
S=stream.S
FM_BRIEF=('Complete both ringfenced investment mandates and their consolidated management reports. '
    'Choose a complete common portfolio for each mandate that maximises the sum of its posted S01 LP NPVs, '
    'subject to its supplied constraints in every scenario. Complete all existing candidate, portfolio and group schedules. '
    'Preserve supplied assumptions, policies, labels, worksheet order and non-applicable blank slots. '
    'Use integer GBP pence and save the completed workbook to /app/output.xlsx.\n')
DBG_BRIEF=('Review and correct both ringfenced investment mandates and their consolidated management reports. '
    'The existing portfolio choices are provisional. Choose complete portfolios that maximise the sum of posted S01 LP NPVs, '
    'subject to each mandate\'s supplied constraints in every scenario. Review all existing candidate, portfolio and group schedules. '
    'Preserve supplied assumptions, policies, labels, worksheet order and non-applicable blank slots. '
    'Use integer GBP pence and save the corrected workbook to /app/output.xlsx.\n')


def recipes():
    return {**c.recipes(),str(Path(__file__).resolve()):c.reference(__file__),
        str(Path(sparse.__file__).resolve()):c.reference(sparse.__file__)}


def _donor(context):
    pair=c.read(context['engineering_pair'])
    c.require(pair['passed'] is True and pair['source_manifest']==context['source_manifest']
        and pair['profile_id']==context['profile_id'] and pair['mode_order']==list(MODES),
        'Use each original complete donor pair, without inheriting its task qualification')
    result={'profile_id':context['profile_id'],'engineering_pair':context['engineering_pair'],'views':{}}
    for mode in MODES:
        ref=pair['view_manifests'][mode];view=c.read(ref)
        c.require(view['kind']=='materialized_unverified_linear_capital_scaled_task_view' and view['version']==1
            and view['mode']==mode and view['goal_is_byte_exact_source_copy'] is True
            and view['source']==context['workbook'], 'A local view belongs to a different original source')
        count=1522188 if mode=='financial_modeling' else 0
        c.require(view['masked_target_count']==count and view['formula_edit_count']==(86400 if mode=='debugging' else 0)
            and view['choice_cell_count']==(360 if mode=='debugging' else 0), 'The complete original local task scope changed')
        result['views'][mode]={'manifest':ref,'plan':view['plan'],'sheetnames':view['sheetnames']}
    actual=c.read(pair['validation_terminals']['debugging']);controls=c.read(actual['controls_evidence'])
    c.require(actual['passed'] is True and actual['mode']=='debugging'
        and actual['local_controls']==controls['rewards']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},
        'The deterministic local control must have original full-D evidence')
    result['control_primary']=controls['observable_primary']
    result['control_evidence']=actual['controls_evidence']
    return result


def _pool_value(prospective):
    ref=prospective if isinstance(prospective,dict) else c.reference(prospective)
    frozen=c.validate_prospective(ref)
    return {'kind':POOL_KIND,'version':1,'prospective':ref,
        'pair_order':[p[0] for p in c.PAIRS],'pairs':deepcopy(frozen['pairs']),
        'donors':[_donor(row) for row in frozen['contexts']], 'counts':dict(COUNTS),
        'mode_order':list(MODES),'recipe':recipes(),'new_source_calls':0,'new_financial_forwards':0,
        'new_solver_model_Harbor_calls':0,'task_materials_emitted':0,'qualified':False,
        'local_quality_and_difficulty_inherited':False,
        'FM_scope':'Both whole original masks, including720 choices and2 completion gates, plus302 group targets',
        'DBG_scope':'Both complete original fault and provisional-choice inventories, with natural group propagation'}


def freeze_pool(prospective,output):
    output=Path(output).absolute();c.require(output==output.resolve() and not output.exists(),'Use a fresh whole-pool declaration')
    value=_pool_value(prospective);output.mkdir(parents=True)
    return c.write(output/'whole_views_contract.json',value)


def validate_pool(record):
    value=c.read(record);c.require(value==_pool_value(value['prospective']),'The complete fixed pair view contract changed')
    return value


def compile_views(rows,composition,report,*,toy=False):
    """Map retained local lists; no financial arithmetic or workbook execution."""
    mask={};faults=[];choices=[];control=None;names=[]
    c.require(len(rows)==len(composition['donors'])==2,'Keep both complete mandates')
    for donor,mapping in zip(rows,composition['donors'],strict=True):
        sheet_map=mapping['sheet_map'];names.extend(sheet_map.values())
        fm,dbg=donor['financial_modeling'],donor['debugging']
        c.require(fm['mode']=='financial_modeling' and dbg['mode']=='debugging'
            and fm['sheetnames']==dbg['sheetnames']==list(sheet_map), 'A donor plan has a different complete worksheet inventory')
        for row in fm['masked_targets']:
            sheet=sheet_map[row['sheet']];cells=mask.setdefault(sheet,set())
            c.require(row['cell'] not in cells,'A full FM target is duplicated');cells.add(row['cell'])
        for edit in dbg['formula_edits']:
            row=deepcopy(edit);old=row['sheet'];row['sheet']=sheet_map[old];row['fund_id']=mapping['id']
            for key in ('before','after'):
                if type(row[key]) is str and row[key].startswith('='):
                    row[key]=stream._N['syntax'].rewrite_formula(row[key],sheet_map,local_sheet=old)
            faults.append(row)
        for edit in dbg['choice_edits']:
            row=deepcopy(edit);row['sheet']=sheet_map[row['sheet']];row['fund_id']=mapping['id'];choices.append(row)
        if control is None:
            point=donor['control_primary'];mapped=(sheet_map[point['sheet']],point['cell'])
            selected=[r for r in faults if (r['sheet'],r['cell'])==mapped]
            c.require(len(selected)==1,'The original proven control point must be a declared formula root')
            control=deepcopy(selected[0])
    c.require(report['sheet'] not in names,'The group-report namespace overlaps a mandate');names.append(report['sheet'])
    mask[report['sheet']]=set(report['financial'])
    c.require(len({(r['sheet'],r['cell']) for r in faults+choices})==len(faults)+len(choices),
        'Declared fault/choice edits overlap')
    c.require(all(r['cell'] in mask.get(r['sheet'],set()) for r in choices),
        'Every provisional choice must also be removed from the complete FM input')
    total=sum(map(len,mask.values()))
    if not toy:
        c.require(len(names)==COUNTS['sheets'] and total==COUNTS['targets']
            and len(faults)==COUNTS['DBG_formula_roots'] and len(choices)==COUNTS['choices']
            and sum('B3' in mask[s] for s in mask if s.endswith('Portfolio'))==2,
            'The full pair formula, choice, completion-gate or target census changed')
    return {'sheetnames':names,'FM_mask':{s:sorted(v) for s,v in mask.items()},
        'DBG_faults':faults,'DBG_choices':choices,'control_root':control,
        'FM_target_count':total,'DBG_formula_root_count':len(faults),'DBG_choice_count':len(choices),
        'group_target_count':len(report['financial']),'toy':toy}


def plan(contract_record,terminal,source_preparation):
    declared=validate_pool(contract_record);sf=c.read(source_preparation);certificate=c.read(sf['certificate'])
    c.require(certificate['prospective']==declared['prospective'] and terminal['preparation']==source_preparation
        and terminal['source']==terminal['actual_calls'][-1]['output'] and sf['geometry']==
        {k:COUNTS[k] for k in ('formulas','nonempty','targets')},'Use this complete genuine pair source and exact geometry')
    pair=certificate['pair_id'];contexts=c.pair_contexts(c.read(declared['prospective'])['contexts'],pair)
    lookup={r['profile_id']:r for r in declared['donors']};rows=[]
    for context in contexts:
        bound=lookup[context['profile_id']]
        row={mode:c.read(bound['views'][mode]['plan']) for mode in MODES}
        row['control_primary']=bound['control_primary'];rows.append(row)
    composed=c.read(sf['local_composition']);report=c.read(sf['report_plan'])
    mapped=compile_views(rows,composed,report)
    return {'kind':PLAN_KIND,'version':1,'pair_id':pair,'whole_views_contract':contract_record,
        'source_preparation':source_preparation,'genuine_goal':terminal['source'],'source_geometry':sf['geometry'],
        'source_formula_count':COUNTS['formulas'],'provided_cells_and_all_context_preserved':True,
        'all_formula_caches_must_be_absent':True,'mode_order':list(MODES),'recipe':recipes(),**mapped,
        'task_qualification_inherited':False,'actual_native_D_unknown':True,'qualified':False}


def actions(plan,mode):
    c.require(mode in MODES,'Choose one explicit mode')
    if mode=='financial_modeling':return {s:{p:('blank',None) for p in points} for s,points in plan['FM_mask'].items()}
    result={}
    for kind,rows in (('formula',plan['DBG_faults']),('number',plan['DBG_choices'])):
        for row in rows:result.setdefault(row['sheet'],{})[row['cell']]=(kind,row['after'])
    return result


def _parts(archive):
    book=X.fromstring(archive.read('xl/workbook.xml'));rels=X.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets={r.get('Id'):r.get('Target') for r in rels}
    return {s.get('name'):stream._resolve('xl/workbook.xml',targets[s.get('{'+stream.R+'}id')]) for s in book.find('{*}sheets')}


def _sheet(source,destination,changes,counts):
    """One physical row at a time; all original metadata remains in place."""
    depth=0;parents=[];namespaces={};opened=False;found=set()
    destination.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    for event,node in X.iterparse(source,events=('start-ns','start','end')):
        if event=='start-ns':
            if depth==0:namespaces[node[0]]=node[1]
            continue
        if event=='start':
            depth+=1;parents.append(node)
            if depth==1:
                c.require(node.tag=='{'+S+'}worksheet','A physical worksheet is required');namespaces['']=S
                attrs={'xmlns'+(':'+p if p else ''):u for p,u in namespaces.items()}
                for k,v in node.attrib.items():
                    if k.startswith('{'):
                        uri,local=k[1:].split('}');prefix=next((p for p,u in namespaces.items() if p and u==uri),None)
                        c.require(prefix is not None,'Root namespace lost');k=prefix+':'+local
                    attrs[k]=v
                destination.write(('<worksheet'+''.join(' '+k+'='+quoteattr(v) for k,v in attrs.items())+'>').encode())
            elif depth==2 and node.tag=='{'+S+'}sheetData':
                destination.write(('<sheetData'+''.join(' '+k+'='+quoteattr(v) for k,v in node.attrib.items())+'>').encode());opened=True
            continue
        if depth==3 and node.tag=='{'+S+'}row' and opened:
            for cell in node.findall('{'+S+'}c'):
                address=cell.get('r');edit=changes.get(address)
                if edit:
                    found.add(address);kind,value=edit
                    for child in list(cell):
                        if child.tag in ('{'+S+'}f','{'+S+'}v','{'+S+'}is'):cell.remove(child)
                    cell.attrib.pop('t',None)
                    if kind=='formula':X.SubElement(cell,'{'+S+'}f').text=value.lstrip('=')
                    elif kind=='number':
                        c.require(type(value)is int and value in (0,1),'Only original provisional binary choices are numeric edits')
                        X.SubElement(cell,'{'+S+'}v').text=str(value)
                    elif kind=='text':cell.set('t','inlineStr');X.SubElement(X.SubElement(cell,'{'+S+'}is'),'{'+S+'}t').text=value
                    else:c.require(kind=='blank','Unknown predeclared cell edit')
                if cell.find('{'+S+'}f') is not None:
                    counts['formulas']+=1
                    for tag in ('v','is'):
                        for cache in list(cell.findall('{'+S+'}'+tag)):cell.remove(cache);counts['cleared_cache_nodes']+=1
                    cell.attrib.pop('t',None)
            destination.write(X.tostring(node));parents[-2].remove(node);node.clear()
        elif depth==2:
            if node.tag=='{'+S+'}sheetData':destination.write(b'</sheetData>');opened=False
            else:destination.write(X.tostring(node))
            parents[-2].remove(node);node.clear()
        elif depth==1:destination.write(b'</worksheet>')
        depth-=1;parents.pop()
    c.require(found==set(changes),'A declared view/control edit did not exist in the source')


def transform(original,destination,changes):
    counts={'formulas':0,'cleared_cache_nodes':0};touched=[]
    with ZipFile(original) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        parts=_parts(zin);c.require(set(changes)<=set(parts),'A task edit names an absent worksheet')
        reverse={p:s for s,p in parts.items()}
        for info in zin.infolist():
            if info.filename in reverse:
                with zin.open(info) as inp,zout.open(info,'w') as out:_sheet(inp,out,changes.get(reverse[info.filename],{}),counts)
                touched.append(info.filename)
            else:zout.writestr(info,zin.read(info.filename))
    return {'source':c.reference(original),'output':c.reference(destination),'edited_cells':sum(map(len,changes.values())),
        'all_formula_caches_absent':True,'all_other_member_bytes_preserved':True,'worksheet_members':touched,**counts}


def cold_cache_census(path):
    count=0
    with ZipFile(path) as archive:
        for part in _parts(archive).values():
            with archive.open(part) as handle:
                parents=[]
                for event,node in X.iterparse(handle,events=('start','end')):
                    if event=='start':parents.append(node);continue
                    if node.tag=='{'+S+'}c':
                        formula=node.find('{'+S+'}f')
                        if formula is not None:
                            count+=1;c.require(bool(formula.text) and node.find('{'+S+'}v')is None
                                and node.find('{'+S+'}is')is None,'Every planned physical formula cache must be absent')
                        if len(parents)>1:parents[-2].remove(node)
                        node.clear()
                    parents.pop()
    return count


def verify(path,plan,*,blank=False,check_caches=False):
    """Whole physical union: only the declared mode edits may differ."""
    mode='financial_modeling' if blank else 'debugging';edits=actions(plan,mode);seen={s:set() for s in edits};count=errors=0
    with ExitStack() as stack:
        books=[]
        for value,data in ((c.checked(plan['genuine_goal']),False),(path,False),(path,True)):
            book=openpyxl.load_workbook(value,read_only=True,data_only=data,keep_links=False);stack.callback(book.close);books.append(book)
        c.require(all(b.sheetnames==plan['sheetnames'] for b in books),'Complete worksheet order changed')
        c.require(all(b.epoch==books[0].epoch and b.calculation.iterate is not True for b in books),
            'The common epoch or noncircular calculation policy changed')
        for sheet in plan['sheetnames']:
            streams=[iter(sparse._sparse_cells(b[sheet])) for b in books];heads=[next(s,None) for s in streams]
            try:
                while any(h is not None for h in heads):
                    point=min(h[0] for h in heads if h is not None);cells=[]
                    for i,it in enumerate(streams):
                        if heads[i] is not None and heads[i][0]==point:cells.append(heads[i][1]);heads[i]=next(it,None)
                        else:cells.append(None)
                    before,after,cache=cells;address=get_column_letter(point[1])+str(point[0]);edit=edits.get(sheet,{}).get(address)
                    count+=1;errors+=int(cache is not None and cache['data_type']=='e')
                    if edit:
                        seen[sheet].add(address);kind,value=edit
                        if kind=='blank':c.require(after is None,'A full FM target retained a value or formula')
                        elif kind=='formula':c.require(after is not None and after['data_type']=='f'
                            and formula_signature(after['value'])==formula_signature(value),'A declared original DBG fault changed')
                        else:c.require(after is not None and type(after['value'])is int and after['value']==value,'A provisional choice changed')
                        if check_caches and blank:c.require(cache is None,'An FM target retained a native cached answer')
                    elif before is not None and before['data_type']=='f':
                        c.require(after is not None and after['data_type']=='f' and formula_signature(after['value'])==formula_signature(before['value']),
                            'A healthy source formula changed outside the declared faults')
                    else:c.require((None if before is None else (before['data_type'],before['value']))==
                        (None if after is None else (after['data_type'],after['value'])),'A given fact, policy, label or context changed')
            finally:
                for it in streams:it.close()
    c.require(all(seen[s]==set(edits[s]) for s in edits),'A full declared target or root was absent')
    c.require(errors==0,'The actual task input contains native error values')
    return {'passed':True,'physical_union_checked':count,'native_errors':errors,'all_original_context_preserved':True,
        'declared_edits_checked':sum(map(len,seen.values())),'numeric_primary':'generic all-numeric HALF_UP2dp'}
