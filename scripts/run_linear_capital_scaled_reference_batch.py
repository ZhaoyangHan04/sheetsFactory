#!/usr/bin/env python3
"""Frozen N360 batch contract around the isolated version-two reference API.

Preparation requires all twenty completed finance terminals and makes no
financial forward or solver calls. Execution is explicit. The existing frozen
four-worker lifecycle retains every attempt and rejection without retries.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DEFAULT_CONFIG = ROOT/'config/research/linear_capital_scaled_reference_P01_P20_v2.json'
API_PATH = ROOT/'scripts/run_linear_capital_scaled_reference.py'
RAW_API_PATH = ROOT/'scripts/prepare_linear_capital_scaled_catalog.py'
FINANCE_API_PATH = ROOT/'scripts/run_linear_capital_scaled_finance.py'
UPSTREAM = ROOT/'scripts/run_linear_capital_reference_batch.py'
UPSTREAM_SHA256 = 'fab59b0ac58c71232d98d2f52a11f0cb04b020f0889398c6c36b51624158a79b'
ORDER = [f'L360-P{i:02d}' for i in range(1,21)]
KIND = 'scaled_producer16_fixed_twenty_reference_batch'
FINANCE_MAP_KIND = 'completed_scaled_linear_finance_terminal_inventory'
POLICY = 'version2_best_and_complete_winner_excluded_runner_OPTIMAL'
EXPECTED_DECLARATION = {'kind':'prospective_scaled_linear_raw_pool','version':2,'count':20,
    'first_development_profile':ORDER[0], 'profiles':[{'id':pid,'seed':202701361+i,
        'revenue_jitter_pence':150000} for i,pid in enumerate(ORDER)]}
EXPECTED_CONFIG = {'kind':KIND,'version':2,'profile_order':ORDER,'declaration':EXPECTED_DECLARATION,
    'original_supervisor_sha256':UPSTREAM_SHA256,
    'reference_api_sha256':'203c40ba1b7c3ec446388cb6a93ada284c0a0c62d334e1c2b09132bed2c1e268',
    'raw_api_sha256':'b5752aedbdda92b2ff5cd2ab6afd6db14ed25fac03be0880b308f6163c7dd8e6',
    'finance_api_sha256':'31b9c6a0edce8642493414298c125dc12251285448faf27dc9f7fdeefa6fbcd0',
    'max_parallel':4,'retries':0,'reference_policy':POLICY,'complete_business_rows':941,
    'resources':{'cpus':16,'threads':16,'memory_bytes':32*1024**3,'pids_limit':256,
        'network':'none','seconds_per_phase':3600,
        'image_id':'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'}}


def load_module(name,path):
    definition = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(definition); definition.loader.exec_module(result)
    return result


api = load_module('_scaled_twenty_reference_api',API_PATH)
raw_api = load_module('_scaled_twenty_raw_api',RAW_API_PATH)
ref, read, write, require = api.reference, api.read, api.write, api.require


def checked_config(value):
    config = read(value)
    require(api._sha(config) == api._sha(EXPECTED_CONFIG)
        and api._sha(read(DEFAULT_CONFIG)) == api._sha(EXPECTED_CONFIG),
        'Use the complete fixed N360 twenty-profile version-two contract')
    for path,key in [(UPSTREAM,'original_supervisor_sha256'),(API_PATH,'reference_api_sha256'),
        (RAW_API_PATH,'raw_api_sha256'),(FINANCE_API_PATH,'finance_api_sha256')]:
        require(ref(path)['sha256'] == config[key], 'A frozen new-scope batch dependency changed: '+key)
    require(config['resources']['image_id'] == api.runtime.IMAGE_ID,
        'The pinned native reference image changed')
    return config


def checked_reference(value):
    record = ref(value) if isinstance(value,(str,Path)) else value
    require(isinstance(record,dict) and ref(record['path']) == record,'A frozen input reference changed')
    return record


def checked_inventory(raw_catalog,finance_terminals):
    raw_ref, finance_ref = checked_reference(raw_catalog), checked_reference(finance_terminals)
    catalog = raw_api.validate_prepared(Path(raw_ref['path']).parent)
    require(catalog == read(raw_ref) and catalog['profile_order'] == ORDER
        and read(catalog['declaration']) == EXPECTED_DECLARATION,
        'The complete prospective N360 raw catalog or declaration changed')
    finance = read(finance_ref)
    require(isinstance(finance,dict) and set(finance) == {'kind','version','raw_catalog','profile_order','profiles'}
        and finance['kind'] == FINANCE_MAP_KIND and type(finance['version']) is int and finance['version'] == 2
        and finance['raw_catalog'] == raw_ref and finance['profile_order'] == ORDER
        and [row['profile_id'] for row in finance['profiles']] == ORDER,
        'Declare every completed finance terminal exactly once in the frozen raw order')
    inventory = []
    for raw, actual in zip(catalog['profiles'],finance['profiles'],strict=True):
        require(set(actual) == {'profile_id','terminal'},'A complete finance terminal member is required')
        terminal_ref = checked_reference(actual['terminal']); terminal = read(terminal_ref)
        require(terminal.get('kind') == 'linear_capital_scaled_full_financial_crosscheck'
            and type(terminal.get('version')) is int and terminal['version'] == 2
            and terminal.get('passed') is True and terminal.get('qualified') is False
            and terminal.get('toy_only') is False and terminal.get('recipe') == api.finance_recipes()
            and terminal.get('raw_preparation') == raw['raw_preparation']
            and terminal.get('specification') == raw['specification']
            and all(type(terminal.get(k)) is int and terminal[k] == 0
                for k in ('optimizer_calls','LO_calls','model_calls','task_count')),
            'Every fixed N360 profile requires its genuine passed complete finance terminal')
        inventory.append({'profile_id':raw['profile_id'],'specification':raw['specification'],
            'raw_preparation':raw['raw_preparation'],'finance_terminal':terminal_ref})
    return inventory, {'raw_catalog':raw_ref,'finance_terminals':finance_ref}


def recipe(config_path):
    paths = (Path(__file__),UPSTREAM,RAW_API_PATH,FINANCE_API_PATH,Path(config_path))
    return {**api.recipes(),**{str(path.resolve()):ref(path) for path in paths}}


def prepare(config_path,raw_catalog,finance_terminals,output):
    config_path = Path(config_path).resolve(); output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh private N360 batch directory')
    config = checked_config(config_path); inventory,lineage = checked_inventory(raw_catalog,finance_terminals)
    output.mkdir(parents=True)
    declaration = write(output/'inventory.json',{'kind':KIND+'_inventory','version':2,
        'profile_order':ORDER,'profiles':inventory,'lineage':lineage,'reference_policy':POLICY,
        'max_parallel':4,'retries':0,'maximum_native_solver_calls':40,'actual_solver_calls':0})
    preparations = {}
    try:
        for row in inventory:
            pid = row['profile_id']; folder = output/'profiles'/pid
            preparations[pid] = api.prepare(row['finance_terminal'],folder)
            api.validate_prepared(folder)
        compatibility = write(output/'zero_service_compatibility.json',{'passed':True,'profile_order':ORDER,
            'validated_preparations':preparations,'reference_api':ref(API_PATH),'runtime_profile':api._profile(),
            'native_solver_calls':0,'financial_forward_calls':0,'LO_calls':0,'model_calls':0,'Harbor_jobs':0})
        return write(output/'prospective.json',{'kind':KIND,'version':2,
            'frozen_at':datetime.now(timezone.utc).isoformat(),'config':ref(config_path),
            'inventory':declaration,'profile_order':ORDER,'preparations':preparations,'lineage':lineage,
            'recipe':recipe(config_path),'compatibility':compatibility,'reference_policy':POLICY,
            'runtime_profile':api._profile(),'max_parallel':4,'retries':0,'maximum_native_solver_calls':40,
            'native_solver_calls':0,'LO_calls':0,'model_calls':0,'Harbor_jobs':0,
            'source_or_task_or_quality_or_difficulty_certified':False,'qualified':False,'task_count':0})
    except BaseException as error:
        write(output/'compatibility_failure.json',{'error_type':type(error).__name__,'error':str(error),
            'preparations':preparations,'native_solver_calls':0,'all_partial_artifacts_retained':True})
        raise


def validate(output,*,validate_profiles=True):
    output = Path(output).resolve(); frozen = read(output/'prospective.json')
    config = checked_config(frozen['config'])
    inventory,lineage = checked_inventory(frozen['lineage']['raw_catalog'],frozen['lineage']['finance_terminals'])
    require(frozen['kind'] == KIND and type(frozen['version']) is int and frozen['version'] == 2
        and frozen['profile_order'] == ORDER and list(frozen['preparations']) == ORDER
        and type(frozen['max_parallel']) is int and frozen['max_parallel'] == 4
        and type(frozen['retries']) is int and frozen['retries'] == 0
        and frozen['maximum_native_solver_calls'] == 40 and frozen['native_solver_calls'] == 0
        and frozen['reference_policy'] == config['reference_policy'] and frozen['runtime_profile'] == api._profile()
        and frozen['lineage'] == lineage and frozen['recipe'] == recipe(frozen['config']['path']),
        'The complete prospective N360 batch contract changed')
    declared = read(frozen['inventory'])
    require(declared['kind'] == KIND+'_inventory' and declared['version'] == 2
        and declared['profiles'] == inventory and declared['profile_order'] == ORDER,
        'The complete pre-call N360 inventory changed')
    api._refs(frozen)
    if validate_profiles:
        for pid in ORDER:
            folder = output/'profiles'/pid
            require(frozen['preparations'][pid] == ref(folder/'preparation.json'),'A profile preparation changed')
            api.validate_prepared(folder)
    return frozen


def adapted_ast():
    """Reuse the exact frozen worker, owned-ID, supervisor and CLI lifecycle."""
    raw = UPSTREAM.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == UPSTREAM_SHA256,'The frozen four-worker supervisor differs')
    tree = ast.parse(raw,filename=str(UPSTREAM))
    wanted = {'worker','owned_jobs','execute','main'}
    tree.body = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in wanted]
    require({node.name for node in tree.body} == wanted,'A frozen supervisor lifecycle function is missing')
    counts = {}
    def changed(key): counts[key] = counts.get(key,0)+1
    class Adapt(ast.NodeTransformer):
        def visit_Dict(self,node):
            keys = {key.value:i for i,key in enumerate(node.keys) if isinstance(key,ast.Constant)}
            if 'finance_accounting_correction' in keys:
                for key in ('finance_accounting_correction','prior_finance_implementation_universe_calls_corrected'):
                    index = next(i for i,k in enumerate(node.keys) if isinstance(k,ast.Constant) and k.value == key)
                    del node.keys[index]; del node.values[index]; changed('remove_old_finance_accounting')
                node.keys.append(ast.Constant('completed_finance_terminal_inventory'))
                node.values.append(ast.parse("frozen['lineage']['finance_terminals']",mode='eval').body)
            if 'kind' in keys and 'version' in keys:
                index = next((i for i,k in enumerate(node.keys) if isinstance(k,ast.Constant) and k.value == 'version'),None)
                if index is not None and isinstance(node.values[index],ast.Constant) and node.values[index].value == 1:
                    node.values[index] = ast.Constant(2); changed('terminal_version')
            return self.generic_visit(node)
        def visit_Constant(self,node):
            replacements = {'P01–P20 original-v1 best and runner references':'N360 P01–P20 version-two best and runner references',
                'original_validator':'version2_validator','original_v1_best_and_runner_OPTIMAL':'version2_best_and_runner_OPTIMAL',
                881:941}
            if node.value in replacements:
                node.value = replacements[node.value]; changed('identity_metadata')
            return node
        def visit_Call(self,node):
            if isinstance(node.func,ast.Name) and node.func.id == 'prepare':
                require([ast.unparse(arg) for arg in node.args] == ['args.config','args.output'],
                    'The frozen prepare CLI dispatch changed')
                node.args = [ast.parse('args.'+key,mode='eval').body
                    for key in ('config','raw_catalog','finance_terminals','output')]
                changed('prepare_dispatch')
            if (isinstance(node.func,ast.Attribute) and node.func.attr == 'add_argument'
                and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value == '--output'):
                extra = ast.parse("command.add_argument('--raw-catalog', type=Path, required=True)\n"
                    "command.add_argument('--finance-terminals', type=Path, required=True)").body
                self.extra_arguments = extra
            return self.generic_visit(node)
        def visit_Expr(self,node):
            self.extra_arguments = None
            result = self.generic_visit(node)
            return [result,*self.extra_arguments] if self.extra_arguments else result
    tree = Adapt().visit(tree)
    require(counts == {'remove_old_finance_accounting':2,'terminal_version':1,'identity_metadata':4,'prepare_dispatch':1},
        'The exact version-two supervisor substitutions changed: '+str(counts))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())

if __name__ == '__main__':
    raise SystemExit(main())
