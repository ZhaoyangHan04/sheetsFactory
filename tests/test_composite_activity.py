"""Activity algorithm tests use a fixture calculator, never actual LO evidence."""
from copy import deepcopy
import hashlib
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

import openpyxl
from openpyxl.formula import Tokenizer
import pytest

from sheets_factory.workbook.composite_finance.activity import (
    qualify_original_formula, screen_composite_activity,
)


class FixtureEngine:
    """Small offline arithmetic cache fixture; not a financial oracle."""
    def __init__(self, fault=None):
        self.calls=[];self.fault=fault

    def metadata(self):
        return {'backend':'libreoffice_uno_docker','network':'none','image_id':'sha256:'+'a'*64,
                'version':'TEST FIXTURE ONLY','macro_execution':'never','external_updates':'never'}

    def recalculate(self, raw, output):
        self.calls.append((Path(raw),Path(output)))
        book=openpyxl.load_workbook(raw);memo={};active=set()
        def value(sheet,address):
            key=sheet,address.replace('$','')
            if key in memo:return memo[key]
            if key in active:raise ValueError('Fixture cycle')
            active.add(key);cell=book[sheet][key[1]]
            if cell.data_type!='f':answer=cell.value or 0
            else:
                expression=''
                for token in Tokenizer(cell.value).items:
                    if token.type=='OPERAND' and token.subtype=='RANGE':
                        sn,ref=(token.value.rsplit('!',1) if '!' in token.value else (sheet,token.value))
                        if sn.startswith("'"):sn=sn[1:-1].replace("''", "'")
                        expression+=repr(value(sn,ref))
                    elif token.type=='FUNC' and token.subtype=='OPEN':
                        expression+=token.value.lower()
                    elif token.type=='SEP':expression+=','
                    else:expression+=token.value
                answer=eval(expression,{'__builtins__':{}},{'round':round,'min':min,'max':max,'row':lambda:cell.row})
            active.remove(key);memo[key]=answer;return answer
        sheets=book.sheetnames
        for sheet in book:
            for cell in list(sheet._cells.values()):
                if cell.data_type=='f':value(sheet.title,cell.coordinate)
        if self.fault=='shadow' and 'private_shadow' in Path(output).name:memo[('Model','A1')]+=.01
        if self.fault=='bulk' and 'combined_v2' in Path(output).name:memo[('Model','C1')]+=.01
        book.close();ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        with ZipFile(raw) as source, ZipFile(output,'w',ZIP_DEFLATED) as target:
            for item in source.infolist():
                payload=source.read(item.filename)
                match=re.fullmatch(r'xl/worksheets/sheet([0-9]+)\.xml',item.filename)
                if match:
                    sn=sheets[int(match.group(1))-1];xml=ET.fromstring(payload)
                    for cell in xml.iter(ns+'c'):
                        key=sn,cell.attrib['r']
                        if cell.find(ns+'f') is None or key not in memo:continue
                        cached=cell.find(ns+'v')
                        if cached is None:cached=ET.SubElement(cell,ns+'v')
                        cached.text=str(memo[key]);cell.attrib.pop('t',None)
                    payload=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
                target.writestr(item,payload)
        return output


def fixture(tmp_path,*,position=False):
    book=openpyxl.Workbook();book.active.title='Model';book.create_sheet('Inputs')['B1']=10
    formulas={'A1':'=Inputs!B1','B1':'=A1*2','C1':'=Inputs!B1*3'}
    changes={'A1':'=Inputs!B1*2','B1':'=A1+Inputs!B1*2','C1':'=Inputs!B1*4'}
    if position:formulas['D3']='=ROW()';changes['D3']='=ROW()*2'
    for address,formula in formulas.items():book['Model'][address]=formula
    path=tmp_path/'source.xlsx';book.save(path);book.close()
    edits=[{'sheet':'Model','cell':a,'before':f,'after':changes[a],'mechanism':'fixture_policy'} for a,f in formulas.items()]
    proposal={'public_instruction':'Public original text','public_rules':['Keep supplied policies.'],
              'edits':edits,'root_impact_batches':[[0],[1],[2]],'root_impact_batch_planning':{'old':True}}
    return path,proposal


def test_joint_activity_detects_cancellation_and_rechecks_bulk_values(tmp_path):
    path,plan=fixture(tmp_path);original=path.read_bytes();caller=deepcopy(plan);engine=FixtureEngine()
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity')
    receipt=result['receipt']
    assert receipt['passed'] and not receipt['blocking'] and receipt['state']=='screened'
    assert receipt['actual_LO_execution_count']==3 and len(engine.calls)==3
    assert receipt['inactive_root_indices']==[1] and receipt['retained_root_count']==2
    assert receipt['authoring_attempts_used']==2 and receipt['max_authoring_attempts']==3
    assert receipt['all_original_sheet_values_unchanged_after_bulk_removal']
    assert [e['cell'] for e in result['plan']['edits']]==['A1','C1']
    assert 'root_impact_batches' not in result['plan'] and 'root_impact_batch_planning' not in result['plan']
    assert result['plan']['public_instruction']==plan['public_instruction']
    assert plan==caller and path.read_bytes()==original
    final=openpyxl.load_workbook(result['combined_input'])
    assert final.sheetnames==['Model','Inputs'] and final['Model']['B1'].value=='=A1*2'
    final.close()
    assert receipt['final_root_impact_certified'] is False and receipt['model_calls']==0


def test_qualification_rewrites_only_range_tokens_and_preserves_strings_anchors():
    result=qualify_original_formula('=IF($A1="A1",SUM(B2:$C$4),\'Other Sheet\'!D5)',"Owner's Ledger")
    assert result=='=IF(\'Owner\'\'s Ledger\'!$A1="A1",SUM(\'Owner\'\'s Ledger\'!B2:$C$4),\'Other Sheet\'!D5)'


@pytest.mark.parametrize('formula',['=ROW()','=COLUMN(A1)','=CELL("filename")','=INDIRECT("A1")',
                                    '=OFFSET(A1,1,0)','=NOW()','=SHEETS()','=UNKNOWN(A1)','=SomeName'])
def test_position_dynamic_unknown_and_unresolved_shadows_need_fallback(formula):
    with pytest.raises(ValueError):qualify_original_formula(formula,'Model')


def test_position_fallback_is_recorded_and_never_silently_removed(tmp_path):
    path,plan=fixture(tmp_path,position=True);engine=FixtureEngine()
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity')
    assert not result['receipt']['passed'] and result['receipt']['state']=='requires_single_root_fallback'
    assert result['receipt']['fallback_roots'][0]['root']=='Model!D3'
    assert result['plan']==plan and result['combined_input'] is None and len(engine.calls)==2


def test_explicit_single_root_fallback_executes_in_original_cell(tmp_path):
    path,plan=fixture(tmp_path,position=True);engine=FixtureEngine()
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity',execute_fallback=True)
    assert result['receipt']['passed'] and len(engine.calls)==4
    rec=next(r for r in result['receipt']['root_records'] if r['root']=='Model!D3')
    assert rec['activity_method']=='actual_single_root_full_context_restoration'
    assert rec['current_normalized_value']==['number','6.00'] and rec['restored_normalized_value']==['number','3.00']


def test_union_graph_rejects_a_cycle_absent_in_each_endpoint_graph(tmp_path):
    path,plan=fixture(tmp_path)
    book=openpyxl.load_workbook(path);book['Model']['A1']='=B1';book['Model']['B1']='=Inputs!B1';book.save(path);book.close()
    plan['edits']=[{'sheet':'Model','cell':'A1','before':'=B1','after':'=Inputs!B1'},
                   {'sheet':'Model','cell':'B1','before':'=Inputs!B1','after':'=A1'}]
    engine=FixtureEngine();result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity')
    assert not result['receipt']['passed'] and 'union graph' in result['receipt']['reason']
    assert not engine.calls and result['plan']==plan


@pytest.mark.parametrize('fault,reason',[('shadow','witness addition changed'),('bulk','Bulk root removal changed')])
def test_any_original_sheet_change_blocks_acceptance_and_retains_evidence(tmp_path,fault,reason):
    path,plan=fixture(tmp_path);engine=FixtureEngine(fault)
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity')
    assert not result['receipt']['passed'] and reason in result['receipt']['reason']
    assert result['plan']==plan and result['combined_input'] is None
    assert (tmp_path/'activity/activity_receipt.json').is_file()
    assert all(item['actual_execution_completed'] for item in result['receipt']['engine_calls'])


def test_authoring_attempt_budget_does_not_allow_an_unverified_pruning_revision(tmp_path):
    path,plan=fixture(tmp_path);engine=FixtureEngine()
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'activity',max_authoring_attempts=1)
    assert result['receipt']['state']=='authoring_attempt_limit' and result['plan']==plan
    assert len(engine.calls)==2 and result['receipt']['authoring_attempts_used']==1


def test_directory_no_overwrite_before_assertions_and_bounds_fail_closed(tmp_path):
    path,plan=fixture(tmp_path);engine=FixtureEngine();directory=tmp_path/'exists';directory.mkdir();(directory/'marker').write_text('keep')
    with pytest.raises(FileExistsError):screen_composite_activity(path,plan,engine=engine,directory=directory)
    assert (directory/'marker').read_text()=='keep'
    bad=deepcopy(plan);bad['edits'][0]['before']='=3'
    result=screen_composite_activity(path,bad,engine=engine,directory=tmp_path/'bad')
    assert not result['receipt']['passed'] and 'assert' in result['receipt']['reason'] and not engine.calls
    result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'bounded',max_dependency_cells=2)
    assert not result['receipt']['passed'] and 'bound' in result['receipt']['reason'] and not engine.calls


@pytest.mark.parametrize('limit',[0,4,True,'3'])
def test_maximum_three_attempts_is_a_strict_configuration_contract(tmp_path,limit):
    with pytest.raises(ValueError,match='one through three'):
        screen_composite_activity(tmp_path/'absent.xlsx',{},engine=FixtureEngine(),directory=tmp_path/'out',max_authoring_attempts=limit)


def test_inherited_cumulative_attempt_budget_is_not_reset(tmp_path):
    path,plan=fixture(tmp_path);plan['candidate_repair']={'attempt_number':3}
    engine=FixtureEngine();result=screen_composite_activity(path,plan,engine=engine,directory=tmp_path/'limited')
    assert result['receipt']['state']=='authoring_attempt_limit'
    assert result['receipt']['authoring_attempts_used']==3 and len(engine.calls)==2
    plan['candidate_repair']['attempt_number']=2
    result=screen_composite_activity(path,plan,engine=FixtureEngine(),directory=tmp_path/'last')
    assert result['receipt']['passed'] and result['receipt']['authoring_attempts_used']==3
    assert result['plan']['activity_authoring']['authoring_attempts_used']==3
    assert result['receipt']['implementation_sha256']==hashlib.sha256(Path(__import__('sheets_factory.workbook.composite_finance.activity',fromlist=['x']).__file__).read_bytes()).hexdigest()


def test_explicit_attempt_cannot_exceed_three_and_bad_inheritance_is_not_coerced(tmp_path):
    path,plan=fixture(tmp_path)
    with pytest.raises(ValueError,match='cumulative'):
        screen_composite_activity(path,plan,engine=FixtureEngine(),directory=tmp_path/'bad',authoring_attempt_number=4)
    plan['candidate_repair']={'attempt_number':3}
    with pytest.raises(ValueError,match='cumulative'):
        screen_composite_activity(path,plan,engine=FixtureEngine(),directory=tmp_path/'reset',authoring_attempt_number=1)
    plan['candidate_repair']={'attempt_number':True}
    with pytest.raises(ValueError,match='integers'):
        screen_composite_activity(path,plan,engine=FixtureEngine(),directory=tmp_path/'bool')
