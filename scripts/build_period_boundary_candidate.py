#!/usr/bin/env python3
"""Create a small synthetic offline candidate; no recalculation or model calls."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from openpyxl import Workbook
from openpyxl.utils.datetime import to_excel
from sheets_factory.workbook.period_boundary_portfolio import spec,oracle,excel

CAUSE=ROOT/'outputs/research/SB2_FM01_02_first_failure_forensics_20261031T162800Z/handoff.json'
CAUSE_SHA='e8280be66dc3c9a578c992162b04272ff2f25035bbf055f1101edad7979c8c7b'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def reference(path):
    p=Path(path).resolve();h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024**2),b''):h.update(block)
    return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}


def save(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,default=json_value,allow_nan=False);stream.write('\n')
    return reference(path)


def json_value(value):
    if isinstance(value,(date,datetime)):return value.isoformat()
    if isinstance(value,Decimal):return str(value)
    raise TypeError(type(value).__name__)


def expected_values(bindings,result):
    values={}
    for b in bindings['derived']:
        v=result
        for part in b['expected_path']:v=v[part]
        assert (type(v) is int if b['kind'] in ['money_pence','integer'] else isinstance(v,date)),b
        values[(b['sheet'],b['cell'])]=v
    assert len(values)==len(bindings['derived'])
    return values


def seed_oracle_caches(source,destination,bindings,values):
    """Write private-oracle caches; explicitly not a LibreOffice validation."""
    sheets={name:f'xl/worksheets/sheet{i+1}.xml' for i,name in enumerate(bindings['sheetnames'])}
    table={sheets[b['sheet']]:{} for b in bindings['derived']}
    for b in bindings['derived']:
        v=values[(b['sheet'],b['cell'])]
        text=str(to_excel(v)) if isinstance(v,date) else format(Decimal(v)/100,'f') if b['kind']=='money_pence' else str(v)
        table[sheets[b['sheet']]][b['cell']]=text
    with zipfile.ZipFile(source) as zin,zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename in table:
                tree=ET.fromstring(raw);seen=set()
                for cell in tree.iter('{'+NS+'}c'):
                    addr=cell.get('r')
                    if addr not in table[item.filename]:continue
                    assert cell.find('{'+NS+'}f') is not None
                    cell.attrib.pop('t',None);v=cell.find('{'+NS+'}v')
                    if v is None:v=ET.SubElement(cell,'{'+NS+'}v')
                    v.text=table[item.filename][addr];seen.add(addr)
                assert seen==set(table[item.filename]);raw=ET.tostring(tree,encoding='utf-8')
            zout.writestr(item,raw)


def recipes():
    return {str(p):reference(p) for p in [Path(__file__).resolve(),Path(spec.__file__).resolve(),Path(oracle.__file__).resolve(),Path(excel.__file__).resolve()]}


def build(value,output,*,evidence=CAUSE):
    output=Path(output).absolute();assert output==output.resolve() and not output.exists()
    public=spec.load_spec(value);cause=reference(evidence)
    assert cause['sha256']==CAUSE_SHA,'Use the actual bound first failure; it supplies evidence only, never workbook data'
    before=recipes();output.mkdir(parents=True)
    evidence_value=json.loads(Path(evidence).read_text())
    assert evidence_value['only_official_miss']=='Working Capital Schedule!M3'
    source_spec=save(output/'public_specification.private.json',public)
    correct=oracle.simulate(public);wrong=oracle.simulate(public,faults=spec.FAULTS)
    oracle_ref=save(output/'independent_correct_oracle.private.json',correct)
    wrong_ref=save(output/'independent_mutant_oracle.private.json',wrong)
    book=Workbook();bindings=excel.emit_workbook(book,public);raw=output/'gold_formulas_uncached.private.xlsx';book.save(raw)
    good=expected_values(bindings,correct);seed_oracle_caches(raw,output/'goal.xlsx',bindings,good)
    b=Workbook();wrong_bindings=excel.emit_workbook(b,public,faults=spec.FAULTS);mutant_raw=output/'debugging_formulas_uncached.private.xlsx';b.save(mutant_raw)
    bad=expected_values(wrong_bindings,wrong)
    seed_oracle_caches(mutant_raw,output/'debugging_input.xlsx',wrong_bindings,bad)
    fm=Workbook();fm_bindings=excel.emit_workbook(fm,public)
    for binding in fm_bindings['derived']:fm[binding['sheet']][binding['cell']]=None
    fm.save(output/'financial_modeling_input.xlsx')
    for mode,text in spec.BRIEFS.items():(output/(mode+'_instruction.md')).write_text(text+'\n')
    save(output/'bindings.private.json',bindings)
    correct_by={(b['sheet'],b['cell']):b for b in bindings['derived']}
    formula_edits=[{'sheet':b['sheet'],'cell':b['cell'],'before':b['formula'],'after':correct_by[b['sheet'],b['cell']]['formula']}
        for b in wrong_bindings['derived'] if b['formula']!=correct_by[b['sheet'],b['cell']]['formula']]
    dbg_D=[{'sheet':sheet,'cell':cell,'kind':correct_by[sheet,cell]['kind'],'wrong_oracle':bad[sheet,cell],'correct_oracle':good[sheet,cell]}
        for sheet,cell in good if good[sheet,cell]!=bad[sheet,cell]]
    fm_D=[{'sheet':sheet,'cell':cell,'kind':correct_by[sheet,cell]['kind'],'input':None,'correct_oracle':good[sheet,cell]} for sheet,cell in good]
    plan=save(output/'task_plan.private.json',{'kind':'unvalidated_period_boundary_candidate_pair','version':1,
        'FM_all_derived_masks':fm_D,'DBG_formula_edits':formula_edits,'DBG_complete_oracle_changed_values':dbg_D,
        'fault_families':list(spec.FAULTS),'all_applicable_rows_of_each_faulted_formula_class_changed':True,
        'adjacent_pristine_same_class_repair_templates_retained':False,'cache_origin':'independent Python Decimal/date oracle, not recalculated',
        'source_or_task_admission_passed':False,'quality_passed':False,'difficulty_validated':False})
    assert recipes()==before
    return save(output/'manifest.json',{'kind':'offline_synthetic_period_boundary_candidate','version':1,'synthetic':True,
        'source_specification':source_spec,'recipe':before,'evidence_transfer':{'actual_first_failure':cause,
            'observed_mechanism':'Completeness scan omitted a terminal-period date while validating only its chosen financial formula edits',
            'transfer_hypothesis':'Heterogeneous fiscal, maturity and terminal-collection boundaries can cause monetary propagation errors when target discovery is incomplete',
            'transfer_hypothesis_validated':False,'official_workbook_or_gold_or_task_used_as_seed':False},
        'independent_oracle':oracle_ref,'independent_fault_oracle':wrong_ref,'plan':plan,
        'gold':reference(output/'goal.xlsx'),'FM_input':reference(output/'financial_modeling_input.xlsx'),'DBG_input':reference(output/'debugging_input.xlsx'),
        'instructions':{mode:reference(output/(mode+'_instruction.md')) for mode in spec.BRIEFS},
        'sheet_count':len(excel.SHEETS),'formula_count':len(bindings['derived']),'FM_D_count':len(fm_D),'DBG_D_count':len(dbg_D),'DBG_formula_edit_count':len(formula_edits),
        'actual_LO_calls':0,'model_calls':0,'solver_calls':0,'Harbor_calls':0,'network_calls':0,
        'oracle_seeded_caches_not_actual_calculation':True,'formula_cache_parity_pending':True,'qualified':False,
        'source_certified':False,'task_controls_passed':False,'difficulty_claimed':False})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--spec',type=Path);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();print(json.dumps(build(spec.prototype() if a.spec is None else a.spec,a.output)));return 0


if __name__=='__main__':raise SystemExit(main())
