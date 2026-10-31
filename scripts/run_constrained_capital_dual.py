#!/usr/bin/env python3
"""Prepare by default; explicitly execute the first constrained dual reference.

This source-engineering tool never calls a model or LibreOffice and never
qualifies a benchmark task. Existing failed engineering checks stay historical.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import threading
import time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as catalog
from sheets_factory.workbook.capital_allocation_scaled import ledger, search_a, search_b, spec

PREPARED_KIND = 'prepared_first_constrained_capital_dual_search'
TERMINAL_KIND = 'complete_constrained_scaled_capital_dual_search'
COUNT = 1 << 30
RECORD_BYTES = COUNT * spec.RECORD_BYTES
RANK_FIELDS = (*search_a.RANK_FIELDS, 'best_full_mask', 'best_plan')


def reference(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked(record):
    spec.require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}, 'Bind path, SHA and byte count')
    spec.require(reference(record['path']) == record, 'Frozen constrained-dual artifact changed: ' + record['path'])
    return Path(record['path'])


def read(record): return json.loads(checked(record).read_text())


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return reference(path)


def recipe():
    paths = [Path(__file__), Path(catalog.__file__), catalog.DEFAULT_CATALOG,
        Path(catalog.original.__file__), catalog.original.DEFAULT_CATALOG,
        Path(spec.__file__), Path(ledger.__file__), Path(ledger.original.__file__),
        Path(ledger.original_spec.__file__), Path(search_a.__file__), search_a.SOURCE,
        Path(search_b.__file__), search_b.KERNEL]
    return {str(path.resolve()): reference(path) for path in paths}


def _catalogue(manifest_ref, profile):
    manifest = read(manifest_ref)
    spec.require(profile == catalog.DEVELOPMENT_ID and profile == '30-D02',
                 'Only the prospectively declared first constrained development profile is enabled')
    spec.require(manifest.get('kind') == 'generated_constrained_scaled_capital_public_specs'
        and manifest.get('status') == 'completed_public_primitives_only'
        and manifest.get('profile_order') == list(catalog.PROFILE_ORDER)
        and manifest.get('confirmation_profile_order') == list(catalog.CONFIRMATION_ORDER)
        and manifest.get('prospective_first_strong_profile') == profile
        and manifest.get('generated_count') == 11 and not manifest.get('failures')
        and manifest.get('source_original_ancestors') == 2
        and manifest.get('raw_ancestors') == spec.RAW_ANCESTORS,
        'The complete original eleven-profile prospective catalogue is required')
    spec.require(checked(manifest['catalog']) == catalog.DEFAULT_CATALOG.resolve(), 'Bind the declared constrained catalogue')
    checked(manifest['prospective_inventory'])
    for identity in manifest['recipe'].values(): checked(identity)
    config = catalog.load_catalog(checked(manifest['catalog']))
    records = manifest['specifications']
    spec.require([row['profile_id'] for row in records] == list(catalog.PROFILE_ORDER), 'No catalogue profile may be reordered or omitted')
    for row in records:
        for key in ('spec', 'public_summary', 'candidate_contract', 'candidate_contract_markdown', 'engineering_inventory'):
            checked(row[key])
    record = next(row for row in records if row['profile_id'] == profile)
    public = spec.load_spec(checked(record['spec']))
    spec.require(public == catalog.build_spec(profile, config) and len(public['projects']) == 30,
                 'The exact raw profile must reproduce from its predeclared primitives')
    spec.require(read(record['candidate_contract']) == catalog.public_contract(profile, config), 'The complete public field contract changed')
    spec.require(checked(record['candidate_contract_markdown']).read_text() == catalog.contract_markdown(read(record['candidate_contract'])),
                 'Public contract JSON and narrative must match')
    inventory = read(record['engineering_inventory'])
    spec.require(inventory == catalog.engineering_inventory(profile, config) and len(inventory['plans']) == 44,
                 'All forty-four prospective fixed plans must remain intact')
    return manifest, record, public, inventory


def _provenance(refs, manifest_ref, record, inventory):
    spec.require(set(refs) == {'fixed_diagnostics', 'financing_scope_addendum', 'pairwise_coverage'}, 'Bind all historical engineering receipts')
    diagnostic, financing, coverage = (read(refs[key]) for key in ('fixed_diagnostics','financing_scope_addendum','pairwise_coverage'))
    spec.require(diagnostic.get('kind') == 'constrained_capital_D02_actual_fixed_plan_diagnostics'
        and diagnostic.get('execution_completed') is True and diagnostic.get('exact_fixed_plan_count') == 44
        and diagnostic.get('all44_A_B_Decimal_outcomes_match') is True
        and diagnostic.get('catalog_manifest') == manifest_ref and diagnostic.get('public_specification') == record['spec'],
        'Bind the exact previous fixed-inventory diagnostic, without changing its result')
    spec.require(financing.get('kind') == 'constrained_D02_fixed_inventory_financing_scope_addendum'
        and financing.get('original_terminal') == refs['fixed_diagnostics']
        and financing.get('original_assessment_preserved') is True, 'Keep the financing-scope clarification separate')
    spec.require(coverage.get('kind') == 'constrained_D02_complete_fixed_inventory_pairwise_readonly_coverage'
        and coverage.get('original_terminal') == refs['fixed_diagnostics']
        and coverage.get('original_probe') == diagnostic['fixed_plan_probe']
        and coverage.get('original_inventory') == record['engineering_inventory']
        and coverage.get('fixed_plan_count') == 44 and coverage.get('total_unordered_pairs') == 946
        and coverage.get('original_assessment_preserved') is True, 'Bind the complete post-execution pairwise coverage')
    original_pairs=coverage.get('original_predeclared_pair_outcomes',[])
    spec.require([(r.get('predeclared_left'),r.get('predeclared_right')) for r in original_pairs]
        == [tuple(pair) for pair in inventory['comparison_pairs']]
        and all(r.get('ordering_reversal') is False for r in original_pairs),
        'Preserve every failed prospective pair; expanded coverage must not rewrite that gate')
    proof = read(diagnostic['fixed_plan_probe'])
    spec.require(proof.get('kind') == 'scaled_capital_explicit_fixed_plan_diagnostics' and proof.get('passed') is True
        and proof.get('plan_count') == 44 and len(proof.get('checks', [])) == 44, 'The original bounded checks are incomplete')
    for declared, row in zip(inventory['plans'], proof['checks']):
        spec.require(row['id'] == declared['id'] and row['plan'] == declared['plan'] and row['A_B_Decimal_match'] is True,
                     'The historical checks must cover every prospective fixed plan in order')
        checked(row['ledger'])
    spec.require(coverage.get('existing_ledger_refs') == [row['ledger'] for row in proof['checks']],
                 'Expanded coverage must bind the same complete fixed-plan ledger inventory')
    checked(coverage['all946_pairs']); checked(coverage['all_reversals'])
    checked(diagnostic['engineering_criteria'])
    return {'original_predeclared_three_pair_gate_passed': False,
        'historical_diagnostic_status': diagnostic['status'],
        'historical_scope_clarification_bound': True,
        'expanded_pairwise_reversal_count': coverage['all_ordering_reversals_count'],
        'expanded_pairwise_denominator': 946, 'expanded_coverage_is_not_retroactive_gate_or_difficulty_pass': True}


def prepare(catalog_manifest, profile, output, *, diagnostics_receipt, financing_scope_addendum, coverage_receipt):
    """Freeze primitives, provenance, wires and both wrappers; start zero calls."""
    manifest_ref = reference(catalog_manifest) if not isinstance(catalog_manifest, dict) else catalog_manifest
    _, record, public, inventory = _catalogue(manifest_ref, profile)
    refs = {key: reference(value) if not isinstance(value, dict) else value for key, value in
        (('fixed_diagnostics',diagnostics_receipt),('financing_scope_addendum',financing_scope_addendum),('pairwise_coverage',coverage_receipt))}
    provenance = _provenance(refs, manifest_ref, record, inventory)
    output = Path(output).absolute()
    spec.require(not output.exists() and not output.is_symlink() and output.resolve().is_relative_to(Path('/data')),
                 'Use a fresh immutable /data preparation directory')
    output.mkdir(parents=True)
    a = search_a.prepare(public, output / 'A'); b = search_b.prepare(public, output / 'B')
    wire = output / 'A_canonical_raw_primitives.txt'; wire.write_text(search_a.raw_primitives(public, list(range(30))))
    return write(output / 'preparation.json', {'kind':PREPARED_KIND,'version':1,'created_at':utcnow(),
        'profile_id':profile,'catalog_manifest':manifest_ref,'public_contract_artifacts':record,
        'public_specification':record['spec'],'spec_sha256':spec.canonical_sha(public),
        'engineering_provenance':refs,'engineering_provenance_summary':provenance,
        'kernel_A_preparation':a,'kernel_B_preparation':b,'canonical_raw_wires':{'A':reference(wire),'B':read(b)['raw_wire']},
        'recipe':recipe(),'count_per_kernel':COUNT,'expected_record_bytes_per_kernel':RECORD_BYTES,
        'kernel_timeout_seconds':14400,'concurrent_kernel_limit':2,'fixed_plan_count':44,
        'confirmation_profiles_not_executed':list(catalog.CONFIRMATION_ORDER),
        'execution_requires_explicit_run':True,'compiler_calls':0,'kernel_calls':0,'Decimal_forward_calls':0,
        'LO_calls':0,'model_calls':0,'source_workbooks':0,'qualified':False,'task_count':0})


def validate_prepared(prepared):
    ref = prepared if isinstance(prepared, dict) else reference(Path(prepared) / 'preparation.json' if Path(prepared).is_dir() else prepared)
    frozen = read(ref)
    spec.require(frozen.get('kind') == PREPARED_KIND and frozen.get('version') == 1 and frozen.get('recipe') == recipe(),
                 'The prospectively frozen constrained driver or mathematics changed')
    _, record, public, inventory = _catalogue(frozen['catalog_manifest'], frozen['profile_id'])
    spec.require(frozen['public_contract_artifacts'] == record and frozen['public_specification'] == record['spec']
        and frozen['spec_sha256'] == spec.canonical_sha(public)
        and frozen['count_per_kernel'] == COUNT and frozen['expected_record_bytes_per_kernel'] == RECORD_BYTES
        and frozen['kernel_timeout_seconds'] == 14400 and frozen['concurrent_kernel_limit'] == 2
        and frozen['fixed_plan_count'] == 44 and frozen['confirmation_profiles_not_executed'] == list(catalog.CONFIRMATION_ORDER),
        'The full decision set, profile, count or execution budget changed')
    spec.require(_provenance(frozen['engineering_provenance'],frozen['catalog_manifest'],record,inventory)
        == frozen['engineering_provenance_summary'], 'The separate historical evidence interpretation changed')
    a = read(frozen['kernel_A_preparation']); b, b_public = search_b.validate_prepared(frozen['kernel_B_preparation'])
    output=Path(ref['path']).parent
    spec.require(Path(frozen['kernel_A_preparation']['path'])==output/'A/prepared.json'
        and Path(frozen['kernel_B_preparation']['path'])==output/'B/preparation.json'
        and Path(frozen['canonical_raw_wires']['A']['path'])==output/'A_canonical_raw_primitives.txt'
        and frozen['canonical_raw_wires']['B']==b['raw_wire'],
        'Both independent preparations and wires must remain in this immutable preparation')
    spec.require(a['kind'] == 'prepared_capital_scaled_A' and a['recipe'] == search_a.recipe()
        and read(a['public_spec']) == public and b_public == public and b['full_enumeration'] is True,
        'Each independent wrapper must consume the same complete raw public primitives')
    spec.require(checked(frozen['canonical_raw_wires']['A']).read_text() == search_a.raw_primitives(public,list(range(30)))
        and checked(frozen['canonical_raw_wires']['B']).read_text() == search_b.raw_wire(public,None),
        'The raw enumeration wires differ from their canonical primitive serialization')
    return frozen, public, inventory


def _compare_results(a, b, public, *, count):
    for result in (a,b):
        spec.require(result['status']=='completed' and result['full_enumeration'] is True and result['toy_only'] is False
            and result['plan_count']==count and result['spec_sha256']==spec.canonical_sha(public)
            and result['records']['bytes']==count*spec.RECORD_BYTES
            and Path(result['records']['path']).stat().st_size==count*spec.RECORD_BYTES, 'A full independent stream is incomplete')
        chunks=result['chunks']; start=0
        for chunk in chunks:
            length=min(spec.CHUNK_RECORDS,count-start)
            spec.require(chunk['start_mask']==start and chunk['end_mask_exclusive']==start+length
                and chunk['record_count']==length and chunk['bytes']==length*spec.RECORD_BYTES
                and type(chunk['sha256']) is str and len(chunk['sha256'])==64, 'Full record chunk coverage is incomplete')
            start+=length
        spec.require(start==count and len(chunks)==(count+spec.CHUNK_RECORDS-1)//spec.CHUNK_RECORDS, 'Missing or extra full-record chunks')
    spec.require(a['records']['sha256']==b['records']['sha256'] and a['chunks']==b['chunks']
        and all(a[field]==b[field] for field in RANK_FIELDS), 'Independent complete records, chunks or ranks disagree')
    return {'kind':'complete_constrained_independent_ordinal_record_equality','records_equal_complete':True,
        'rankings_equal':True,'plan_count':count,'record_bytes_per_kernel':count*spec.RECORD_BYTES,
        'A_records':a['records'],'B_records':b['records'],'all_chunk_hashes_equal':True,'chunk_count_per_kernel':len(a['chunks']),
        'comparison_method':'Both frozen wrappers validated every ordinal/status/null encoding and hashed every byte; compare all chunks and whole SHA, without a third enumeration.',
        'rank_fields':{field:a[field] for field in RANK_FIELDS}}


def _forward_checks(public, inventory, result, directory):
    directory.mkdir()
    selected=[]
    for key in ('best_mask','runnerup_mask'):
        if result[key] is not None:
            selected.append({'id':key,'plan':{p['id']:(result[key]>>i)&1 for i,p in enumerate(public['projects'])}})
    selected.extend(inventory['plans'])  # Preserve all44, including duplicate masks.
    checks=[]
    for index,row in enumerate(selected):
        mask=sum(row['plan'][p['id']]<<i for i,p in enumerate(public['projects']))
        forward=ledger.simulate(public,row['plan'])
        with Path(result['records']['path']).open('rb') as stream:
            stream.seek(mask*spec.RECORD_BYTES); actual=struct.unpack(spec.RECORD_FORMAT,stream.read(spec.RECORD_BYTES))
        flags=sum(1<<si for si,sid in enumerate(spec.SCENARIO_IDS) if forward['scenarios'][sid]['feasible'])
        values=tuple(forward['scenarios'][sid]['npv_pence'] if forward['scenarios'][sid]['feasible'] else spec.NULL_NPV for sid in spec.SCENARIO_IDS)
        entry={'id':row['id'],'mask':mask,'ledger':write(directory/(str(index).zfill(3)+'.json'),forward),
            'record_matches':actual==(mask,flags,*values),'all_journals_balance':all(s['all_journals_balance'] for s in forward['scenarios'].values()),
            'feasible':forward['feasible'],'objective_pence':forward['objective_pence']}
        checks.append(entry)
        spec.require(entry['record_matches'] and entry['all_journals_balance'], 'Independent Decimal forward diagnostic differs: '+row['id'])
    return {'kind':'constrained_forward_best_runnerup_and_complete_declared_fixed_inventory','passed':True,
        'checks':checks,'declared_fixed_plan_count':44,'all_declared_fixed_plans_preserved':True,
        'optimisation_performed':False,'independent_global_optimality_claimed':False}


def execute_prepared(prepared, *, port=0):
    frozen,public,inventory=validate_prepared(prepared)
    output=Path(checked(frozen['kernel_A_preparation'])).parent.parent
    lease=ProducerLease(output).acquire();attempt=None;server=None;audit=None;stop=threading.Event();progress=None
    clock=time.monotonic();phase='capacity_and_first_attempt';results={};errors={}
    try:
        spec.require(not (output/'execution_started.json').exists(), 'Preserve the first actual execution; no silent repeat')
        attempt=output/'attempts'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:12]);attempt.mkdir(parents=True)
        temporary=attempt/'temporary';temporary.mkdir()
        spec.require(temporary.resolve().is_relative_to(output.resolve()), 'Use this immutable attempt /data temporary directory')
        audit=AuditStore(attempt,{'id':attempt.name,'kind':TERMINAL_KIND,'status':'starting','target_count':0,'qualified':0})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
        free_bytes=shutil.disk_usage(output).free
        started=write(attempt/'started.json',{'kind':'started_constrained_capital_dual_search','started_at':utcnow(),
            'preparation':reference(output/'preparation.json'),'recipe':frozen['recipe'],'dashboard_url':url,'producer_pid':os.getpid(),
            'expected_plan_count_per_kernel':COUNT,'concurrent_kernels':2,'timeout_seconds_per_kernel':14400,
            'temporary_directory':str(temporary),'free_data_bytes_at_start':free_bytes})
        write(output/'execution_started.json',{'started':started,'first_attempt_only':True})
        audit.update_run(status='enumerating',dashboard_url=url,producer_pid=os.getpid(),producer_active=True)
        audit.emit('constrained_dual.started',receipt=started);audit.export()
        print(json.dumps({'started':started,'dashboard':url,'pid':os.getpid()}),flush=True)
        spec.require(free_bytes >= 2*RECORD_BYTES+10**9, 'Insufficient /data capacity for both complete64GiB record streams')
        def monitor():
            while not stop.wait(15):
                values={}
                for name,pattern in (('A','**/candidate_records.bin'),('B','**/plans.bin')):
                    size=sum(p.stat().st_size for p in (output/name).glob(pattern) if p.is_file())
                    values[name]={'written_bytes':size,'expected_bytes':RECORD_BYTES,'write_fraction':size/RECORD_BYTES,
                        'wrapper_completed':name in results,'wrapper_failed':name in errors}
                audit.update_run(progress=values,elapsed_seconds=time.monotonic()-clock);audit.export()
        progress=threading.Thread(target=monitor,daemon=True);progress.start()
        def run(name):
            t=time.monotonic();audit.emit('constrained_dual.kernel_started',kernel=name)
            try:
                result=search_a.execute_prepared(output/'A') if name=='A' else search_b.execute_prepared(frozen['kernel_B_preparation'],allow_full=True,timeout_seconds=14400)
                audit.emit('constrained_dual.kernel_completed',kernel=name,receipt=result,elapsed_seconds=time.monotonic()-t)
                return result
            except BaseException as error:
                write(attempt/('kernel_'+name+'_failure.json'),{'kernel':name,'completed_at':utcnow(),'error_type':type(error).__name__,
                    'error':str(error),'elapsed_seconds':time.monotonic()-t,'traceback':traceback.format_exc()})
                raise
        phase='actual_full_dual_enumeration'
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures={executor.submit(run,name):name for name in ('A','B')}
            for future in as_completed(futures):
                name=futures[future]
                try:results[name]=future.result()
                except BaseException as error:errors[name]={'type':type(error).__name__,'message':str(error)}
        spec.require(not errors,'Independent kernel failure; both attempts retained: '+json.dumps(errors))
        phase='compare_complete_records_and_rankings';audit.update_run(status='comparing')
        a,b=read(results['A']),read(results['B'])
        comparison=_compare_results(a,b,public,count=COUNT)
        for result,name,key in ((a,'A','raw_primitives'),(b,'B',None)):
            actual=result[key] if key else read(frozen['kernel_B_preparation'])['raw_wire']; expected=frozen['canonical_raw_wires'][name]
            spec.require(actual['sha256']==expected['sha256'] and actual['bytes']==expected['bytes'], 'Executed raw wire changed')
        comparison_ref=write(attempt/'complete_record_comparison.json',{**comparison,'kernel_A_result':results['A'],'kernel_B_result':results['B']})
        phase='independent_Decimal_forward_checks';audit.update_run(status='forward_validating')
        forward_ref=write(attempt/'independent_decimal_validation.json',_forward_checks(public,inventory,a,attempt/'Decimal'))
        validate_prepared(output)
        acceptable=a['unique_best'] is True and a['gap_pence'] is not None and a['gap_pence']>=1
        terminal=write(attempt/'receipt.json',{'kind':TERMINAL_KIND,'version':1,'status':'completed' if acceptable else 'completed_unacceptable_optimum',
            'passed':acceptable,'complete_independent_search_finished':True,'completed_at':utcnow(),'elapsed_seconds':time.monotonic()-clock,
            'started':started,'preparation':reference(output/'preparation.json'),'profile_id':frozen['profile_id'],
            'catalog_manifest':frozen['catalog_manifest'],'public_specification':frozen['public_specification'],
            'public_contract_artifacts':frozen['public_contract_artifacts'],'engineering_provenance':frozen['engineering_provenance'],
            'engineering_provenance_summary':frozen['engineering_provenance_summary'],
            'kernel_A_result':results['A'],'kernel_B_result':results['B'],'complete_record_comparison':comparison_ref,
            'independent_decimal_validation':forward_ref,'records_equal_complete':True,'count':COUNT,'plan_count':COUNT,
            'full_enumeration':True,'toy_only':False,**{key:a[key] for key in RANK_FIELDS},'recipe':frozen['recipe'],
            'source_original_ancestors':2,'LO_calls':0,'model_calls':0,'source_workbooks':0,'qualified':False,'task_count':0,
            'source_admission_or_quality_or_difficulty_certified':False})
        audit.update_run(status='completed' if acceptable else 'source_hold',terminal_receipt=terminal)
        audit.emit('constrained_dual.completed',receipt=terminal)
        print(json.dumps({'terminal':terminal,'unique_optimum_acceptable':acceptable}),flush=True)
        return terminal
    except BaseException as error:
        if attempt is not None:
            failure=write(attempt/'failure.json',{'kind':'constrained_capital_dual_failure','status':'failed','phase':phase,
                'completed_at':utcnow(),'elapsed_seconds':time.monotonic()-clock,'error_type':type(error).__name__,
                'error':str(error),'traceback':traceback.format_exc(),'results':results,'kernel_errors':errors,
                'qualified':False,'task_count':0,'LO_calls':0,'model_calls':0})
            if audit is not None:audit.update_run(status='failed',failure=failure)
        raise
    finally:
        stop.set()
        if progress is not None:progress.join(timeout=20)
        if audit is not None:
            audit.update_run(producer_active=False,finished_at=utcnow());audit.export()
        lease.release()
        if server is not None:server.stop()
        if audit is not None:audit.db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-manifest');parser.add_argument('--profile');parser.add_argument('--output')
    parser.add_argument('--diagnostics-receipt');parser.add_argument('--financing-scope-addendum');parser.add_argument('--coverage-receipt')
    parser.add_argument('--prepared');parser.add_argument('--run',action='store_true')
    args=parser.parse_args(argv)
    if args.run:
        spec.require(args.prepared is not None and not any((args.catalog_manifest,args.profile,args.output,args.diagnostics_receipt,args.financing_scope_addendum,args.coverage_receipt)),
                     'Explicit execution consumes only an existing --prepared directory')
        result=execute_prepared(args.prepared)
    else:
        spec.require(args.prepared is None and all((args.catalog_manifest,args.profile,args.output,args.diagnostics_receipt,args.financing_scope_addendum,args.coverage_receipt)),
                     'Preparation requires complete catalogue/profile/output and historical evidence references')
        result=prepare(args.catalog_manifest,args.profile,args.output,diagnostics_receipt=args.diagnostics_receipt,
            financing_scope_addendum=args.financing_scope_addendum,coverage_receipt=args.coverage_receipt)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
