#!/usr/bin/env python3
"""One process: genuine ten-donor parse, two cold proofs, complete source3."""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
import importlib.util
import inspect
import json
from pathlib import Path
import sqlite3
import sys
from types import FunctionType, SimpleNamespace
import weakref

from sheets_factory.workbook.linear_capital_ringfenced_pairs import contract as c, composition as proof, stream_composition as stream

ROOT=c.ROOT
PILOT=ROOT/'scripts/run_ringfenced_pair_source_pilot.py'
PILOT_SHA='3be90b1ff63dd11808448263f5d097ea79b73283c14e1d9a6e367a1228a07dc2'
_SEAL=object();_LIVE=weakref.WeakKeyDictionary()
KIND='prepared_two_ringfenced_pair_source_same_process_session'
TERMINAL_KIND='completed_two_ringfenced_pair_source_same_process_session'
PARSE_CACHE_KIND='witnessed_complete_ten_ringfenced_pure_parse_cache'
PROFILE=ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
PROFILE_SHA='20fc02fec3aaf4918ece50d18ef9e315ffee9fccce088863f044ebac301a026a'
_LARGE_DATA_LEAVES={'bindings.json','independent_A_expected.json','independent_B_expected.json','universe_A.json','universe_B.json'}
JSON_METADATA_LIMIT=16*1024**2


def _refs(value):
    if isinstance(value,dict):
        if set(value)=={'path','sha256','bytes'}:yield value
        else:
            for item in value.values():yield from _refs(item)
    elif isinstance(value,list):
        for item in value:yield from _refs(item)


def _stat(path):
    path=Path(path);c.require(not path.is_symlink() and path.is_file() and path.absolute()==path.resolve(),'Use unchanged real artifacts')
    s=path.stat();return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


class _Artifacts:
    """Hash once; fail closed on identity/size/mtime/ctime drift at each boundary."""
    def __init__(self):self.records={};self.expanded=set();self.absent=set()
    def add(self,record,*,expand=False):
        path=Path(record['path']);key=str(path)
        if key in self.records:
            c.require(self.records[key][0]==record,'Conflicting immutable artifact references')
            c.require(_stat(path)==self.records[key][1],'An admitted artifact changed before dependency expansion')
        else:
            before=_stat(path);c.checked(record);after=_stat(path)
            c.require(before==after,'An artifact changed during its full hash verification')
            self.records[key]=(deepcopy(record),after)
        if expand and path.suffix=='.json' and key not in self.expanded:
            self.expanded.add(key)
            after=self.records[key][1]
            try:
                if after[2]>JSON_METADATA_LIMIT:
                    # These closed schemas are complete numeric/locator data, not
                    # metadata envelopes. Their whole bytes were cold checked;
                    # no path/ref inside them drives any later filesystem read.
                    c.require(path.name in _LARGE_DATA_LEAVES,'Unknown large metadata needs explicit dependency coverage')
                else:
                    for child in _refs(c.read(record)):self.add(child,expand=True)
            except BaseException:
                self.expanded.remove(key);raise
    def guard(self):
        for record,stamp in self.records.values():
            c.require(_stat(record['path'])==stamp,'An admitted artifact changed; the process-local proof is invalid')
        for path in self.absent:
            c.require(not path.exists() and not path.is_symlink(),'An unadmitted live database journal appeared')
    def forbid(self,path):
        path=Path(path);c.require(not path.exists() and not path.is_symlink(),'An unadmitted live database journal appeared')
        self.absent.add(path)
    def bind(self,value,*,expand=False):
        for record in _refs(value):self.add(record,expand=expand)


class _Admission:
    __slots__=('__weakref__',)
    def __init__(self,seal,prospective,frozen,pair_id,artifacts):
        c.require(seal is _SEAL,'A live genuine admission cannot be constructed from JSON')
        _LIVE[self]={'prospective':deepcopy(prospective),'frozen':deepcopy(frozen),'pair_id':pair_id,'artifacts':artifacts,
            'preflight':None,'certificate':None,'certificate_ref':None,'source_namespace':None,'pilot':None,'state':'minting'}
    def guard(self):
        c.require(type(self) is _Admission and self in _LIVE and _LIVE[self]['state'] not in ('spent','failed'),
            'A live unspent same-process admission is required')
        _LIVE[self]['artifacts'].guard()
    def parsed(self,prospective):
        self.guard();d=_LIVE[self]
        c.require(prospective==d['prospective'] and d['preflight'] is not None,'The exact genuine parsed inventory is required')
        return deepcopy(d['preflight'])
    def checked_certificate(self,record):
        self.guard();d=_LIVE[self];record=record if isinstance(record,dict) else c.reference(record)
        c.require(record==d['certificate_ref'] and d['certificate'] is not None,'A different, renamed or fabricated certificate is not admitted')
        expected=c.public_contract(d['frozen']['contexts'],d['pair_id'])
        c.require(c.read(d['certificate_ref'])==d['certificate'] and c.read(d['certificate']['contract'])==expected
            and [r['profile_id'] for r in d['certificate']['local_whole_evidence']]
                ==[r['profile_id'] for r in c.pair_contexts(d['frozen']['contexts'],d['pair_id'])],'Wrong donor or public pair contract')
        return deepcopy(d['certificate'])


def _require(admission):
    c.require(type(admission) is _Admission and admission in _LIVE,'Only the opaque process-local genuine admission is accepted')
    admission.guard();return admission


def _pilot():
    c.require(c.reference(PILOT)['sha256']==PILOT_SHA,'The frozen complete two-source lifecycle changed')
    spec=importlib.util.spec_from_file_location('_pair_session_frozen_pilot',PILOT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def _clone(function,namespace):
    result=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    result.__kwdefaults__=function.__kwdefaults__;return result


def _source(admission,pilot):
    ns=dict(pilot._N)
    for name,value in pilot._N.items():
        if isinstance(value,FunctionType) and value.__globals__ is pilot._N:ns[name]=_clone(value,ns)
    ns.update(KIND=KIND,TERMINAL_KIND=TERMINAL_KIND,
        composition=SimpleNamespace(validate_certificate=admission.checked_certificate),
        recipes=lambda:{**pilot.recipes(),str(Path(__file__).resolve()):c.reference(__file__)})
    return ns


def _parse_identity(prospective,frozen):
    entry=c.reference(PILOT);profile=c.reference(PROFILE)
    c.require(entry['sha256']==PILOT_SHA and profile['sha256']==PROFILE_SHA,'Frozen pure-parse producer or profile changed')
    parser_modules={Path(inspect.getmodule(function).__file__).resolve() for function in
        (stream.syntax_ancestor.Tokenizer,stream.syntax_ancestor.is_date_format,stream.syntax_ancestor.range_boundaries)}
    return {'prospective':prospective,'contexts':deepcopy(frozen['contexts']),'recipe':c.recipes(),
        'producer_entry':entry,'geometry_profile':profile,
        'parser_dependencies':{str(path):c.reference(path) for path in sorted(parser_modules)},
        'python_runtime':{'executable':c.reference(Path(sys.executable).resolve()),'version':sys.version}}


def _sqlite_companions(database_ref):
    return [Path(database_ref['path']+suffix) for suffix in ('-wal','-shm','-journal')]


def _completed_parse(report_ref,prospective,frozen,log_ref,summary_ref,database_ref,observed_exit_code):
    """Replay a completed frozen producer's entire inventory and execution record."""
    c.require(type(observed_exit_code) is int and observed_exit_code==0,'The witnessed original process must naturally exit zero')
    report=c.read(report_ref)
    c.require(report['kind']==stream.PREFLIGHT_KIND and report['version']==1
        and report['prospective']==prospective and report['recipe']==c.recipes()
        and report['passed'] is True and report['all_ten_donors_checked_before_hydration'] is True
        and type(report['new_workbooks_services_forwards']) is int and report['new_workbooks_services_forwards']==0
        and report['total_physical_formulas']==12473280,'The complete deterministic ten-donor proof is required')
    c.require(len(report['donors'])==10,'All ten donors must be present')
    for actual,context in zip(report['donors'],frozen['contexts'],strict=True):
        c.require(actual['profile_id']==context['profile_id'] and actual['workbook']==context['workbook']
            and actual['sheets']==370 and actual['physical_formulas']==1247328
            and actual['business_criterion_sites']==280 and actual['all_formula_roundtrips_checked'] is True
            and actual['parsed_formula_cache_bound']==8192 and actual['financial_bindings_expanded']==0
            and type(actual['other_formula_elements']) is int and actual['other_formula_elements']>=0,
            'A donor identity, order, geometry or complete parse proof changed')
    report_path=Path(report_ref['path']);audit=report_path.parent.parent/(report_path.parent.name+'_all_ten_formula_preflight_audit')
    c.require(summary_ref['path']==str(audit/'summary.json') and database_ref['path']==str(audit/'run.sqlite'),
        'Bind the original frozen producer audit beside its exact output')
    summary=c.read(summary_ref)
    c.require(summary['run']['status']=='passed' and summary['run']['phase']=='all_ten_formula_preflight'
        and summary['run']['producer_active'] is False and summary['run']['model_calls']==0
        and summary['run']['solver_calls']==0 and summary['metrics']['total_tokens']==0
        and summary['tasks']==[] and summary['nodes']==[] and summary['llm_calls']==[],
        'The original pure-parse producer did not complete cleanly')
    db_path=c.checked(database_ref)
    c.require(all(not path.exists() and not path.is_symlink() for path in _sqlite_companions(database_ref)),
        'The finished producer database must have no live journal or uncheckpointed state')
    with closing(sqlite3.connect(db_path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        run=json.loads(db.execute("SELECT value FROM state WHERE key='run'").fetchone()[0])
        c.require(run['status']=='passed' and run['phase']=='all_ten_formula_preflight'
            and run['producer_active'] is False and run['model_calls']==0 and run['solver_calls']==0
            and all(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0 for table in ('tasks','nodes','calls')),
            'The authoritative producer database is incomplete or contains service work')
    lines=[json.loads(line) for line in c.checked(log_ref).read_text().splitlines() if line.strip()]
    progress=[{'phase':'all_ten_formula_preflight','profile_id':row['profile_id'],'donors_complete':i,
        'physical_formulas_checked':i*1247328} for i,row in enumerate(frozen['contexts'],1)]
    c.require(len(lines)==12 and lines[0]['phase']=='all_ten_formula_preflight'
        and set(lines[0])=={'dashboard_url','phase'} and lines[1:11]==progress and lines[-1]==report_ref,
        'The original full-ten execution transcript is incomplete or reordered')
    return report


def freeze_preflight_cache(preflight,log,output,*,observed_exit_code):
    """Document an actual finished scan; admission still needs Root's separate SHA pin."""
    report_ref=preflight if isinstance(preflight,dict) else c.reference(preflight)
    report=c.read(report_ref);prospective=report['prospective'];frozen=c.validate_prospective(prospective)
    audit=Path(report_ref['path']).parent;directory=audit.parent/(audit.name+'_all_ten_formula_preflight_audit')
    log_ref=log if isinstance(log,dict) else c.reference(log)
    summary=c.reference(directory/'summary.json');database=c.reference(directory/'run.sqlite')
    _completed_parse(report_ref,prospective,frozen,log_ref,summary,database,observed_exit_code)
    return c.write(output,{'kind':PARSE_CACHE_KIND,'version':1,'identity':_parse_identity(prospective,frozen),
        'preflight':report_ref,'execution':{'log':log_ref,'summary':summary,'database':database,
        'observed_process_exit_code':observed_exit_code},'financial_source_or_model_admission':False,
        'requires_separate_root_expected_sha256':True})


def _cached_parse(cache,expected_sha,prospective,frozen,artifacts):
    c.require(type(expected_sha) is str and len(expected_sha)==64 and all(ch in '0123456789abcdef' for ch in expected_sha),
        'A separate Root-pinned proof SHA is required')
    cache_ref=cache if isinstance(cache,dict) else c.reference(cache)
    c.require(cache_ref['sha256']==expected_sha,'The pure proof cache differs from the Root-pinned SHA')
    value=c.read(cache_ref);identity=_parse_identity(prospective,frozen)
    c.require(value['kind']==PARSE_CACHE_KIND and value['version']==1 and value['identity']==identity
        and value['financial_source_or_model_admission'] is False and value['requires_separate_root_expected_sha256'] is True,
        'The Root-pinned cache does not cover the current whole inventory and code closure')
    execution=value['execution']
    artifacts.bind([cache_ref,identity,value['preflight'],execution])
    for path in _sqlite_companions(execution['database']):artifacts.forbid(path)
    result=_completed_parse(value['preflight'],prospective,frozen,execution['log'],execution['summary'],
        execution['database'],execution['observed_process_exit_code'])
    artifacts.guard();return result,cache_ref


def _mint(prospective,pair_id,*,parse_cache=None,expected_cache_sha256=None):
    prospective=prospective if isinstance(prospective,dict) else c.reference(prospective)
    frozen=c.validate_prospective(prospective);contexts=c.pair_contexts(frozen['contexts'],pair_id)
    artifacts=_Artifacts();artifacts.bind([prospective,*c.recipes().values(),c.reference(__file__),c.reference(PILOT)])
    # All ten parsed inventory artifacts are bound; only the selected two
    # financial proof closures need expansion into their dependency envelopes.
    artifacts.bind(frozen['contexts'])
    for context in contexts:artifacts.bind([context['reference'],context['source_manifest']],expand=True)
    admission=_Admission(_SEAL,prospective,deepcopy(frozen),pair_id,artifacts)
    try:
        d=_LIVE[admission];d['parse_cache']=None
        c.require((parse_cache is None)==(expected_cache_sha256 is None),'Supply both the witnessed cache and its separate Root SHA')
        if parse_cache is None:d['preflight']=stream.preflight_all(prospective)  # the sole real full-ten parse
        else:d['preflight'],d['parse_cache']=_cached_parse(parse_cache,expected_cache_sha256,prospective,frozen,artifacts)
        admission.guard()
        private=dict(vars(proof));private['stream_composition']=SimpleNamespace(preflight_all=admission.parsed)
        compose=_clone(proof._compose,private)
        d['certificate']=compose({**frozen,'_reference':prospective},pair_id)  # sole two genuine cold provider calls
        admission.guard();d['state']='admitted';return admission
    except BaseException:_LIVE[admission]['state']='failed';raise


def prepare(prospective,output,*,pair_id='R2-01',parse_cache=None,expected_cache_sha256=None):
    """Performs real pure emission/cold proof; no native call. Root review first."""
    output=Path(output).absolute()
    c.require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),'Use a fresh complete session output')
    pilot=_pilot()
    def operation():
        admission=_mint(prospective,pair_id,parse_cache=parse_cache,expected_cache_sha256=expected_cache_sha256)
        d=_LIVE[admission];d['pilot']=pilot
        try:
            output.mkdir(parents=True)
            certificate={**d['certificate'],'prospective':d['prospective'],'created_at':datetime.now(timezone.utc).isoformat()}
            d['certificate']=certificate;d['certificate_ref']=c.write(output/'certificate.json',certificate)
            d['artifacts'].bind([d['certificate_ref'],certificate],expand=False);admission.guard()
            locals_=stream._compose(certificate['donors'],output/'locals_uncalculated.xlsx',mode='goal',target_count=3044376,
                expected_census={'sheets':740,'formulas':2494656,'nonempty':3547132},
                ancestry={'composition_certificate':d['certificate_ref'],'native_source_or_quality_inherited':False})
            local_ref=c.write(output/'composition.json',locals_);d['artifacts'].bind([local_ref,locals_]);admission.guard()
            d['source_namespace']=_source(admission,pilot)
            d['artifacts'].bind(list(d['source_namespace']['recipes']().values()));admission.guard()
            prepared=d['source_namespace']['prepare'](d['certificate_ref'],local_ref,output/'source')
            d['artifacts'].bind([prepared,c.read(prepared)],expand=False);admission.guard();d['state']='prepared'
            session_record=c.write(output/'session_preparation.json',{'kind':'complete_same_process_pair_preparation',
                'version':1,'prospective':d['prospective'],'pair_id':pair_id,'certificate':d['certificate_ref'],
                'source_preparation':prepared,'one_complete_witnessed_full_ten_parse':True,
                'full_ten_parse_executed_this_session':d['parse_cache'] is None,'root_pinned_prior_preflight':d['parse_cache'],
                'genuine_local_reference_validations':2,
                'genuine_original_source_validations':2,'process_local_token_serialized':False,
                'artifact_hashes_and_stats_guarded':len(d['artifacts'].records),'native_calls':0,
                'memoized_financial_universes_reused':True,'new_financial_forwards':0,'qualified':False,
                'implementation':c.reference(__file__)})
            d['artifacts'].add(session_record)
            return admission
        except BaseException:d['state']='failed';raise
    return pilot._observed('same_process_genuine_prepare',output,operation)


def execute_prepared(admission):
    admission=_require(admission);d=_LIVE[admission];c.require(d['state']=='prepared','A token can launch the native source chain only once')
    d['state']='running'
    try:
        source=Path(d['certificate_ref']['path']).parent/'source'
        result=d['pilot']._observed('same_process_source_execute',source,
            lambda:d['source_namespace']['execute_prepared'](source))
        admission.guard();d['state']='spent';return result
    except BaseException:d['state']='failed';raise


def validate_completed(terminal,*,parse_cache=None,expected_cache_sha256=None):
    """Fresh process re-establishes the real evidence once, then full actual gates."""
    value=c.read(terminal);c.require(value['kind']==TERMINAL_KIND and value['version']==1,'Use this exact same-process source protocol')
    prepared=c.read(value['preparation']);certificate=c.read(prepared['certificate'])
    pilot=_pilot();admission=_mint(certificate['prospective'],certificate['pair_id'],
        parse_cache=parse_cache,expected_cache_sha256=expected_cache_sha256);d=_LIVE[admission]
    try:
        expected={k:v for k,v in certificate.items() if k not in ('prospective','created_at')}
        c.require(expected==d['certificate'],'Complete fresh cold certificate or parsed inventory changed')
        d['certificate']=certificate;d['certificate_ref']=prepared['certificate']
        d['artifacts'].bind([prepared,certificate,value],expand=False)
        d['source_namespace']=_source(admission,pilot)
        result=d['source_namespace']['validate_completed'](terminal)
        admission.guard();return result
    finally:d['state']='spent'


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prospective',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--pair',default='R2-01');p.add_argument('--run',action='store_true')
    p.add_argument('--parse-cache',type=Path);p.add_argument('--expected-cache-sha256')
    args=p.parse_args(argv);admission=prepare(args.prospective,args.output,pair_id=args.pair,
        parse_cache=args.parse_cache,expected_cache_sha256=args.expected_cache_sha256)
    result=execute_prepared(admission) if args.run else {'preparation':c.reference(args.output/'source/preparation.json'),
        'native_calls':0,'same_process_token_persisted':False,'resume_requires_fresh_genuine_admission':True}
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
