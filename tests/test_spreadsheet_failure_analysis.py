"""Pure OOXML/JSON fixtures: no calculation, evaluator, model, or service calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from sheets_factory.evaluation import spreadsheet_failure_analysis as a


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Offline analysis must not execute services")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def book(path, sheets, *, fonts=None, font_ids=None, date1904=False):
    """Cells are (type, value, optional attributes); formula values=(text,cache)."""
    fonts = fonts or ['<font><color rgb="FF000000"/></font>']
    font_ids = font_ids or list(range(len(fonts)))
    wb=ET.Element("workbook", xmlns=a.S); ET.SubElement(wb,"workbookPr", date1904="1" if date1904 else "0")
    ss=ET.SubElement(wb,"sheets");rels=ET.Element("Relationships",xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    with ZipFile(path,"w") as z:
        z.writestr("xl/styles.xml",'<styleSheet xmlns="'+a.S+'"><fonts count="'+str(len(fonts))+'">'+''.join(fonts)+'</fonts><cellXfs count="'+str(len(font_ids))+'">'+''.join('<xf fontId="'+str(i)+'" numFmtId="0"/>' for i in font_ids)+'</cellXfs></styleSheet>')
        for index,(name,cells) in enumerate(sheets.items(),1):
            ET.SubElement(ss,"sheet",name=name,sheetId=str(index),attrib={"{"+a.R+"}id":"rId"+str(index)})
            ET.SubElement(rels,"Relationship",Id="rId"+str(index),Target="worksheets/sheet"+str(index)+".xml")
            ws=ET.Element("worksheet",xmlns=a.S);data=ET.SubElement(ws,"sheetData");row=ET.SubElement(data,"row",r="1")
            for address,record in cells.items():
                typ,value,*attrs=record;attributes={"r":address,**(attrs[0] if attrs else {})}
                if typ!="f":attributes["t"]="inlineStr" if typ=="s" else typ
                c=ET.SubElement(row,"c",attributes)
                if typ=="f":
                    formula,cached=value;fattrs=attributes.pop("fattrs",{}) if "fattrs" in attributes else {}
                    f=ET.SubElement(c,"f",fattrs);f.text=formula
                    if cached is not None:ET.SubElement(c,"v").text=str(cached)
                elif typ=="s":ET.SubElement(ET.SubElement(c,"is"),"t").text=value
                elif value is not None:ET.SubElement(c,"v").text=str(value)
            z.writestr("xl/worksheets/sheet"+str(index)+".xml",ET.tostring(ws))
        z.writestr("xl/workbook.xml",ET.tostring(wb));z.writestr("xl/_rels/workbook.xml.rels",ET.tostring(rels))
    return path


@pytest.fixture
def evidence(tmp_path):
    source=book(tmp_path/"input.xlsx",{"Main":{"A1":("n",2),"A2":("n",3),"B1":("f",("A1+A1",4)),"C1":("f",("A1",2))}})
    goal=book(tmp_path/"goal.xlsx",{"Main":{"A1":("n",2),"A2":("n",3),"B1":("f",("A1+A2",5)),"C1":("f",("A1",2))}})
    output=book(tmp_path/"output.xlsx",{"Main":{"A1":("n",20),"A2":("n",3),"B1":("f",("SUM(A1,A2)",23)),"C1":("f",("A1",20))}})
    manifest={"kind":"spreadsheet_failure_analysis_case","version":1,"case_id":"Debugging/01_01","mode":"debugging","source":source,"reference":goal,"output":output,"public_instruction":"Please audit this file thoroughly and fix any other issues."}
    return manifest


def test_root_equivalence_does_not_hide_upstream_error_or_declare_business_failure(evidence):
    r=a.analyze(evidence)
    assert r["summary"]["intended_definition_changes"]==1
    root=r["intended_root_output_status"][0]
    assert root["conditional_additive_equivalence"]["does_not_prove_upstream_values_correct"]
    assert not root["reference_output_cache_equal"]
    assert r["summary"]["extra_existing_definition_changes"]==1
    assert r["observed_business_error_established"] is False
    assert next(x for x in r["cause_findings"] if x["label"]=="scoring_ambiguity")["status"]=="supported_scope_policy_ambiguity_hypothesis"


def test_missing_caches_remain_unknown_and_no_output_remains_unknown(evidence,tmp_path):
    evidence["source"]=book(tmp_path/"uncached.xlsx",{"Main":{"B1":("f",("A1+A1",None))}})
    r=a.analyze(evidence)
    assert r["source_cache_status"]["missing_formula_caches"]==1
    assert any(x["cell"]=="B1" for x in r["cached_value_diagnostics"]["unknown_cache_points"])
    del evidence["output"]
    r=a.analyze(evidence)
    assert r["completion"]=="no_submitted_output_bound"
    assert all(x["business_error_established"] is False for x in r["cause_findings"])


def test_raw_numeric_noise_separate_from_declared_analysis_rounding(evidence,tmp_path):
    evidence["output"]=book(tmp_path/"noise.xlsx",{"Main":{"B1":("f",("A1+A2","5.000000000001"))}})
    evidence["analysis_numeric_quantum"]="0.01"
    r=a.analyze(evidence);d=r["cached_value_diagnostics"]
    assert any(x["cell"]=="B1" for x in d["raw_only_reference_output_differences"])
    assert not r["official_score_recomputed"]


def test_baseline_must_retain_input_definitions(evidence,tmp_path):
    evidence["baseline_cache"]=book(tmp_path/"bad_baseline.xlsx",{"Main":{"A1":("n",200)}})
    r=a.analyze(evidence)
    assert any(x["issue"]=="baseline_cached_workbook_definitions_differ" for x in r["holds"])


def test_shared_formula_followers_and_no_cache_not_empty(tmp_path):
    p=book(tmp_path/"shared.xlsx",{"Main":{"A1":("f",("B1",1)),"A2":("f",("",None))}})
    # Modify only the fixture to build an authentic shared-master/follower pair.
    with ZipFile(p) as z:parts={n:z.read(n) for n in z.namelist()}
    x=ET.fromstring(parts['xl/worksheets/sheet1.xml']);cells=x.findall('{*}sheetData/{*}row/{*}c')
    for cell in cells:cell.find('{*}f').set('t','shared');cell.find('{*}f').set('si','0')
    parts['xl/worksheets/sheet1.xml']=ET.tostring(x)
    with ZipFile(p,'w') as z:
        for n,b in parts.items():z.writestr(n,b)
    r=a.workbook(p)
    assert r['cells']['Main']['A2']['definition']['formula']=='B2'
    assert r['cells']['Main']['A2']['cached']['type']=='unknown_cache'


def test_style_index_reordering_does_not_create_font_change(tmp_path):
    fonts=['<font><color rgb="FF000000"/></font>','<font><color rgb="FF0000FF"/></font>']
    left=book(tmp_path/'left.xlsx',{'Main':{'A1':('n',2,{'s':'1'})}},fonts=fonts)
    right=book(tmp_path/'right.xlsx',{'Main':{'A1':('n',2,{'s':'0'})}},fonts=fonts,font_ids=[1,0])
    assert a.font_diff(a.workbook(left),a.workbook(right))['changes']==[]
    changed=book(tmp_path/'changed.xlsx',{'Main':{'A1':('n',2)}},fonts=fonts)
    d=a.font_diff(a.workbook(left),a.workbook(changed))
    assert d['raw_color_tree_changes']==1 and d['does_not_establish_financial_error']


def test_font_witness_bound_keeps_exact_counts_and_deterministic_digest(tmp_path):
    cells={'A'+str(i):('n',i) for i in range(1,8)}
    left=book(tmp_path/'left.xlsx',{'Main':cells},fonts=['<font><color rgb="FF000000"/></font>'])
    right=book(tmp_path/'right.xlsx',{'Main':cells},fonts=['<font><color rgb="FF0000FF"/></font>'])
    x,y=a.workbook(left),a.workbook(right);small=a.font_diff(x,y,example_limit=2);full=a.font_diff(x,y,example_limit=20)
    assert len(small['changes'])==2 and small['examples_truncated']
    assert small['total_font_tree_changes']==small['raw_color_tree_changes']==7
    assert small['all_ordered_change_rows_sha256']==full['all_ordered_change_rows_sha256']


def test_quoted_sheet_comma_and_doubled_quote_regions():
    rows=a.answer_regions("'PP&E, Debt, NWC'!$B$2:L91,'Owner''s model'!A1:B2")
    assert rows[0]['sheet']=='PP&E, Debt, NWC'
    assert rows[1]['sheet']=="Owner's model"
    assert a._in_regions('PP&E, Debt, NWC','L91',rows)
    assert not a._in_regions('PP&E, Debt, NWC','M91',rows)


def inventory(tmp_path,evidence,monkeypatch):
    evaluator=dump(tmp_path/'official_evaluation.py',{'test_revision':1})
    monkeypatch.setattr(a,'OFFICIAL_EVALUATOR_SHA256',a.reference(evaluator)['sha256'])
    cases=[]
    for index,(key,mode,path) in enumerate([('Debugging/01_01','debugging','Double Counting_input.xlsx'),('Debugging/01_02','debugging','Embedded Hardcode_input.xlsx'),('Debugging/01_04','debugging','Inconsistent Color Coding_input.xlsx'),('Financial_Model/01_01','financial_modeling','01_input.xlsx')]):
        cases.append({'case_key':key,'task_id':'task'+str(index),'mode':mode,'category':key.split('/')[0],'input':a.reference(evidence['source']),'goal':a.reference(evidence['reference']),'official_record':{'instruction':evidence['public_instruction'],'spreadsheet_path':path,'answer_position':"'Main'!A1:C2"},'existing_attempt':None})
    return dump(tmp_path/'inventory.json',{'cases':cases,'official_evaluator':a.reference(evaluator)})


@pytest.mark.parametrize('key,formula,color,group',[('Debugging/01_02',True,False,'debugging/embedded_formula'),('Debugging/01_04',False,True,'debugging/color_font'),('Debugging/01_01',False,False,'debugging/ordinary'),('Financial_Model/01_01',False,False,'financial_modeling/ordinary')])
def test_exact_official_groups_and_formula_font_modes(evidence,tmp_path,monkeypatch,key,formula,color,group):
    inv=inventory(tmp_path,evidence,monkeypatch)
    r=a.analyze(a.case_from_inventory(inv,key,output=evidence['output']))
    assert r['evaluator_contract']['with_formula']==formula
    assert r['evaluator_contract']['with_font_color']==color
    assert r['evaluator_contract']['group']==group
    assert not r['observed_business_error_established']


def test_unrecognized_evaluator_is_not_silently_accepted(evidence,tmp_path,monkeypatch):
    inv=inventory(tmp_path,evidence,monkeypatch);manifest=a.case_from_inventory(inv,'task0')
    monkeypatch.setattr(a,'OFFICIAL_EVALUATOR_SHA256','0'*64)
    with pytest.raises(ValueError,match='Unsupported official evaluator'):a.analyze(manifest)


def test_terminal_sanitizes_configuration_exception_and_keeps_scores_separate(evidence,tmp_path):
    secret='CANARY_PRIVATE_CREDENTIAL_DO_NOT_COPY'
    result=dump(tmp_path/'result.json',{'finished_at':'2026-10-31T00:00:00Z','config':{'api_key':secret},'exception_info':{'exception_type':'NonZeroAgentExitCodeError','message':secret},'verifier_result':{'rewards':{'reward':1}}})
    terminal=dump(tmp_path/'terminal.json',{'official_primary':{'result':{'accuracy':0,'regression_accuracy':.97,'modification_accuracy':.74,'error_message':secret}},'protocol_state':'unknown','native_run_complete':False,'project_exact_diagnostic':{'reward':1,'tool_time':{'passed':False,'exact_seconds':42,'configuration':secret}}})
    evidence.update(result=result,case_terminal=terminal)
    r=a.analyze(evidence);text=json.dumps(r)
    assert secret not in text
    assert r['terminal_layers']['native_terminal']['reward']==1
    assert r['terminal_layers']['official_raw_scores']['accuracy']==0
    assert r['terminal_layers']['protocol']['native_run_complete'] is False
    assert r['terminal_layers']['tool_time']['fields']=={'passed':False,'exact_seconds':42}


def test_network_syntax_and_gold_request_do_not_claim_retrieval(evidence,tmp_path):
    trace=dump(tmp_path/'trajectory.json',{'steps':[{'step_id':1,'source':'agent','tool_calls':[{'function_name':'exec_command','arguments':{'input':'print("http://schemas.openxmlformats.org/")'}}]},{'step_id':2,'source':'agent','tool_calls':[{'function_name':'exec_command','arguments':{'input':'curl https://example.com/spreadsheetbench/golden.xlsx -H Authorization:secret'}}]}]})
    r=a.trajectory_summary(trace);text=json.dumps(r)
    assert len(r['request_syntax_observations'])==1
    assert r['possible_external_answer_requests'][0]['step_id']==2
    assert r['observed_external_answer_retrieval']=='not_established_by_syntax_scan'
    assert 'Authorization:secret' not in text


def test_save_freezes_paths_deduplicates_and_detects_changed_refs(evidence,tmp_path):
    root=tmp_path/'reports';before={str(p):a.reference(p) for p in (evidence['source'],evidence['reference'],evidence['output'])}
    one=a.save_analysis(evidence,root);two=a.save_analysis(evidence,root)
    assert one==two
    manifest=a.read(a.read(one)['case_manifest'])
    assert isinstance(manifest['source'],dict)
    assert all(a.reference(p)==ref for p,ref in before.items())
    book(evidence['output'],{'Main':{'A1':('n',999)}})
    with pytest.raises(ValueError,match='Bound evidence changed'):a.analyze(manifest)
    new=a.save_analysis(evidence,root)
    assert new!=one and a.read(one)['report']!=a.read(new)['report']


def test_secret_file_denied_before_read(tmp_path):
    p=tmp_path/'auth.json';p.write_text('DO_NOT_READ')
    with pytest.raises(ValueError,match='Credential'):a.reference(p)


def trial(root,task,output,*,finished=True,valid=True):
    path=root/'harbor_jobs/pass1'/('trial-'+task);path.mkdir(parents=True)
    artifact=path/'artifacts/app/output.xlsx';artifact.parent.mkdir(parents=True);artifact.write_bytes(output.read_bytes())
    result=dump(path/'result.json',{'task_name':'sheetsfactory/'+task,'finished_at':'2026-10-31T00:00:00Z' if finished else None,'verifier_result':{'rewards':{'reward':0}}})
    if not valid:result.write_text('{')
    return result


def test_incremental_scan_skips_active_and_partial_and_handles_prefixed_task_names(evidence,tmp_path,monkeypatch):
    inv=inventory(tmp_path,evidence,monkeypatch);evaluation=tmp_path/'evaluation'
    trial(evaluation,'task0',evidence['output'])
    trial(evaluation,'task1',evidence['output'],finished=False)
    trial(evaluation,'task2',evidence['output'],valid=False)
    scan=a.read(a.scan_completed(inv,evaluation,tmp_path/'reports'))
    assert len(scan['reports'])==1 and len(scan['analysis_errors'])==1
    assert scan['reports'][0]['task_id']=='task0'
    assert scan['unreported_cases_not_treated_as_failures']==3
    assert scan['skipped'][0]['reason']=='trial_not_terminal'
    assert scan['groups']['debugging/ordinary']['official_score_known']==0


def test_cohort_terminal_supersedes_trial_and_groups_scores(evidence,tmp_path,monkeypatch):
    inv=inventory(tmp_path,evidence,monkeypatch);cohort=tmp_path/'cohort';case=cohort/'cases/task0'
    trial(case/'evaluation','task0',evidence['output'])
    terminal={'task_id':'task0','official_primary':{'result':{'accuracy':0,'regression_accuracy':.9,'modification_accuracy':1}},'disposition':'new_first_attempt','project_exact_diagnostic':{'reward':0}}
    dump(case/'terminal.json',terminal)
    first=a.read(a.scan_completed(inv,cohort,tmp_path/'reports'))
    second=a.read(a.scan_completed(inv,cohort,tmp_path/'reports'))
    assert len(first['reports'])==1
    assert first['reports'][0]['receipt']==second['reports'][0]['receipt']
    assert first['groups']['debugging/ordinary']['official_raw_zero']==1
    assert first['reports'][0]['evidence_stage']=='official_case_terminal'


def test_reused_original_case_keeps_original_result_and_submission(evidence,tmp_path,monkeypatch):
    inv=inventory(tmp_path,evidence,monkeypatch);old=trial(tmp_path/'old','task0',evidence['output'])
    data=a.read(inv);data['cases'][0]['existing_attempt']={'result':a.reference(old),'official_scores':{'accuracy':0}}
    dump(inv,data);cohort=tmp_path/'cohort'
    dump(cohort/'cases/task0/terminal.json',{'task_id':'task0','disposition':'reused_original_completed_attempt','project_exact_diagnostic':0})
    scan=a.read(a.scan_completed(inv,cohort,tmp_path/'reports'))
    report=a.read(a.read(scan['reports'][0]['receipt'])['report'])
    assert report['evidence']['result']==a.reference(old)
    assert report['terminal_layers']['official_raw_scores']['accuracy']==0


def test_json_schema_accepts_frozen_manifest_and_report(evidence):
    schema=pytest.importorskip('jsonschema')
    contract=a.read(a.ROOT/'config/spreadsheet_failure_analysis_v1.schema.json')
    schema.Draft202012Validator.check_schema(contract)
    schema.validate(a.freeze_manifest(evidence),contract)
    schema.validate(a.analyze(evidence),contract)


def test_cli_case_then_scan_is_offline(evidence,tmp_path):
    path=a.ROOT/'scripts/analyze_spreadsheet_failure.py'
    spec=importlib.util.spec_from_file_location('_offline_failure_cli',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    manifest=dump(tmp_path/'manifest.json',a.freeze_manifest(evidence))
    receipt=m.main(['case','--manifest',str(manifest),'--output',str(tmp_path/'reports')])
    assert a.read(receipt)['new_model_LO_solver_network_calls']==0


@pytest.mark.parametrize('quantum',['0','-1','1e-30','NaN'])
def test_invalid_analysis_precision_rejected(evidence,quantum):
    evidence['analysis_numeric_quantum']=quantum
    with pytest.raises((ValueError,ArithmeticError)):a.freeze_manifest(evidence)
