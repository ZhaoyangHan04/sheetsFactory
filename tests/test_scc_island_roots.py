"""Offline arithmetic/cache fixtures only; no test invokes or attests real LO."""
from copy import deepcopy
from datetime import date
import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.workbook.properties import CalcProperties
import pytest


from sheets_factory.checkers import scc_island_roots as scc

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def rewrite(path, callback):
    with ZipFile(path) as source:
        records = [(item, source.read(item.filename)) for item in source.infolist()]
    with ZipFile(path, 'w', ZIP_DEFLATED) as target:
        for item, raw in records:
            target.writestr(item, callback(item.filename, raw))


def patch_cell(path, sheet_index, address, *, formula=None, cached=None):
    def callback(name, raw):
        if name != f'xl/worksheets/sheet{sheet_index}.xml':
            return raw
        tree = ET.fromstring(raw)
        cell = next(c for c in tree.iter(NS + 'c') if c.attrib['r'] == address)
        if formula is not None:
            cell.find(NS + 'f').text = formula[1:]
        if cached is not None:
            value = cell.find(NS + 'v')
            if value is None:
                value = ET.SubElement(cell, NS + 'v')
            value.text = str(cached)
        return ET.tostring(tree)
    rewrite(path, callback)


class OfflineIterativeEngine:
    """Small synchronous, cent-rounded fixture, never an Excel/finance oracle."""
    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault

    def metadata(self):
        return {'backend': 'libreoffice_uno_docker', 'network': 'none',
                'image_id': 'sha256:' + 'a' * 64, 'version': 'OFFLINE FIXTURE ONLY',
                'test_fixture': True}

    def recalculate(self, raw, output):
        self.calls.append((Path(raw), Path(output)))
        if self.fault == 'engine_failure' and len(self.calls) == 2:
            raise RuntimeError('Explicit offline fixture execution failure')
        book = openpyxl.load_workbook(raw)
        caches = openpyxl.load_workbook(raw, data_only=True)
        formulas = {(sheet.title, cell.coordinate): (cell.value if isinstance(cell.value, str) else cell.value.text) for sheet in book
                    for cell in sheet._cells.values() if cell.data_type == 'f'}
        values = {key: caches[key[0]][key[1]].value or 0 for key in formulas}

        def flat(items):
            for item in items:
                if isinstance(item, list):
                    yield from flat(item)
                else:
                    yield item

        def reference(sheet, text, prior):
            name, address = text.rsplit('!', 1) if '!' in text else (sheet, text)
            if name.startswith("'"):
                name = name[1:-1].replace("''", "'")
            def value(address):
                key = name, address.replace('$', '')
                return prior[key] if key in prior else (book[key[0]][key[1]].value or 0)
            if ':' not in address:
                return value(address)
            left, top, right, bottom = range_boundaries(address)
            return [value(get_column_letter(col) + str(row))
                    for row in range(top, bottom + 1) for col in range(left, right + 1)]

        def evaluate(key, text, prior):
            pieces = []
            for token in Tokenizer(text).items:
                if token.type == 'OPERAND' and token.subtype == 'RANGE':
                    pieces.append(repr(reference(key[0], token.value, prior)))
                elif token.type == 'FUNC' and token.subtype == 'OPEN':
                    pieces.append(token.value.lower())
                else:
                    pieces.append(token.value)
            return eval(''.join(pieces), {'__builtins__': {}, 'datetime': datetime}, {
                'round': round, 'sum': lambda *a: sum(flat(a)), 'min': min, 'max': max,
                'n': lambda a: a if isinstance(a, (int, float)) else 0})

        limit = book.calculation.iterateCount or 128
        for _ in range(limit):
            after = {key: evaluate(key, text, values) for key, text in formulas.items()}
            if after == values:
                break
            values = after
        else:
            raise RuntimeError('Offline iterative counterfactual did not converge')
        names = book.sheetnames[:]
        book.close(); caches.close()

        def callback(name, payload):
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):
                return payload
            index = int(name.split('sheet')[-1].split('.')[0]) - 1
            tree = ET.fromstring(payload)
            for cell in tree.iter(NS + 'c'):
                key = names[index], cell.attrib['r']
                if key in values:
                    cached = cell.find(NS + 'v')
                    if cached is None:
                        cached = ET.SubElement(cell, NS + 'v')
                    cached.text = str(values[key])
            return ET.tostring(tree)

        with ZipFile(raw) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
            for item in source.infolist():
                target.writestr(item, callback(item.filename, source.read(item.filename)))
        if self.fault == 'business_subcent':
            patch_cell(output, 1, 'A1', cached=99.001)
        elif self.fault == 'second_pass_subcent' and len(self.calls) == 2:
            patch_cell(output, 3, 'A1', cached=4.801)
        elif self.fault == 'island_formula':
            patch_cell(output, 3, 'A1', formula='=99')
        if callable(self.fault):
            self.fault(len(self.calls), Path(raw), Path(output))
        return Path(output)


def fixture(tmp_path, *, original=None, changed=None, extra_inputs=None):
    original = original or {'A1': '=ROUND((B1+Inputs!B1)/2,2)', 'B1': '=ROUND(A1/2,2)', 'C1': '=A1*2'}
    changed = changed or {'A1': '=ROUND((B1+Inputs!B1)/3,2)', 'B1': '=ROUND(A1/3,2)', 'C1': '=A1*3'}
    book = openpyxl.Workbook(); book.active.title = 'Model'
    book.create_sheet('Inputs')['B1'] = 12
    book['Inputs']['C7'] = 'provided text'; book['Inputs']['D7'] = True
    for address, value in (extra_inputs or {}).items():
        book['Inputs'][address] = value
    book.calculation = CalcProperties(iterate=True, iterateCount=128, iterateDelta=1e-9)
    for address, text in original.items():
        book['Model'][address] = text
    raw = tmp_path / 'goal_raw.xlsx'; book.save(raw); book.close()
    goal, combined = tmp_path / 'goal.xlsx', tmp_path / 'combined.xlsx'
    OfflineIterativeEngine().recalculate(raw, goal)
    book = openpyxl.load_workbook(goal)
    for address, text in changed.items():
        book['Model'][address] = text
    raw = tmp_path / 'combined_raw.xlsx'; book.save(raw); book.close()
    OfflineIterativeEngine().recalculate(raw, combined)
    edits = [{'sheet': 'Model', 'cell': address, 'before': text, 'after': changed[address]}
             for address, text in original.items() if address in changed and changed[address] != text]
    return goal, combined, edits


def prove(tmp_path, paths, engine=None, **kwargs):
    return scc.prove_scc_island_root_impacts(goal=paths[0], combined_input=paths[1], edits=paths[2],
        engine=engine or OfflineIterativeEngine(), directory=tmp_path / 'proof', **kwargs)


def test_components_are_complete_on_cycles_self_loops_and_long_chains():
    graph = {('S', str(i)): {('S', str(i+1))} for i in range(3000)}
    graph['S', '3000'] = {('S', '3000')}
    graph['S', '20'].add(('S', '10'))
    result = scc.strongly_connected_components(graph)
    assert frozenset(('S', str(i)) for i in range(10, 21)) in result
    assert frozenset({('S', '3000')}) in result
    assert set().union(*result) == set(graph)
    with pytest.raises(ValueError, match='frontier omitted'):
        scc.strongly_connected_components({'a': {'b'}})


def test_plan_is_unexecuted_and_copies_complete_SCC_at_original_coordinates(tmp_path):
    paths = fixture(tmp_path); before = [p.read_bytes() for p in paths[:2]]
    result = scc.plan_scc_island_contexts(goal=paths[0], combined_input=paths[1], edits=paths[2],
                                         directory=tmp_path / 'plan')
    assert result['state'] == 'planned_unexecuted' and result['passed'] is False
    assert result['actual_LO_execution_count'] == 0
    assert [r['SCC_size'] for r in result['root_SCCs']] == [2, 2, 1]
    assert result['private_island_formula_count_per_context'] == 5
    assert result['union_graph']['complete_root_SCCs_equal_full_workbook_union_SCCs']
    assert result['copied_calculation_settings']['iterateCount'] == 128
    raw = openpyxl.load_workbook(result['contexts'][0]['raw_path'])
    assert raw['__SCI_0000_000']['A1'].value == "=ROUND(('__SCI_0000_000'!B1+'Inputs'!B1)/3,2)"
    assert raw['__SCI_0000_000']['B1'].value == "=ROUND('__SCI_0000_000'!A1/2,2)"
    assert raw['__SCI_0001_000']['A1'].value == "=ROUND(('__SCI_0001_000'!B1+'Inputs'!B1)/2,2)"
    assert raw['__SCI_0002_000']['C1'].value == "='Model'!A1*3"
    assert raw['Inputs']['D7'].value is True
    raw.close()
    assert [p.read_bytes() for p in paths[:2]] == before
    with pytest.raises(FileExistsError):
        scc.plan_scc_island_contexts(goal=paths[0], combined_input=paths[1], edits=paths[2], directory=tmp_path/'plan')


def test_offline_local_witnesses_equal_offline_2N_whole_counterfactual_values(tmp_path):
    paths = fixture(tmp_path); original = [p.read_bytes() for p in paths[:2]]; edits = deepcopy(paths[2])
    engine = OfflineIterativeEngine(); result = prove(tmp_path, paths, engine)
    assert result['passed'] is True, result.get('reason')
    assert len(engine.calls) == result['actual_LO_execution_count'] == 6
    assert len(result['contexts']) == 2
    assert all(c['full_used_area_exact_two_pass_stable'] for c in result['contexts'])
    assert all(c['fixed_point_residual']['all_SCC_members_exact_Fx_equal_x'] for c in result['contexts'])
    assert result['counterfactual_uniqueness_claimed'] is False
    assert result['source_uniqueness_transferred_to_mutants'] is False
    assert result['full_counterfactual_convergence_claimed'] is False
    assert result['complete_per_root_changed_sets_claimed'] is False
    assert result['individual_root_LO_executions'] == result['individual_marginal_LO_executions'] == 0
    for index, edit in enumerate(edits):
        for field, context, observed in [('after', paths[0], 'after_in_original_SCC'),
                                         ('before', paths[1], 'before_in_combined_SCC')]:
            book = openpyxl.load_workbook(context); book[edit['sheet']][edit['cell']] = edit[field]
            raw = tmp_path / f'strict_{index}_{field}_raw.xlsx'; output = tmp_path / f'strict_{index}_{field}.xlsx'
            book.save(raw); book.close(); OfflineIterativeEngine().recalculate(raw, output)
            book = openpyxl.load_workbook(output, data_only=True)
            assert scc.exact_typed_value(book[edit['sheet']][edit['cell']]) == result['root_checks'][index][observed]['exact']
            book.close()
    assert paths[2] == edits and [p.read_bytes() for p in paths[:2]] == original


def test_union_SCC_includes_feedback_created_only_by_before_after_union(tmp_path):
    paths = fixture(tmp_path, original={'A1': '=B1', 'B1': '=Inputs!B1'},
                    changed={'A1': '=Inputs!B1*2', 'B1': '=ROUND(A1/4,2)'})
    result = prove(tmp_path, paths)
    assert result['passed'] is True, result.get('reason')
    assert [r['SCC_size'] for r in result['root_SCCs']] == [2, 2]
    assert result['union_graph']['cyclic_SCC_count'] == 1


def test_counterfactual_local_nonconvergence_is_fail_closed(tmp_path):
    # Both supplied contexts converge, but restoring A1 alone creates A1=B1,
    # B1=A1+1. The SCC island must actually execute and reject this case.
    paths = fixture(tmp_path, original={'A1': '=B1', 'B1': '=Inputs!B1'},
                    changed={'A1': '=Inputs!B1*2', 'B1': '=A1+1'})
    result = prove(tmp_path, paths)
    assert result['passed'] is False and not result['root_impacts']
    assert result['state'] == 'execution_error' and 'did not converge' in result['reason']


@pytest.mark.parametrize('fault, reason', [('business_subcent', 'business values'),
    ('second_pass_subcent', 'stability'), ('island_formula', 'formula differs'),
    ('engine_failure', 'execution failure')])
def test_actual_evidence_failures_never_leave_partial_impacts(tmp_path, fault, reason):
    result = prove(tmp_path, fixture(tmp_path), OfflineIterativeEngine(fault))
    assert result['passed'] is False and result['root_impacts'] == []
    assert reason in result['reason']


@pytest.mark.parametrize('text', ['=INDIRECT("B1")', '=OFFSET(B1,0,0)', '=ROW()', '=UNKNOWN(B1)',
    '=missing_name', '=B1:B2', '=ROUND(B1:B2,2)', '={1,2}', '=@B1', '=B1#'])
def test_unresolved_dynamic_array_positional_and_implicit_formulas_reject(tmp_path, text):
    paths = fixture(tmp_path)
    for path in paths[:2]:
        patch_cell(path, 1, 'C1', formula=text)
    paths[2][-1].update(before=text, after=text+'+1')
    patch_cell(paths[1], 1, 'C1', formula=text+'+1')
    engine = OfflineIterativeEngine(); result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and result['root_impacts'] == [] and not engine.calls


def test_mixed_internal_external_range_is_explicitly_unsupported(tmp_path):
    paths = fixture(tmp_path, original={'A1': '=ROUND(SUM(A1:B1)/4,2)', 'B1': '=Inputs!B1'},
                    changed={'A1': '=ROUND(SUM(A1:B1)/3,2)', 'B1': '=Inputs!B1'})
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'explicit boundary mirror' in result['reason']


@pytest.mark.parametrize('kwargs', [{'max_dependency_cells': 1}, {'max_dependency_edges': 1},
    {'per_formula_reference_cells': 1}, {'max_island_cells': 1}, {'max_island_sheets': 1},
    {'max_dependency_cells': True}])
def test_no_bound_silently_truncates_graph_or_islands(tmp_path, kwargs):
    result = prove(tmp_path, fixture(tmp_path), **kwargs)
    assert result['passed'] is False and result['root_impacts'] == []
    assert result['actual_LO_started_count'] == 0


def test_original_nonroot_formula_and_primitive_cannot_change(tmp_path):
    paths = fixture(tmp_path)
    patch_cell(paths[1], 2, 'B1', cached=13)
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'definition differs' in result['reason']


def test_different_iteration_settings_are_not_silently_repaired(tmp_path):
    paths = fixture(tmp_path)
    def callback(name, raw):
        if name != 'xl/workbook.xml':
            return raw
        tree = ET.fromstring(raw)
        tree.find(NS + 'calcPr').set('iterateCount', '64')
        return ET.tostring(tree)
    rewrite(paths[1], callback)
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'calculation settings differ' in result['reason']


def add_array_definition(path, *, sheet_index=2, address='E30', text='=12'):
    def callback(name, raw):
        if name != f'xl/worksheets/sheet{sheet_index}.xml':
            return raw
        tree = ET.fromstring(raw); data = tree.find(NS + 'sheetData')
        row = ET.SubElement(data, NS + 'row', {'r': '30'})
        cell = ET.SubElement(row, NS + 'c', {'r': address})
        ET.SubElement(cell, NS + 'f', {'t': 'array', 'ref': address}).text = text[1:]
        ET.SubElement(cell, NS + 'v').text = '12'
        return ET.tostring(tree)
    rewrite(path, callback)


def test_unchanged_unrelated_array_object_is_not_treated_as_ordinary_formula_text(tmp_path):
    paths = fixture(tmp_path)
    for p in paths[:2]:
        add_array_definition(p)
    result = prove(tmp_path, paths)
    assert result['passed'] is True, result.get('reason')


def test_array_formula_in_dependency_closure_is_still_rejected(tmp_path):
    paths = fixture(tmp_path)
    for p in paths[:2]:
        add_array_definition(p)
        patch_cell(p, 1, 'C1', formula="=Inputs!E30*2")
    patch_cell(paths[1], 1, 'C1', formula="=Inputs!E30*3")
    paths[2][-1].update(before='=Inputs!E30*2', after='=Inputs!E30*3')
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'Array or nonordinary' in result['reason']


def test_implicit_intersection_in_unchanged_external_ancestor_is_rejected(tmp_path):
    paths = fixture(tmp_path)
    for p in paths[:2]:
        patch_cell(p, 1, 'C1', formula='=ROUND(Inputs!B1:B2,2)')
    # Make A1 depend on the external C1 ancestor while only A1 is edited.
    old, new = '=ROUND((B1+C1)/2,2)', '=ROUND((B1+C1)/3,2)'
    patch_cell(paths[0], 1, 'A1', formula=old)
    patch_cell(paths[1], 1, 'A1', formula=new)
    patch_cell(paths[1], 1, 'B1', formula=paths[2][1]['before'])
    paths = paths[0], paths[1], [{'sheet':'Model','cell':'A1','before':old,'after':new}]
    engine = OfflineIterativeEngine(); result = prove(tmp_path, paths, engine)
    assert result['passed'] is False and 'implicit-intersection' in result['reason']
    assert not engine.calls


def test_forged_periodic_cache_stability_is_not_a_fixed_point_proof(tmp_path):
    paths = fixture(tmp_path)
    def alias(call, raw, output):
        if 'fixed_point_residual' in output.name:
            return
        book = openpyxl.load_workbook(output)
        locations = [(i + 1, c.coordinate) for i, sheet in enumerate(book)
                     if sheet.title.startswith('__SCI_') for c in sheet._cells.values() if c.data_type == 'f']
        book.close()
        for index, address in locations:
            patch_cell(output, index, address, cached=99)
    result = prove(tmp_path, paths, OfflineIterativeEngine(alias))
    assert result['passed'] is False and result['root_impacts'] == []
    assert 'residual F(x) differs from x' in result['reason']
    assert result['actual_LO_execution_count'] == 3


def test_residual_rejects_subcent_equation_error_even_if_grading_is_unchanged(tmp_path):
    paths = fixture(tmp_path)
    def error(call, raw, output):
        if 'fixed_point_residual' in output.name:
            patch_cell(output, 3, 'A1', cached=4.801)
    result = prove(tmp_path, paths, OfflineIterativeEngine(error))
    assert result['passed'] is False and 'residual F(x) differs from x' in result['reason']


def test_source_bytes_are_bound_before_analysis_and_after_execution(tmp_path):
    paths = fixture(tmp_path)
    def change(call, raw, output):
        if call == 1:
            with paths[0].open('ab') as stream:
                stream.write(b'changed source bytes')
    result = prove(tmp_path, paths, OfflineIterativeEngine(change))
    assert result['passed'] is False and 'Source context changed' in result['reason']


@pytest.mark.parametrize('boundary', [None, True, 'text boundary', date(2024, 1, 1)])
def test_frozen_residual_rejects_unproven_blank_boolean_text_or_date_semantics(tmp_path, boundary):
    original = {'A1':'=ROUND((B1+Inputs!B1)/2,2)','B1':'=ROUND(A1/2,2)',
                'C1':'=A1*2+N(Inputs!E30)'}
    changed = {**original, 'C1':'=A1*3+N(Inputs!E30)'}
    paths = fixture(tmp_path, original=original, changed=changed, extra_inputs={'E30':boundary})
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'finite non-date numeric' in result['reason']
    assert result['actual_LO_execution_count'] == 2


def test_persisted_certificate_validator_binds_the_same_six_call_proof(tmp_path):
    paths = fixture(tmp_path); result = prove(tmp_path, paths)
    assert result['passed'] is True, result.get('reason')
    assert scc.validate_scc_island_root_certificate(result, *paths) == result['root_impacts']


@pytest.mark.parametrize('mutation', ['count', 'implementation', 'source', 'residual', 'global_claim',
    'sequence', 'artifact', 'root_active'])
def test_certificate_tampering_cannot_upgrade_missing_proof(tmp_path, mutation):
    paths = fixture(tmp_path); result = prove(tmp_path, paths)
    assert result['passed'] is True, result.get('reason')
    changed = deepcopy(result)
    if mutation == 'count':
        changed['actual_LO_execution_count'] = 4
    elif mutation == 'implementation':
        changed['implementation_sha256'] = '0'*64
    elif mutation == 'source':
        changed['goal_sha256'] = '0'*64
    elif mutation == 'residual':
        changed['contexts'][0]['fixed_point_residual']['all_SCC_members_exact_Fx_equal_x'] = False
    elif mutation == 'global_claim':
        changed['counterfactual_uniqueness_claimed'] = True
    elif mutation == 'sequence':
        changed['engine_calls'][2]['pass'] = 2
    elif mutation == 'artifact':
        with Path(changed['engine_calls'][0]['output_path']).open('ab') as stream:
            stream.write(b'altered artifact bytes')
    else:
        changed['root_checks'][0]['individual_active'] = False
    with pytest.raises(ValueError):
        scc.validate_scc_island_root_certificate(changed, *paths)


def test_implementation_change_during_execution_is_rejected_without_editing_real_code(tmp_path, monkeypatch):
    paths = fixture(tmp_path); real_sha = scc._sha; counts = {'implementation':0}
    def changing_hash(path):
        if Path(path) == Path(scc.__file__):
            counts['implementation'] += 1
            if counts['implementation'] >= 3:
                return '0' * 64
        return real_sha(path)
    monkeypatch.setattr(scc, '_sha', changing_hash)
    result = prove(tmp_path, paths)
    assert result['passed'] is False and 'implementation changed during proof' in result['reason']
