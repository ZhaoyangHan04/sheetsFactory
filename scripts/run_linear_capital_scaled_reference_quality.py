#!/usr/bin/env python3
"""Prepare N360 reference-review quality; services require --prepared --run.

The frozen normal lifecycle is reused in a private namespace. Source/view
admission, construction, numbered diagnosis, repairs and Harbor remain intact.
No public-solving program or public-runtime preparation is required or claimed.
"""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
import importlib.util as _util
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
UPSTREAM = _Path(__file__).with_name('run_linear_capital_scaled_quality.py')
UPSTREAM_SHA256 = 'a81ae3953098d8c0f3e19ebdb250be1a2634a75718f53a0e5089b5b8950af539'
RESOURCE_GATE = _Path(__file__).with_name('run_heterogeneous_native_quality.py')
RESOURCE_GATE_SHA256 = 'e16991e7950e6cc3a9948d59507b768cb2c6fe90d7c098e32a644596cc7d3de4'


def _load(path, digest, name):
    if path != path.resolve() or _hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('A frozen normal lifecycle dependency changed: '+str(path))
    definition = _util.spec_from_file_location(name, path)
    module = _util.module_from_spec(definition); definition.loader.exec_module(module)
    return module


_source = _load(UPSTREAM, UPSTREAM_SHA256, '_N360_reference_normal_lifecycle')
_resource_gate = _load(RESOURCE_GATE, RESOURCE_GATE_SHA256, '_N360_reference_actual_resource_gate')


def adapted_ast():
    if _hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen N360 normal lifecycle changed')
    tree = _source.adapted_ast(); counts = {}
    def mark(key): counts[key] = counts.get(key, 0) + 1
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            changes = {('sheets_factory.pipelines','linear_capital_scaled_quality'):'linear_capital_scaled_reference_review',
                ('sheets_factory.task_adapters','linear_capital_scaled'):'linear_capital_scaled_reference_review'}
            key = (node.module, node.names[0].name) if len(node.names)==1 else None
            if key in changes:
                node.names[0].name=changes[key]; mark('import:'+key[1])
            elif key == ('sheets_factory.workbook','linear_capital_scaled_public_recovery'):
                mark('remove_solver_import'); return None
            return node
        def visit_Constant(self, node):
            names = {'prepared_complete_native_linear_capital_scaled_normal_quality':'prepared_complete_native_linear_capital_scaled_reference_quality',
                'config/pipelines/linear_capital_scaled_quality_v2.yaml':'config/pipelines/linear_capital_scaled_reference_quality_v1.yaml',
                '_normal_scaled_linear_support_':'_normal_reference_scaled_linear_support_'}
            if type(node.value) is str and node.value in names:
                before=node.value; node.value=names[before]; mark('string:'+before)
            return node
        def visit_FunctionDef(self, node):
            if node.name == 'main': mark('remove_main'); return None
            if node.name in {'prepare','prepare_many'}:
                position=next(i for i,a in enumerate(node.args.kwonlyargs) if a.arg=='public_runtime_preparation')
                if node.args.kw_defaults[position] is not None: raise ValueError('The original runtime argument changed')
                node.args.kw_defaults[position]=_ast.Constant(None); mark('runtime_default')
            if node.name == 'recipes':
                class Remove(_ast.NodeTransformer):
                    def visit_Tuple(self, item):
                        values=[n for n in item.elts if not (isinstance(n,_ast.Name) and n.id=='recovery')]
                        if len(values)!=len(item.elts):mark('remove_recipe_solver');item.elts=values
                        return self.generic_visit(item)
                node=Remove().visit(node)
            if node.name == 'execute_prepared':
                for item in _ast.walk(node):
                    if isinstance(item,_ast.Try):
                        for i,statement in enumerate(item.body):
                            if isinstance(statement,_ast.If) and _ast.unparse(statement.test)=='observer.receipt':
                                item.body[i+1:i+1]=_ast.parse("resource_gate = validate_normal_resources(out,audit,observer.receipt)\nif not resource_gate['passed']: status=2").body
                                mark('actual_resource_gate'); break
            return self.generic_visit(node)
        def visit_Assign(self, node):
            targets=[_ast.unparse(n) for n in node.targets]
            if targets==['runtime_ref']:
                node.value=_ast.Constant(None); mark('no_runtime_ref')
            if targets==["config['recovery']"]:
                node.value=_ast.parse("{'compiler_backend':'reference_review','public_solver_required':False,'public_solver_attempted':False}",mode='eval').body
                mark('review_configuration')
            return self.generic_visit(node)
        def visit_Expr(self, node):
            if _ast.unparse(node)=='recovery.validate_public_runtime(runtime_ref)':
                mark('remove_runtime_check'); return None
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    expected={'import:linear_capital_scaled_quality':1,'import:linear_capital_scaled':1,
        'remove_solver_import':1,'string:prepared_complete_native_linear_capital_scaled_normal_quality':1,
        'string:config/pipelines/linear_capital_scaled_quality_v2.yaml':1,
        'string:_normal_scaled_linear_support_':1,'remove_main':1,'runtime_default':2,
        'remove_recipe_solver':1,'actual_resource_gate':1,'no_runtime_ref':1,
        'review_configuration':1,'remove_runtime_check':1}
    if counts!=expected:raise ValueError('The exact reference-review lifecycle adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), str(_source.UPSTREAM), 'exec'), globals())
_recipes = recipes
_prepare_many = prepare_many
_validate_prepared = validate_prepared


def recipes(config, admissions):
    rows = _recipes(config, admissions)
    paths = [UPSTREAM, _source.UPSTREAM, RESOURCE_GATE,
        _Path(pipeline.__file__), _Path(pipeline.source.__file__), pipeline.source.UPSTREAM,
        _Path(adapter.__file__), _Path(adapter._source.__file__), adapter._source.UPSTREAM,
        _Path(_resource_gate.pipeline.__file__)]
    for path in paths:
        record=reference(path); rows[record['path']]=record['sha256']
    return rows


def prepare_many(selections, output, *, provider_registry=pipeline.DEFAULT_PROVIDERS,
                 config_path=DEFAULT_CONFIG):
    return _prepare_many(selections, output, provider_registry=provider_registry,
        config_path=config_path, public_runtime_preparation=None)


def prepare(source_manifest, validation_terminal, output, *, source_provider='scaled360',
            provider_registry=pipeline.DEFAULT_PROVIDERS, config_path=DEFAULT_CONFIG):
    return prepare_many([{'source_manifest':source_manifest,'validation_terminal':validation_terminal,
        'source_provider':source_provider}],output,provider_registry=provider_registry,config_path=config_path)


def validate_prepared(output):
    frozen, config, admissions = _validate_prepared(output)
    require(frozen['public_runtime_preparation'] is None
        and config['diagnosis']['reference_evidence_policy']=='reference_review',
        'A reference-review preparation cannot claim an independent public-solving runtime')
    return frozen, config, admissions


def validate_normal_resources(output, audit, observer_receipt):
    """Existing actual two-role validation withdraws unsupported qualifications."""
    require(_hashlib.sha256(RESOURCE_GATE.read_bytes()).hexdigest()==RESOURCE_GATE_SHA256,
        'The frozen actual Harbor resource gate changed')
    return _resource_gate.validate_normal_resources(output, audit, observer_receipt)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path)
    parser.add_argument('--validation-terminal',type=Path,action='append')
    parser.add_argument('--source-provider',default='scaled360')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--prepared',type=Path)
    parser.add_argument('--run',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.source_manifest,args.validation_terminal,args.output)), 'Use an existing preparation or a fresh explicit inventory')
        if args.run:return execute_prepared(args.prepared,port=args.port)
        frozen=validate_prepared(args.prepared)[0]
        print(json.dumps({'validated':str(args.prepared),'count':frozen['count'],'models':0,'LO_calls':0}));return 0
    require(not args.run and args.source_manifest and args.validation_terminal and args.output,
        'Prepare and review before a later explicit --prepared --run')
    result=prepare_many([{'source_manifest':args.source_manifest,'validation_terminal':terminal,
        'source_provider':args.source_provider} for terminal in args.validation_terminal],args.output)
    print(json.dumps({'preflight':result,'models':0,'LO_calls':0,'solver_calls':0,'Harbor_jobs':0}));return 0


if __name__=='__main__':raise SystemExit(main())
