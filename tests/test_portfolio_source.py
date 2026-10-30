"""Namespace, financial coverage and admission checks without LO or model calls."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('_portfolio_source_test',ROOT/'scripts/build_portfolio_source.py')
API=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)


def test_formula_tokens_preserve_strings_and_both_qualified_range_endpoints():
    mapping={'Scenario':'T01 Scenario','Calendar':'T01 Calendar',"Owner's note":"T01 Owner's note"}
    formula='=SUM(\'Scenario\'!$B$7:\'Scenario\'!$B$12)+IF("Scenario!A1"="x",Calendar!C2,\'Owner\'\'s note\'!D4)'
    result=API.rewrite_formula(formula,mapping)
    assert result=='=SUM(\'T01 Scenario\'!$B$7:\'T01 Scenario\'!$B$12)+IF("Scenario!A1"="x",\'T01 Calendar\'!C2,\'T01 Owner\'\'s note\'!D4)'
    assert API.rewrite_formula('=SUM(C2:D2)+$B$4',mapping)=='=SUM(C2:D2)+$B$4'


@pytest.mark.parametrize('formula',["='[old.xlsx]Scenario'!B2",'=Scenario:Calendar!C2',"='Unknown'!A1"])
def test_external_3d_and_unknown_sheet_references_are_rejected(formula):
    with pytest.raises(ValueError):API.rewrite_formula(formula,{'Scenario':'T01 Scenario','Calendar':'T01 Calendar'})


@pytest.fixture
def configs(tmp_path):
    catalog=json.loads((ROOT/'config/derived_advanced_tax_scenarios_v1.json').read_text())
    catalog['base_config']=str(ROOT/'config/derived_advanced_tax_brief_v1.json')
    cat=tmp_path/'catalog.json';cat.write_text(json.dumps(catalog))
    config=json.loads((ROOT/'config/derived_portfolio_v1.json').read_text())
    config.update(source_catalog=str(cat),base_config=catalog['base_config'],minimum_numeric_financial_formulas=0)
    config['entities']=config['entities'][:2]
    path=tmp_path/'portfolio.json';path.write_text(json.dumps(config))
    return path,config,catalog


@pytest.fixture
def prepared(configs,tmp_path):
    path,_,_=configs
    output=tmp_path/'prepared'
    return output,API.prepare_portfolio(ROOT,path,output)


def test_complete_prepared_portfolio_has_no_selected_or_cached_finance_claim(prepared):
    output,manifest=prepared
    assert manifest['status']=='prepared_pending_real_LO'
    assert manifest['selected']==[] and manifest['qualified'] is False and manifest['task_count']==0
    assert manifest['entity_count']==2 and manifest['sheet_count']==31
    assert manifest['formula_count']>13000 and manifest['numeric_financial_formula_count']>10000
    assert manifest['ancestor_unique_count']==1 and manifest['unique_workbooks_inspected']==0
    assert manifest['all_entity_ledgers_passed'] and manifest['all_required_mechanisms_observed']
    assert manifest['all_formula_cells_have_independent_expectations']
    assert manifest['group_checks']['group_balance_plug_used'] is False
    assert manifest['api_calls']==manifest['llm_tokens']==0
    expected=json.loads((output/'private/independent_expectations.json').read_text())
    formulas=json.loads((output/'private/formula_snapshot.json').read_text())
    assert not set(formulas)-set(expected)
    roots=json.loads((output/'private/financial_formula_roots.json').read_text())
    assert len(roots)==manifest['numeric_financial_formula_count']
    assert not any(any(name in address for name in ('Calendar!','Scenario!','Source Inputs!','Read Me!')) for address in roots)
    group=json.loads((output/'private/group_ledger.json').read_text())
    assert all(Decimal(value)==0 for row in group['monthly'] for key,value in row.items() if key.startswith('group_'))
    assert len({entry['case']['advanced_tax_patch'].get('interest_deduction_ebitda_fraction','.30') for entry in manifest['entities']})==2


def test_raw_namespace_retains_each_literal_and_exact_formulas_and_compressed_plans(prepared):
    output,manifest=prepared
    merged=openpyxl.load_workbook(manifest['raw_workbook']['path'])
    templates=json.loads((output/'private/reconstruction_templates.json').read_text())
    assert 'Portfolio Index' in merged and merged['Portfolio Index']['A13'].value=='T01'
    for entity in templates['entities']:
        original=openpyxl.load_workbook(entity['original_raw']['path'])
        for sheet in original:
            target=merged[entity['sheet_mapping'][sheet.title]]
            for cell in sheet._cells.values():
                want=API.rewrite_formula(cell.value,entity['sheet_mapping']) if cell.data_type=='f' else cell.value
                assert target[cell.coordinate].value==want
                assert target[cell.coordinate].number_format==cell.number_format
        plans=entity['financial_modeling_plan']
        assert plans['mask_ranges'] and len(plans['mask_ranges'])<=64
        assert all(region['sheet'].startswith(entity['entity_id']+' ') for region in plans['mask_ranges'])
        assert 'Calendar' not in [region['sheet'].split(' ',1)[1] for region in plans['mask_ranges']]
        assert entity['mapped_bindings']['monthly']['sales']['sheet']==entity['entity_id']+' Operations'
        original.close()
    assert templates['group_mask_ranges']
    assert all(not cell.is_date for region in templates['group_mask_ranges']
               for row in merged[region['sheet']][region['range']] for cell in row)
    merged.close()


def test_verify_rejects_changed_recipe_before_any_lo_call(prepared,monkeypatch):
    output,_=prepared
    path=output/'manifest.json'
    manifest=json.loads(path.read_text());manifest['recipe']['scripts/build_portfolio_source.py']['sha256']='0'*64
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(API,'LibreOfficeEngine',lambda *args:pytest.fail('LO must not be called for altered evidence'))
    with pytest.raises(ValueError,match='recipe changed'):API.verify_portfolio(ROOT,output)


def test_rejects_duplicate_economics_without_silent_parameter_changes(configs,tmp_path):
    path,config,_=configs
    config['entities']=[{'id':'T01','catalog_case':'T01'},{'id':'T02','catalog_case':'T01'}]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='Duplicate economic'):API.prepare_portfolio(ROOT,path,tmp_path/'duplicate')


def test_parent_or_intercompany_balances_require_a_different_supported_contract(configs,tmp_path):
    path,config,_=configs
    config['intercompany_transactions']=True;path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='no parent or intercompany'):API.prepare_portfolio(ROOT,path,tmp_path/'intercompany')


def test_missing_required_mechanism_rejects_without_downshifting_requirement(configs,tmp_path):
    path,config,catalog=configs
    catalog['cases'][0]['required_regimes'].append('payoff_followed_by_reserve_release')
    Path(config['source_catalog']).write_text(json.dumps(catalog))
    with pytest.raises(ValueError,match='Untriggered required'):API.prepare_portfolio(ROOT,path,tmp_path/'untriggered')


def test_cent_accuracy_and_type_semantics_are_preserved():
    assert API._matches(1.2300000000001,'1.23','money')
    assert not API._matches(1.235,'1.23','money')
    assert not API._matches(True,'1','money')
    assert not API._matches(float('nan'),'0','money')
    assert API._matches(2,'2','control') and not API._matches(2.01,'2','control')
