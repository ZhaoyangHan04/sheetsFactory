#!/usr/bin/env python3
"""Build a fresh policy-specialized source through the frozen source workflow.

Only the emitter, source namespaces, and explicit recipe dependencies differ.
The unchanged workflow still requires the independent full mathematical audit,
three actual recalculations/audits, and two complete typed stability checks.
Importing this module or preparing a source performs no financial execution.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path


UPSTREAM = Path(__file__).resolve().with_name("build_heterogeneous_source.py")
UPSTREAM_SHA256 = "0d8abfe960901da24c76fbdc3fbaaebb9bc37b973f6fa326904517ae495d7fba"


def specialized_builder_ast(source: bytes) -> ast.Module:
    """Apply only the enumerated changes to an exact, SHA-bound upstream AST."""
    if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("The frozen original heterogeneous source builder changed")
    tree = ast.parse(source, filename=str(UPSTREAM))
    changed = set()
    namespaces = {
        "PREPARED_KIND": (
            "prepared_heterogeneous_contract_source",
            "prepared_policy_specialized_heterogeneous_contract_source",
        ),
        "SOURCE_KIND": (
            "independently_verified_heterogeneous_contract_source",
            "independently_verified_policy_specialized_heterogeneous_contract_source",
        ),
    }
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in namespaces:
                old, new = namespaces[name]
                if name in changed or not isinstance(node.value, ast.Constant) or node.value.value != old:
                    raise ValueError("The frozen source namespace assignment differs")
                node.value.value = new
                changed.add(name)
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name == "recipes":
            if "recipes" in changed or not isinstance(node.body[-1], ast.Return):
                raise ValueError("The frozen source recipe layout differs")
            dependencies = ast.parse('''paths += [
                ROOT / "scripts/build_heterogeneous_source.py",
                ROOT / "src/sheets_factory/workbook/heterogeneous_contracts/specialized_excel.py",
                ROOT / "src/sheets_factory/workbook/heterogeneous_contracts/policy_specialization.py",
            ]''').body[0]
            node.body.insert(-1, dependencies)
            changed.add("recipes")
        if node.name != "execute_prepared":
            continue
        imports = [n for n in node.body if isinstance(n, ast.ImportFrom)
                   and n.module == "sheets_factory.workbook.heterogeneous_contracts"]
        if len(imports) != 1 or [(a.name, a.asname) for a in imports[0].names] != [
            ("excel", None), ("ledger", None), ("validate", None)
        ]:
            raise ValueError("The frozen execution imports differ")
        imports[0].names[0] = ast.alias(name="specialized_excel", asname="excel")
        changed.add("emitter")
        source_kinds = []
        for child in ast.walk(node):
            if isinstance(child, ast.Dict):
                source_kinds.extend(value for key, value in zip(child.keys, child.values)
                                    if isinstance(key, ast.Constant) and key.value == "source_kind")
        if len(source_kinds) != 1 or not isinstance(source_kinds[0], ast.Constant) or source_kinds[0].value != "hypothetical_heterogeneous_contracts_source":
            raise ValueError("The frozen manifest source kind differs")
        source_kinds[0].value = "hypothetical_policy_specialized_heterogeneous_contracts_source"
        changed.add("source_kind")
    if changed != {"PREPARED_KIND", "SOURCE_KIND", "recipes", "emitter", "source_kind"}:
        raise ValueError("The exact source-builder specialization was not applied")
    return ast.fix_missing_locations(tree)


# __file__ deliberately remains this wrapper: every inherited preparation and
# execution binds it in recipes(), together with the exact original builder.
# The original __main__ guard also supplies the ordinary explicit --run CLI.
exec(compile(specialized_builder_ast(UPSTREAM.read_bytes()), str(UPSTREAM), "exec"), globals())
