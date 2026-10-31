"""Research Gurobi adapter tests: mocked solver/Docker only, no license use."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from sheets_factory.workbook.linear_capital_portfolio import gurobi_runtime as runtime, model_gurobi as backend
from sheets_factory.workbook.linear_capital_portfolio import producer_optimization_runtime as original
from test_linear_capital_optimization_runtime import matrix, services


def test_explicit_isolated_research_profile_and_original_namespace_unchanged():
    assert original.BACKENDS == {'cp_sat': ('model_b', 'solve_cp_sat', 'native_model.pbtxt')}
    assert runtime.BACKENDS == {'gurobi': ('model_gurobi', 'solve_gurobi', 'native_model.lp')}
    assert runtime.DISTRIBUTIONS == {'gurobipy': '13.0.0'}
    assert runtime.profile_reference()['path'].endswith('linear_capital_gurobi_research_v1.json')
    assert runtime.reference(original.__file__)['sha256'] == runtime.PRODUCER_UPSTREAM_SHA256
    assert set(runtime._source_files()) == {'model_gurobi.py', 'frozen_optimization_runtime.py'}


def test_bundle_matrix_checks_are_exact_pure_frozen_functions_without_host_root():
    path = Path(original.__file__).with_name('optimization_runtime.py')
    names = {n.name for n in backend.matrix_checks_ast().body}
    expected = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert ast.dump(ast.Module(body=expected, type_ignores=[])) == ast.dump(backend.matrix_checks_ast())
    assert not any(isinstance(n, ast.Assign) for n in backend.matrix_checks_ast().body)


@pytest.mark.parametrize('bad', ['size', 'bool_choice', 'unknown_choice', 'wrong_row', 'coefficient_overflow'])
def test_gurobi_request_rejects_invalid_size_or_exact_integer_domain_before_import(bad):
    model = matrix(); excluded = None
    if bad == 'size': model['rows'] = [dict(model['rows'][0], id=f'r{i:04d}') for i in range(2001)]
    if bad == 'bool_choice': excluded = {'P001': True, 'P002': 0}
    if bad == 'unknown_choice': excluded = {'P001': 1}
    if bad == 'wrong_row': model['rows'][0]['coefficients'] = [1]
    if bad == 'coefficient_overflow': model['rows'][0]['coefficients'][0] = 2**53
    with pytest.raises(ValueError): backend.validate_request(model, excluded)


def test_complete_no_good_counts_against_restricted_license_constraint_limit():
    model = matrix(); model['rows'] = [dict(model['rows'][0], id=f'r{i:04d}') for i in range(2000)]
    backend.validate_request(model, None)
    with pytest.raises(ValueError, match='2000'): backend.validate_request(model, {'P001': 1, 'P002': 0})


def test_solver_requires_isolated_container_not_host_license(tmp_path):
    with pytest.raises(ValueError, match='isolated /app'):
        backend.solve_gurobi(matrix(), time_limit_seconds=30, threads=16,
            log_path=tmp_path/'solver.log', model_path=tmp_path/'native.lp')


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    vendor = tmp_path/'research_vendor'; vendor.mkdir(); (vendor/'dummy.py').write_text('# Explicit fixture\n')
    monkeypatch.setattr(runtime, 'VENDOR_SITE_PACKAGES', vendor); monkeypatch.setattr(runtime, 'VENDOR_ROOTS', {'dummy.py'})
    model = tmp_path/'model.json'; model.write_text(json.dumps(matrix()))
    def make():
        output = tmp_path/'job'; ref = runtime.prepare(model, output, backend='gurobi', time_limit_seconds=30,
            vendor_site_packages=vendor); return output, ref
    return make


def test_prepare_does_not_import_gurobi_or_start_docker(prepared, monkeypatch):
    monkeypatch.setattr(runtime, '_command', lambda *_a, **_k: pytest.fail('No Docker during preparation'))
    output, ref = prepared(); proof = runtime.validate_prepared(output)
    assert proof['resources']['cpus'] == proof['request']['threads'] == 16
    assert proof['request']['time_limit_seconds'] == 30
    assert proof['solver_calls'] == proof['model_calls'] == 0
    assert proof['producer_profile'] == runtime.profile_reference()
    assert set(proof['source_code']) == {'model_gurobi.py', 'frozen_optimization_runtime.py'}


def fake_runtime(output, monkeypatch, *, limited=False, fault=None):
    state = services(monkeypatch); frozen = runtime.validate_prepared(output); bundle = output/'job_bundle'; cid = 'b'*64
    def actual():
        return {'Id': cid, 'Image': runtime.IMAGE_ID, 'Name': '/sf-gurobi-research-'+frozen['request']['nonce'],
            'NanoCpus': 16*10**9, 'Memory': 32*1024**3, 'PidsLimit': 256, 'NetworkMode': 'none',
            'Privileged': False, 'CapDrop': ['ALL'], 'CapAdd': ['CAP_DAC_OVERRIDE'], 'SecurityOpt': ['no-new-privileges'],
            'User': '0', 'WorkingDir': '/app', 'Entrypoint': ['/usr/bin/python3'], 'Cmd': ['/app/run.py'],
            'Mounts': [{'Type': 'bind', 'Source': str(bundle), 'Destination': '/app', 'RW': True}],
            'State': {'Status': 'exited' if state.get('attached') else 'created', 'Running': False, 'ExitCode': 0, 'OOMKilled': False}}
    def command(args, *, timeout=30):
        if args[:3] == ['docker', 'image', 'inspect']: return subprocess.CompletedProcess(args, 0, runtime.IMAGE_ID, '')
        if args[:2] == ['docker', 'create']:
            assert args[args.index('--cpus')+1] == '16' and args[args.index('--network')+1] == 'none'
            return subprocess.CompletedProcess(args, 0, cid, '')
        if args[:2] == ['docker', 'inspect']:
            return (subprocess.CompletedProcess(args, 1, '', 'No such object') if state.get('cleaned')
                else subprocess.CompletedProcess(args, 0, json.dumps(actual()), ''))
        if args[:2] == ['docker', 'rm']:
            state['cleaned'] = True; return subprocess.CompletedProcess(args, 0, cid, '')
        raise AssertionError(args)
    def attach(args, stdout, stderr, timeout):
        assert timeout == 150; state['attached'] = True; stdout.write_text('Explicit offline mock'); stderr.write_text('')
        result = {'status': 'TIME_LIMIT' if limited else 'OPTIMAL', 'checked_optimal': not limited,
            'plan': {'P001': 1, 'P002': 0}, 'objective_pence': 7, 'exclude_plan': None,
            'model_sha256': frozen['model_canonical_sha256'], 'specification_sha256': matrix()['specification_sha256'],
            'universe_sha256': matrix()['universe_sha256'], 'threads': 16, 'time_limit_seconds': 30,
            'gap_parameters': {'relative': 1 if fault == 'gap' else 0, 'absolute': 0}}
        for name, value in (('solver_result.json', result), ('runtime_result.json', {'completed': True,
            'financial_forward_executed': False, 'model_canonical_sha256': frozen['model_canonical_sha256'],
            'backend': 'gurobi', 'threads': 16, 'gap_requested': 0, 'distribution_versions': runtime.DISTRIBUTIONS})):
            (bundle/name).write_text(json.dumps(value))
        for name in ('solver.log', 'native_model.lp', 'native_model.lp.parameters.prm'):
            (bundle/name).write_text('Explicit offline native artifact')
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runtime, '_command', command); monkeypatch.setattr(runtime, '_attach', attach)
    return state


@pytest.mark.parametrize('limited', [False, True])
def test_mocked_gurobi_lifecycle_preserves_limit_and_all_resource_cleanup(prepared, monkeypatch, limited):
    output, _ = prepared(); state = fake_runtime(output, monkeypatch, limited=limited)
    ref = runtime.execute_prepared(output); report = runtime._read(ref['path'])
    assert report['status'] == ('reference_not_proven_optimal' if limited else 'reference_optimal_checked')
    assert state['released'] and state['cleaned'] and state['stopped'] and state['closed']
    assert report['actual_resources_verified'] is True and report['qualified'] is False
    with pytest.raises(ValueError): runtime.execute_prepared(output)


def test_changed_native_gap_rejected(prepared, monkeypatch):
    output, _ = prepared(); state = fake_runtime(output, monkeypatch, fault='gap')
    with pytest.raises(runtime.OptimizationRuntimeError): runtime.execute_prepared(output)
    assert state['cleaned'] and state['released']
