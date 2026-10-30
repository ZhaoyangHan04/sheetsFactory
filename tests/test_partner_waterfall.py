import copy
import json
from decimal import Decimal as D
from pathlib import Path
import importlib.util
import tempfile
import unittest
import openpyxl

from sheets_factory.workbook.partner_waterfall import allocate_year, initial_state, simulate, xirr, xnpv
from sheets_factory.workbook.partner_waterfall.contract import FINANCIAL_FIELDS, PROVIDED_STATE_FIELDS, PUBLIC_RULES


def policy(**patch):
    p = json.loads((Path(__file__).parents[1]/'config/derived_partner_waterfall_v1.json').read_text())
    p.update(opening_capital='100.00', preference_rate='.10', lp_xirr_hurdle='.01')
    p.update(patch)
    return p


class PartnerWaterfallTest(unittest.TestCase):
    def test_four_tiers_and_next_year_flip_have_hand_calculated_cash(self):
        p = policy(); old = initial_state(p); frozen = copy.deepcopy(old)
        out = allocate_year(p, old, 2024, '0', '150')
        r = out['annual']; self.assertEqual(old, frozen)
        # £9 LP pref; £90/£10 capital; £2.25 GP catch-up; remaining £38.75 split.
        self.assertEqual(r['lp_preference'], D('9.00'))
        self.assertEqual(r['lp_return_of_capital'], D('90.00'))
        self.assertEqual(r['gp_return_of_capital'], D('10.00'))
        self.assertEqual(r['gp_catchup'], D('2.25'))
        self.assertEqual(r['lp_residual'], D('31.00'))
        self.assertEqual(r['gp_residual'], D('7.75'))
        self.assertEqual(r['lp_distribution'], D('130.00'))
        self.assertEqual(r['gp_distribution'], D('20.00'))
        self.assertEqual(r['capital_distribution'], D('100.00'))
        self.assertEqual(r['profit_distribution'], D('50.00'))
        self.assertTrue(r['flip_earned']); self.assertEqual(r['carry_rate'], D('.2'))
        self.assertEqual(r['flip_effective_year'], 2025)
        next_out = allocate_year(p, out['state'], 2025, '0', '10')
        # Higher cumulative target creates £7.142857 catch-up on £40 LP/£10 GP profit.
        self.assertEqual(next_out['annual']['gp_catchup'], D('7.14'))
        self.assertEqual(next_out['annual']['gp_residual'], D('.86'))
        self.assertEqual(next_out['annual']['lp_residual'], D('2.00'))
        self.assertEqual(next_out['annual']['carry_rate'], D('.3'))
        self.assertTrue(all(out['checks'].values()))
        self.assertEqual(sum(sum(e['debit_positive_entries'].values()) for e in out['journal']), 0)
        self.assertNotIn('income', {k for e in out['journal'] for k in e['debit_positive_entries']})

    def test_unpaid_preference_does_not_compound_and_new_calls_do_not_accrue(self):
        p = policy(); a = allocate_year(p, initial_state(p), 2024, '100', '0')
        self.assertEqual(a['annual']['preference_accrual'], D('9'))
        self.assertEqual(a['annual']['preference_close'], D('9'))
        b = allocate_year(p, a['state'], 2025, '0', '5')
        self.assertEqual(b['annual']['preference_accrual'], D('18'))
        self.assertEqual(b['annual']['preference_close'], D('22'))
        self.assertEqual(b['annual']['capital_distribution'], 0)

    def test_partial_roc_rounds_partner_residual_and_cannot_overpay_capital(self):
        p = policy(opening_capital='.03', lp_capital_fraction='.5', preference_rate='0')
        a = allocate_year(p, initial_state(p), 2024, '0', '.02')
        self.assertEqual(a['annual']['lp_return_of_capital'], D('.01'))
        self.assertEqual(a['annual']['gp_return_of_capital'], D('.01'))
        b = allocate_year(p, a['state'], 2025, '0', '.01')
        self.assertEqual(b['annual']['lp_return_of_capital'], D('.01'))
        self.assertEqual(b['annual']['gp_return_of_capital'], 0)
        self.assertTrue(all(b['checks'].values()))

    def test_xirr_unique_actual_dates_and_ambiguous_cashflows_do_not_qualify(self):
        flows = [{'date': '2023-04-01', 'amount': '-100'}, {'date': '2024-03-31', 'amount': '110'}]
        self.assertLess(abs(xirr(flows)-D('.1')), D('1e-40'))  # exactly 365 elapsed days
        self.assertEqual(xnpv('.1', flows), 0)
        self.assertIsNone(xirr([*flows, {'date':'2025-03-31','amount':'-1'}]))
        self.assertIsNone(xirr([{'date':'2023-04-01','amount':'-1'}]))
        netted = [*flows, {'date':'2024-03-31','amount':'-10'}]
        self.assertLess(abs(xirr(netted)), D('1e-40'))
        self.assertRaises(ValueError, xnpv, '-1', flows)

    def test_capital_return_is_required_for_flip_and_subsequent_calls_do_not_unflip(self):
        p = policy(preference_rate='1', lp_xirr_hurdle='0')
        a = allocate_year(p, initial_state(p), 2024, '0', '100')
        self.assertGreater(a['annual']['lp_xirr'], 0)
        self.assertGreater(a['annual']['lp_capital_close'], 0)
        self.assertFalse(a['annual']['flip_earned'])
        p = policy(); a = allocate_year(p, initial_state(p), 2024, '0', '150')
        b = allocate_year(p, a['state'], 2025, '100', '0')
        self.assertEqual(b['annual']['carry_rate'], D('.3'))
        self.assertEqual(b['annual']['lp_sign_changes'], 2)
        self.assertIsNone(b['annual']['lp_xirr'])
        self.assertEqual(b['annual']['flip_effective_year'], 2025)

    def test_infeasible_inputs_and_calendar_replay_fail_without_silent_repair(self):
        p=policy(); s=initial_state(p)
        for capital,cash in [('-1','0'), ('0','.001'), ('NaN','0')]:
            with self.assertRaises(ValueError): allocate_year(p,s,2024,capital,cash)
        with self.assertRaises(ValueError): allocate_year(p,s,2025,0,0)
        bad=dict(p, unlisted_rule=1)
        with self.assertRaises(ValueError):initial_state(bad)
        with self.assertRaises(ValueError):simulate(p,[])

    def test_missing_actual_mechanisms_are_rejected_and_helper_fields_are_provided(self):
        p=policy(); inputs=[{'year':y,'capital_called':'0','distributable_cash':'0'} for y in p['years']]
        result=simulate(p,inputs,required_regimes=('gp_catchup','carry_flip_earned'))
        self.assertFalse(result['selected']);self.assertFalse(result['qualified'])
        self.assertEqual(result['missing_required_regimes'],['gp_catchup','carry_flip_earned'])
        self.assertEqual(result['task_count'],0)
        self.assertFalse(set(FINANCIAL_FIELDS)&set(PROVIDED_STATE_FIELDS))
        self.assertIn('NEXT FY',' '.join(PUBLIC_RULES))

    def test_parent_optional_route_preserves_default_and_financial_statements_balance(self):
        location=Path(__file__).with_name('test_holding_treasury.py')
        module_spec=importlib.util.spec_from_file_location('holding_fixture_for_partners',location)
        fixtures=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(fixtures)
        from sheets_factory.workbook.holding_treasury.ledger import simulate_parent
        args=fixtures.fixture()
        self.assertEqual(simulate_parent(*args),simulate_parent(*args,waterfall_spec=None))
        p=policy(opening_capital='10')
        result=simulate_parent(*args,waterfall_spec=p)
        self.assertTrue(all(result['checks'].values()))
        self.assertEqual(len(result['partner_waterfall']),20)
        for r,w,g in zip(result['annual'],result['partner_waterfall'],result['consolidated']):
            self.assertEqual(r['capital_close'],w['lp_capital_close']+w['gp_capital_close'])
            self.assertEqual(r['balance_check'],0);self.assertEqual(r['cash_check'],0)
            self.assertEqual(g['balance_check'],0);self.assertEqual(g['cash_check'],0)
            self.assertEqual(r['cash_close'],D(args[0]['parameters']['minimum_cash']))
            self.assertEqual(r['cff'],r['bank_draw']-r['mandatory_margin']-r['optional_repayment']+r['lp_capital']-w['total_distribution'])
        with self.assertRaisesRegex(ValueError,'opening contribution'):
            simulate_parent(*args,waterfall_spec=policy(opening_capital='11'))

    def test_excel_independent_binding_covers_every_formula_and_keeps_flags_provided(self):
        from sheets_factory.workbook.partner_waterfall.excel import emit_waterfall
        from sheets_factory.workbook.partner_waterfall.schema import FIELDS
        p=policy();book=openpyxl.Workbook();source=book.active;source.title='Provided funded cash'
        refs={}
        for i,y in enumerate(p['years'],2):
            source.cell(i,1,0);source.cell(i,2,150 if i==2 else 0)
            refs[y]={'capital_called':f"'Provided funded cash'!A{i}",
                     'distributable_cash':f"'Provided funded cash'!B{i}"}
        meta=emit_waterfall(book,p,refs)
        formula_set={(s.title,c.coordinate) for s in book for c in s._cells.values() if c.data_type=='f'}
        self.assertEqual(formula_set,{(b['sheet'],b['cell']) for b in meta['bindings']})
        self.assertEqual(len(meta['bindings']),20*len(FIELDS)+2)
        self.assertTrue(all(not b['target_eligible'] for b in meta['bindings'] if b['field'] in PROVIDED_STATE_FIELDS))
        import inspect
        from sheets_factory.workbook.partner_waterfall import excel
        self.assertNotIn('from .ledger',inspect.getsource(excel))
        self.assertNotIn('allocate_year(',inspect.getsource(excel))


if __name__=='__main__':unittest.main()
