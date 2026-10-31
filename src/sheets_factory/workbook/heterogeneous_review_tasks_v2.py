"""Bounded v2: retain six literal clarifications and their two direct text caches.

The frozen v1 implementation executes in a private namespace. No original
module globals, files, numerical values, formulas or financial policies change.
"""
from __future__ import annotations

import ast
from pathlib import Path

from . import heterogeneous_native_merge as merge

ROOT=Path(__file__).resolve().parents[3]
UPSTREAM={
    "src/sheets_factory/workbook/heterogeneous_review_tasks.py":"c0432c67ed821448b5b26ee650e597987cd00f2aa5fdef9753b9143834187327",
    "scripts/prepare_heterogeneous_review_task_pair.py":"f6f7aa604b44501fd71b56995fd8fc02e83e56f6d1aa83b6085fed88ffa73a68",
    "scripts/validate_heterogeneous_review_task_pair.py":"3a5d1eefc5a6d02646a0d12145b2da41609bd626e2a8a8e7867681a9de949d6e",
    "config/heterogeneous_review_tasks_v1.json":"c8c8e09813077b071812e35d36a58875bd324263ec4bf47dfcde691c7d3f731c",
    "tests/test_heterogeneous_review_tasks.py":"46cc9d987e24f5197fe188f88dc2828f52b6be1ef3a2b431db74ea9f428bda61",
}
ALIASES=[
    {"sheet":"DCF - Valuation as picture","cell":"H6","source_sheet":"DCF - Stories to Numbers","source_cell":"G10"},
    {"sheet":"DCF - Valuation as picture","cell":"K6","source_sheet":"DCF - Stories to Numbers","source_cell":"G12"},
]
PATHS={
    "scripts/prepare_heterogeneous_review_task_pair.py":"scripts/prepare_heterogeneous_review_task_pair_v2.py",
    "scripts/validate_heterogeneous_review_task_pair.py":"scripts/validate_heterogeneous_review_task_pair_v2.py",
    "tests/test_heterogeneous_review_tasks.py":"tests/test_heterogeneous_review_tasks_v2.py",
    "config/heterogeneous_review_tasks_v1.json":"config/heterogeneous_review_tasks_v2.json",
}
for _path,_sha in UPSTREAM.items():
    merge.require(merge.file_ref(ROOT/_path)["sha256"]==_sha,"Frozen v1 heterogeneous task source changed")


class _Adapter(ast.NodeTransformer):
    def __init__(self):self.paths={k:0 for k in PATHS};self.versions=0;self.comparisons=0;self.injections=0;self.literal_count=0
    def visit_Constant(self,node):
        if isinstance(node.value,str) and node.value in PATHS:
            self.paths[node.value]+=1;return ast.copy_location(ast.Constant(PATHS[node.value]),node)
        return node
    def visit_Assign(self,node):
        self.generic_visit(node)
        if any(isinstance(t,ast.Name) and t.id=="VERSION" for t in node.targets):node.value=ast.Constant(2)
        return node
    def visit_Dict(self,node):
        self.generic_visit(node)
        for index,(key,value) in enumerate(zip(node.keys,node.values)):
            if isinstance(key,ast.Constant) and key.value=="version" and isinstance(value,ast.Constant) and value.value==1:
                node.values[index]=ast.Constant(2);self.versions+=1
        return node
    def visit_Compare(self,node):
        self.generic_visit(node)
        if isinstance(node.left,ast.Subscript) and isinstance(node.left.slice,ast.Constant) and len(node.comparators)==1 and isinstance(node.comparators[0],ast.Constant):
            if node.left.slice.value=="version" and node.comparators[0].value==1:node.comparators[0]=ast.Constant(2);self.comparisons+=1
            elif node.left.slice.value=="primary_value_mismatch_count" and node.comparators[0].value==6:node.comparators[0]=ast.Constant(8);self.literal_count+=1
        return node
    def visit_Expr(self,node):
        self.generic_visit(node)
        if isinstance(node.value,ast.Call) and len(node.value.args)>1 and isinstance(node.value.args[1],ast.Constant) and node.value.args[1].value in {"Exactly six approved presentation corrections required","Six presentation corrections required"}:
            # The six literal patches remain individually checked before the
            # declared, formula-preserving cache transfers are appended.
            source="snapshot" if node.value.args[1].value.startswith("Exactly") else "source"
            extra=ast.parse("patches.extend(_alias_edits(c, "+source+", patches))").body[0]
            self.injections+=1;return [node,extra]
        return node


_source=(ROOT/next(iter(UPSTREAM))).read_text()
_tree=ast.parse(_source);_adapter=_Adapter();_tree=_adapter.visit(_tree)
merge.require(_adapter.paths=={"scripts/prepare_heterogeneous_review_task_pair.py":1,"scripts/validate_heterogeneous_review_task_pair.py":1,"tests/test_heterogeneous_review_tasks.py":1,"config/heterogeneous_review_tasks_v1.json":3} and _adapter.versions==7 and _adapter.comparisons==2 and _adapter.injections==2 and _adapter.literal_count==1,"Frozen v1 task AST anchors changed")
ast.fix_missing_locations(_tree)
_ns={"__name__":__name__+"._frozen_v1","__package__":__package__,"__file__":__file__}
exec(compile(_tree,str(ROOT/next(iter(UPSTREAM))),"exec"),_ns)
_BASE_PARTS=_ns["_edited_parts"];_BASE_RECIPES=_ns["recipes"];_BASE_LOAD=_ns["_load_config"];_BASE_WRITE=_ns["write"];_BASE_VALIDATE=_ns["validate_prepared"]


def _alias_edits(config,snapshot,literals):
    merge.require(config["text_alias_cache_transfers"]==ALIASES,"Exactly two declared text aliases required")
    patches={(e["sheet"],e["cell"]):e for e in literals}
    targets={tuple(p) for row in _ns["read"](config["closure"])["rows"] for p in row["reverse_closure_points"]}
    edits=[]
    for alias in ALIASES:
        point=(alias["sheet"],alias["cell"]);source=(alias["source_sheet"],alias["source_cell"])
        cell=snapshot["cells"][point[0]][point[1]];original=snapshot["cells"][source[0]][source[1]]
        expected=merge._quote(source[0])+"!"+source[1]
        merge.require(cell["is_formula"] and merge._formula_tokens(cell["formula"])==merge._formula_tokens(expected),"Text alias must retain its exact direct identity formula")
        merge.require(cell["primary"]==original["primary"] and cell["primary"]["type"]=="string" and source in patches and patches[source]["action"]=="text","Text alias must follow an approved literal text patch")
        merge.require(point not in targets,"Text aliases unexpectedly intersect343/766 financial expectations")
        edits.append(dict(alias,action="text_cache_identity",value=patches[source]["value"],unchanged_direct_formula=cell["formula"],original_typed_cache=cell["primary"]))
    return edits


def _edited_parts_v2(parts,edits):
    normal=[e for e in edits if e["action"]!="text_cache_identity"];aliases=[e for e in edits if e["action"]=="text_cache_identity"]
    result,audits=_BASE_PARTS(parts,normal)
    if not aliases:return result,audits
    merge.require([{k:e[k] for k in ("sheet","cell","source_sheet","source_cell")} for e in aliases]==ALIASES,"No undeclared text-cache edit is permitted")
    mapping=_ns["_sheet_parts"](result);grouped={}
    for e in aliases:grouped.setdefault(mapping[e["sheet"]],[]).append(e)
    for part,rows in grouped.items():
        doc=merge._xml(result[part]);cells={c.getAttribute("r"):c for c in merge._all(doc) if c.namespaceURI==merge.S and c.localName=="c"}
        before={a:merge._semantic(c) for a,c in cells.items()}
        for e in rows:
            c=cells[e["cell"]];f=merge._children(c,"f");v=merge._children(c,"v")
            merge.require(c.getAttribute("t")=="str" and len(f)==len(v)==1 and merge._text(f[0])==e["unchanged_direct_formula"] and merge._text(v[0])==e["original_typed_cache"]["value"],"Text alias formula/cache contract changed")
            formula=merge._semantic(f[0]);merge._set_text(v[0],e["value"])
            merge.require(merge._semantic(f[0])==formula,"Text alias formula changed")
        after={a:merge._semantic(c) for a,c in cells.items()};changed={a for a in before if before[a]!=after[a]}
        merge.require(changed=={e["cell"] for e in rows},"Undeclared alias worksheet mutation")
        result[part]=merge._bytes(doc);audits.append({"part":part,"declared_cells":sorted(changed),"actually_changed_cells":sorted(changed),"all_other_cell_subtrees_identical":True,"only_direct_text_caches_changed":True})
    return result,audits


def _recipes_v2():
    result=_BASE_RECIPES()
    for path,sha in UPSTREAM.items():
        binding=_ns["ref"](ROOT/path);merge.require(binding["sha256"]==sha,"Frozen historical recipe changed");result[path]=binding
    return result


def _load_config_v2(path):
    c=_BASE_LOAD(path);lineage=c["prior_failure_lineage"]
    merge.require(len(lineage)==1 and lineage[0]["terminal"]["sha256"]=="1746d8bd22a7128ad79f296fb381e6f2bd64a4de3a60889b48e375a42e86945d","Exact retained three-call failure lineage required")
    old=_ns["read"](lineage[0]["terminal"])
    merge.require(old["status"]=="held" and not old["passed"] and old["LO_calls_started"]==old["LO_calls_completed"]==3 and old["model_calls"]==old["solver_calls"]==old["Harbor_calls"]==0,"Prior failed attempt cannot be promoted")
    merge.require(c["text_alias_cache_transfers"]==ALIASES,"Only two declared text-cache transfers supported")
    return c


def _cache_proof(frozen):
    c=_ns["read"](frozen["config"]);edits=_ns["read"](frozen["presentation_patch_proof"])["edits"]
    aliases=[e for e in edits if e["action"]=="text_cache_identity"]
    merge.require(len(edits)==8 and len(aliases)==2,"Six literal edits plus two cache transfers required")
    rows=[{k:e[k] for k in ("sheet","cell","source_sheet","source_cell","unchanged_direct_formula","original_typed_cache")}|{"expected_typed_cache":{"type":"string","value":e["value"]},"outside_financial_scope766":True,"formula_preserved":True} for e in aliases]
    return {"kind":"declared_two_direct_text_alias_cache_transfers","version":2,"source":frozen["source"],"presentation":frozen["source_presentation"],"aliases":rows,"prior_failure_lineage":c["prior_failure_lineage"],"numeric_caches_changed":0,"all_other_cell_subtrees_unchanged_except_six_literals_and_two_caches":True}


def _write_v2(path,value):
    if value.get("kind")==_ns["VIEW_KIND"] and value.get("version")==2 and "text_alias_cache_proof" not in value:
        value=dict(value);value["text_alias_cache_proof"]=_BASE_WRITE(Path(path).parent/"private/text_alias_cache_proof.json",_cache_proof(value))
    elif value.get("kind")=="heterogeneous_review_task_view_actual_validation" and value.get("version")==2:
        value=dict(value);value["text_alias_cache_proof"]=_ns["read"](value["preparation"])["text_alias_cache_proof"]
    return _BASE_WRITE(path,value)


def _validate_prepared_v2(value):
    frozen,plan=_BASE_VALIDATE(value)
    merge.require(_ns["read"](frozen["text_alias_cache_proof"])==_cache_proof(frozen),"Declared text alias cache proof changed")
    return frozen,plan


_ns.update(_alias_edits=_alias_edits,_edited_parts=_edited_parts_v2,recipes=_recipes_v2,_load_config=_load_config_v2,write=_write_v2,validate_prepared=_validate_prepared_v2)
for _name in ("KIND","VIEW_KIND","MATERIAL_KIND","VERSION","MODES","helper","read","ref","write","checked","recipes","all_refs","surgery","verify_surgery","delta","judge","prepare_pair","validate_prepared","_parts","_sheet_parts","_namespace_proof"):
    globals()[_name]=_ns[_name]
