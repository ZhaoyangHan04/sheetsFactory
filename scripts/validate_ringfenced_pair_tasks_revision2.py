#!/usr/bin/env python3
"""Same complete pair views/eight calls, admitted only by genuine source R3."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import FunctionType,SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/validate_ringfenced_pair_tasks.py'
FROZEN_SHA='4c7a3c00c3b0a14b46c4106fddcec9473888eab29c825f7cc8a8b6e6f5417ff4'
SOURCE=ROOT/'scripts/run_ringfenced_pair_session_revision3.py'
SOURCE_SHA='b3cc7cc25c667a997614f81c3411810e2bea30f8a5d1cd346f9e8d92e892d3af'
SOURCE_KIND='completed_two_ringfenced_pair_source_same_process_session_revision3'
KIND='prepared_complete_ringfenced_pair_task_engineering_revision2'
TERMINAL_KIND='complete_ringfenced_pair_task_engineering_revision2'


def _load(path,digest,name):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('The frozen complete task/source provider changed')
    loader=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module


previous=_load(FROZEN,FROZEN_SHA,'_R3_pair_task_frozen_original')
session=_load(SOURCE,SOURCE_SHA,'_R3_pair_task_genuine_source')
_P={**vars(previous),'__file__':__file__,'__name__':'_isolated_R3_pair_task_provider',
    'SOURCE':SOURCE,'SOURCE_SHA':SOURCE_SHA,'SOURCE_KIND':SOURCE_KIND,'session':session,
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND}
_N={**previous._N,'__file__':__file__,'__name__':'_isolated_R3_pair_eight_stage_workflow',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND}
for ns,old in ((_P,vars(previous)),(_N,previous._N)):
    for name,value in old.items():
        if isinstance(value,FunctionType) and value.__globals__ is old:
            function=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__)
            function.__kwdefaults__=deepcopy(value.__kwdefaults__);ns[name]=function
_P['_N']=_N
_P.update(execute_prepared=_N['execute_prepared'],validate_completed=_N['validate_completed'])
source=SimpleNamespace(validate_source=_P['_genuine'],now=previous.source.now,stage=previous.source.stage,
    validate_call=_P['_validate_call'],owned_absence=previous.source.owned_absence,compare_typed=_P['_compare_typed'])
_P['source']=source;_N['source']=source
_original_recipes=_P['recipes']


def recipes():
    previous.require(previous.reference(FROZEN)['sha256']==FROZEN_SHA
        and previous.reference(SOURCE)['sha256']==SOURCE_SHA,'A frozen complete R3 task dependency changed')
    return {**_original_recipes(),str(FROZEN):previous.reference(FROZEN)}


_P['recipes']=recipes
for name in ('recipes','prepare','validate_prepared','verify_definitions','verify_input_caches'):_N[name]=_P[name]
for name in ('reference','checked','read','write','require','base','views','STAGES','prepare',
             'validate_prepared','verify_definitions','verify_input_caches','main','_genuine'):
    globals()[name]=_P[name]
execute_prepared=_N['execute_prepared'];validate_completed=_N['validate_completed']


if __name__=='__main__':raise SystemExit(main())
