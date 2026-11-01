#!/usr/bin/env python3
"""Fixed P01 recovery revision2: permit only an absent or empty stable WAL."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path
import stat

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/recover_linear_capital_scaled_P01_normal_evidence.py'
FROZEN_SHA='b98a5ea69689848a71aeacaa12660ceee041ee7a75f722fe92f532dd2f2f2afd'
LINEAGE={
    'approved_revision':{'path':str(ROOT/'outputs/research/P01_normal_recovery_empty_WAL_revision2_proposal_20261101T002258Z/prospective.json'),
        'sha256':'87cbdc1fd42e47524418569e5635371a810d463705b4fc508f236ed730a7f8b0','bytes':3793},
    'retained_v1_prospective':{'path':str(ROOT/'outputs/research/P01_normal_append_only_recovery_20261101T001728Z/prepared/prospective.json'),
        'sha256':'f7ed3d42afc3a61189bf1472189f3e1be9a914bc1a95b136c10bdef9b0a730b6','bytes':17867},
    'retained_v1_failure':{'path':str(ROOT/'outputs/research/P01_normal_append_only_recovery_20261101T001728Z/prepared/failure.json'),
        'sha256':'18bdd5732ba54bb56c0e6bb65f8d37aa3dbdc58a064edf242865e0a9c57cd44c','bytes':239208},
}
_N={'__file__':__file__,'__name__':'_isolated_fixed_P01_normal_recovery_revision2'}


def adapted_ast():
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:
        raise ValueError('The retained first recovery implementation changed')
    tree=ast.parse(FROZEN.read_bytes());counts={}
    def mark(key):counts[key]=counts.get(key,0)+1
    class Adapt(ast.NodeTransformer):
        current=None
        def visit_FunctionDef(self,node):
            prior=self.current;self.current=node.name;node=self.generic_visit(node);self.current=prior
            if node.name=='prepare':
                for index,item in enumerate(node.body):
                    if isinstance(item,ast.Expr) and ast.unparse(item.value)=='access.guard()':
                        node.body.insert(index,ast.parse('_bind_sidecar_metadata(frozen, access)').body[0]);mark('prepare_metadata');break
            elif node.name=='validate_prepared':
                if not isinstance(node.body[-1],ast.Return):raise ValueError('The original prepared validation return changed')
                node.body.insert(-1,ast.parse('_validate_sidecar_metadata(frozen, access)').body[0]);mark('validate_metadata')
            return node
        def visit_Call(self,node):
            if self.current=='_tasks' and ast.unparse(node)=="require(not database.with_name(database.name + '-wal').exists(), 'A stable closed original database is required')":
                node.args[0]=ast.parse('_allow_empty_wal(database, access)').body[0].value;mark('empty_wal_guard')
            return self.generic_visit(node)
        def visit_Dict(self,node):
            if self.current in ('prepare','_recover'):
                for key,value in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and key.value=='version' and isinstance(value,ast.Constant) and value.value==1:
                        value.value=2;mark('version_'+self.current)
            return self.generic_visit(node)
        def visit_Compare(self,node):
            if self.current=='validate_prepared' and ast.unparse(node)=="frozen['version'] == 1":
                node.comparators[0]=ast.Constant(2);mark('version_validate_prepared')
            return self.generic_visit(node)
        def visit_Constant(self,node):
            changes={'prepared_fixed_P01_normal_append_only_evidence_recovery':'prepared_fixed_P01_normal_append_only_evidence_recovery_revision2',
                'fixed_P01_normal_append_only_evidence_recovery_certificate':'fixed_P01_normal_append_only_evidence_recovery_certificate_revision2'}
            if type(node.value) is str and node.value in changes:
                old=node.value;node.value=changes[old];mark('kind_'+old)
            return node
    tree=Adapt().visit(tree)
    expected={'prepare_metadata':1,'validate_metadata':1,'empty_wal_guard':1,'version_prepare':1,'version__recover':1,
        'version_validate_prepared':1,'kind_prepared_fixed_P01_normal_append_only_evidence_recovery':1,
        'kind_fixed_P01_normal_append_only_evidence_recovery_certificate':1}
    if counts!=expected:raise ValueError('The exact recovery-v2 seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),str(FROZEN),'exec'),_N)
_first_access=_N['Access'];_first_recipes=_N['recipes'];_first_recover=_N['_recover']
require,reference=_N['require'],_N['reference']


def _fingerprint(path):
    value=path.lstat()
    return {key:getattr(value,'st_'+key) for key in ('dev','ino','mode','nlink','size','mtime_ns','ctime_ns')}


def _sidecar(path,*,wal):
    require(not path.is_symlink() and path==path.resolve(),'SQLite sidecars must be real nonsymlink paths')
    if not path.exists():return {'path':str(path),'exists':False}
    before=_fingerprint(path)
    require(stat.S_ISREG(before['mode']) and (not wal or before['size']==0),
        'Only an absent or exact zero-byte regular WAL is compatible with immutable SQLite')
    record=reference(path)
    require(before==_fingerprint(path),'A SQLite sidecar changed while recording its state')
    return {'path':str(path),'exists':True,'reference':record,'stat':before}


def _snapshot():
    database=_N['RUN']/'run.sqlite'
    return {'database':reference(database),'wal':_sidecar(database.with_name(database.name+'-wal'),wal=True),
        'shm':_sidecar(database.with_name(database.name+'-shm'),wal=False)}


def _register(access,snapshot):
    access.checked(snapshot['database'],'unchanged_original_database')
    for name in ('wal','shm'):
        if snapshot[name]['exists']:access.checked(snapshot[name]['reference'],'stable_sqlite_'+name)
    access.sqlite_snapshot=deepcopy(snapshot)


def _bind_sidecar_metadata(frozen,access):
    for record in LINEAGE.values():access.checked(record,'immutable_prior_recovery_lineage')
    state=_snapshot();_register(access,state)
    frozen['sqlite_sidecar_policy']='absent_or_exact_zero_byte_WAL_immutable_SQLite_with_stable_sidecar_inventory'
    frozen['sqlite_snapshot']=state;frozen['prior_recovery_lineage']=deepcopy(LINEAGE)
    frozen['preparation_access_inventory']=access.inventory()


def _validate_sidecar_metadata(frozen,access):
    require(frozen['sqlite_sidecar_policy']=='absent_or_exact_zero_byte_WAL_immutable_SQLite_with_stable_sidecar_inventory'
        and frozen['prior_recovery_lineage']==LINEAGE,'The explicit SQLite compatibility scope or retained failure lineage changed')
    for record in LINEAGE.values():access.checked(record,'immutable_prior_recovery_lineage')
    require(_snapshot()==frozen['sqlite_snapshot'],'The frozen SQLite database or sidecar existence/stat/hash changed')
    _register(access,frozen['sqlite_snapshot'])


def _allow_empty_wal(database,access):
    require(database==_N['RUN']/'run.sqlite','Another SQLite database cannot enter this fixed recovery')
    current=_snapshot()
    if hasattr(access,'sqlite_snapshot'):
        require(current==access.sqlite_snapshot,'The SQLite sidecars changed before immutable reading')
    _register(access,current)
    return True


class Access(_first_access):
    def guard(self):
        super().guard()
        if hasattr(self,'sqlite_snapshot'):
            require(_snapshot()==self.sqlite_snapshot,'The SQLite database or WAL/SHM metadata changed during recovery')


def recipes():
    result=_first_recipes();result[str(FROZEN)]=reference(FROZEN)
    for record in LINEAGE.values():
        require(reference(record['path'])==record,'The retained original recovery failure/proposal changed')
        result[record['path']]=deepcopy(record)
    return result


def _recover(frozen,access):
    result=_first_recover(frozen,access);access.guard()
    result['prior_recovery_lineage']=deepcopy(LINEAGE)
    result['sqlite_snapshot_at_preparation']=deepcopy(frozen['sqlite_snapshot'])
    result['sqlite_snapshot_at_exit']=_snapshot()
    require(result['sqlite_snapshot_at_preparation']==result['sqlite_snapshot_at_exit'],
        'SQLite state changed before the new certificate was written')
    result['SQLite_database_or_sidecar_write_delete_checkpoint_performed']=False
    return result


_N.update(Access=Access,recipes=recipes,_recover=_recover,_bind_sidecar_metadata=_bind_sidecar_metadata,
    _validate_sidecar_metadata=_validate_sidecar_metadata,_allow_empty_wal=_allow_empty_wal)
for _name,_value in _N.items():
    if not _name.startswith('__'):globals().setdefault(_name,_value)

if __name__=='__main__':raise SystemExit(main())
