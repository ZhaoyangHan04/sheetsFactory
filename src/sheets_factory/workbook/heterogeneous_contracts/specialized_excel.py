"""Fresh uncached workbook materialization of categorical policy definitions.

The original independent emitter and frozen structural specializer are reused.
No journal, financial result, cache, or reference workbook is accepted. This
module proves physical definition/metadata preservation, not financial source
qualification; a new independent audit and actual recalculations remain due.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import excel as original
from . import policy_specialization as compiler

PUBLIC_NOTES = original.PUBLIC_NOTES
PHASES = original.PHASES
expression_formula = original.expression_formula


def _require(condition,message):
    if not condition:raise ValueError(message)


def _implementation(module):
    path=Path(module.__file__).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _self_implementation():
    path=Path(__file__).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _typed(value):
    # Mechanical primitive identity only. No monetary/rate/date operation.
    return type(value).__name__,value.hex() if type(value) is float else value


def _style(cell):
    return None if cell._style is None else tuple(cell._style)


def _snapshot(book):
    return {(sheet.title,cell.coordinate):(_typed(cell.value),cell.data_type,_style(cell))
            for sheet in book.worksheets for cell in sheet._cells.values()}


def _location(row):return row['sheet'],row['cell']


def _physical_contents(bindings):
    result={}
    for category,key in [('input_bindings','stored_value'),('literal_bindings','value'),('arithmetic_bindings','formula')]:
        for row in bindings[category]:
            location=_location(row)
            _require(location not in result,'Physical input/literal/formula coverage overlaps')
            result[location]=(category,row[key])
    return result


def validate_materialized_structure(book,bindings):
    """Recheck all physical contents, formulas and closed bound references.

    This checks uncalculated definitions and provided literals. It never reads
    a cached financial result or claims numeric financial equivalence.
    """
    _require(book.sheetnames==bindings['sheetnames'],'Worksheet names/order differ from the complete bindings')
    _require(not book.defined_names and not getattr(book,'_external_links',[]),
        'A public source cannot contain extra names or external links')
    expected=_physical_contents(bindings)
    observed={(sheet.title,cell.coordinate):cell for sheet in book.worksheets
              for cell in sheet._cells.values() if cell.value is not None}
    _require(set(observed)=={key for key,(_,value) in expected.items() if value is not None},
        'Unbound content, a missing field, or an old template remains in the workbook')
    for (sheet,address),(category,value) in expected.items():
        cell=book[sheet][address]
        _require(_typed(cell.value)==_typed(value),'A bound formula or native primitive differs from the actual cell')
        _require((cell.data_type=='f')==(category=='arithmetic_bindings'),
            'A provided literal became a formula or a calculation lost its formula type')
    rows=bindings['arithmetic_bindings']
    _require(type(bindings.get('formula_count')) is int and bindings['formula_count']==len(rows),
        'The complete materialized formula count differs')
    available={compiler._reference(row) for row in bindings['input_bindings']+bindings['literal_bindings']}
    graph,dependencies=compiler._graph(rows,available)
    compiler._order(graph,dependencies)
    financial=set()
    for row in bindings['financial_bindings']:
        ref=compiler._reference(row)
        _require(ref in graph and ref not in financial and graph[ref]['formula']==row['formula']
            and compiler.canonical(graph[ref]['expression'])==compiler.canonical(row['expression']),
            'A financial alias is missing, duplicated or differs from its actual definition')
        financial.add(ref)
    return {'kind':'uncached_policy_specialized_workbook_structure','version':1,
        'worksheets':len(book.sheetnames),'physical_formulas':len(rows),
        'financial_physical_roots':len(financial),'native_input_bindings':len(bindings['input_bindings']),
        'literal_bindings':len(bindings['literal_bindings']),'physical_nonempty_cells':len(observed),
        'all_financial_roots_and_references_present':True,'all_physical_formulas_and_native_values_bound':True,
        'cached_financial_results_read_or_written':False,'numeric_financial_equivalence_verified':False,
        'actual_recalculations':0,'quality_or_difficulty_certified':False}


def emit_heterogeneous_workbook(book,specification,*,max_formulas=1_000_000,allow_production=False):
    """Emit and specialize a fresh workbook through the existing raw-spec API.

    Full dimensions keep the original explicit allow_production gate. The
    intermediate original workbook is never saved, archived or copied into a
    public sheet. Only retained NEW definitions/labels survive this call.
    """
    recipe={'wrapper':_self_implementation(),'original_emitter':_implementation(original),
            'specializer':_implementation(compiler)}
    old=original.emit_heterogeneous_workbook(book,specification,
        max_formulas=max_formulas,allow_production=allow_production)
    validate_materialized_structure(book,old)
    before=_snapshot(book);sheetnames=list(book.sheetnames)
    calculation=deepcopy(book.calculation)
    new,compilation_report=compiler.specialize_bindings(old,enabled=True)
    compiled_bindings_sha256=compiler.canonical(new)
    _require(new['input_bindings']==old['input_bindings'] and new['public_notes']==list(PUBLIC_NOTES)
        and new['phases']==list(PHASES),'A primitive or a public policy changed')
    _require([compiler._identity(r) for r in new['financial_bindings']]
        ==[compiler._identity(r) for r in old['financial_bindings']],
        'Financial paths, sparse origins, units or semantic ownership changed')
    old_formulas={_location(row):row for row in old['arithmetic_bindings']}
    new_formulas={_location(row):row for row in new['arithmetic_bindings']}
    _require(new_formulas.keys()<=old_formulas.keys(),'Specialization introduced an unbound physical formula')
    old_literals={_location(row):row for row in old['literal_bindings']}
    new_literals={_location(row):row for row in new['literal_bindings']}
    _require(new_literals.keys()<=old_literals.keys() and all(new_literals[key]==old_literals[key] for key in new_literals),
        'A native literal was added or modified')
    removed_formulas=old_formulas.keys()-new_formulas.keys()
    removed_literals=old_literals.keys()-new_literals.keys()
    allowed_labels={(sheet,'A'+address[1:]) for sheet,address in removed_formulas if address.startswith('B')}
    _require(removed_literals<=allowed_labels,'Only dead calculation-row labels may be removed')
    for (sheet,address),row in old_formulas.items():
        cell=book[sheet][address]
        _require(cell.data_type=='f' and cell.value==row['formula'],'The original uncached definition changed before specialization')
        cell.value=new_formulas[(sheet,address)]['formula'] if (sheet,address) in new_formulas else None
    for sheet,address in removed_literals:
        cell=book[sheet][address]
        _require(_typed(cell.value)==_typed(old_literals[(sheet,address)]['value']),'A dead helper label changed')
        cell.value=None
    after=_snapshot(book)
    allowed=set(old_formulas)|removed_literals
    _require(book.sheetnames==sheetnames and book.calculation==calculation,'Worksheet or calculation configuration changed')
    _require(all(after.get(key)==value for key,value in before.items() if key not in allowed),
        'An unrelated cell, native input or public note changed')
    _require(all(after[key][2]==value[2] for key,value in before.items()),'A format/style changed during materialization')
    geometry=validate_materialized_structure(book,new)
    _require(geometry['financial_physical_roots']==len(old['financial_bindings']), 'A financial physical alias was lost')
    _require(recipe=={'wrapper':_self_implementation(),'original_emitter':_implementation(original),
            'specializer':_implementation(compiler)},'The source compiler recipe changed')
    new['implementation']=recipe['wrapper']
    new['specialized_materialization']={'version':1,'implementation':recipe['wrapper'],
        'original_emitter':recipe['original_emitter'],'specializer':recipe['specializer'],
        'compiled_bindings_sha256':compiled_bindings_sha256,'structural_compilation_report':compilation_report,
        'geometry':geometry,'unmodified_cells_styles_and_configuration_preserved':True,
        'removed_formula_cells':len(removed_formulas),'removed_literal_helper_cells':len(removed_literals),
        'original_templates_saved_or_materialized_as_archive':False,
        'financial_equivalence_verified':False,'actual_LO_calls':0,'source_or_task_qualified':False}
    return new
