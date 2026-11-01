#!/usr/bin/env python3
"""Corrected cached-source admission and same-daemon two-input engineering."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
from pathlib import Path
import subprocess
from types import FunctionType

_ROOT = Path(__file__).resolve().parents[1]
_BASE = _ROOT/'scripts/build_cached_ringfenced_pair_task_batch.py'
_BASE_SHA = 'dd25b46be03f4e2b678a09614c6c2e95a80e6482bcedca3adace1749ce61d651'
if hashlib.sha256(_BASE.read_bytes()).hexdigest() != _BASE_SHA:
    raise ValueError('The original frozen two-input task builder changed')
_loader = importlib.util.spec_from_file_location('_cached_pair_task_frozen_v1', _BASE)
_original = importlib.util.module_from_spec(_loader); _loader.loader.exec_module(_original)
for _name, _value in vars(_original).items():
    if not _name.startswith('__'):
        globals()[_name] = _value
for _name, _value in vars(_original).items():
    if isinstance(_value, FunctionType) and _value.__globals__ is vars(_original):
        _function = FunctionType(_value.__code__, globals(), _name, _value.__defaults__, _value.__closure__)
        _function.__kwdefaults__ = _value.__kwdefaults__; globals()[_name] = _function

SOURCE_BUILDER = ROOT/'scripts/build_cached_ringfenced_pair_source_revision2.py'
SOURCE_BUILDER_SHA = '08b6e3055178f5516de71eaeb4e5cbb82f56adfe78f394a7a70e0c5bff5ed855'
_inherited_recipes = recipes


def recipes():
    require(ref(_BASE)['sha256'] == _BASE_SHA, 'The frozen original task builder changed')
    return {**_inherited_recipes(), 'original_task_builder': ref(_BASE),
        'same_daemon_before_after_required': True}


def _daemon_id():
    identity = subprocess.run(['docker', 'info', '--format', '{{.ID}}'],
        capture_output=True, text=True, check=True).stdout.strip()
    require(bool(identity), 'The Docker daemon identity before the first input call is unknown')
    return identity


def _owned_cleanup(observations, daemon_before_id):
    require(bool(daemon_before_id), 'The initial Docker daemon identity is unknown')
    value = dual.owned_cleanup(observations)
    require(value['passed'] is True and value['all_owned_containers_absent'] is True
        and value['daemon_id'] == daemon_before_id, 'Input cleanup belongs to another or unknown Docker daemon')
    return {**value, 'daemon_before_id': daemon_before_id, 'same_daemon_before_after': True}


_tree = ast.parse(inspect.getsource(_original.run))
_run = _tree.body[0]
_try = next(node for node in _run.body if isinstance(node, ast.Try))
_run.body.insert(_run.body.index(_try), ast.parse('daemon_before_id = None').body[0])
_engine = [node for node in _try.body if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == 'engine' for target in node.targets)]
require(len(_engine) == 1, 'The private native engine construction seam changed')
_position = _try.body.index(_engine[0])+1
_try.body[_position:_position] = ast.parse("""
daemon_before_id = _daemon_id()
write(output/'native_daemon_before.json', {'daemon_before_id': daemon_before_id,
    'prospective': prospective, 'runtime_profile': ref(PROFILE)})
""").body


class _Cleanup(ast.NodeTransformer):
    count = 0
    terminal = 0
    failure = 0

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == 'dual' and node.func.attr == 'owned_cleanup':
            require(len(node.args) == 1 and not node.keywords, 'The original cleanup signature changed')
            self.count += 1
            return ast.copy_location(ast.Call(func=ast.Name(id='_owned_cleanup', ctx=ast.Load()),
                args=[*node.args, ast.Name(id='daemon_before_id', ctx=ast.Load())], keywords=[]), node)
        return node

    def visit_Dict(self, node):
        self.generic_visit(node)
        names = [key.value for key in node.keys if isinstance(key, ast.Constant)]
        if 'actual_native_input_calls' in names:
            self.terminal += 1
            node.keys.append(ast.Constant('native_daemon_before'))
            node.values.append(ast.parse("ref(output/'native_daemon_before.json')", mode='eval').body)
        if 'actual_LO_calls_started' in names and 'failure_is_not_model_zero' in names:
            self.failure += 1
            node.keys.append(ast.Constant('daemon_before_id'))
            node.values.append(ast.Name(id='daemon_before_id', ctx=ast.Load()))
        return node


_patch = _Cleanup(); _tree = _patch.visit(_tree)
require((_patch.count, _patch.terminal, _patch.failure) == (2, 1, 1), 'The exact two-input cleanup/result seams changed')
exec(compile(ast.fix_missing_locations(_tree), __file__, 'exec'), globals())


if __name__ == '__main__': main()
