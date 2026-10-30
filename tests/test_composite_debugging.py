"""Offline semantic authoring checks; fixture caches are not engine proofs."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.composite_finance import debugging as dbg
from sheets_factory.workbook.lease_finance.contract import load_lease_spec, month_date
from sheets_factory.workbook.lease_finance.excel import emit_lease_workbook
from sheets_factory.workbook.lease_finance.ledger import simulate_lease

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def lease_draft():
    spec = load_lease_spec(ROOT / 'config/derived_lease_contract_v1.json')
    ledger = simulate_lease(spec)
    book = openpyxl.Workbook()
    book.remove(book.active)
    bindings = emit_lease_workbook(spec, workbook=book)
    cached = openpyxl.Workbook()
    cached.remove(cached.active)
    for sheet in book:
        other = cached.create_sheet(sheet.title)
        for cell in sheet._cells.values():
            if cell.data_type != 'f':
                other[cell.coordinate] = cell.value
    for binding in bindings['cell_bindings']:
        source = binding['source']
        if source[0] == 'lease_monthly':
            _, identity, period, field = source
            value = ledger['lease_monthly'][identity][period-1][field]
        elif source[0] == 'monthly':
            _, period, field = source
            value = ledger['monthly'][period-1][field]
        elif source[0] == 'annual':
            _, year, field = source
            value = ledger['annual'][year][field]
        elif source[0] == 'calendar_date':
            value = datetime.combine(month_date(spec['start_date'], source[1]), datetime.min.time())
        elif source[0] == 'calendar_year':
            when = month_date(spec['start_date'], source[1])
            value = when.year + int(when.month >= 4)
        elif source[0] == 'period':
            value = source[1]
        cached[binding['sheet']][binding['cell']] = float(value) if isinstance(value, Decimal) else value
    draft = dbg._Draft(book, cached)
    dbg._lease_defects(draft, spec)
    yield draft
    book.close()
    cached.close()


def test_real_lease_contract_events_have_unique_asserted_economic_roots(lease_draft):
    edits = lease_draft.edits
    assert len(edits) > 100
    assert len({(edit['sheet'], edit['cell']) for edit in edits}) == len(edits)
    for edit in edits:
        assert lease_draft.book[edit['sheet']][edit['cell']].value == edit['before']
        assert edit['after'].startswith('=') and edit['after'] != edit['before']
        assert not lease_draft.book[edit['sheet']][edit['cell']].is_date
        assert not edit['sheet'].endswith(('Inputs', 'Events', 'Calendar', 'Read Me'))
        evidence = edit['private_expected_activity']
        assert evidence['normalized_local_change_expected']
        assert evidence['individual_and_combined_marginal_engine_proof_required']
        assert dbg._q(Decimal(evidence['cached_original_value'])) != dbg._q(Decimal(evidence['local_counterfactual_value']))


def test_lease_defects_are_distinct_timing_stock_cash_and_terminal_mechanisms(lease_draft):
    mechanisms = {edit['mechanism'] for edit in lease_draft.edits}
    assert {'lease_payment_timing', 'lease_direct_cost_classification',
            'lease_event_interest_basis', 'lease_retained_vs_surrendered',
            'lease_termination_fee_sign', 'lease_periodic_vs_monthly_rent',
            'lease_per_review_index_bound', 'lease_terminal_penny_settlement',
            'lease_terminal_rou_settlement', 'lease_cash_vs_book_tax_interface'} <= mechanisms
    partial = [edit for edit in lease_draft.edits if edit['mechanism'] == 'lease_retained_vs_surrendered']
    assert len(partial) == 2
    assert all(edit['event_context']['global_month'] == 55 for edit in partial)
    assert all('(1-' in edit['after'] for edit in partial)
    bounded = [edit for edit in lease_draft.edits if edit['mechanism'] == 'lease_per_review_index_bound']
    assert {(edit['event_context']['lease_id'], edit['event_context']['global_month']) for edit in bounded} == {('P01',37),('P01',49),('P01',109)}


def test_termination_fee_defects_preserve_signed_pnl_context(lease_draft):
    edits = [edit for edit in lease_draft.edits if edit['mechanism'] == 'lease_termination_fee_sign']
    assert len(edits) == 2
    by_month = {edit['event_context']['global_month']: edit for edit in edits}
    for month, fee in [(55, Decimal(60000)), (103, Decimal(125000))]:
        proof = by_month[month]['private_expected_activity']
        assert Decimal(proof['local_counterfactual_value']) - Decimal(proof['cached_original_value']) == fee


def test_small_rate_or_penny_inactive_roots_are_screened_without_claiming_engine_proof():
    book, cached = openpyxl.Workbook(), openpyxl.Workbook()
    for target in (book.active, cached.active):
        target.title='Financial'
        target['A3']='amount'
    book.active['C3']='=1/1000'
    cached.active['C3']=.001
    draft=dbg._Draft(book,cached)
    draft.add('Financial','amount',3,'=2/1000',Decimal('.002'),'rate','A policy.',{})
    assert draft.edits == []
    draft.add('Financial','amount',3,'=1',Decimal(1),'money','A policy.',{})
    assert len(draft.edits)==1
    assert 'not_engine_execution' in draft.edits[0]['private_expected_activity']['method']
    book.close();cached.close()


def test_date_formula_is_rejected_even_if_a_numeric_prediction_is_supplied():
    book,cached=openpyxl.Workbook(),openpyxl.Workbook()
    for target in (book.active,cached.active):target.title='Financial';target['A3']='date'
    book.active['C3']='=DATE(2027,1,1)'
    cached.active['C3']=datetime(2027,1,1)
    draft=dbg._Draft(book,cached)
    with pytest.raises(ValueError,match='public date'):
        draft.add('Financial','date',3,'=DATE(2028,1,1)',Decimal(1),'date','Policy',{})
    book.close();cached.close()


def _graph_source(tmp_path, formulas):
    book=openpyxl.Workbook();book.active.title='Model'
    book.create_sheet('Inputs')['B1']=100
    for address,formula in formulas.items():book['Model'][address]=formula
    path=tmp_path/'graph.xlsx';book.save(path);book.close()
    return path


def _edits(formulas, changes):
    return [{'sheet':'Model','cell':address,'before':formulas[address],'after':after}
            for address,after in changes.items()]


def test_grouping_proves_no_intra_batch_ancestry_and_keeps_cross_batch_conflicts(tmp_path):
    formulas={'A1':'=Inputs!B1','B1':'=A1*2','C1':'=Inputs!B1*3','D1':'=B1+C1'}
    path=_graph_source(tmp_path,formulas)
    edits=_edits(formulas,{'A1':'=Inputs!B1/2','B1':'=A1/2','C1':'=Inputs!B1/3','D1':'=B1-C1'})
    original=path.read_bytes()
    proof=dbg.suggest_root_impact_batches(path,edits)
    assert proof['planning_only'] and not proof['actual_root_impact_certified']
    assert sorted(index for batch in proof['root_impact_batches'] for index in batch)==list(range(4))
    assert {tuple(pair) for pair in proof['conflict_pairs']} == {(0,1),(0,3),(1,3),(2,3)}
    for batch in proof['root_impact_batches']:
        assert all([left,right] not in proof['conflict_pairs'] for left in batch for right in batch if left<right)
    assert proof['batch_count']==3
    assert path.read_bytes()==original


def test_grouping_includes_dependencies_created_only_by_mutation(tmp_path):
    formulas={'A1':'=Inputs!B1','B1':'=Inputs!B1*2'}
    path=_graph_source(tmp_path,formulas)
    proof=dbg.suggest_root_impact_batches(path,_edits(formulas,{'A1':'=Inputs!B1/2','B1':'=A1*2'}))
    assert proof['conflict_pairs']==[[0,1]] and proof['batch_count']==2


@pytest.mark.parametrize('after,message', [('=B1','Cycle'),('=INDIRECT("B1")','Unresolved')])
def test_grouping_rejects_cycles_and_unresolved_paths(tmp_path,after,message):
    formulas={'A1':'=Inputs!B1','B1':'=A1'}
    path=_graph_source(tmp_path,formulas)
    with pytest.raises(ValueError,match=message):
        dbg.suggest_root_impact_batches(path,_edits(formulas,{'A1':after}))


def test_grouping_is_iterative_for_long_chains_and_enforces_coverage_bound(tmp_path):
    formulas={'A1':'=Inputs!B1',**{f'A{i}':f'=A{i-1}*2' for i in range(2,1502)}}
    path=_graph_source(tmp_path,formulas)
    edits=_edits(formulas,{'A1':'=Inputs!B1/2','A1501':'=A1500/2'})
    assert dbg.suggest_root_impact_batches(path,edits,max_dependency_cells=2000)['batch_count']==2
    with pytest.raises(ValueError,match='cell bound'):
        dbg.suggest_root_impact_batches(path,edits,max_dependency_cells=1000)


def test_grouping_rejects_changed_before_assertion_duplicate_and_edge_limits(tmp_path):
    formulas={'A1':'=Inputs!B1','B1':'=A1'};path=_graph_source(tmp_path,formulas)
    edits=_edits(formulas,{'A1':'=Inputs!B1/2','B1':'=A1/2'})
    changed=deepcopy(edits);changed[0]['before']='=9'
    with pytest.raises(ValueError,match='before assertion'):dbg.suggest_root_impact_batches(path,changed)
    with pytest.raises(ValueError,match='Duplicate'):dbg.suggest_root_impact_batches(path,[edits[0],edits[0]])
    with pytest.raises(ValueError,match='edge bound'):dbg.suggest_root_impact_batches(path,edits,max_dependency_edges=1)


def _orchestration_fixture(tmp_path,monkeypatch):
    book=openpyxl.Workbook();book.active.title='Inputs';book.active['B1']=100
    cached=openpyxl.Workbook();cached.active.title='Inputs';cached.active['B1']=100
    contracts={'lease':{},'programme':{},'operating':{},'holding':{}}
    public=book.create_sheet('Model Input Contracts')
    for row,(key,value) in enumerate(contracts.items(),4):public.cell(row,1,key);public.cell(row,2,json.dumps(value))
    for name in ('Lease Read Me','Reopener Brief','Operating Read Me','Holding Brief'):
        book.create_sheet(name)['A3']='The explicit hypothetical business policies preserve all provided inputs, periods and original module contracts.'
    for name in ('Lease Test','Programme Test','Holding Test'):
        sheet=book.create_sheet(name);cache=cached.create_sheet(name)
        for row in range(3,53):
            sheet.cell(row,1,f'financial {row}');cache.cell(row,1,f'financial {row}')
            sheet.cell(row,3,f'=Inputs!B1*{row}');cache.cell(row,3,100*row)
    path=tmp_path/'source.xlsx';cache_path=tmp_path/'fixture_cached.xlsx'
    book.save(path);cached.save(cache_path);book.close();cached.close()
    original_load=openpyxl.load_workbook
    def load(path_arg,**kwargs):
        return original_load(cache_path if kwargs.get('data_only') and Path(path_arg)==path else path_arg,**kwargs)
    monkeypatch.setattr(dbg.openpyxl,'load_workbook',load)
    def populate(name,module):
        def execute(draft,*args):
            for row in range(3,53):
                draft.add(name,f'financial {row}',3,f'=Inputs!B1*{row}/2',Decimal(100*row)/2,
                          module+'_policy', 'Apply the supplied business policy.',{'module':module,'period':row})
        return execute
    monkeypatch.setattr(dbg,'_lease_defects',populate('Lease Test','lease'))
    monkeypatch.setattr(dbg,'_regulatory_defects',populate('Programme Test','programme'))
    monkeypatch.setattr(dbg,'_holding_defects',populate('Holding Test','holding'))
    return path


def test_proposal_schema_diverse_budget_no_public_answers_and_source_immutability(tmp_path,monkeypatch):
    path=_orchestration_fixture(tmp_path,monkeypatch);original=hashlib.sha256(path.read_bytes()).hexdigest()
    full=dbg.propose_task(path);limited=dbg.propose_task(path,max_roots=100)
    assert len(full['edits'])==150 and len(limited['edits'])==100
    assert {edit['event_context']['module'] for edit in limited['edits']}=={'lease','programme','holding'}
    assert full['scenario_inputs']==[] and 'mask_ranges' not in full
    assert len({(edit['sheet'],edit['cell']) for edit in full['edits']})==150
    assert isinstance(full['public_rules'],list) and len(full['public_rules'])==1
    assert 60<=len(full['public_instruction'].split())<=100
    assert not any(term in full['public_instruction'] for term in ('C3','=Inputs','counterfactual','225','/workspace/'))
    assert full['semantic_authoring_receipt']['actual_root_impact_certified'] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest()==original
    assert dbg.propose_task(path,max_roots=100)['edits']==limited['edits']


@pytest.mark.parametrize('maximum',[99,301,True,'200'])
def test_invalid_requested_root_budgets_reject_before_file_access(maximum):
    with pytest.raises(ValueError,match='max_roots'):dbg.propose_task('absent.xlsx',max_roots=maximum)


def test_unimplemented_mode_and_missing_contract_are_rejected(tmp_path):
    with pytest.raises(ValueError,match='debugging only'):dbg.propose_task('absent.xlsx',mode='financial_modeling')
    book=openpyxl.Workbook();path=tmp_path/'plain.xlsx';book.save(path);book.close()
    with pytest.raises(ValueError,match='public input contracts'):dbg.propose_task(path)
