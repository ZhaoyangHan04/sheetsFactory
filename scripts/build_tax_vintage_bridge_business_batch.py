#!/usr/bin/env python3
"""Engineer new tax-vintage materials using the frozen full-source native protocol."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec, oracle_a, oracle_b, excel

BASE = ROOT/'scripts/build_associate_bridge_business_batch.py'
BASE_SHA = '96d222ae67e21c4b09bf23f4b13f24f73f0133a00fcc7c661509d00e69936dd4'
REPLACEMENTS = {
    'independently_verified_associate_bridge_business_source_v1': 'independently_verified_tax_vintage_bridge_business_source_v2',
    'frozen_associate_bridge_business_task_plans_v1': 'frozen_tax_vintage_bridge_business_task_plans_v2',
    'associate_bridge_business_revision': 'tax_vintage_bridge_business_revision',
    'bridge-': 'tax-vintage-',
    'Complete the historical and forecast management reports for these businesses using the supplied operating data and investment-accounting policies. Preserve the source inputs, nonapplicable fields and workbook layout.':
        'Complete the historical and forecast management reports using the supplied operating, investment and tax-vintage records. Preserve source inputs, nonapplicable fields and workbook layout.',
    'Audit and repair the management reports for these businesses. Apply the supplied operating assumptions and investment-accounting policies so the financial reports reconcile throughout. Preserve source inputs, nonapplicable fields and workbook layout.':
        'Audit and repair the management reports using the supplied operating, investment and tax-vintage records. Preserve source inputs, nonapplicable fields and workbook layout.',
}


def _namespace():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen native construction protocol changed')
    tree = ast.parse(BASE.read_text(), filename=str(BASE)); counts = Counter()
    class Revision(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in REPLACEMENTS:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(REPLACEMENTS[node.value]), node)
            if type(node.value) is int and node.value == 88676:
                counts['formula_count'] += 1
                return ast.copy_location(ast.Constant(286166), node)
            return node
    tree = Revision().visit(tree)
    if counts != Counter({**{name:1 for name in REPLACEMENTS}, 'formula_count':1}):
        raise ValueError('The exact native construction revision seams changed: '+str(counts))
    ns = {'__name__':'_tax_vintage_frozen_native_builder', '__file__':__file__}
    exec(compile(ast.fix_missing_locations(tree), str(BASE), 'exec'), ns)
    ns.update(spec=spec, oracle_a=oracle_a, oracle_b=oracle_b, excel=excel)
    return ns


def plan(public, bindings, definition, mode):
    variant = public['case_id']+('-FM' if mode == 'financial_modeling' else '-DBG')
    result = {'variant_id':variant, 'mode':mode, 'source_case':public['case_id'],
              'given_facts_and_policies_protected':True}
    if mode == 'financial_modeling':
        result['mask_points'] = sorted(definition['formulas'])
        return result
    from openpyxl.utils import quote_sheetname
    financial, facts = bindings['financial'], bindings['provided_facts']
    def cell(record):
        return quote_sheetname(record['sheet'])+'!'+record['cell']
    def r(identity, period, field):
        return cell(financial[identity+'/'+period+'/'+field])
    def f(identity, field):
        return cell(facts[identity+'/'+field])
    faults = {}
    def add(identity, period, field, wrong, family):
        b = financial[identity+'/'+period+'/'+field]; point = b['sheet']+'!'+b['cell']
        if '='+wrong != definition['formulas'][point]:
            faults[point] = {'semantic_key':identity+'/'+period+'/'+field, 'family':family,
                             'faulty_formula':'='+wrong}
    for i, entity in enumerate(public['bridge']['base']['entities']):
        identity = entity['id']; policy = public['tax_policies'][identity]
        lot_origins = {lot['lot_id']:lot['origin_index'] for lot in policy['opening_lots']}
        lot_origins.update({lot:int(lot[1:]) for lot in spec.LOT_IDS if lot.startswith('C')})
        display = tuple(reversed(spec.LOT_IDS[::2]))+tuple(reversed(spec.LOT_IDS[1::2]))
        family = (i+spec.CASE_IDS.index(public['case_id'])) % 3
        for q in range(4, 12):
            period = spec.QUARTERS[q]; term = excel._term(policy, q)
            if family == 2:
                at = q-term['cash_tax_lag']
                add(identity, period, 'cash_tax_paid', r(identity,spec.QUARTERS[at],'current_tax') if at >= 0 else '0', 'assessment_lag_replaced_by_current_lag')
                rate_scale = {'fraction':1, 'percent_units':100, 'basis_points':10000}[entity['rate_unit']]
                wrong = 'MAX(0,'+r(identity,period,'tax_ordinary_before_losses')+'+'+r(identity,period,'tax_investment_before_losses')+'-'+r(identity,period,'loss_ordinary_used')+'-'+r(identity,period,'loss_investment_used')+')*'+f(identity,'parent_tax_rate')+'/'+str(rate_scale)
                add(identity,period,'current_tax',wrong,'current_pool_cross_netting')
                continue
            for pool in spec.POOLS:
                ordering = display if family == 0 else sorted(spec.LOT_IDS,key=lambda lot:(lot_origins[lot],lot))
                previous = []
                for lot in ordering:
                    birth = lot_origins[lot]
                    if birth >= q:
                        continue
                    old = r(identity,spec.QUARTERS[q-1],'tax_lot_'+lot+'_'+pool+'_close')
                    if lot.startswith('O'):
                        expiry = f(identity,'tax_opening_'+lot+'_last_eligible_index')
                    else:
                        chosen = term if family == 1 else excel._term(policy,birth)
                        expiry = str(birth)+'+'+f(identity,'tax_term_'+str(chosen['effective_index'])+'_carry_quarters')
                    comparison = '<' if family == 1 else '<='
                    live = 'IF('+str(q)+comparison+expiry+','+old+',0)'
                    cap = 'MAX(0,'+r(identity,period,'tax_'+pool+'_before_losses')+')*'+f(identity,'tax_term_'+str(term['effective_index'])+'_'+pool+'_cap_bp')+'/10000'
                    remaining = cap+('-SUM('+','.join(previous)+')' if previous else '')
                    field = 'tax_lot_'+lot+'_'+pool+'_used'
                    add(identity,period,field,'MIN('+live+',MAX(0,'+remaining+'))',
                        'register_order_used_as_FIFO' if family == 0 else 'expiry_boundary_and_term_reaged')
                    previous.append(r(identity,period,field))
    result.update(faults=faults, injected_formula_count=len(faults), actual_primary_difference_pending=True)
    return result


_N = _namespace()
_N['plan'] = plan
_old_recipes = _N['recipes']
def recipes():
    return _old_recipes()+[_N['ref'](BASE)]
_N['recipes'] = recipes


def freeze_raw(bridge_manifest, output):
    """Freeze eight raw contracts before any production financial forward."""
    output = Path(output).absolute()
    if output.exists():
        raise ValueError('Use a fresh raw-cohort namespace')
    bridge_ref = _N['ref'](bridge_manifest); bridge = _N['read'](bridge_ref)
    cases = {c['case_id']:c for c in bridge['cases']}
    output.mkdir(parents=True)
    rows = []
    for case_id in spec.CASE_IDS:
        original = _N['read'](cases[spec.bridge_case(case_id)]['specification'])
        public = spec.build(original, case_id)
        rows.append({'case_id':case_id, 'specification':_N['write'](output/(case_id+'.json'), public),
                     'canonical_sha256':spec.canonical_sha256(public)})
    return _N['write'](output/'manifest.json', {'kind':'frozen_raw_tax_vintage_bridge_business_cases_v2',
        'created_at':datetime.now(timezone.utc).isoformat(), 'cases':rows, 'count':len(rows),
        'bridge_raw_cohort':bridge_ref, 'fixed_before_financial_oracle_and_model':True,
        'actual_financial_forwards':0, 'actual_LO_calls':0, 'actual_model_calls':0,
        'spec_implementation':_N['ref'](spec.__file__)})


def build(raw_manifest, case_id, output, *, port=0):
    return _N['build'](raw_manifest, case_id, output, port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command',required=True)
    p = sub.add_parser('freeze-raw'); p.add_argument('--bridge-manifest',required=True,type=Path); p.add_argument('--output',required=True,type=Path)
    p = sub.add_parser('build'); p.add_argument('--raw-manifest',required=True,type=Path); p.add_argument('--case',required=True,choices=spec.CASE_IDS); p.add_argument('--output',required=True,type=Path); p.add_argument('--port',default=0,type=int)
    args = parser.parse_args(argv)
    result = freeze_raw(args.bridge_manifest,args.output) if args.command == 'freeze-raw' else build(args.raw_manifest,args.case,args.output,port=args.port)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
