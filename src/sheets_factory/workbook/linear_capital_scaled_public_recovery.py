"""New N360 public-only table compiler, isolated replay and strict witness core.

Only the supplied workbook/brief and generic vendored code enter a replay.
The normal-quality hook is deliberately unavailable until a separate N360
opaque source/view admission provider exists. The old family provider is never
accepted. Import, parsing, runtime preparation and bundling start no services.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

import openpyxl

from .linear_capital_scaled import spec,excel,finance,model_b
from .linear_capital_scaled import optimization_runtime as runtime_support

UPSTREAM=Path(__file__).with_name('linear_capital_public_recovery.py')
UPSTREAM_SHA256='40809694186ee35f3250ee4432f041bfb124d69f24c0e8420c2f758e08d5b47e'
SETTING='linear_capital_scaled'
BACKEND='linear_scaled_public_native_tables_shared_decimal_cp_sat_excel_v2'
NORMAL_QUALITY_INTEGRATION_AVAILABLE=False
TABLE_BOUNDS={'ContractNotes':(64,2),'Projects':(388,22),'Scenarios':(16,24),
    'ResourceUse':(362,362),'Limits':(764,3),'Sites':(63,7),'Prerequisites':(123,5),'Portfolio':(376,512)}


def require(condition,message):
    if not condition:raise ValueError(message)


class ScaledPublicAdmissionUnavailable(ValueError):
    """No new opaque provider is registered; an old witness cannot substitute."""


def _source_binding(ctx):
    raise ScaledPublicAdmissionUnavailable(
        'N360 opaque source/view admission integration is deferred; the old family provider is not accepted')


def _admission_source(ctx):
    raise ScaledPublicAdmissionUnavailable(
        'N360 actual-LO admission helper is deferred; no old source helper may substitute')


def _fingerprint(path):
    info=path.stat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink() and path==path.resolve(),
        'A real nonsymlink artifact is required')
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_mode,info.st_nlink)


def reference(value):
    path=Path(value).absolute();before=_fingerprint(path);digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024**2),b''):digest.update(block)
    require(_fingerprint(path)==before,'An artifact changed while hashing')
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':before[2]}


class References:
    """Generic exact artifact guards, with no family admission capability."""
    def __init__(self):self.files={}
    def check(self,record):
        require(type(record) is dict and set(record)=={'path','sha256','bytes'}
            and type(record['path']) is str and Path(record['path']).is_absolute()
            and type(record['bytes']) is int and record['bytes']>=0
            and type(record['sha256']) is str and re.fullmatch('[0-9a-f]{64}',record['sha256']),
            'A complete SHA256/bytes/path reference is required')
        prior=self.files.get(record['path'])
        require(prior is None or prior==record,'Conflicting references name one physical file')
        require(reference(record['path'])==record,'A bound artifact changed: '+record['path'])
        self.files[record['path']]=deepcopy(record);return Path(record['path'])
    def read(self,value):
        record=value if isinstance(value,dict) else reference(value);path=self.check(record)
        result=runtime_support._read(path);self.check(record);return result
    def walk(self,value):
        if isinstance(value,dict):
            if set(value)=={'path','sha256','bytes'}:self.check(value)
            else:
                for item in value.values():self.walk(item)
        elif isinstance(value,(list,tuple)):
            for item in value:self.walk(item)
    def guard(self):
        for record in tuple(self.files.values()):self.check(record)


def solve_public_model(model,*,time_limit_seconds,threads,log_path,model_path):
    """Shared new B solver; the explicit resource ceiling is already sixteen."""
    require(type(threads) is int and 1<=threads<=16,'The public recovery needs explicitly bounded workers')
    return model_b.solve_cp_sat(model,time_limit_seconds=time_limit_seconds,threads=threads,
        log_path=log_path,model_path=model_path)


def adapted_ast():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('The frozen public compiler/replay template changed')
    tree=ast.parse(raw,filename=str(UPSTREAM));counts={}
    def changed(name):counts[name]=counts.get(name,0)+1
    excluded={'reference','inventory','public_implementation_recipe','public_program_source',
        'prepare_public_runtime','validate_public_runtime','solve_public_model','_source_binding'}
    tree.body=[node for node in tree.body if not isinstance(node,ast.FunctionDef) or node.name not in excluded]
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.level==1 and node.module=='linear_capital_portfolio':
                node.module='linear_capital_scaled';node.names=[ast.alias(name=n) for n in ('excel','finance','model_b','spec')]
                changed('financial_import')
            elif node.level==2 and node.module=='pipelines.linear_capital_quality':
                require([n.name for n in node.names]==['References'],'Only generic reference imports may be removed')
                changed('generic_refs');return ast.Pass()
            return node
        def visit_Assign(self,node):
            names={t.id for t in node.targets if isinstance(t,ast.Name)}
            if names=={'SETTING'}:node.value=ast.Constant(SETTING);changed('setting')
            if names=={'BACKEND'}:node.value=ast.Constant(BACKEND);changed('backend')
            if names=={'PUBLIC_TABLE_BOUNDS'}:node.value=ast.parse(repr(TABLE_BOUNDS),mode='eval').body;changed('bounds')
            return self.generic_visit(node)
        def visit_Call(self,node):
            source=ast.unparse(node)
            replacements={"_rows(projects, 2, 240)":"_rows(projects,2,360)",
                "_rows(sites, 2, 40)":"_rows(sites,2,60)",
                "_rows(prereqs, 2, 80)":"_rows(prereqs,2,120)"}
            if source in replacements:
                changed(source);return ast.parse(replacements[source],mode='eval').body
            if ast.unparse(node.func)=='ledger.simulate':
                node.func=ast.parse('finance.simulate_b',mode='eval').body;changed('financial_forward')
            return self.generic_visit(node)
        def visit_Compare(self,node):
            text=ast.unparse(node)
            if text=='n == 240':node.comparators[0]=ast.Constant(360);changed('production_dimension')
            elif text=="setting['version'] == 1":node.comparators[0]=ast.Constant(2);changed('opt_in_version')
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys={key.value:i for i,key in enumerate(node.keys) if isinstance(key,ast.Constant)}
            if {'kind','version','dimension_mode','project_ids','shared_limits'}<=keys.keys():
                node.values[keys['kind']]=ast.Constant(spec.SPEC_KIND);node.values[keys['version']]=ast.Constant(2);changed('raw_identity')
            elif 'kind' in keys and 'version' in keys:
                value=node.values[keys['kind']]
                if isinstance(value,ast.Constant) and value.value=='public_native_linear_capital_reconstruction':
                    node.values[keys['version']]=ast.Constant(2);changed('report_version')
            elif {'version','revision','source','implementation','public_recipe'}<=keys.keys():
                node.values[keys['version']]=ast.Constant(2);changed('witness_version')
            return self.generic_visit(node)
        def visit_Attribute(self,node):
            text=ast.unparse(node)
            if text=="ctx.data['_linear_admission'].source":
                changed('opaque_source');return ast.parse('_admission_source(ctx)',mode='eval').body
            return self.generic_visit(node)
        def visit_If(self,node):
            if ast.unparse(node.test)=='ctx.config.get(SETTING) is None':
                node.body=ast.parse("raise ScaledPublicAdmissionUnavailable('Explicit N360 recovery opt-in and new opaque provider are required')").body
                changed('no_legacy_fallback')
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            if node.name=='valid_linear_capital_recovery_witness':
                node.name='valid_linear_capital_scaled_recovery_witness';changed('witness_name')
            node=self.generic_visit(node)
            if node.name=='_execution_valid':
                for index,item in enumerate(node.body):
                    if isinstance(item,ast.Assign) and ast.unparse(item).startswith("report = json.loads("):
                        node.body.insert(index+1,ast.parse("require(type(report.get('version')) is int and report['version']==2,'A new N360 reconstruction report is required')").body[0])
                        changed('report_version_guard');break
            return node
        def visit_ClassDef(self,node):
            if node.name=='LinearCapitalRecoveryNode':node.name='LinearCapitalScaledRecoveryNode';changed('node_name')
            return self.generic_visit(node)
        def visit_Name(self,node):
            if node.id=='valid_linear_capital_recovery_witness':node.id='valid_linear_capital_scaled_recovery_witness';changed('witness_call')
            return node
        def visit_Constant(self,node):
            replacements={'public_native_linear_capital_reconstruction':'public_native_linear_capital_scaled_reconstruction',
                'linear-recovery-replay-':'linear-scaled-recovery-replay-',
                'sheetsfactory-linear-public-':'sheetsfactory-linear-scaled-public-',
                'linear_recovery_public':'linear_scaled_recovery_public'}
            if node.value in replacements if isinstance(node.value,str) else False:
                node.value=replacements[node.value];changed('name:'+node.value)
            return node
    tree=Adapt().visit(tree)
    expected={'financial_import':1,'generic_refs':2,'setting':1,'backend':1,'bounds':1,
        '_rows(projects, 2, 240)':1,'_rows(sites, 2, 40)':1,'_rows(prereqs, 2, 80)':1,
        'financial_forward':1,'production_dimension':1,'opt_in_version':1,'raw_identity':1,
        'report_version':1,'witness_version':1,'opaque_source':2,'no_legacy_fallback':1,
        'witness_name':1,'report_version_guard':1,'node_name':1,'witness_call':1,
        'name:public_native_linear_capital_scaled_reconstruction':2,
        'name:linear-scaled-recovery-replay-':2,'name:sheetsfactory-linear-scaled-public-':1,
        'name:linear_scaled_recovery_public':1}
    if counts!=expected:raise ValueError('The exact N360 public substitutions changed: '+str(counts))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())

_frozen_settings=_settings


def _settings(ctx):
    profile,profile_ref,runtime_ref,prepared=_frozen_settings(ctx)
    expected={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
    require(all(profile['docker_resources'][role]==expected for role in ('source','agent','verifier')),
        'The new source LO, model and verifier must retain the same 2CPU/32GiB profile')
    return profile,profile_ref,runtime_ref,prepared


def _runtime_source_files():
    # Check every frozen kernel on warm as well as cold preparations. These
    # checks parse source only; they do not run either financial forward.
    spec.adapted_ast();excel.adapted_ast();model_b.adapted_ast()
    for name in finance.UPSTREAMS:finance.adapted_ast(name)
    paths={**finance.source_files(),**model_b.source_files(),
        'excel':Path(excel.__file__),'frozen_excel':excel.upstream_path()}
    return {name+'.py':Path(path).resolve() for name,path in paths.items()}


def inventory(directory):
    return {name:reference(path) for name,path in runtime_support._walk_files(Path(directory)).items()}


def public_program_source():
    tree=adapted_ast();functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    functions['solve_public_model']=ast.parse(inspect.getsource(solve_public_model)).body[0]
    selected=[functions[name] for name in PUBLIC_FUNCTIONS]
    imports='from pathlib import Path\nimport ast,inspect,json,re,tempfile\nimport openpyxl\nfrom portfolio import spec,finance,model_b,excel\n'
    constants='\n'.join(name+' = '+repr(globals()[name]) for name in
        ('PROJECT_COLUMNS','SCENARIO_COLUMNS','INPUT_SHEETS','PUBLIC_TABLE_BOUNDS'))
    return imports+constants+'\n\n'+ast.unparse(ast.Module(body=selected,type_ignores=[]))+'\n'


def public_implementation_recipe():
    adapted_ast();runtime_support.profile_reference()
    return {'transport':reference(__file__),'frozen_public_template':reference(UPSTREAM),
        'vendor_copy_support':reference(runtime_support.__file__),
        **{'package/'+name:reference(path) for name,path in _runtime_source_files().items()}}


def prepare_public_runtime(output,*,vendor_site_packages=None):
    """Generic existing code/vendor copy only; no problem material is accepted."""
    output=Path(output).absolute()
    require(output==output.resolve() and not output.exists(),'Use a fresh real N360 runtime preparation directory')
    output.mkdir(parents=True);directory=output/'runtime';directory.mkdir()
    try:
        recipe=public_implementation_recipe();package=directory/'portfolio';package.mkdir()
        (package/'__init__.py').write_bytes(b'')
        for name,path in _runtime_source_files().items():shutil.copyfile(path,package/name)
        (directory/'public_program.py').write_text(public_program_source(),encoding='utf-8')
        vendor=runtime_support.VENDOR_SITE_PACKAGES if vendor_site_packages is None else vendor_site_packages
        sources=runtime_support._copy_vendor(vendor,directory/'vendor')
        require(recipe==public_implementation_recipe(),'Public N360 runtime code changed during preparation')
        return _write(output/'preparation.json',{'kind':'prepared_public_linear_capital_scaled_recovery_runtime',
            'version':2,'directory':str(directory),'inventory':inventory(directory),'public_recipe':recipe,
            'vendor_sources':sources,'solver_versions':runtime_support.DISTRIBUTIONS,'image_id':IMAGE,
            'model_calls':0,'LO_calls':0,'solver_calls':0,'financial_forwards':0,'qualified':False,
            'normal_quality_opaque_admission_available':False})
    except BaseException as error:
        _write(output/'failure.json',{'type':type(error).__name__,'error':str(error),
            'solver_calls':0,'model_calls':0,'LO_calls':0,'financial_forwards':0});raise


def validate_public_runtime(value):
    record=value if isinstance(value,dict) else reference(value);key=(record['path'],record['sha256'],record['bytes'])
    if key in _RUNTIME_SESSIONS:
        result,refs=_RUNTIME_SESSIONS[key];refs.guard()
        require(result['public_recipe']==public_implementation_recipe(),'The public N360 implementation changed')
        return deepcopy(result)
    refs=References();result=refs.read(record)
    require(result.get('kind')=='prepared_public_linear_capital_scaled_recovery_runtime'
        and type(result.get('version')) is int and result['version']==2
        and result.get('public_recipe')==public_implementation_recipe()
        and result.get('solver_versions')==runtime_support.DISTRIBUTIONS and result.get('image_id')==IMAGE
        and result.get('qualified') is False and result.get('normal_quality_opaque_admission_available') is False
        and all(type(result.get(k)) is int and result[k]==0 for k in ('model_calls','LO_calls','solver_calls','financial_forwards')),
        'A complete frozen new-scope zero-execution public runtime is required')
    directory=Path(result['directory']);require(directory==directory.resolve(),'A real runtime directory is required')
    actual=inventory(directory);require(actual==result['inventory'],'The complete public N360 runtime inventory changed')
    core={'portfolio/__init__.py','public_program.py'}|{'portfolio/'+name for name in _runtime_source_files()}
    require(set(actual)==core|{'vendor/'+name for name in result['vendor_sources']},
        'The runtime contains undeclared files or private task material')
    require((directory/'public_program.py').read_text()==public_program_source()
        and (directory/'portfolio/__init__.py').read_bytes()==b'','The standalone N360 public program differs')
    for name,path in _runtime_source_files().items():
        require({k:actual['portfolio/'+name][k] for k in ('sha256','bytes')}
            =={k:reference(path)[k] for k in ('sha256','bytes')},'A generic public kernel copy differs')
    root=runtime_support.VENDOR_SITE_PACKAGES.absolute()
    require({name.split('/')[0] for name in result['vendor_sources']}==runtime_support.VENDOR_ROOTS,
        'The complete approved solver environment is required')
    for name,original in result['vendor_sources'].items():
        require(not Path(name).is_absolute() and all(part not in ('','.','..') for part in name.split('/'))
            and original['path']==str(root/name),'A vendor source escaped the approved environment')
        refs.check(original)
        require({k:actual['vendor/'+name][k] for k in ('sha256','bytes')}
            =={k:original[k] for k in ('sha256','bytes')},'A public solver package copy differs')
    from email.parser import Parser
    for distribution,version in runtime_support.DISTRIBUTIONS.items():
        metadata=directory/'vendor'/(distribution+'-'+version+'.dist-info')/'METADATA'
        require(metadata.is_file(),'A declared solver distribution lacks metadata')
        fields=Parser().parsestr(metadata.read_text())
        require(fields.get('Version')==version and fields.get('Name','').lower().replace('-','_')==distribution,
            'The installed solver distribution identity/version changed')
    refs.walk(result);_RUNTIME_SESSIONS[key]=(deepcopy(result),refs);return deepcopy(result)
