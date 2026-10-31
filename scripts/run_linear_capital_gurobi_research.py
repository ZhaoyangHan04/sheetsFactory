#!/usr/bin/env python3
"""One restricted-license Gurobi research best/runner attempt; never task release.

Retains the frozen producer's complete finance, matrix, resource, cleanup and
once-only gates in an independent namespace. Only the backend, research labels,
owned container prefix and declared profile change. No financial code changes.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
UPSTREAM = ROOT/'scripts/run_linear_capital_producer_reference.py'
PRODUCER_HARNESS_SHA256 = '7e0610ee7f4665b808da6d37b23c45cd3e1f57d3d525c991d4b8ae81df22bd80'
AUTHORIZED_FINANCE_SHA256 = '799dd082b091e906560f056dafb97af07df2b4a99ddfdee92004cf49c7c4e258'
EMBEDDED_LICENSE_SHA256 = 'bfd93a10cf47cee70f6a2bbc5938e4da380db896bcfabd9c5d08fb7e8bb8e408'
RESEARCH_PURPOSE = 'internal_noncommercial_solver_evaluation_not_task_or_source_publication'


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != PRODUCER_HARNESS_SHA256:
        raise ValueError('The frozen producer orchestration changed')
    tree = _ast.parse(raw); counts = {}
    def mark(name): counts[name] = counts.get(name, 0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            for alias in node.names:
                if alias.name == 'producer_optimization_runtime':
                    alias.name = 'gurobi_runtime'; mark('runtime')
            return node
        def visit_Assign(self, node):
            names = {n.id for n in node.targets if isinstance(n, _ast.Name)}
            if 'KIND' in names:
                node.value = _ast.Constant('linear_capital_gurobi_restricted_research_best_runner_reference'); mark('kind')
            elif 'PREPARED' in names:
                node.value = _ast.Constant('prepared_linear_capital_gurobi_restricted_research_best_runner_reference'); mark('prepared')
            return self.generic_visit(node)
        def visit_Call(self, node):
            if isinstance(node.func, _ast.Attribute) and _ast.unparse(node.func) == 'runtime.prepare':
                for keyword in node.keywords:
                    if keyword.arg == 'backend' and isinstance(keyword.value, _ast.Constant) and keyword.value.value == 'cp_sat':
                        keyword.value.value = 'gurobi'; mark('prepare_backend')
            elif isinstance(node.func, _ast.Name) and node.func.id == '_checked_preparation':
                if isinstance(node.args[2], _ast.Constant) and node.args[2].value == 'cp_sat':
                    node.args[2].value = 'gurobi'; mark('preparation_backend')
            elif isinstance(node.func, _ast.Name) and node.func.id == 'validate_solver_receipt':
                for keyword in node.keywords:
                    if keyword.arg == 'backend' and keyword.value.value == 'cp_sat':
                        keyword.value.value = 'gurobi'; mark('validation_backend')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == '/sf-producer16-integer-':
                node.value = '/sf-gurobi-research-'; mark('owned_name')
            elif node.value == 'Private producer16 global best and runner, independent A/B finance':
                node.value = 'Restricted Gurobi research best and runner, independent A/B finance'; mark('display')
            return node
        def visit_Dict(self, node):
            if any(isinstance(k, _ast.Constant) and k.value == 'kind' and isinstance(v, _ast.Name) and v.id == 'KIND'
                   for k, v in zip(node.keys, node.values)):
                node.keys += [_ast.Constant('research_evaluation_only'), _ast.Constant('prospective_declaration')]
                node.values += [_ast.Constant(True), _ast.parse("reference(output/'prospective_declaration.json')", mode='eval').body]
                mark('research_envelope')
            return self.generic_visit(node)
    tree.body = [n for n in tree.body if not (isinstance(n, _ast.If) and _ast.unparse(n.test) == "__name__ == '__main__'")]
    tree = Adapt().visit(tree)
    expected = {'runtime': 1, 'kind': 1, 'prepared': 1, 'prepare_backend': 2,
        'preparation_backend': 1, 'validation_backend': 1, 'owned_name': 1,
        'display': 1, 'research_envelope': 1}
    if counts != expected:
        raise ValueError('The exact research-only orchestration substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
_base_prepare, _base_validate_prepared = prepare, validate_prepared
_base_validate_completed, _base_validate_solver_receipt = validate_completed, validate_solver_receipt


def recipes():
    paths = [Path(__file__), UPSTREAM, ROOT/'scripts/run_linear_capital_reference.py',
        Path(runtime.__file__), runtime.PROFILE, Path(spec.__file__), Path(finance_crosscheck.__file__),
        Path(runtime.__file__).with_name('optimization_runtime.py'),
        Path(runtime.__file__).with_name('producer_optimization_runtime.py'), *runtime._source_files().values()]
    return {str(p): reference(p) for p in paths}


def _profile():
    return {'research_profile': runtime.profile_reference(), 'image_id': runtime.IMAGE_ID,
        'cpus': 16, 'threads': 16, 'memory_bytes': 32*1024**3, 'pids_limit': 256,
        'network': 'none', 'private_solver_seconds': TIME_LIMIT,
        'agent_and_verifier_cpus_unchanged': 2, 'agent_tool_budget_seconds_unchanged': 1800,
        'research_evaluation_only': True, 'commercial_or_production_use_authorized': False,
        'purpose': RESEARCH_PURPOSE}


def _declaration(preparation):
    frozen = read(preparation)
    require(frozen['financial_crosscheck']['sha256'] == AUTHORIZED_FINANCE_SHA256,
        'Only the exact authorized original C01 financial matrices are in scope')
    return {'kind': 'prospective_restricted_gurobi_C01_research', 'version': 1,
        'preparation': preparation, 'financial_crosscheck': frozen['financial_crosscheck'],
        'best_preparation': frozen['best_preparation'], 'recipe': frozen['recipe'], 'runtime_profile': _profile(),
        'time_limit_seconds_per_job': 3600, 'automatic_retries': 0, 'MIPGap': 0, 'MIPGapAbs': 0,
        'best_then_complete_winner_excluded_runner_only_after_checked_OPTIMAL': True,
        'required_independent_integer_rows_per_matrix': 881, 'required_integer_gap_pence': 1,
        'private_density_gate': frozen['private_density_gate'], 'global_search_implementation_count': 1,
        'independent_financial_implementations': 2, 'purpose': RESEARCH_PURPOSE,
        'license_source': 'public_gurobipy_13.0.0_wheel_embedded_restricted_license_only',
        'embedded_license_sha256': EMBEDDED_LICENSE_SHA256,
        'license_primary_sources': [
            'https://support.gurobi.com/hc/en-us/articles/29682074018833-What-does-Restricted-license-for-non-production-use-only-mean',
            'https://www.gurobi.com/product/pricing-and-licensing/',
            'https://pypi.org/project/gurobipy/13.0.0/'],
        'personal_remote_or_paid_license_permitted': False,
        'commercial_or_production_use_authorization_claimed': False,
        'previous_CP_SAT_and_SCIP_results_preserved': True,
        'native_OPTIMAL_is_not_formal_certificate': True,
        'source_or_task_or_quality_or_difficulty_certified': False,
        'actual_solver_calls_at_declaration': 0, 'model_calls': 0, 'LO_calls': 0}


def prepare(finance_terminal, output):
    finance_ref = reference(finance_terminal) if isinstance(finance_terminal, (str, Path)) else finance_terminal
    require(finance_ref['sha256'] == AUTHORIZED_FINANCE_SHA256, 'The authorized original C01 finance receipt changed')
    record = _base_prepare(finance_terminal, output)
    write(Path(output)/'prospective_declaration.json', _declaration(record))
    return record


def validate_prepared(output):
    frozen, finance = _base_validate_prepared(output)
    record = reference(Path(output)/'preparation.json')
    require(read(Path(output)/'prospective_declaration.json') == _declaration(record),
        'The prospective restricted research declaration changed or is missing')
    return frozen, finance


def validate_solver_receipt(preparation, terminal, *, model, backend, exclude_plan=None):
    require(backend == 'gurobi', 'Only the separately authorized Gurobi research backend is permitted')
    value = _base_validate_solver_receipt(preparation, terminal, model=model, backend=backend, exclude_plan=exclude_plan)
    solver = value['solver']; frozen = read(preparation); bundle = Path(frozen['bundle'])
    license_ref = solver.get('embedded_public_license')
    require(license_ref == {'path': '/app/vendor/gurobipy/.libs/gurobi.lic', 'sha256': EMBEDDED_LICENSE_SHA256, 'bytes': 90}
        and reference(bundle/'vendor/gurobipy/.libs/gurobi.lic')['sha256'] == EMBEDDED_LICENSE_SHA256,
        'The actual job did not use the exact public wheel embedded license')
    require(solver.get('backend') == 'gurobi_restricted_research' and solver.get('solver_version') == '13.0.0'
        and solver.get('research_evaluation_only') is True and solver.get('personal_or_remote_license_used') is False
        and solver.get('formal_global_certificate') is False and solver.get('second_solve_automatically_started') is False
        and solver.get('feasibility_tolerances_changed') is False
        and solver.get('parameters') == {'Threads': 16, 'TimeLimit': 3600.0, 'MIPGap': 0.0, 'MIPGapAbs': 0.0},
        'The actual native Gurobi parameters or restricted research boundary changed')
    require('Restricted license - for non-production use only' in (bundle/'solver.log').read_text(),
        'The actual native log does not identify the restricted public license')
    require(type(solver.get('native_variables')) is int and solver['native_variables'] == 240
        and type(solver.get('native_linear_constraints')) is int
        and solver['native_linear_constraints'] == 881+int(exclude_plan is not None),
        'All 240 projects and all 881 business rows plus the complete no-good must be present')
    if value['checked_optimal']:
        require(type(solver.get('raw_status')) is int and solver['raw_status'] == 2,
            'Only native Gurobi OPTIMAL can establish this research reference')
    return value


def validate_completed(value):
    result = _base_validate_completed(value)
    output = Path(result['preparation']['path']).parent
    require(result.get('research_evaluation_only') is True
        and result['prospective_declaration'] == reference(output/'prospective_declaration.json'),
        'The result is not the exact prospective restricted research attempt')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
