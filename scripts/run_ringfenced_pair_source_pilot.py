#!/usr/bin/env python3
"""Fixed-pool pure preparation; explicit composition and genuine source3 pilot."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/run_ringfenced_group_source_pilot.py'
UPSTREAM_SHA='1502531abb5f232f192a2b5aa5847c90f1c172700620043d662dc704a8e46ca0'


def _load():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:raise ValueError('Frozen complete source3 pilot ancestor changed')
    tree=ast.parse(raw);counts={};imports=0
    replacements={
        'config/runtime_profiles/ringfenced_group_source_pilot_v1.yaml':'config/runtime_profiles/ringfenced_pair_source_v1.yaml',
        'ringfenced_group_source_pilot_v1':'ringfenced_pair_source_v1',
        'prepared_four_ringfenced_group_source_engineering_pilot':'prepared_two_ringfenced_pair_source_engineering_pilot',
        'completed_four_ringfenced_group_source_engineering_pilot':'completed_two_ringfenced_pair_source_engineering_pilot',
        'Four-mandate whole-source engineering pilot':'Two-mandate whole-source engineering pilot',
        5200000:2600000,7500000:3600000,6400000:3200000,
        1480:740,4989312:2494656,7094264:3547132,6088752:3044376,
        4989614:2494958,7094703:3547571,6089054:3044678,1481:741}
    class Pair(ast.NodeTransformer):
        def visit_ImportFrom(self,n):
            nonlocal imports
            if n.module=='sheets_factory.workbook.linear_capital_ringfenced_group':n.module='sheets_factory.workbook.linear_capital_ringfenced_pairs';imports+=1
            return n
        def visit_Constant(self,n):
            if type(n.value) in (str,int) and n.value in replacements:
                counts[n.value]=counts.get(n.value,0)+1;n.value=replacements[n.value]
            return n
    tree.body=[n for n in tree.body if not (isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and ast.unparse(n.test)=="__name__ == '__main__'")]
    tree=Pair().visit(tree);ast.fix_missing_locations(tree)
    expected={k:(2 if k==7500000 else 1) for k in replacements}
    if imports!=1 or counts!=expected:raise ValueError('Unknown frozen source3 pair adaptation sites: '+repr(counts))
    ns={'__name__':'_isolated_two_ringfenced_source_pilot','__file__':__file__}
    exec(compile(tree,str(UPSTREAM),'exec'),ns)
    return ns


_N=_load();contract=_N['contract'];composition=_N['composition'];stream_composition=_N['stream_composition']
KIND=_N['KIND'];TERMINAL_KIND=_N['TERMINAL_KIND'];PROFILE=_N['PROFILE']
_BASE_RECIPES=_N['recipes']


def recipes():
    return {**_BASE_RECIPES(),str(UPSTREAM):contract.reference(UPSTREAM)}


_N['recipes']=recipes


def _observed(label,output,operation):
    """The parent panel exists before any expensive genuine cold admission."""
    output=Path(output).absolute();audit_dir=output.parent/(output.name+'_'+label+'_audit')
    contract.require(not audit_dir.exists(),'Preserve the first command audit directory; use a fresh output')
    audit=_N['AuditStore'](audit_dir,{'id':audit_dir.name,'name':label+'; engineering only','status':'running',
        'target_count':0,'qualified':False,'model_calls':0,'solver_calls':0})
    server=_N['DashboardServer'](audit.snapshot,audit.events,host='127.0.0.1',port=0);stop=threading.Event();clock=time.monotonic();error=None
    def pulse():
        while not stop.wait(15):audit.update_run(elapsed_seconds=time.monotonic()-clock,phase=label);audit.export()
    thread=threading.Thread(target=pulse,daemon=True)
    try:
        url=server.start();audit.update_run(dashboard_url=url,phase=label);audit.export()
        print(json.dumps({'dashboard_url':url,'phase':label}),flush=True);thread.start()
        return operation()
    except BaseException as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        contract.write(audit_dir/'failure.json',error);raise
    finally:
        stop.set()
        if thread.ident:thread.join(timeout=1)
        audit.update_run(status='failed' if error else 'passed',elapsed_seconds=time.monotonic()-clock,producer_active=False);audit.export()
        server.stop();audit.db.close()


def prepare(certificate,local_composition,output):
    return _observed('source_prepare',output,lambda:_N['prepare'](certificate,local_composition,output))


def execute_prepared(output):
    return _observed('source_execute',output,lambda:_N['execute_prepared'](output))


validate_prepared=_N['validate_prepared'];validate_completed=_N['validate_completed'];load_profile=_N['load_profile']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze-pool',action='store_true');p.add_argument('--preflight',action='store_true')
    p.add_argument('--build-certificate',action='store_true');p.add_argument('--compose',action='store_true')
    p.add_argument('--prospective',type=Path);p.add_argument('--pair',default='R2-01');p.add_argument('--certificate',type=Path)
    p.add_argument('--local-composition',type=Path);p.add_argument('--output',type=Path);p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true')
    a=p.parse_args(argv)
    if a.prepared:
        contract.require(not any((a.freeze_pool,a.preflight,a.build_certificate,a.compose,a.output,a.prospective,a.certificate,a.local_composition)),'Use the exact frozen source preparation')
        result=execute_prepared(a.prepared) if a.run else _observed('source_validate',a.prepared,lambda:validate_prepared(a.prepared))
    else:
        contract.require(a.output is not None and not a.run,'Use a fresh output and explicitly run only an existing source preparation')
        actions=sum((a.freeze_pool,a.preflight,a.build_certificate,a.compose))
        contract.require(actions<=1,'Choose exactly one pure preparation phase')
        if a.freeze_pool:
            result=_observed('freeze_pool',a.output,lambda:contract.freeze(a.output))
        elif a.preflight:
            contract.require(a.prospective is not None,'Supply the complete ten-context prospective')
            def scan():
                report=stream_composition.preflight_all(a.prospective)
                contract.require(not a.output.exists(),'Preserve the first preflight output');a.output.mkdir(parents=True)
                return contract.write(a.output/'preflight.json',report)
            result=_observed('all_ten_formula_preflight',a.output,scan)
        elif a.build_certificate:
            contract.require(a.prospective is not None,'Supply the fixed whole-pool prospective')
            result=_observed('pair_reference_cold',a.output,lambda:composition.build_certificate(a.prospective,a.output,pair_id=a.pair))
        elif a.compose:
            contract.require(a.certificate is not None,'Supply the complete genuine pair certificate')
            def compose():
                contract.require(not a.output.exists(),'Use a fresh composition directory');a.output.mkdir(parents=True)
                receipt=stream_composition.compose(contract.reference(a.certificate),a.output/'locals_uncalculated.xlsx')
                return contract.write(a.output/'composition.json',receipt)
            result=_observed('pure_pair_composition',a.output,compose)
        else:
            contract.require(a.certificate is not None and a.local_composition is not None,'Supply certificate and complete uncalculated local composition')
            result=prepare(a.certificate,a.local_composition,a.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
