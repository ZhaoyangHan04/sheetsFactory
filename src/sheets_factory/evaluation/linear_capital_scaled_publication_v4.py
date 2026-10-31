"""Genuine N360 reference-review admission for prospective v4 publication.

Only the N360 source/view boundary and its retained local-control layout differ
from the frozen generic resource publisher. No public solver is required or
claimed. Loading this module performs no service calls.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from . import clock_resource_publication as template
from . import clock_resource_publication_v4 as clocks
from . import linear_capital_scaled_frontier_v4 as native
from .streaming_verifier import compare_files
from ..pipelines import linear_capital_scaled_reference_review as admission
from ..task_adapters import linear_capital_scaled_reference_review as adapter
from ..workbook.resource_engine import load_runtime_profile

ROOT = Path(__file__).resolve().parents[3]
require = template.require
KIND = 'frozen_linear_capital_scaled_reference_quality_cohort_v4'
NORMAL_ENTRY = 'scripts/run_linear_capital_scaled_reference_quality.py'
NORMAL_ENTRY_SHA256 = '4df6616a67a491fa6824bd16a87744a7e5ddec64f5a8e8fd3d491714e232c516'
EXTRA_RECIPE = (
    'src/sheets_factory/evaluation/clock_resource_publication_v4.py',
    'src/sheets_factory/evaluation/linear_capital_scaled_publication_v4.py',
    'src/sheets_factory/evaluation/linear_capital_scaled_finalization_v4.py',
    'src/sheets_factory/evaluation/tool_time_clock_bounds_v4.py',
    'src/sheets_factory/evaluation/clock_resource_frontier_v4.py',
    'src/sheets_factory/evaluation/native_transport_frontier_v4.py',
    'src/sheets_factory/evaluation/linear_capital_scaled_frontier_v4.py',
    'src/sheets_factory/evaluation/native_transport_frontier.py',
    'config/native_transport_profiles/factory_stream_retries8_v1.json',
    'scripts/publish_linear_capital_scaled_v4.py',
    NORMAL_ENTRY,
    'src/sheets_factory/pipelines/linear_capital_scaled_reference_review.py',
    'src/sheets_factory/task_adapters/linear_capital_scaled_reference_review.py',
    'config/pipelines/linear_capital_scaled_reference_quality_v1.yaml',
    'config/task_adapters/linear_capital_scaled_reference_review_nodes.yaml',
    'scripts/audit_harbor_job.py')
_MATERIAL_IDENTITIES={}


def material_identity(directory,mode):
    """Ignore task names and ZIP packaging, while hashing every typed cell.

    Reuse is keyed by freshly checked complete file SHA values, never filesystem
    timestamps. The same bytes copied into a cohort need no second XML scan.
    """
    import hashlib,json
    directory=Path(directory)
    source=reference(directory/'environment/input.xlsx');goal=reference(directory/'tests/reference.xlsx')
    instruction=reference(directory/'instruction.md')
    key=(mode,source['sha256'],source['bytes'],goal['sha256'],goal['bytes'],instruction['sha256'])
    if key not in _MATERIAL_IDENTITIES:
        template._frozen_ast(ROOT/'scripts/prepare_linear_capital_development.py',
            '5bafc37a217545fe96d79a97c834c1439b6b1b859f38efeaa95223e941d51ba4')
        helper=support(ROOT,'prepare_linear_capital_development.py')
        core={'mode':mode,'input_definitions':helper.workbook_identity(source['path'],formulas=True),
            'input_values':helper.workbook_identity(source['path']),'goal_values':helper.workbook_identity(goal['path']),
            'instruction_sha256':instruction['sha256']}
        digest=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        _MATERIAL_IDENTITIES[key]={**core,'sha256':digest}
    return deepcopy(_MATERIAL_IDENTITIES[key])


@lru_cache(maxsize=1)
def normal_entry():
    template._frozen_ast(ROOT/NORMAL_ENTRY, NORMAL_ENTRY_SHA256)
    return template.support(ROOT, Path(NORMAL_ENTRY).name)


def control_attempt(base, tracked, release):
    """Resolve one immutable completed current-revision attempt, never 'latest'."""
    base = Path(base); controls = release._json(base/'private/local_controls.json', base, tracked)
    revision = release._json(base/'private/diagnosis.json', base, tracked)['reference_binding']['task_revision_hash']
    source, goal = template.reference(base/'public/input.xlsx'), template.reference(base/'private/goal.xlsx')
    matches = []
    directory = base/'private/controls'
    template.require(directory == directory.resolve() and directory.is_dir(), 'Actual N360 control history is missing')
    for path in sorted(directory.glob('attempt_*/attempt.json')):
        value = release._json(path, base, tracked)
        template.require(type(value.get('completed')) is bool, 'Malformed retained N360 control attempt')
        if value['completed'] and value.get('revision_hash') == revision and value.get('source') == source and value.get('goal') == goal:
            template.require(value.get('reports') == controls, 'Completed N360 control reports changed')
            matches.append((path, value))
    template.require(len(matches) == 1, 'Require exactly one completed matching N360 local-control attempt')
    return matches[0]


def control_path(base, name, tracked, release):
    if name == 'oracle': return Path(base)/'private/goal.xlsx'
    if name == 'nop': return Path(base)/'public/input.xlsx'
    template.require(name in {'equivalent', 'missed_root', 'extra_change'}, 'Unknown local control')
    path, _ = control_attempt(base, tracked, release)
    return path.parent/(name+'.xlsx')


@lru_cache(maxsize=1)
def release_namespace():
    tree = template._frozen_ast(ROOT/'scripts/package_release.py', '8d81ac3e6300e9159e435125884dee1e915f5b89ead1098ed9c35f51e4db2ff2')
    counts = {'path': 0, 'comparison': 0}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_validate_reference_review':
            for item in ast.walk(node):
                if isinstance(item, ast.Assign) and [ast.unparse(t) for t in item.targets] == ['output']:
                    item.value = ast.parse('_n360_control_path(base, name, tracked, _this_release)', mode='eval').body; counts['path'] += 1
                elif isinstance(item, ast.Assign) and [ast.unparse(t) for t in item.targets] == ['actual']:
                    template.require(ast.unparse(item.value) == 'compare_workbooks(input_path, goal_path, output)',
                        'The exact reference-review control comparator changed')
                    item.value.func.id = '_n360_compare_files'; counts['comparison'] += 1
    template.require(counts == {'path': 1, 'comparison': 1}, 'The bounded N360 control-layout adaptation changed')
    module = ModuleType('sheets_factory_N360_reference_release')
    module.__file__ = str(ROOT/'scripts/package_release.py')
    module.__dict__.update(_n360_control_path=control_path, _n360_compare_files=compare_files, _this_release=module)
    exec(compile(ast.fix_missing_locations(tree), module.__file__, 'exec'), module.__dict__)
    return module


@lru_cache(maxsize=1)
def publisher_namespace():
    # The generic atomic publisher serializes this explicit pending status into
    # the delivered manifest. Root-job finalization is a separate later gate.
    tree = clocks.publisher_ast(); count = 0; retry_guard = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ['manifest'] and isinstance(node.value, ast.Dict):
            node.value.keys.extend(ast.Constant(k) for k in ('final20_qualified', 'final_root_controls_pending', 'reference_evidence_policy'))
            node.value.values.extend([ast.Constant(False), ast.Constant(True), ast.Constant('reference_review')]); count += 1
        if isinstance(node, ast.FunctionDef) and node.name == '_validate_confirmation_history':
            node.body.insert(0,ast.parse("_require(not evidence.get('infrastructure_retries') and not evidence.get('infra_history') and frozen.get('infrastructure_retry_policy') == {'max_retries':0,'scored_attempts_per_task':1,'never_retry_scored':True}, 'The fixed N360 confirmation has zero outer retries and preserves infrastructure as unknown')").body[0]);retry_guard += 1
    template.require(count == retry_guard == 1, 'The exact generic final manifest or history declaration changed')
    module = ModuleType('sheets_factory_N360_v4_dataset_publisher'); module.__file__ = str(ROOT/'scripts/publish_linear_capital_scaled_v4.py')
    module.__dict__.update(_policy_v4=_policy_n360, _track_v4=_track_n360, _project_v4=_project_n360)
    exec(compile(ast.fix_missing_locations(tree), module.__file__, 'exec'), module.__dict__)
    module.release = release_namespace()
    return module


def _policy_n360(frozen, require):
    require(type(frozen.get('tool_time_policy_version')) is int and frozen['tool_time_policy_version'] == 4
        and frozen.get('tool_time_policy') == native.POLICY_V4,
        'Require the prospectively declared complete N360 v4 budget policy')
    return dict(native.POLICY_V4)


def _track_n360(timing, result_path, tracked, backend, base_tracker, release, require):
    from types import SimpleNamespace
    require(backend is not None and backend.runner.POLICY_V4 == native.POLICY_V4,
        'Require the explicit prospective N360 negative-bound policy')
    if timing.get('measurement_branch') != 'complete_proven_lower_bound_exhausted':
        context = SimpleNamespace(runner=SimpleNamespace(POLICY_V4=clocks.POLICY_V4), cohort=backend.cohort)
        return clocks._track_v4(timing, result_path, tracked, context, base_tracker, release, require)
    stop=Path(result_path).parent/'private/tool_time/stop_receipt.json'
    expected = native.account_trial_tool_time_v4(result_path,stop_receipt_file=stop if stop.is_file() else None)
    require(timing == expected and timing.get('state') == 'verified_tool_budget_lower_bound'
        and timing.get('passed') is False, 'The original complete evidence does not reproduce the negative bound')
    previous = timing['retained_general_v4_receipt']; bound = previous['complete_owned_overlap_receipt']
    require(bound.get('complete') is True and bound.get('cumulative_exact_ns') is None
        and bound.get('cumulative_tool_seconds') is None and type(bound.get('cumulative_lower_bound_ns')) is int
        and bound['cumulative_lower_bound_ns'] >= 1800*10**9
        and bound['cumulative_lower_bound_ns'] <= bound['cumulative_upper_bound_ns'],
        'An incomplete or straddling interval cannot prove budget exhaustion')
    sessions = bound['original_exact_receipt']['session_files']; result_path = Path(result_path).absolute()
    require(len(sessions) == 1 and Path(sessions[0]['path']).is_relative_to(result_path.parent/'agent/sessions'),
        'The complete negative proof requires its original unique native session')
    files = bound['artifacts']; code = [backend.cohort['publication_recipe']['src/sheets_factory/evaluation/'+name]
        for name in ('tool_time_clock_bounds_v4.py','tool_time_clock_bounds.py','tool_time.py')]
    trial = {str(result_path), str(result_path.parent/'agent/codex.txt'), sessions[0]['path']}
    require(len(files) == 6 and len({r['path'] for r in files}) == 6
        and {r['path'] for r in files} == trial | {r['path'] for r in code}, 'Negative-bound artifact closure differs')
    for record in files:
        if record['path'] not in trial: require(record in code, 'An undeclared timing parser was used')
        else: release._file(Path(record['path']),result_path.parent,tracked)
        require(reference(record['path']) == record, 'Negative-bound evidence changed')
        require(tracked.setdefault(record['path'],record['sha256']) == record['sha256'], 'Conflicting negative-bound evidence')
    base_tracker(bound['original_exact_receipt'],result_path,tracked)
    base_tracker(previous['base_policy_v3_receipt']['base_policy_v2_receipt'],result_path,tracked)
    if stop.is_file():
        import json
        value=json.loads(release._file(stop,result_path.parent,tracked))
        for record in (value.get('identity_file'),value.get('result_file')):
            require(isinstance(record,dict),'An inspected negative-bound stop input is missing')
            release._file(Path(record['path']),result_path.parent,tracked)
            require(reference(record['path'])==record,'An inspected negative-bound stop input changed')
        identity=read(value['identity_file']['path']);record=identity['trial_config']
        release._file(Path(record['path']),result_path.parent,tracked)
        require(reference(record['path'])==record,'The original inspected negative-bound configuration changed')
    return {'complete_proved_failure_artifact_sha256':{r['path']:r['sha256'] for r in files},'clock_bound_is_exact':False}


def _project_n360(timing, evidence, require):
    if timing.get('measurement_branch') != 'complete_proven_lower_bound_exhausted':
        return clocks._project_v4(timing,evidence,require)
    require(timing.get('passed') is False and timing.get('state') == 'verified_tool_budget_lower_bound',
        'The complete negative timing projection changed')
    fields = ('method','budget_seconds','strict_less_than','state','passed','cumulative_tool_seconds','cumulative_exact_ns',
        'cumulative_lower_bound_ns','cumulative_upper_bound_ns','cumulative_lower_bound_seconds','cumulative_upper_bound_seconds',
        'parallel_executions','model_response_time_included','coverage')
    return {**{k:timing[k] for k in fields},'policy_version':4,'measurement_branch':timing['measurement_branch'],
        'cumulative_tool_nanoseconds':None,'evidence_sha256':evidence}


def _run(self, run, family, tracked):
    run = Path(run).absolute(); require(run == run.resolve() and run.is_dir(), 'A real original normal-quality directory is required')
    require(family in self_families(), 'Only genuine N360 modes are admitted')
    key = str(run)
    if key not in self.runs:
        entry = normal_entry(); frozen, config, sessions = entry.validate_prepared(run)
        require(config['diagnosis']['reference_evidence_policy'] == 'reference_review'
            and config['recovery'] == {'compiler_backend': 'reference_review', 'public_solver_required': False, 'public_solver_attempted': False},
            'Only the current all-check reference-review route is admitted')
        profile = admission.validate_configuration(config)
        require(profile['image']['id'] == IMMUTABLE_IMAGE, 'The approved immutable N360 image is required')
        proofs = []
        for session in sessions:
            source = admission.require_source_admission(session.source)
            proof = admission.require_view_admission(session)
            require(type(session.source) is admission.LinearSourceAdmission
                and type(session) is admission.ReferenceViewAdmission and session.source.provider_id == 'scaled360'
                and proof['kind'] == 'admitted_complete_native_linear_capital_scaled_reference_review_view'
                and proof['version'] == 2 and proof['source_provider'] == 'scaled360'
                and proof['source_financial_evidence'] == source,
                'A genuine complete N360 source and exact forty-recipe view admission are required')
            proofs.append(proof)
        self.runs[key] = {'frozen': frozen, 'config': config, 'sessions': sessions, 'proofs': proofs, 'profile': profile}
        self._bind([reference(run/'preflight_manifest.json'), frozen, config[adapter.SETTING]], self.extra_tracked)
    self._bind(self.runs[key]['proofs'], tracked)
    for path, digest in self.extra_tracked.items():
        require(tracked.setdefault(path, digest) == digest, 'Conflicting frozen N360 dependency')
    return self.runs[key]


def _validate_task(self, run, task, tracked):
    row = self._mapping(task['id']); run = Path(run)
    require(str(run.absolute()) == row['source_run'] and task.get('status') == 'qualified'
        and all(task.get(k) == row[k] for k in ('mode', 'revision', 'revision_hash', 'source_id'))
        and task.get('harbor_export_binding') == row['audited_harbor_export_binding']
        and audit_binding_matches(row['harbor_export_binding'], task['harbor_export_binding']),
        'The current N360 qualified revision differs from its prospectively frozen mapping')
    state = self._run(run, row['family'], tracked)
    require(material_identity(run/'SpreadsheetEval'/task['id'],task['mode'])==row['material_task_version'],
        'The independently checked logical material differs from its phase reservation identity')
    matches = [(s, p) for s, p in zip(state['sessions'], state['proofs']) if p['mode'] == task['mode'] and p['workbook']['sha256'] == task['source_id']]
    require(len(matches) == 1, 'The task has no unique genuine admitted N360 view')
    session, proof = matches[0]; admission.require_source_admission(session.source); admission.require_view_admission(session)
    base = run/'tasks'/task['id']/'revisions'/f"{task['revision']:03d}"; private = base/'private'; public = base/'public'
    for path, expected in ((public/'input.xlsx', proof['input']), (private/'goal.xlsx', proof['goal'])):
        actual = reference(path); require((actual['sha256'], actual['bytes']) == (expected['sha256'], expected['bytes']), 'The genuine admitted task workbook changed')
    plan = read(private/'plan.json'); expected = adapter.canonical_plan(session)
    require({k: v for k, v in plan.items() if k != 'public_instruction'} == {k: v for k, v in expected.items() if k != 'public_instruction'}
        and plan['public_instruction'] == (public/'instruction.md').read_text(), 'The complete N360 construction or current instruction differs')
    delta = compare_workbooks(public/'input.xlsx', private/'goal.xlsx', private/'goal.xlsx')
    require(read(private/'expected_delta.json') == delta and delta == session.delta,
        'The independently admitted complete actual N360 delta changed')
    diagnosis = read(private/'diagnosis.json')
    require(diagnosis.get('releasable') is True and diagnosis.get('reference_evidence_policy') == 'reference_review'
        and len(diagnosis.get('enabled_check_ids', [])) == 12
        and set(diagnosis['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1,13)}, 'All twelve current normal checks are mandatory')
    # Generic release checks the actual payload-digested public/review batches,
    # supported Q01–Q04, current reference receipt and oracle/nop again.
    attempt_path, attempt = control_attempt(base, tracked, self.release)
    controls = read(private/'local_controls.json'); require(set(controls) == set(CONTROL_REWARDS), 'Require all five controls')
    calls = attempt.get('actual_LO_calls', [])
    require(len(calls) == 3 and [c.get('role') for c in calls] == ['normal_control_'+n for n in ('equivalent','missed_root','extra_change')],
        'Require exactly the retained three actual N360 local-control calls')
    resources = []
    for name, reward in CONTROL_REWARDS.items():
        output = control_path(base, name, tracked, self.release)
        actual = compare_files(public/'input.xlsx', private/'goal.xlsx', output)
        require(actual == controls[name] and type(actual.get('reward')) is int and actual['reward'] == reward,
            'A complete N360 local control is inconsistent: '+name)
    for call, name in zip(calls, ('equivalent','missed_root','extra_change')):
        require(call.get('completed') is True and call['input'] == reference(attempt_path.parent/(name+'.raw.xlsx'))
            and call['output'] == reference(attempt_path.parent/(name+'.xlsx')), 'A retained local-control call uses different actual bytes')
        evidence = call['actual_resource_evidence']
        actual = session.source.helper.validate_actual_call(call, evidence['terminal'],
            {'runtime_profile': proof['runtime_profile'], 'runtime_profile_value': state['profile']})
        require(actual == evidence and actual.get('thread_cap_verified') is True, 'Actual capped calculation resource/cleanup evidence differs')
        resources.append(actual)
    self._bind([attempt, plan, delta, reference(private/'diagnosis.json')], tracked)
    observation = reference(run/'normal_Harbor_resource_observation.json'); wrapper = checked(observation)
    observation_ref = wrapper['receipt']; self._bind([observation, observation_ref], tracked)
    if row.get('control_observation_receipts') is not None:
        require(row['control_observation_receipts'] == {a: [observation_ref] for a in ('oracle','nop')}, 'The frozen actual normal observer inventory changed')
    observed_row = {**row, 'control_observation_receipts': {a: [observation_ref] for a in ('oracle','nop')}}
    harbor_resources = self.validate_control_observations(observed_row, task, state['profile'], tracked)
    self.tasks[task['id']] = {'source_run': str(run), 'family': row['family'], 'task': deepcopy(task),
        'runtime_profile': proof['runtime_profile'], 'runtime': state['profile'], 'source_admission': reference(run/'preflight_manifest.json'),
        'view_admission': proof, 'reference_evidence_policy': 'reference_review', 'public_solver_required': False,
        'actual_calculation_resource_bindings': resources, 'actual_harbor_resource_bindings': harbor_resources}


def _validate_n360_cohort(cohort):
    import hashlib,json
    require(len(cohort['tasks'])==20 and all(sum(r['mode']==mode for r in cohort['tasks'])==10 for mode in MODES)
        and cohort.get('tool_time_policy')==native.POLICY_V4 and cohort.get('native_transport_profile')==native.transport_profile()
        and cohort.get('effective_infrastructure_retries')==0 and cohort.get('execution_concurrency')==4
        and cohort.get('reference_evidence_policy')=='reference_review' and cohort.get('public_solver_required') is False
        and cohort.get('final20_qualified') is False and cohort.get('confirmation_phase_once_per_material') is True,
        'The genuine N360 whole-twenty prospective phase/resource/policy declaration differs')
    identities=[r.get('material_task_version',{}).get('sha256') for r in cohort['tasks']]
    require(None not in identities and len(set(identities))==20,'Every N360 confirmation material must be distinct')
    require(cohort.get('confirmation_cohort_identity')==hashlib.sha256(json.dumps(sorted(identities),sort_keys=True,
        separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest(),'The common full-cohort material identity differs')


def _bind_confirmation_reservation(self,frozen_path,frozen,evaluation,tracked):
    directory=self.root/'outputs/difficulty/.linear_scaled_confirmation_reservations'
    common=directory/('cohort_'+self.cohort['confirmation_cohort_identity']+'.json')
    record=reference(common);value=checked(record)
    require(value.get('kind')=='linear_capital_scaled_v4_confirmation_reservation' and value.get('version')==1
        and value.get('phase')=='confirmation' and value.get('cohort')==reference(self.cohort_path)
        and value.get('cohort_identity')==self.cohort['confirmation_cohort_identity']
        and value.get('evaluation_output')==str(Path(frozen_path).parent)
        and value.get('effective_infrastructure_retries')==0
        and _stamp(value['started_at'])<=_stamp(frozen['frozen_at']),
        'The complete phase confirmation lacks its original durable shared reservation')
    prior={r['path']:r['sha256'] for r in frozen.get('prior_selections',[])}
    require(all(prior.get(r['path'])==r['sha256'] for r in value['model_selections']),
        'The selection silently dropped model history captured at reservation')
    self._bind([record,value],tracked)
    for row in self.cohort['tasks']:
        material=reference(directory/('material_'+row['material_task_version']['sha256']+'.json'))
        require(checked(material)=={**value,'common_reservation':record,'material_task_version':row['material_task_version']},
            'A material reservation is missing, shared across cohorts or changed')
        self._bind(material,tracked)


def backend_ast():
    tree = template.backend_ast(); counts = {'runner': 0, 'kind': 0, 'recipe': 0, 'agent': 0, 'run': 0, 'task': 0, 'release': 0, 'version': 0, 'policy': 0, 'reference': 0, 'families': 0, 'metadata': 0, 'cohort_guard':0,'reservation_guard':0}
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module is None and [(a.name,a.asname) for a in node.names] == [('clock_resource_frontier','runner')]:
                node.names[0].name = 'linear_capital_scaled_frontier_v4'; counts['runner'] += 1
            return node
        def visit_Assign(self, node):
            targets = [ast.unparse(t) for t in node.targets]
            if targets == ['KIND']: node.value = ast.Constant(KIND); counts['kind'] += 1
            elif targets == ['RECIPE_FILES']:
                node.value.elts.extend(ast.Constant(n) for n in EXTRA_RECIPE); counts['recipe'] += 1
            elif targets == ['agent_import_path']:
                node.value = ast.Constant('sheets_factory.evaluation.linear_capital_scaled_frontier_v4:LocalCodex'); counts['agent'] += 1
            elif targets == ['self.release']:
                node.value = ast.parse('release_namespace()',mode='eval').body; counts['release'] += 1
            return self.generic_visit(node)
        def visit_FunctionDef(self, node):
            if node.name in {'_run','validate_task'}:
                target = '_n360_run' if node.name == '_run' else '_n360_validate_task'
                node.body = ast.parse('return '+target+'('+', '.join(a.arg for a in node.args.args)+')').body
                counts['run' if node.name == '_run' else 'task'] += 1; return node
            if node.name == 'self_families':
                node.body = ast.parse("return {'linear_capital_scaled_FM': 'financial_modeling', 'linear_capital_scaled_DBG': 'debugging'}").body
                counts['families'] += 1; return node
            if node.name=='validate_cohort_shape':
                node.body.append(ast.parse('_validate_n360_cohort(cohort)').body[0]);counts['cohort_guard']+=1
            elif node.name=='validate_confirmation_source':
                node.body.append(ast.parse('_bind_confirmation_reservation(self,frozen_path,frozen,evaluation,tracked)').body[0]);counts['reservation_guard']+=1
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = ast.unparse(node)
            if text == "cohort['version'] == 1": node.comparators[0] = ast.Constant(4); counts['version'] += 1
            elif text == "cohort.get('tool_time_policy_version') == 3": node.comparators[0] = ast.Constant(4); counts['policy'] += 1
            return self.generic_visit(node)
        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and ast.unparse(node.func) == 'self.release._validate_task':
                node.keywords.append(ast.keyword(arg='reference_policy',value=ast.Constant('reference_review'))); counts['reference'] += 1
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == 'SHA-bound source, actual calculation receipts and strict public replay resource witness':
                node.value = 'Genuine N360 source/view, actual calculation and Harbor resources, supported reference review; no public-solving claim'; counts['metadata'] += 1
            return node
    tree = Adapt().visit(tree)
    require(counts == {k: 1 for k in counts}, 'The bounded genuine N360 publication adaptation changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_n360_run, _n360_validate_task = _run, _validate_task
exec(compile(backend_ast(), __file__, 'exec'), globals())
LinearCapitalScaledPublicationBackend = ResourcePublicationBackend
