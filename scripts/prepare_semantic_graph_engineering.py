#!/usr/bin/env python3
"""One new V3 engineering input, exactly two pinned recalculations, no models."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import copy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore,utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.pipelines.joint_repair_activity import IMAGE_ID,validate_physical_edits
from sheets_factory.task_adapters.composite_semantic_family_v3 import compile_semantic_mutation,ADAPTER_ID,canonical_sha
from sheets_factory.task_adapters.lease_family import MAIN,NS,_paths,ref,sha,compare_exact_typed
from sheets_factory.task_adapters.public_input_priority import checked,require
from sheets_factory.workbook import compare_workbooks
from sheets_factory.workbook.engine import LibreOfficeEngine


def write(path,value):
    with Path(path).open('x')as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def native_errors(path):
    result={}
    with ZipFile(path)as archive:
        for sheet,name in _paths(archive).items():
            doc=ET.fromstring(archive.read(name))
            for cell in doc.findall('.//m:sheetData/m:row/m:c',NS):
                if cell.get('t')=='e':
                    value=cell.find('m:v',NS)
                    result[sheet+'!'+cell.get('r')]=None if value is None else value.text
    return result


def inject_formulas(baseline,destination,edits):
    """Preserve non-root package parts and assert every original definition."""
    pending={(e['sheet'],e['cell']):e for e in edits}
    require(len(pending)==len(edits)and len(edits)>0,'Duplicate or empty physical root set')
    with ZipFile(baseline)as zin,ZipFile(destination,'x')as zout:
        paths=_paths(zin);names={v:k for k,v in paths.items()}
        require(all(s in paths for s,c in pending),'Unknown mutation sheet')
        modified={paths[s]for s,c in pending}
        for info in zin.infolist():
            data=zin.read(info.filename)
            if info.filename in modified:
                tree=ET.fromstring(data);sheet=names[info.filename]
                for c in tree.findall('.//m:sheetData/m:row/m:c',NS):
                    e=pending.pop((sheet,c.get('r')),None)
                    if e is None:continue
                    f=c.find('m:f',NS)
                    require(f is not None and '='+str(f.text or'')==e['before'],
                            'Original formula assertion differs: '+sheet+'!'+c.get('r'))
                    require(isinstance(e['after'],str)and e['after'].startswith('=')and e['after']!=e['before'],
                            'A physical mutation must be a changed formula')
                    f.text=e['after'][1:]
                    for child in list(c):
                        if child.tag in {'{'+MAIN+'}v','{'+MAIN+'}is'}:c.remove(child)
                    c.attrib.pop('t',None)
                data=ET.tostring(tree,encoding='utf-8')
            zout.writestr(copy(info),data)
        require(not pending,'Some declared roots were not physically injected')
    with ZipFile(baseline)as before,ZipFile(destination)as after:
        require(before.namelist()==after.namelist(),'Workbook package entries changed')
        untouched=[p for p in before.namelist()if p not in modified]
        require(all(before.read(p)==after.read(p)for p in untouched),'An unselected package part changed')
    validation=validate_physical_edits(baseline,destination,edits)
    return {**validation,'passed':True,'exact_formula_edit_set':True,
            'mutated_root_cached_values_removed':True,'unchanged_package_parts':len(untouched),
            'modified_package_parts':sorted(modified),'edits_sha256':canonical_sha(edits)}


def run(output,source_handoff,offline_report,policy_file,*,port=0):
    output=Path(output).resolve();require(not output.exists(),'Use a fresh engineering output directory')
    output.mkdir(parents=True);temporary=output/'temporary';temporary.mkdir()
    require(Path(os.environ.get('TMPDIR','')).resolve()==temporary,
            'TMPDIR must explicitly equal this new output/temporary directory')
    tempfile.tempdir=None
    handoff=json.loads(Path(source_handoff).read_text());source=handoff['source_binding']
    report=json.loads(Path(offline_report).read_text());policy=json.loads(Path(policy_file).read_text())
    baseline=checked(source['source']);scope=json.loads(checked(source['scope_inventory']).read_text())
    require(report.get('offline_compile_complete')is True and report.get('adapter')==ADAPTER_ID
            and report.get('source')==ref(baseline)and report.get('policy')==policy,
            'Offline V3 source or policy binding differs')
    paths=[Path(__file__),ROOT/'src/sheets_factory/task_adapters/composite_semantic_family_v3.py',
           ROOT/'src/sheets_factory/task_adapters/composite_full_family_v2.py',
           ROOT/'src/sheets_factory/task_adapters/lease_family.py',ROOT/'src/sheets_factory/workbook/profile.py',
           ROOT/'src/sheets_factory/workbook/engine.py',ROOT/'src/sheets_factory/workbook/compare.py',
           ROOT/'src/sheets_factory/pipelines/joint_repair_activity.py',Path(policy_file)]
    recipe={str(p.resolve()):ref(p)for p in paths};write(output/'recipe_start.json',recipe)
    audit=AuditStore(output,{'id':output.name,'kind':'semantic_graph_v3_joint_engineering',
        'status':'compiling','qualified':0,'llm_calls_permitted':False})
    panel=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port)
    url=panel.start();audit.update_run(producer_active=True,producer_pid=os.getpid(),dashboard_url=url)
    write(output/'dashboard.json',{'url':url,'pid':os.getpid(),'output':str(output)})
    print(json.dumps({'output':str(output),'pid':os.getpid(),'dashboard':url}),flush=True)
    phase='compile';start=time.monotonic();calls=[]
    try:
        plan=compile_semantic_mutation(baseline,scope,policy)
        require(len(plan['edits'])==report['root_count']==scope['prospective_nonzero_roots']
                and canonical_sha(plan['edits'])==report['edits_sha256'],
                'The freshly compiled full V3 edit set differs from offline preparation')
        write(output/'plan.json',plan)
        phase='raw_formula_injection';raw=output/'mutated_raw.xlsx'
        injection=inject_formulas(baseline,raw,plan['edits'])
        injection.update(baseline=ref(baseline),raw_mutant=ref(raw),plan=ref(output/'plan.json'),root_count=len(plan['edits']))
        write(output/'raw_injection_receipt.json',injection)
        engine=LibreOfficeEngine(ROOT,IMAGE_ID,300);runtime=engine.metadata()
        require(runtime.get('backend')=='libreoffice_uno_docker'and runtime.get('image_id')==IMAGE_ID
                and runtime.get('network')=='none','The actual pinned runtime differs')
        write(output/'runtime.json',runtime)
        actual,stable=output/'input.xlsx',output/'second_pass.xlsx'
        for index,(inp,dest)in enumerate(((raw,actual),(actual,stable))):
            phase=('mutant_normalize','mutant_second_recalculation')[index];t=time.monotonic()
            call={'phase':phase,'index':index,'started_at':utcnow(),'completed':False,'input':ref(inp),
                  'backend':runtime['backend'],'image_id':runtime['image_id'],'network':runtime['network']}
            calls.append(call)
            (output/'engine_calls.json').write_text(json.dumps(calls,indent=2))
            audit.emit('semantic.recalculation.started',**call);audit.export()
            engine.recalculate(inp,dest)
            call.update(completed=True,completed_at=utcnow(),duration_seconds=time.monotonic()-t,output=ref(dest))
            (output/'engine_calls.json').write_text(json.dumps(calls,indent=2))
            audit.emit('semantic.recalculation.completed',**call);audit.export();print(json.dumps(call),flush=True)
        phase='complete_joint_proof'
        physical=validate_physical_edits(baseline,actual,plan['edits'])
        second_physical=validate_physical_edits(actual,stable,[])
        write(output/'actual_physical_validation.json',physical);write(output/'stable_definition_validation.json',second_physical)
        stability=compare_exact_typed(actual,stable);write(output/'exact_stability.json',stability)
        require(stability.get('passed')is True,'The V3 joint input is not exact typed stable across both actual passes')
        delta=compare_workbooks(actual,baseline,baseline)
        require(delta.get('structure_ok')is True and delta.get('expected_change_count',0)>0,'Missing full workbook D')
        write(output/'full_delta.json',delta)
        roots={e['sheet']+'!'+e['cell']for e in plan['edits']};changed=set(delta['expected_changes'])
        errors={name:native_errors(path)for name,path in [('source',baseline),('mutant',actual),('second',stable)]}
        errors['introduced']={k:v for k,v in errors['mutant'].items()if errors['source'].get(k)!=v}
        write(output/'native_errors.json',errors)
        for record in recipe.values():checked(record)
        receipt={'kind':'semantic_graph_v3_joint_engineering_probe','status':'joint_engineering_probe_complete_not_task_admitted',
            'baseline':ref(baseline),'source_manifest':source['source_manifest'],
            'source_financial_admission':source['financial_admission'],'source_binding':source,
            'source_identity_unchanged':'composite_complete_financial_graph_v2',
            'mutation_provider':{'id':ADAPTER_ID,'implementation':ref(ROOT/'src/sheets_factory/task_adapters/composite_semantic_family_v3.py'),
                'policy':ref(policy_file),'policy_sha256':canonical_sha(policy),'offline_compilation':ref(offline_report)},
            'plan':ref(output/'plan.json'),'input':ref(actual),'second_pass':ref(stable),
            'raw_injection':ref(output/'raw_injection_receipt.json'),'physical_validation':ref(output/'actual_physical_validation.json'),
            'stable_definition_validation':ref(output/'stable_definition_validation.json'),
            'root_count':len(roots),'edits_sha256':canonical_sha(plan['edits']),
            'actual_LO_recalculations':2,'engine_calls':ref(output/'engine_calls.json'),
            'engine_duration_seconds':sum(c['duration_seconds']for c in calls),
            'stability':ref(output/'exact_stability.json'),'exact_typed_stable':True,
            'full_delta':ref(output/'full_delta.json'),'expected_change_count':delta['expected_change_count'],
            'changed_edited_root_count':len(roots&changed),'unchanged_edited_root_count':len(roots-changed),
            'native_errors':ref(output/'native_errors.json'),'source_error_count':len(errors['source']),
            'mutant_error_count':len(errors['mutant']),'introduced_error_count':len(errors['introduced']),
            'individual_or_marginal_activity_tested':False,'counterfactual_global_uniqueness_claimed':False,
            'SCC_executions':0,'LLM_calls':0,'quality_calls':0,'strong_calls':0,
            'five_controls_recovery_quality_Harbor_pending':True,'qualified':False,'task_count':0}
        write(output/'engineering_receipt.json',receipt);audit.update_run(status=receipt['status'])
        print(json.dumps(receipt),flush=True);return ref(output/'engineering_receipt.json')
    except BaseException as error:
        write(output/'failure_receipt.json',{'phase':phase,'error_type':type(error).__name__,'reason':str(error),
            'engine_calls':calls,'qualified':False,'task_count':0,'LLM_calls':0})
        audit.update_run(status='rejected',error=str(error));raise
    finally:
        audit.update_run(producer_active=False,finished_at=utcnow(),elapsed_seconds=time.monotonic()-start)
        audit.export();panel.stop()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--source-handoff',required=True);p.add_argument('--offline-report',required=True)
    p.add_argument('--policy',required=True);p.add_argument('--port',type=int,default=0)
    a=p.parse_args();run(a.output,a.source_handoff,a.offline_report,a.policy,port=a.port)

if __name__=='__main__':main()
