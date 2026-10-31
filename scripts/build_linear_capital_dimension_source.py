#!/usr/bin/env python3
"""Cold three-pass enlarged source; requires a genuine complete SCIP reference."""
from __future__ import annotations
import argparse,ast,hashlib,importlib.util,json,os,re,shutil,subprocess,sys,threading,time,traceback,uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree
from zipfile import ZipFile,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore,utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook import linear_capital_dimension_source_support as support
from sheets_factory.workbook import linear_capital_dimension_scip_reference as references

UPSTREAM=ROOT/'scripts/build_linear_capital_source.py'
JOIN=ROOT/'scripts/build_linear_capital_producer_source.py'
CACHE=ROOT/'scripts/build_equity_income_group_source.py'
ABSENCE=ROOT/'scripts/validate_period_boundary_candidate_v2.py'
PINS={UPSTREAM:'8a4d9a84908242faa807fd969707326e028afaa17a3f8a9b0fc82d597f54c90e',
 JOIN:'79099dcc2e0ba8ad7f7ded6fc6416452ed22f3f8e686e22f36de19d5d0621a52',
 CACHE:'1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690',
 ABSENCE:'0b974c2d7b45ae8f9b844663a06f147c95570094f56e514db15b6b5661b99e48',
 ROOT/'scripts/run_linear_capital_dimension_scip_reference.py':'b96c1ac1d35829421709ae305258024c1027772f7f0242118a9a2f96d5810851',
 Path(references.__file__):'a32b842d72e1654b410e2be833bd01fb274faec85e232af019235950ea2908f4',
 ROOT/'src/sheets_factory/workbook/linear_capital_dimension_scip_backend.py':'9ce0795455eecfc017232dd04ca863a19ba12fe61f023475213ad36c849f6cf5',
 ROOT/'config/runtime_profiles/linear_capital_dimension_scip3600_v1.json':'9d24b9e1098fa4e7b5e9b7ad01fde742d91fefa25d940c07e08b24f371b518c2',
 ROOT/'src/sheets_factory/workbook/linear_capital_dimension_excel.py':'20631d0314cb2d3311607c050fd1540aed616e117811e43a5998a44d9516e1de',
 Path(support.__file__):'74adf9b38b8a08e44a93ca82dd0671b941477d5b8827297566356af726092ee5',
 support.profile_path(720):'9469991757ff857c78390459817f59c56104ca14d8913163e98968c6c016a791',
 support.profile_path(1080):'72231791839379620bbdfeaa1aa67478752f21769399189f05d922df612f7ea5'}
require=support.require


def guard():
 for path,digest in PINS.items():require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Frozen dimension source ancestor changed: '+path.name)
 support.source_files()


def _definitions(path,names):return support._definitions(path,names)
def _compile(tree,ns):exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),ns)


def cache_census(path):
 count=0
 with ZipFile(path)as archive:
  for name in archive.namelist():
   if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml',name):continue
   with archive.open(name)as stream:
    for _,cell in ElementTree.iterparse(stream,events=('end',)):
     tag=cell.tag.rsplit('}',1)[-1]
     if tag=='c':
      if cell.find('{*}f')is not None:
       count+=1;require(cell.find('{*}v')is None,'Every first-input formula cache must be absent')
      cell.clear()
     elif tag=='row':cell.clear()
 return count


def _lifecycle_ast(n):
 wanted={'_module','_resource_support','_output','prepare','validate_prepared','_stage','execute_prepared','validate_source'}
 tree=_definitions(UPSTREAM,wanted);hits=Counter()
 class Adapt(ast.NodeTransformer):
  def visit_ImportFrom(self,node):
   if node.module=='sheets_factory.workbook.linear_capital_portfolio'and [x.name for x in node.names]==['excel']:
    hits['emitter']+=1;return ast.copy_location(ast.Pass(),node)
   if node.module=='sheets_factory.workbook.heterogeneous_contracts.validate'and [x.name for x in node.names]==['compare_typed_caches']:
    hits['stability']+=1;return ast.copy_location(ast.Pass(),node)
   return node
  def visit_Constant(self,node):
   if node.value=='linear_capital_native_source_build_terminal':node.value=f'linear_capital_n{n}_native_source3_terminal';hits['terminal']+=1
   return node
  def visit_Assign(self,node):
   node=self.generic_visit(node)
   if len(node.targets)==1 and isinstance(node.targets[0],ast.Name)and node.targets[0].id=='bindings'and ast.unparse(node.value).startswith('excel.emit_workbook('):
    hits['clearance']+=1
    return [node,*ast.parse("clearance=clear_all_formula_caches(raw,attempt/'cold_start.xlsx')\nrequire(clearance['all_formula_caches_cleared']==bindings['formula_count'],'All physical formulas require cold caches')\nrecords['cache_clearance']=write(attempt/'formula_cache_clearance.json',clearance)\nraw=checked(clearance['output'])").body]
   if ast.unparse(node.targets[0])=="call['actual_resource_evidence']":
    hits['cleanup_actual']+=1
    return [node,*ast.parse("call['owned_cleanup']=record_owned_cleanup(call,attempt/index_name(index))").body]
   return node
  def visit_Dict(self,node):
   node=self.generic_visit(node);keys=[getattr(k,'value',None)for k in node.keys]
   if 'source_copy'in keys and 'source_preparation'in keys:
    node.keys.append(ast.Constant('cache_clearance'));node.values.append(ast.parse("records['cache_clearance']",mode='eval').body);hits['clearance_manifest']+=1
   return node
  def visit_FunctionDef(self,node):
   node=self.generic_visit(node)
   if node.name=='validate_source':
    require(isinstance(node.body[-1],ast.Return)and ast.unparse(node.body[-1].value)=='manifest','Frozen source admission return changed')
    node.body[-1:-1]=ast.parse('validate_clearance_and_cleanup(manifest,bindings,calls)').body;hits['cold_extra']+=1
   return node
 tree=Adapt().visit(tree)
 require(hits==Counter(emitter=1,stability=1,terminal=2,clearance=1,cleanup_actual=1,clearance_manifest=1,cold_extra=1),
  'Exact dimension source3 lifecycle sites changed: '+str(hits))
 return tree


@lru_cache(maxsize=2)
def _source(n):
 core=support.for_dimension(n);module=ModuleType(__name__+f'._n{n}');ns=vars(module)
 ns.update(vars(core));ns.pop('NO_SOURCE_ADMISSION',None);ns.pop('OPTIMAL_GOLD_SUPPLIED',None)
 ns.update(__name__=__name__+f'._n{n}',__file__=__file__,ROOT=ROOT,
  importlib=importlib,contextmanager=contextmanager,os=os,shutil=shutil,sys=sys,threading=threading,time=time,traceback=traceback,uuid=uuid,
  AuditStore=AuditStore,DashboardServer=DashboardServer,ProducerLease=ProducerLease,utcnow=utcnow,
  PREPARED_KIND=f'prepared_linear_capital_n{n}_native_source3',SOURCE_KIND=f'independently_verified_linear_capital_n{n}_native_source3',
  DEFAULT_PROFILE=support.profile_path(n),IMAGE_ID=support.load_runtime_profile(support.profile_path(n))['image']['id'])
 reference,read,write,checked=core.reference,core.read,core.write,core.checked
 helper={'reference':reference,'require':require,'ZipFile':ZipFile,'ZIP_DEFLATED':ZIP_DEFLATED,'re':re,'subprocess':subprocess}
 _compile(_definitions(CACHE,{'clear_all_formula_caches'}),helper)
 _compile(_definitions(ABSENCE,{'owned_absence'}),helper)
 def clear_all_formula_caches(source,destination):
  record=helper['clear_all_formula_caches'](source,destination)
  require(cache_census(destination)==record['all_formula_caches_cleared'],'Cold input lost a physical formula')
  return {**record,'remaining_formula_cache_elements':0,'native_calculation_claimed':False}
 def recipes():
  guard();paths=[Path(__file__),*PINS,*support.source_files().values(),*[Path(p)for p in references.recipes()]]
  return {str(p.resolve()):reference(p)['sha256']for p in paths}
 def provider():return references.experiment(n)
 def runtime(profile):return reference(profile),support.load_runtime_profile(profile,dimension=n)
 def validate_reference(value,public):
  record=value if isinstance(value,dict)else reference(value);claimed=read(record)
  require(claimed.get('kind')==provider().KIND and type(claimed.get('version'))is int and claimed['version']==3
   and claimed.get('passed')is True,'A completed native SCIP best AND full-excluded runner reference is required')
  result=provider().validate_completed(record)
  require(result['kind']==provider().KIND and result['passed']is True
   and core.spec.load_spec(read(result['specification']))==public
   and result['specification_sha256']==core.spec.canonical_sha256(public),'The exact fixed raw contract or reference dimension differs')
  winner=core.spec.validate_plan(public,result['winner_plan'])
  require(result['unique_best']is True and type(result['gap_pence'])is int and result['gap_pence']>=1
   and result['winner_objective_pence']-result['runner_objective_pence']==result['gap_pence']
   and result['selected_project_count']==sum(winner.values())and result['selection_density_not_required']is True
   and result['solver_status_is_not_formal_certificate']is True,'A complete unique posted integer-pence best and runner is required')
  return record,result
 def record_owned_cleanup(call,path):
  receipt=helper['owned_absence']([call]);ref=write(path,receipt)
  require(receipt['all_owned_containers_absent']is True and receipt['daemon_reachable']is True,'Owned full-CID cleanup is incomplete or unknown')
  return ref
 def validate_clearance_and_cleanup(manifest,bindings,calls):
  clearance=read(manifest['cache_clearance']);checked(clearance['source']);cold=checked(clearance['output'])
  require(clearance['all_formula_caches_cleared']==bindings['formula_count']==cache_census(cold)
   and clearance['remaining_formula_cache_elements']==0 and clearance['financial_formula_or_literal_edits']==0
   and clearance['native_calculation_claimed']is False and calls[0]['input']==clearance['output'],
   'First source pass must consume every original formula with no seeded caches')
  ids=[]
  for call in calls:
   cid=call['actual_resource_evidence']['container_id'];ids.append(cid);cleanup=read(call['owned_cleanup'])
   row=cleanup['owned'][0]if len(cleanup.get('owned',[]))==1 else {}
   missing=re.fullmatch(r'(?i:(?:error:\s*)?no such (?:object|container):\s*)'+re.escape(cid),row.get('stderr','').strip())is not None
   require(cleanup['all_owned_containers_absent']is True and cleanup['daemon_reachable']is True and cleanup['cleanup_mutations_by_validator']is False
    and bool(cleanup['daemon_version'])
    and cleanup['absence_parser_policy']=='v2_case_insensitive_message_exact_full_owned_id'
    and len(cleanup['owned'])==1 and row['full_id']==cid and row['absent']is True
    and row['returncode']==1 and not row['stdout'].strip() and missing,
    'Exactly each owned full container ID must have complete retained cleanup evidence')
  require(len(ids)==len(set(ids))==3,'Three distinct native source containers required')
 ns.update(recipes=recipes,_reference_provider=provider,runtime=runtime,_validate_reference=validate_reference,
  clear_all_formula_caches=clear_all_formula_caches,record_owned_cleanup=record_owned_cleanup,
  validate_clearance_and_cleanup=validate_clearance_and_cleanup,index_name=lambda index:f'owned_cleanup_pass{index}.json')
 _compile(_lifecycle_ast(n),ns);_compile(_definitions(JOIN,{'expected_results'}),ns)
 return module


def source(n):
 guard();support.profile_path(n)
 return _source(n)


def main(argv=None):
 parser=argparse.ArgumentParser(__doc__);sub=parser.add_subparsers(dest='command',required=True)
 for name in ('prepare','validate','run','validate-source'):
  p=sub.add_parser(name);p.add_argument('--projects',type=int,choices=(720,1080),required=True)
  if name=='prepare':
   for flag in ('spec','reference','output'):p.add_argument('--'+flag,type=Path,required=True)
   p.add_argument('--profile',type=Path)
  elif name=='validate-source':p.add_argument('--manifest',type=Path,required=True)
  else:
   p.add_argument('--prepared',type=Path,required=True)
   if name=='run':p.add_argument('--port',type=int,default=0)
 args=parser.parse_args(argv)
 if hasattr(args,'port')and not 0<=args.port<=65535:parser.error('Use a port between0 and65535')
 entry=source(args.projects)
 if args.command=='prepare':result=entry.prepare(args.spec,args.reference,args.output,profile=args.profile or entry.DEFAULT_PROFILE)
 elif args.command=='validate':entry.validate_prepared(args.prepared);result={'passed':True,'preparation':entry.reference(args.prepared/'preparation.json')}
 elif args.command=='run':result=entry.execute_prepared(args.prepared,port=args.port)
 else:result=entry.validate_source(args.manifest)
 print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
