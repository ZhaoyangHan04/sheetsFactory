"""Explicit, source-bound twelve-node heterogeneous debugging proposal.

This module only reads evidence and returns an ordinary plan. It does not write
workbooks, run a journal, recalculate, or certify a task or individual activity.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

from openpyxl.formula.tokenizer import Tokenizer

from ..workbook.heterogeneous_contracts import excel

ADAPTER_ID = 'heterogeneous_localized_three_policy_v1'
DESIGN_SHA256 = '31218da2f44f808474a88db6d194df28d9918b260d5ef7e72e16176baf87a357'
SOURCE_MANIFEST_SHA256 = '7d946c7b8be5a1b30405797699c3f500202a1b37140b5090d8c25f968a1e136a'
SOURCE_WORKBOOK_SHA256 = 'c597eef2c6a4a5b78418e30d92fd0cd2a54a34992c2b0f77c4a235b5780413e0'
# Fixed dates are selected before any task/model result. They are not replaced
# when a later counterfactual is ineffective.
SELECTORS = (
 ('Q01','quarter_coupon','S01','E05',6,'cash_coupon','financial'),
 ('Q02','quarter_coupon','S02','E06',5,'cash_coupon','coupon due'),
 ('Q03','quarter_coupon','S03','E05',16,'cash_coupon','coupon due'),
 ('Q04','quarter_coupon','S03','E06',4,'interest_payable_close','financial'),
 ('T01','tax_FIFO','S01','E05',6,'eligible_current_interest','financial'),
 ('T02','tax_FIFO','S03','E06',1,'eligible_current_interest','financial'),
 ('T03','tax_FIFO','S02','E01',6,'interest_vintages','expired'),
 ('T04','tax_FIFO','S02','E03',12,'loss_vintages','expired'),
 ('V01','covenant_timing_cure','S01','E04',5,'trap_operative','financial'),
 ('V02','covenant_timing_cure','S03','E06',14,'trap_operative','financial'),
 ('V03','covenant_timing_cure','S01','E05',0,'trap_next','provisional restriction next'),
 ('V04','covenant_timing_cure','S03','E02',3,'trap_next','provisional restriction next'),
)
PENDING = ('actual_joint_mutant_recalculation','two_pass_typed_mutant_stability',
 'complete_whole_workbook_D','three_actual_family_effects','native_guards',
 'five_local_controls','independent_public_recovery','twelve_quality_checks',
 'actual_Harbor_oracle_nop','difficulty')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(value):
    path = Path(value).absolute()
    _require(path == path.resolve(strict=True) and path.is_file(), 'Use a real regular artifact, without symlink aliases')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''): digest.update(block)
    after = path.stat()
    _require((before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
             (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'Artifact changed during hashing')
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':after.st_size}


def checked(record):
    _require(isinstance(record,dict) and set(record)=={'path','sha256','bytes'}
        and type(record['bytes']) is int and record['bytes']>=0, 'A complete immutable reference is required')
    _require(reference(record['path'])==record, 'Artifact SHA, size or path changed')
    return Path(record['path'])


def _read(record):
    path = checked(record) if isinstance(record,dict) else checked(reference(record))
    def unique(pairs):
        result = {}
        for key,value in pairs:
            _require(key not in result, 'Duplicate JSON key')
            result[key]=value
        return result
    value=json.loads(path.read_text(),object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    _require(isinstance(value,dict), 'An object artifact is required')
    return value


def setting(*, enabled=False):
    _require(type(enabled) is bool, 'enabled must be an explicit Boolean')
    return {'adapter':ADAPTER_ID,'version':1,'enabled':enabled,'design_sha256':DESIGN_SHA256,
        'source_manifest_sha256':SOURCE_MANIFEST_SHA256,'physical_roots':12}


def validate_setting(value):
    _require(isinstance(value,dict) and type(value.get('enabled')) is bool
        and type(value.get('version')) is int and value==setting(enabled=value['enabled']),
        'Only the exact fixed localized policy is supported')
    _require(value['enabled'] is True, 'Localized debugging is disabled by default')
    return deepcopy(value)


def _ref(row):
    match=re.fullmatch(r'([A-Z]+)([1-9][0-9]*)',row['cell'])
    _require(match is not None, 'A physical A1 cell is required')
    return "'"+row['sheet'].replace("'","''")+"'!$"+match[1]+'$'+match[2]


def _tree(value):
    return [_tree(v) for v in value] if isinstance(value,(tuple,list)) else value


def _replace(tree, before, after):
    if tree==before:return deepcopy(after),1
    if not isinstance(tree,list):return tree,0
    result=[];count=0
    for item in tree:
        changed,n=_replace(item,before,after);result.append(changed);count+=n
    return result,count


def _signature(formula):
    # Only exact numeric lexical equivalence is permitted after source LO.
    return [(t.type,t.subtype,Decimal(t.value) if t.type=='OPERAND' and t.subtype=='NUMBER' else t.value)
            for t in Tokenizer(formula).items if t.type!='WHITE-SPACE']


class _Locator:
    def __init__(self,public,bindings):
        self.public=public;self.bindings=bindings
        self.arithmetic={}
        for row in bindings['arithmetic_bindings']:
            key=(row['sheet'],row['cell'])
            _require(key not in self.arithmetic,'Duplicate physical arithmetic binding')
            _require(row['formula']=='='+excel.expression_formula(row['expression']), 'Formula and bound expression differ')
            self.arithmetic[key]=row
        _require(len(self.arithmetic)==bindings['formula_count'], 'Incomplete arithmetic coverage')
        self.financial={};self.labels={};self.inputs={}
        for row in bindings['financial_bindings']:
            key=(row['sheet'],row['cell']);actual=self.arithmetic.get(key)
            _require(actual is not None and actual['formula']==row['formula'] and actual['expression']==row['expression'],
                'Financial binding differs from same-cell arithmetic')
            if row['cell'].startswith('B'):
                identity=(tuple(row['expected_path']),row.get('vintage_origin'),row.get('vintage_field'))
                _require(identity not in self.financial,'Duplicate internal financial identity')
                self.financial[identity]=row
        for row in bindings['literal_bindings']:
            key=(row['sheet'],row['cell'])
            _require(key not in self.labels,'Duplicate literal cell')
            self.labels[key]=row['value']
        for row in bindings['input_bindings']:
            key=tuple(row['path'])
            _require(key not in self.inputs,'Duplicate provided input identity')
            self.inputs[key]=row

    def owner(self,sid,eid,t,field):return ['scenarios',sid,'entities',eid,'monthly',t,field]

    def field(self,sid,eid,t,field):
        path=self.owner(sid,eid,t,field)
        _require((tuple(path),None,None) in self.financial, 'Missing internal financial field')
        return self.financial[(tuple(path),None,None)]

    def helper(self,sid,eid,t,field,label):
        month=self.public['months'][t];owner=self.owner(sid,eid,t,field)
        matches=[r for r in self.arithmetic.values() if r['sheet']==sid+' Calculations'
            and r['cell'].startswith('B') and r.get('semantic_owner')==owner
            and self.labels.get((r['sheet'],'A'+r['cell'][1:]))==label.format(eid=eid,month=month)]
        _require(len(matches)==1,'Owned helper label/AST role is not unique')
        return matches[0]

    def ancestor(self,ancestor,target):
        wanted=_ref(ancestor);stack=[_tree(target['expression'])];seen=set()
        byref={_ref(row):row for row in self.arithmetic.values()}
        while stack:
            node=stack.pop()
            if isinstance(node,list):stack.extend(node)
            elif isinstance(node,str):
                if node==wanted:return True
                if node in byref and node not in seen:
                    seen.add(node);stack.append(_tree(byref[node]['expression']))
        return False


def _mutate(locator,selector,row):
    identifier,_,sid,eid,t,field,_=selector
    before=_tree(row['expression'])
    r=lambda name:_ref(locator.field(sid,eid,t,name))
    if identifier=='Q01':
        _require(len(before)==4 and before[0]=='if' and before[2]==['sum',r('interest_payable_open'),r('interest_accrual')] and before[3]==0,'Coupon stock/flow shape changed')
        after=deepcopy(before);after[2]=r('interest_accrual')
    elif identifier=='Q02':
        _require(len(before)==4 and before[0]=='if' and before[3]==0 and before[2][0]=='if' and before[2][2]==1,
            'Quarterly coupon maturity branch changed')
        selected=locator.helper(sid,eid,t,'term_id','L06 {month} effective next_coupon_month')
        initial=_ref(locator.inputs[('loans',5,'terms',0,'next_coupon_month')])
        after=deepcopy(before);after[2][3],count=_replace(after[2][3],_ref(selected),initial)
        _require(count==3,'The effective coupon date must occur in comparison, year and month')
    elif identifier=='Q03':
        _require(len(before)==4 and before[0]=='if' and before[3]==0 and len(before[2])==4 and before[2][0]=='if' and before[2][2]==1,'Maturity override shape changed')
        after=['if',before[1],before[2][3],0]
    elif identifier=='Q04':
        _require(before==['sub',['sum',r('interest_payable_open'),r('interest_accrual')],r('cash_coupon')],'Accrued-interest close shape changed')
        after=['sub',r('interest_accrual'),r('cash_coupon')]
    elif identifier in {'T01','T02'}:
        _require(before==['if',['eq',r('tax_policy'),'ACCRUAL_MONTHLY'],r('interest_accrual'),r('cash_coupon')],'Tax-basis policy shape changed')
        after=r('cash_coupon' if identifier=='T01' else 'interest_accrual')
    elif identifier in {'T03','T04'}:
        _require(len(before)==4 and before[0]=='if' and before[3]==0 and before[1][0]=='lt' and len(before[1])==3,'FIFO expiry comparator changed')
        key='interest_carry_months' if identifier=='T03' else 'loss_carry_months'
        index=int(eid[1:])-1
        _require(before[1][1]==_ref(locator.inputs[('entities',index,key)]) and before[1][2][0]=='sub','FIFO expiry age/carry binding changed')
        after=deepcopy(before);after[1][0]='le'
    elif identifier in {'V01','V02'}:
        failure=['and',r('test_applicable'),['eq',r('test_pass'),0]]
        monthly=['eq',r('dscr_policy'),'MONTHLY_CURRENT']
        branch=['if',monthly,['if',['or',r('trap_open'),failure],1,0],r('trap_open')]
        _require(len(before)==4 and before[0]=='if' and before[2]==0 and before[3]==branch,'Operative restriction timing shape changed')
        after=deepcopy(before);after[3]=r('trap_open') if identifier=='V01' else branch[2]
    elif identifier=='V03':
        cure=locator.helper(sid,eid,t,'cure_next','{eid} {month} provisional cure next')
        after,count=_replace(before,['lt',_ref(cure),2],['lt',_ref(cure),1])
        _require(count==1,'Observed-pass cure threshold changed')
    else:
        _require(identifier=='V04' and len(before)==4 and before[0]=='if' and before[1]==r('facility_closed_open') and before[2]==0
            and before[3][0]=='if' and before[3][1]==r('test_applicable') and before[3][3]==r('trap_open'),'Non-test restriction persistence shape changed')
        after=deepcopy(before);after[3][3]=0
    _require(after!=before,'A syntactic policy mutation is required')
    return after


def compile_mutations(public,bindings):
    """Pure, uncalculated twelve-edit compiler; not source admission or activity."""
    _require(len(public['months'])==24 and len(public['entities'])==6 and len(public['scenarios'])==3,
        'The declared six-entity, 24-month, three-scenario scope is required')
    locator=_Locator(public,bindings);edits=[];metadata=[]
    for selector in SELECTORS:
        identifier,family,sid,eid,t,field,role=selector
        if role=='financial':row=locator.field(sid,eid,t,field)
        elif role=='expired':
            identity=(tuple(['scenarios',sid,field,eid,'monthly',t]),'2027-01-01','expired')
            _require(identity in locator.financial,'The oldest eligible vintage node is missing')
            row=locator.financial[identity]
        else:
            row=locator.helper(sid,eid,t,field,'{eid} {month} '+role)
            _require(locator.ancestor(row,locator.field(sid,eid,t,field)), 'Selected helper is not a causal ancestor')
        _require(row['sheet']==sid+' Calculations' and re.fullmatch(r'B[1-9][0-9]*',row['cell']), 'Display aliases cannot be fault roots')
        after='='+excel.expression_formula(_mutate(locator,selector,row))
        _require(after!=row['formula'],'Fault compiler produced an unchanged formula')
        edits.append({'sheet':row['sheet'],'cell':row['cell'],'before':row['formula'],'after':after})
        metadata.append({'id':identifier,'family':family,'scenario':sid,'entity':eid,'month':public['months'][t],
            'sheet':row['sheet'],'cell':row['cell'],'before_expression_sha256':canonical(row['expression']),
            'individual_activity_claimed':False})
    _require(len({(e['sheet'],e['cell']) for e in edits})==12,'Root locations overlap')
    return edits,metadata


def _formula_subset(path,locations):
    wanted={};namespace={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        relations=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        byid={r.attrib['Id']:r.attrib['Target'] for r in relations}
        for sheet in workbook.find('s:sheets',namespace):
            name=sheet.attrib['name']
            cells={cell for s,cell in locations if s==name}
            if not cells:continue
            rid=sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            target=byid[rid];member=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            with archive.open(member) as stream:
                for _,element in ET.iterparse(stream,events=('end',)):
                    if element.tag.endswith('}c'):
                        if element.attrib.get('r') in cells:
                            f=element.find('s:f',namespace)
                            _require(f is not None and f.text is not None,'An asserted root is not a physical formula')
                            wanted[(name,element.attrib['r'])]='='+f.text
                        element.clear()
    _require(set(wanted)==set(locations),'An asserted root is absent from the audited workbook')
    return wanted


def _source(source_proof,normalized_path):
    manifest_ref=source_proof if isinstance(source_proof,dict) else reference(source_proof)
    _require(manifest_ref.get('sha256')==SOURCE_MANIFEST_SHA256,'Only the prospectively bound actual v2 source is supported')
    manifest=_read(manifest_ref)
    _require(manifest.get('kind')=='independently_verified_heterogeneous_contract_source'
        and type(manifest.get('version')) is int and manifest['version']==1
        and manifest.get('scope')=={'entities':6,'months':24,'scenarios':3}
        and manifest.get('actual_LO_recalculations')==3 and manifest.get('qualified') is False,
        'The verified source scope or source-only contract differs')
    original=manifest['workbook'];checked(original)
    actual=reference(normalized_path)
    _require(original['sha256']==SOURCE_WORKBOOK_SHA256 and (actual['sha256'],actual['bytes'])==(original['sha256'],original['bytes']),
        'Normalized source differs from the audited source bytes')
    recipe=manifest['source_recipe_sha256']
    _require(isinstance(recipe,dict) and len(recipe)>=6 and canonical(recipe)==manifest['source_recipe_digest'], 'Source recipe is incomplete')
    for path,digest in recipe.items():_require(reference(path)['sha256']==digest,'Source recipe changed')
    public=_read(manifest['private_specification']);bindings=_read(manifest['bindings'])
    _require(canonical(public)==manifest['specification_sha256']==bindings['specification_sha256'], 'Source primitives and bindings differ')
    checked(manifest['independent_ledger']);checked(manifest['source_preparation']);checked(manifest['geometry']);checked(manifest['mechanism_coverage']);checked(manifest['runtime_profile'])
    _require(len(manifest['financial_audits'])==len(manifest['engine_calls'])==3,'Three actual source calls/audits are required')
    outputs=[]
    for index,(call,audit_ref) in enumerate(zip(manifest['engine_calls'],manifest['financial_audits'])):
        _require(call.get('completed') is True and call.get('index')==index+1,'Source call ordering or terminal status differs')
        checked(call['input']);checked(call['output']);outputs.append(call['output'])
        if index:_require(call['input']==outputs[index-1],'Source actual recalculation chain is broken')
        report=_read(audit_ref)
        _require(report.get('passed') is True and report.get('all_values_checked') is True and report.get('mismatch_count')==report.get('native_error_count')==0
            and report.get('audited_file')==call['output'] and report.get('bindings_sha256')==canonical(bindings)
            and report.get('specification_sha256')==canonical(public)
            and report.get('physical_formulas_checked')==bindings['formula_count']
            and report.get('financial_journal_fields_checked')==len(bindings['financial_bindings']), 'Actual complete financial/cache audit is not bound')
        checked(call['started_receipt']);checked(call['terminal_receipt'])
        evidence=call['actual_resource_evidence'];checked(evidence['started']);terminal=_read(evidence['terminal'])
        _require(terminal.get('actual_resources_verified') is True and terminal.get('source')==call['input'] and terminal.get('output')==call['output']
            and terminal.get('profile')==manifest['runtime_profile'] and terminal.get('image_id')==manifest['runtime']['image_id']
            and terminal.get('actual_resources')=={'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256}, 'Actual source resources are unbound')
    _require(outputs[0]==original,'Source goal is not the first actual audited pass')
    stable=_read(manifest['stability'])
    _require(stable.get('kind')=='three_actual_pass_full_typed_stability' and stable.get('stable') is True and len(stable['comparisons'])==2,'Actual source stability is incomplete')
    for index,item in enumerate(stable['comparisons'],1):
        comparison=item['comparison']
        _require(item['left']==outputs[0] and item['right']==outputs[index] and comparison.get('passed') is True
            and comparison.get('entire_value_union_checked') is True and comparison.get('typed_value_mismatches')==0
            and type(comparison.get('union_cells_checked')) is int and comparison['union_cells_checked']>0,'Actual typed source stability is unbound')
    return manifest_ref,manifest,public,bindings


def _assert_current_source(manifest_ref,manifest,normalized_path):
    checked(manifest_ref);checked(manifest['bindings']);checked(manifest['workbook'])
    actual=reference(normalized_path);original=manifest['workbook']
    _require((actual['sha256'],actual['bytes'])==(original['sha256'],original['bytes']), 'Source changed while planning')
    for path,digest in manifest['source_recipe_sha256'].items():
        _require(reference(path)['sha256']==digest,'Source recipe changed while planning')


def public_instruction():
    return ('Audit and repair the existing heterogeneous debt, tax and covenant model against its supplied contracts. '
        'The supplied investment, operating and contract assumptions are fixed inputs. Preserve the legitimate differences '
        'between facilities, tax regimes, covenant calendars and effective contract terms. Correct the financial schedules '
        'and connected results without changing those assumptions. Keep the original worksheet names and order; '
        'repair existing model cells only, preserve unrelated formulas and supplied literals, do not add helpers, '
        'and leave non-applicable covenant displays blank as specified in the policy notes. '
        'Read /app/input.xlsx and save the repaired workbook to /app/output.xlsx. Results are checked after recalculation.')


def propose_debugging_task(normalized_path,policy=None,*,source_proof):
    """Return a private, unexecuted ordinary DBG plan after explicit admission."""
    policy=validate_setting(setting() if policy is None else policy)
    recipe={'provider':reference(__file__),'emitter':reference(excel.__file__)}
    manifest_ref,manifest,public,bindings=_source(source_proof,normalized_path)
    edits,roots=compile_mutations(public,bindings)
    actual=_formula_subset(normalized_path,{(r['sheet'],r['cell']) for r in edits})
    for edit in edits:
        before=actual[(edit['sheet'],edit['cell'])]
        _require(_signature(before)==_signature(edit['before']),'Audited physical before formula differs from its semantic binding')
        edit['before']=before
        _require(_signature(before)!=_signature(edit['after']),'The actual source normalization removed a physical mutation')
    _assert_current_source(manifest_ref,manifest,normalized_path)
    _require(recipe=={'provider':reference(__file__),'emitter':reference(excel.__file__)},'Task compiler recipe changed')
    return {'edits':edits,'public_instruction':public_instruction(),'public_rules':[], 'assumptions_added':[],
        'family_adapter':{'id':ADAPTER_ID,'policy':policy,'source_manifest':manifest_ref,'audited_source':manifest['workbook'],
            'bindings':manifest['bindings'],'recipe':recipe,'root_count':12,'policy_family_count':3,'roots':roots,
            'edits_sha256':canonical(edits),'individual_root_activity_claimed':False,
            'pending':{name:True for name in PENDING},'quality_or_difficulty_certified':False}}
