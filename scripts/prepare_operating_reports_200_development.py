#!/usr/bin/env python3
"""Freeze the fixed200 pair; explicitly run two isolated first attempts under v6."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
_BASE = _ROOT / 'scripts/prepare_period_boundary_development.py'
_BASE_SHA = '44d87bf6fb55fde4a1b29a444ad32d472b7ebe3d7ba8379ce2395bdbf9301c2d'
_VALIDATOR = _ROOT / 'scripts/validate_operating_reports_200_tasks.py'
_VALIDATOR_SHA = 'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5'
_RUNNER_SHA = '4a0c68ce47657f22b00200f5b50c46a88af221968280934a3297a09c44e18d74'
_SPECIFICATION_SHA = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
_LOCK_WAIT_SECONDS = 30.0


def _adapted_ast():
    if _hashlib.sha256(_BASE.read_bytes()).hexdigest() != _BASE_SHA:
        raise ValueError('The frozen shared two-mode lifecycle changed')
    tree = _ast.parse(_BASE.read_bytes()); counts = {}
    def mark(key): counts[key] = counts.get(key, 0) + 1
    replacements = {
        'prequality_synthetic_period_boundary_development_pair': 'prequality_fixed_operating_reports_200_development_pair_v6',
        'synthetic_period_boundary_financial_portfolio': 'fixed_hypothetical_operating_reports_200',
        'synthetic_period_boundary_prequality_development_source': 'fixed_operating_reports_200_prequality_development_source_v6',
        'prequality_period_boundary_native_first_attempt_terminal': 'prequality_fixed_operating_reports_200_native_first_attempt_terminal_v6',
        'period_boundary_permanent_material_first_attempt_reservation': 'fixed_operating_reports_200_permanent_material_first_attempt_reservation_v6',
        'period-boundary-': 'operating-reports-200-',
        'source_specification': 'specification', 'candidate_manifest': 'candidate_preparation',
    }
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'sheets_factory.workbook.period_boundary_portfolio.spec':
                mark('remove_old_brief'); return None
            if node.module == 'sheets_factory.evaluation' and [(n.name,n.asname) for n in node.names] == [('native_transport_frontier','runner')]:
                node.names[0].name = 'linear_capital_scaled_frontier_v6'; mark('runner')
            return node
        def visit_FunctionDef(self, node):
            if node.name in ('recipes', '_checked_engineering', '_instruction', 'reserve', 'main'):
                mark('replace_'+node.name); return None
            return self.generic_visit(node)
        def visit_If(self, node):
            if _ast.unparse(node.test) == "__name__ == '__main__'":
                mark('remove_main_call'); return None
            return self.generic_visit(node)
        def visit_Assign(self, node):
            names = [_ast.unparse(t) for t in node.targets]
            if names == ['VALIDATOR']:
                node.value = _ast.Name('_VALIDATOR',_ast.Load()); mark('validator')
            elif names == ['VALIDATOR_SHA']:
                node.value = _ast.Name('_VALIDATOR_SHA',_ast.Load()); mark('validator_sha')
            return self.generic_visit(node)
        def visit_Attribute(self, node):
            if isinstance(node.value,_ast.Name) and node.value.id == 'runner':
                if node.attr == 'POLICY_V3': node.attr = 'POLICY_V6'; mark('policy')
                elif node.attr == '_persist_failure':
                    mark('failure'); return _ast.Name('_persist_failure',_ast.Load())
            return self.generic_visit(node)
        def visit_Dict(self, node):
            for key,value in zip(node.keys,node.values):
                if isinstance(key,_ast.Constant) and key.value == 'tool_time_policy_version':
                    if not isinstance(value,_ast.Constant) or value.value != 3:
                        raise ValueError('Unexpected inherited clock version')
                    value.value = 6; mark('clock')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in replacements:
                mark('string:'+node.value); node.value = replacements[node.value]
            return node
    tree = Adapt().visit(tree)
    expected = {'remove_old_brief':1,'runner':1,'replace_recipes':1,'replace__checked_engineering':1,
                'replace__instruction':1,'replace_reserve':1,'replace_main':1,'remove_main_call':1,
                'validator':1,'validator_sha':1,'policy':1,'failure':2,'clock':1,
                **{'string:'+key:count for key,count in zip(replacements,(1,2,2,1,0,1,2,2),strict=True)}}
    expected = {key:value for key,value in expected.items() if value}
    if counts != expected:
        raise ValueError('The exact fixed200 first-attempt adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(_adapted_ast(), __file__, 'exec'), globals())
__doc__ = 'Freeze the fixed200 pair; explicitly run two isolated first attempts under v6.'
_base_validate_prepared = validate_prepared
_persist_failure = runner._namespace['_persist_failure']


def _checked_engineering(value):
    driver = validation_driver(); actual = driver.validate_completed(value)
    require(actual['kind'] == 'complete_fixed_operating_reports_200_task_engineering'
            and actual['version'] == 1 and actual['passed'] is True
            and actual['actual_LO_calls_started'] == actual['actual_LO_calls_completed'] == 8
            and actual['qualified'] is False and actual['normal_all12_QA_passed'] is False,
            'Require genuine complete fixed200 eight-call engineering')
    prepared = read(actual['preparation']); candidate = read(prepared['candidate_preparation'])
    require(prepared['kind'] == 'prepared_fixed_operating_reports_200_task_engineering'
            and prepared['version'] == 1 and prepared['source_manifest'] == actual['source_manifest']
            and prepared['financial_target_count'] == 62322 and prepared['independent_business_field_count'] == 93510
            and prepared['DBG_formula_root_count'] == 200 and set(actual['records']['modes']) == set(MODES)
            and candidate['kind'] == 'prepared_unverified_fixed_operating_reports_200_pair'
            and candidate['version'] == 1 and candidate['qualified'] is False
            and candidate['specification'] == prepared['specification']
            and canonical(read(prepared['specification'])) == _SPECIFICATION_SHA,
            'Bind the original fixed200 raw facts and complete 93510/62322/200 scope')
    for mode in MODES:
        material = actual['records']['modes'][mode]
        require(material['goal'] == prepared['genuine_goal']
                and material['controls'] == {'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
                and checked(material['instruction']).read_bytes() == checked(candidate['views'][mode]['instruction']).read_bytes()
                and type(material['complete_D_count']) is int and material['complete_D_count'] > 0
                and (mode != 'financial_modeling' or material['complete_D_count'] == 62322),
                'Keep the genuine unchanged two-mode full-D controls and original public request')
    return actual, {**candidate,'instructions':{mode:candidate['views'][mode]['instruction'] for mode in MODES}}


def _instruction(candidate, mode):
    original = checked(candidate['views'][mode]['instruction']).read_bytes()
    require(bool(original.strip()), 'The original public business request must be present')
    original.decode('utf-8')
    return original, original+b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'


def recipes():
    from sheets_factory.evaluation import clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier
    from sheets_factory.evaluation import native_transport_frontier,native_transport_frontier_v4,clock_resource_frontier_v4,tool_time_clock_bounds_v4
    from sheets_factory.evaluation import linear_capital_scaled_frontier_v4,linear_capital_scaled_frontier_v5,tool_time_clock_bounds_v5,tool_time_clock_bounds_v6
    from sheets_factory.evaluation import resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier
    require(ref(runner.__file__)['sha256'] == _RUNNER_SHA, 'Freeze the prospective v6 native runner')
    runner.verify_dependencies(); runner.adapted_ast(); h = history_helper(); driver = validation_driver()
    paths = [Path(__file__),_BASE,_VALIDATOR,HISTORY,h.SHARED,ROOT/'scripts/prepare_linear_capital_development.py',PROFILE,runner.PROFILE_PATH,
             *[Path(module.__file__) for module in (runner,clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier,
                native_transport_frontier,native_transport_frontier_v4,clock_resource_frontier_v4,tool_time_clock_bounds_v4,
                linear_capital_scaled_frontier_v4,linear_capital_scaled_frontier_v5,tool_time_clock_bounds_v5,tool_time_clock_bounds_v6,
                resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier)]]
    return {**driver.recipes(), **{str(path.resolve()):ref(path) for path in paths}}


def validate_prepared(prepared):
    frozen = _base_validate_prepared(prepared)
    for mode in MODES:
        source = read(frozen['modes'][mode]['source_view'])
        require(source['tool_time_policy_version'] == 6 and source['tool_time_policy'] == dict(runner.POLICY_V6),
                'Freeze strict cumulative clock v6 before either first attempt')
    return frozen


def reserve(prepared, frozen, mode, destination):
    """Lock only this logical material; a different mode never waits on its cold validation."""
    import time
    h = history_helper(); identity = frozen['modes'][mode]['material_task_version']
    core = {key:identity[key] for key in ('mode','input_definitions','input_values','goal_values','instruction_sha256')}
    root = Path(h.HISTORY_ROOTS[0]).absolute(); require(root == root.resolve(),'Use the real history root')
    directory = root/'.native_development_material_reservations'; directory.mkdir(parents=True,exist_ok=True)
    require(directory == directory.resolve(),'The permanent material reservation directory must be real')
    key = canonical(core); fd = os.open(directory/(key+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        deadline = time.monotonic()+_LOCK_WAIT_SECONDS
        while True:
            try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB); break
            except BlockingIOError:
                require(time.monotonic() < deadline,'The same-material reservation lock wait expired; no attempt was launched')
                time.sleep(min(.05,max(0,deadline-time.monotonic())))
        current = h.selection_history(identity)
        require(all(item in current for item in frozen['selection_history_inventory']),'Known historical evidence disappeared')
        partition = h.history_partition(current); path = directory/(key+'.json')
        require(not path.exists() and not path.is_symlink(),'This logical material already reserved its permanent first attempt; no renamed/repacked retry')
        started = Path(prepared)/(mode+'_development_started.json'); require(not started.exists(),'This prepared mode already started')
        reservation = write(path,{'kind':'fixed_operating_reports_200_permanent_material_first_attempt_reservation_v6',
            'version':1,'material_task_version':identity,'content_material_identity':core,
            'prepared_snapshot':ref(Path(prepared)/'probe_manifest.json'),'evaluation_output':str(destination),'mode':mode,
            'selection_history_inventory':current,'prior_model_selection_inventory':partition['model_selections'],
            'nonmodel_preparation_inventory':partition['nonmodel_preparations'],'model':'gpt-6.1-sol','reasoning_effort':'xhigh',
            'outer_retries':0,'no_resampling_after_success_failure_or_infrastructure':True})
        return write(started,{'reservation':reservation,'history':current,'prior_model_selections':partition['model_selections'],
            'mode':mode,'model':'gpt-6.1-sol','reasoning_effort':'xhigh','concurrency':1,'outer_retries':0})


def run_pair(prepared, destination):
    """Exactly two independent processes, each retaining the original per-mode lifecycle."""
    import subprocess
    frozen = validate_prepared(prepared); destination = Path(destination).absolute()
    require(destination == destination.resolve() and not destination.exists(),'Use one fresh pair execution directory')
    destination.mkdir(parents=True); children = {}; streams = []; codes = {}
    write(destination/'pair_started.json',{'kind':'fixed200_two_process_first_attempt_dispatch_v6','version':1,
        'prepared':ref(Path(prepared)/'probe_manifest.json'),'mode_order':list(MODES),'max_parallel_modes':2,
        'per_mode_attempts':1,'outer_retries':0,'qualified':False})
    try:
        for mode in MODES:
            stream = (destination/(mode+'.stdout')).open('xb'); streams.append(stream)
            command = [sys.executable,str(Path(__file__).resolve()),'run-development','--prepared',str(Path(prepared).absolute()),
                       '--mode',mode,'--output',str(destination/mode)]
            children[mode] = subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            write(destination/(mode+'_process_started.json'),{'pid':children[mode].pid,'command':command,
                'task_id':frozen['modes'][mode]['task_id'],'no_credentials_in_arguments':True})
    except BaseException as error:
        _persist_failure(destination/'dispatch_failure',error)
        raise
    finally:
        for mode,child in children.items(): codes[mode] = child.wait()
        for stream in streams: stream.close()
        write(destination/'pair_dispatch_terminal.json',{'kind':'fixed200_two_process_dispatch_terminal_v6','version':1,
            'exit_codes':codes,'launched_modes':list(children),'qualified':False,'outer_retries':0,
            'both_processes_exited_zero':len(codes)==2 and all(code==0 for code in codes.values())})
    require(len(codes)==2 and all(code==0 for code in codes.values()),'At least one original first-attempt process failed; all artifacts are retained')
    return ref(destination/'pair_dispatch_terminal.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command',required=True)
    p = commands.add_parser('prepare'); p.add_argument('--validation',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p = commands.add_parser('validate'); p.add_argument('--prepared',type=Path,required=True)
    p = commands.add_parser('run-development'); p.add_argument('--prepared',type=Path,required=True); p.add_argument('--mode',choices=MODES,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--port',type=int,default=0)
    p = commands.add_parser('run-pair'); p.add_argument('--prepared',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = prepare(args.validation,args.output) if args.command=='prepare' else validate_prepared(args.prepared) if args.command=='validate' else run_pair(args.prepared,args.output) if args.command=='run-pair' else run_development(args.prepared,args.mode,args.output,port=args.port)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
