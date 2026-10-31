#!/usr/bin/env python3
"""Isolated v2 gate: accept exact owned Docker absence messages in either case."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/validate_period_boundary_candidate.py'
UPSTREAM_SHA256='84e9346b3802dd763c5a867fc47b84c8d982a7a6e15864d05dc247d6df11a6a3'
KIND='prepared_period_boundary_shared_engineering_v2'
TERMINAL_KIND='period_boundary_actual_shared_engineering_validation_v2'
VERSION=2


def owned_absence(calls):
    ids=[c['actual_resource_evidence']['container_id'] for c in calls]
    if len(ids)!=len(set(ids)) or not all(re.fullmatch('[0-9a-f]{64}',cid) for cid in ids):
        raise ValueError('Distinct full owned IDs required')
    rows=[]
    for cid in ids:
        process=subprocess.run(['docker','inspect',cid,'--format','{{.Id}}'],capture_output=True,text=True,timeout=15)
        # Match the whole diagnostic and the exact owned ID. Other failures stay unknown.
        missing=re.fullmatch(r'(?i:(?:error:\s*)?no such (?:object|container):\s*)'+re.escape(cid),process.stderr.strip()) is not None
        rows.append({'full_id':cid,'returncode':process.returncode,'stdout':process.stdout,'stderr':process.stderr,
            'absent':process.returncode==1 and not process.stdout.strip() and missing})
    daemon=subprocess.run(['docker','version','--format','{{.Server.Version}}'],capture_output=True,text=True,timeout=15)
    return {'all_owned_containers_absent':all(row['absent'] for row in rows),
        'daemon_reachable':daemon.returncode==0 and bool(daemon.stdout.strip()),'owned':rows,
        'daemon_version':daemon.stdout.strip(),'cleanup_mutations_by_validator':False,
        'absence_parser_policy':'v2_case_insensitive_message_exact_full_owned_id'}


def _namespace():
    source=UPSTREAM.read_bytes()
    if hashlib.sha256(source).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('Frozen original period validator changed')
    counts={'terminal_kind':0,'version_write':0,'version_check':0}
    class Protocol(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='period_boundary_actual_shared_engineering_validation':
                counts['terminal_kind']+=1
                return ast.copy_location(ast.Constant(TERMINAL_KIND),node)
            return node
        def visit_Dict(self,node):
            node=self.generic_visit(node)
            keys=[key.value if isinstance(key,ast.Constant) else None for key in node.keys]
            if 'kind' in keys and 'version' in keys:
                kind=node.values[keys.index('kind')]
                if (isinstance(kind,ast.Name) and kind.id=='KIND') or (isinstance(kind,ast.Constant) and kind.value==TERMINAL_KIND):
                    index=keys.index('version')
                    if not isinstance(node.values[index],ast.Constant) or node.values[index].value!=1:
                        raise ValueError('Unexpected original protocol version')
                    node.values[index]=ast.Constant(VERSION);counts['version_write']+=1
            return node
        def visit_Compare(self,node):
            node=self.generic_visit(node)
            if (isinstance(node.left,ast.Subscript) and isinstance(node.left.value,ast.Name)
                and node.left.value.id in ('f','terminal') and isinstance(node.left.slice,ast.Constant)
                and node.left.slice.value=='version' and len(node.comparators)==1
                and isinstance(node.comparators[0],ast.Constant) and node.comparators[0].value==1):
                node.comparators[0]=ast.Constant(VERSION);counts['version_check']+=1
            return node
    tree=Protocol().visit(ast.parse(source,filename=str(UPSTREAM)))
    if counts!={'terminal_kind':2,'version_write':2,'version_check':2}:
        raise ValueError('Unexpected original protocol structure')
    namespace={'__name__':'_isolated_period_boundary_validation_v2','__file__':str(UPSTREAM)}
    exec(compile(ast.fix_missing_locations(tree),str(UPSTREAM),'exec'),namespace)
    original_recipes=namespace['recipes']
    def bound_recipes():
        result=original_recipes()
        result[str(Path(__file__).resolve())]=namespace['reference'](Path(__file__).resolve())
        return result
    namespace.update(KIND=KIND,owned_absence=owned_absence,recipes=bound_recipes)
    return namespace


_PRIVATE=_namespace()
for _name in ('prepare','validate_prepared','execute_prepared','validate_completed','reference','checked','read','write','main','STAGES'):
    globals()[_name]=_PRIVATE[_name]
recipes=_PRIVATE['recipes']

if __name__=='__main__':
    raise SystemExit(main())
