#!/usr/bin/env python3
"""Waterfall source3 revision2: allow empty original placeholders, cold input stays strict."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from xml.etree import ElementTree as X
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/build_waterfall_portfolios_source.py'
UPSTREAM_SHA='09223a654ce5231d83d15b292f299d6ffab9f0b0e1151dbe24eba9af187cc69e'
KIND='prepared_waterfall_portfolios_cold_source3_revision2'
SOURCE_KIND='independently_checked_waterfall_portfolios_cold_source3_revision2'
FAILURE=ROOT/'outputs/research/waterfall24_source3_20261101T001230Z/prepared/preparation_failure.json'
FAILURE_SHA='e43225cd945534c3f87e1ac2730aa1b2e128c689a55ba09100be008e73e528b2'
FAILURE_PROSPECTIVE=ROOT/'outputs/research/waterfall24_source3_20261101T001230Z/prospective.json'
FAILURE_PROSPECTIVE_SHA='9ddfdf4313c8030ec0ba45abc2cfd616acca67c04d70839d820754a7e7ba98bf'
FAILURE_CENSUS=ROOT/'outputs/research/waterfall_source3_empty_cache_node_failure_readonly_20261101T001343Z/receipt.json'
FAILURE_CENSUS_SHA='7a0640fe3bb271732a3de5adbeae4fc925b280d2dde7e96ac3db797723735c52'
S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def unseeded_original(path):
    """Allow only absent/empty scalar v placeholders in the ORIGINAL renderer file."""
    count=0
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not (name.startswith('xl/worksheets/') and name.endswith('.xml')):continue
            root=X.fromstring(archive.read(name))
            for cell in root.iter(S+'c'):
                if cell.find(S+'f') is None:continue
                if cell.find(S+'is') is not None:
                    raise ValueError('Original formula inline caches are forbidden')
                values=cell.findall(S+'v')
                if len(values)>1:raise ValueError('Duplicate original cache placeholders are invalid')
                for value in values:
                    if value.text not in (None,'') or value.attrib or len(value):
                        raise ValueError('Original formula caches may contain no actual value')
                count+=1
    return count


def _load():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:
        raise ValueError('The frozen first waterfall source3 driver changed')
    tree=ast.parse(raw);changed=0
    class Adapt(ast.NodeTransformer):
        def visit_Call(self,node):
            nonlocal changed
            if (isinstance(node.func,ast.Name) and node.func.id=='_physical_empty'
                    and len(node.args)==1 and ast.unparse(node.args[0])=="checked(candidate['source'])"):
                node.func.id='_unseeded_original';changed+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='prepared_waterfall_portfolios_cold_source3':node.value=KIND
            elif node.value=='independently_checked_waterfall_portfolios_cold_source3':node.value=SOURCE_KIND
            return node
    tree.body=[n for n in tree.body if not (isinstance(n,ast.If) and isinstance(n.test,ast.Compare)
        and ast.unparse(n.test)=="__name__ == '__main__'")]
    tree=Adapt().visit(tree);ast.fix_missing_locations(tree)
    if changed!=2:raise ValueError('Exactly the prepare and validate original-source checks must change')
    namespace={'__name__':'_isolated_waterfall_source3_revision2','__file__':str(UPSTREAM),
        '_unseeded_original':unseeded_original}
    exec(compile(tree,str(UPSTREAM),'exec'),namespace)
    return namespace


_P=_load();_BASE_RECIPES=_P['recipes']


def recipes():
    entries=((UPSTREAM,UPSTREAM_SHA),(FAILURE,FAILURE_SHA),(FAILURE_PROSPECTIVE,FAILURE_PROSPECTIVE_SHA),
             (FAILURE_CENSUS,FAILURE_CENSUS_SHA))
    for path,digest in entries:
        if _P['reference'](path)['sha256']!=digest:
            raise ValueError('The preserved first failure or frozen source3 lineage changed')
    return {**_BASE_RECIPES(),**{str(p.resolve()):_P['reference'](p) for p in
        (Path(__file__),FAILURE,FAILURE_PROSPECTIVE,FAILURE_CENSUS)}}


_P['recipes']=recipes
_P['_N']['recipes']=recipes
_N=_P['_N']
for _name in ('prepare','validate_prepared','execute_prepared','validate_source','validate_completed','main'):
    globals()[_name]=_P[_name]
for _name in ('reference','checked','read','write','runtime'):
    globals()[_name]=_P[_name]


if __name__=='__main__':raise SystemExit(main())
