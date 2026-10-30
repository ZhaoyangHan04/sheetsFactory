import copy
import importlib.util
import json
from pathlib import Path
import unittest
from datetime import date
from decimal import Decimal as D
import openpyxl
from sheets_factory.workbook.holding_treasury.ledger import simulate_parent,operating_bridge
from sheets_factory.workbook.holding_treasury.excel import emit_parent,PUBLIC_RULES
from sheets_factory.workbook.holding_treasury.schema import PROGRAMME_FIELDS,SHEETS
from sheets_factory.workbook.holding_treasury.validate import audit_workbook,expected_cells


def fixture():
    spec={'years':list(range(2024,2044)),'parameters':{
      'opening_cash':'10','minimum_cash':'5','facility_limit':'1000','additional_lp_commitment':'1000',
      'rav_advance_rate':'.85','claim_advance_rate':'.8','operating_ownership':'.25','gbp_per_usd':'.8'},
      'annual_inputs':[{'year':y,'bank_rate':'.1','management_fee':'0','claim_haircut':'1' if y==2025 else '.25'}
                       for y in range(2024,2044)]}
    programme=[]
    for y in spec['years']:
        first=y==2024;second=y==2025;third=y==2026
        equity='95' if first else ('85' if second else '75')
        programme.append(dict(year=y,period_start=f'{y-1}-04-01',period_end=f'{y}-03-31',
          owner_capital='100' if first else '0',owner_distribution='20' if y<=2026 else '0',
          net_income='10' if y<=2026 else '0',asset_revaluation='5' if first else '0',
          total_assets='115' if first else ('105' if second else '95'),total_equity=equity,
          cash_close='0',closing_rav_nominal='80' if first else ('70' if second else '60'),
          claims_close='35',debt_close='20',lease_liability_close='0',cfo='10' if first else ('20' if y<=2026 else '0'),
          cfi='-110' if first else '0',cff='100' if first else ('-20' if y<=2026 else '0')))
    project={'monthly':[{'date':f'{2027+i//12}-{i%12+1:02d}-01','net_income':'4','dividend':'2'} for i in range(36)],
             'valuation':{'equity_exit':'200'}}
    public={'parameters':{'start_date':'2027-01-01','equity_paid_in':'100'}}
    return spec,programme,project,public


def workbook_fixture(spec,programme,project,public):
    book=openpyxl.Workbook();up=book.active;up.title='Programme Provided';op=book.create_sheet('Operating Provided')
    pr={}
    for yi,rec in enumerate(programme):
        r=yi+2;pr[rec['year']]={}
        for ci,field in enumerate(PROGRAMME_FIELDS,2):
            up.cell(r,ci,float(rec[field]));pr[rec['year']][field]=f"'Programme Provided'!${openpyxl.utils.get_column_letter(ci)}${r}"
    op['M1']=float(public['parameters']['equity_paid_in']);op['M2']=float(project['valuation']['equity_exit'])
    ore={'equity_paid_in':"'Operating Provided'!$M$1",'equity_exit':"'Operating Provided'!$M$2",'monthly':[]}
    for i,rec in enumerate(project['monthly']):
        r=i+2;op.cell(r,1,date.fromisoformat(rec['date']));op.cell(r,1).number_format='yyyy-mm-dd'
        op.cell(r,2,float(rec['net_income']));op.cell(r,3,float(rec['dividend']))
        ore['monthly'].append({'date':f"'Operating Provided'!$A${r}",'net_income':f"'Operating Provided'!$B${r}",
                               'dividend':f"'Operating Provided'!$C${r}"})
    meta=emit_parent(book,spec,pr,ore)
    return book,meta


class HoldingTreasuryTest(unittest.TestCase):
    def test_journal_and_consolidation_eliminate_internal_owner_flows(self):
        args=fixture();result=simulate_parent(*args)
        self.assertTrue(all(result['checks'].values()));self.assertEqual(len(result['annual']),20)
        for entry in result['journal']:self.assertEqual(sum(entry['debit_positive_entries'].values()),0)
        for parent,group,source in zip(result['annual'],result['consolidated'],args[1]):
            self.assertEqual(parent['programme_investment_close'],D(source['total_equity']))
            self.assertEqual(group['cash_check'],0);self.assertEqual(group['balance_check'],0)
            self.assertEqual(group['equity'],parent['equity'])
            self.assertEqual(group['net_income'],parent['net_income'])
            self.assertEqual(group['cfo'],parent['cfo']+D(source['cfo'])-D(source['owner_distribution']))
            self.assertEqual(group['cfi'],parent['cfi']+D(source['cfi'])+D(source['owner_capital']))
        self.assertGreater(result['annual'][-1]['programme_investment_close'],0)

    def test_native_calendar_and_posted_usd_then_gbp(self):
        args=fixture();b=operating_bridge(args[0],args[2],args[3]);counts={y:sum(r['fiscal_year']==y for r in b) for y in range(2027,2031)}
        self.assertEqual(counts,{2027:3,2028:12,2029:12,2030:9})
        result=simulate_parent(*args);by={r['year']:r for r in result['annual']}
        self.assertEqual(by[2027]['operating_acquisition'],D('20'))
        self.assertEqual(by[2030]['operating_sale'],D('40'))
        self.assertEqual(by[2030]['operating_sale_carrying'],D('34.4'))
        self.assertEqual(by[2030]['operating_sale_gain'],D('5.6'))
        args[2]['monthly'][0]['net_income']='.03';args[0]['parameters']['gbp_per_usd']='.5'
        b=operating_bridge(args[0],args[2],args[3]);self.assertEqual(b[0]['income_usd'],D('.01'));self.assertEqual(b[0]['income_gbp'],D('.01'))

    def test_margin_finite_lp_and_future_interest_are_path_dependent(self):
        args=fixture();result=simulate_parent(*args);r=result['annual']
        self.assertGreater(r[1]['mandatory_margin'],0)
        self.assertGreater(r[0]['lp_capital'],0)
        self.assertEqual(r[1]['bank_interest'],D('6.90'))
        self.assertEqual(r[1]['bank_close'],D('39.50'))
        alt=copy.deepcopy(args);alt[0]['annual_inputs'][1]['claim_haircut']='.25';other=simulate_parent(*alt)
        self.assertNotEqual(other['annual'][2]['bank_interest'],r[2]['bank_interest'])
        bad=copy.deepcopy(args);bad[0]['parameters']['additional_lp_commitment']='0'
        with self.assertRaisesRegex(ValueError,'Finite holding LP'):simulate_parent(*bad)

    def test_missing_financial_bridge_or_changed_calendar_is_rejected(self):
        args=fixture();args[1][0]['lease_liability_close']='1'
        with self.assertRaisesRegex(ValueError,'liabilities'):simulate_parent(*args)
        args=fixture();args[2]['monthly'][0]['date']='2027-02-01'
        with self.assertRaisesRegex(ValueError,'calendar'):simulate_parent(*args)
        args=fixture();args[1][0]['cfo']='11'
        with self.assertRaisesRegex(ValueError,'cash-flow'):simulate_parent(*args)

    def test_excel_covers_all_formulas_and_does_not_call_ledger(self):
        args=fixture();book,meta=workbook_fixture(*args)
        formulas={(s.title,c.coordinate) for s in book for c in s._cells.values() if c.data_type=='f'}
        bound={(b['sheet'],b['cell']) for b in meta['bindings']}
        self.assertEqual(formulas,bound);self.assertEqual(len(bound),2020)
        self.assertTrue(any('NA()' in c.value for s in book for c in s._cells.values() if c.data_type=='f'))
        self.assertIn('tax-transparent',PUBLIC_RULES[0]);self.assertIn('January 2027',PUBLIC_RULES[1])
        import inspect
        from sheets_factory.workbook.holding_treasury import excel
        self.assertNotIn('from .ledger',inspect.getsource(excel))
        self.assertNotIn('simulate_parent(',inspect.getsource(excel))

    def test_config_has_finite_declared_funding_and_all_calendar_inputs(self):
        path=Path(__file__).parents[1]/'config/derived_holding_treasury_v1.json'
        spec=json.loads(path.read_text());self.assertEqual(len(spec['annual_inputs']),20)
        self.assertGreater(D(spec['parameters']['additional_lp_commitment']),0)

    def test_uncalculated_formula_is_not_a_valid_result_and_public_input_edits_fail(self):
        import tempfile
        args=fixture();book,meta=workbook_fixture(*args);ledger=simulate_parent(*args)
        expected=expected_cells(ledger,meta['bindings']);self.assertEqual(len(expected),2020)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'raw.xlsx';book.save(path)
            report=audit_workbook(path,ledger,meta['bindings'],spec=args[0])
            self.assertFalse(report['passed']);self.assertEqual(len(report['mismatches']),2020)
            self.assertTrue(report['public_parameters_verified'])
            book[SHEETS['inputs']]['B7']='=0.85';book.save(path)
            report=audit_workbook(path,ledger,meta['bindings'],spec=args[0])
            self.assertFalse(report['public_parameters_verified']);self.assertEqual(len(report['control_mismatches']),1)


if __name__=='__main__':unittest.main()
