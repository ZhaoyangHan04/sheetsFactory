#!/usr/bin/env python3
"""Review the new tax-vintage source with the frozen isolated-review lifecycle."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec

BASE = ROOT/'scripts/run_associate_bridge_shared_review.py'
BASE_SHA = '1d9b46db226014ecab53916ac1b5e5bd1d2a2e21dcaf07eb2a5ba9dd515af003'
SPEC_SHA = 'c62468e5a8ab4e2d0329a448599ad86097aa7d91f9f2a5c14c31c65d90f40857'
REPLACEMENTS = {
    'independently_verified_associate_bridge_business_source_v1':'independently_verified_tax_vintage_bridge_business_source_v2',
    'associate_bridge_business_spec_v1':'tax_vintage_bridge_business_spec_v2',
    'associate_bridge_values_v1':'tax_vintage_bridge_values_v2',
    'prepared_associate_bridge_shared_semantic_review':'prepared_tax_vintage_shared_semantic_review',
    'actual_associate_bridge_shared_semantic_review':'actual_tax_vintage_shared_semantic_review',
    'associate_bridge_shared_semantic_review':'tax_vintage_shared_semantic_review',
    'New associate bridge shared semantic review':'New tax vintage shared semantic review',
}


def guard():
    for file, wanted in ((BASE,BASE_SHA),(Path(spec.__file__),SPEC_SHA)):
        if hashlib.sha256(file.read_bytes()).hexdigest() != wanted:
            raise ValueError('A frozen review protocol or tax-vintage inventory changed')


def _namespace():
    guard(); tree = ast.parse(BASE.read_text(),filename=str(BASE)); counts = Counter()
    class Revision(ast.NodeTransformer):
        def visit_Constant(self,node):
            if isinstance(node.value,str) and node.value in REPLACEMENTS:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(REPLACEMENTS[node.value]),node)
            if type(node.value) is int and node.value == 93510:
                counts['scope'] += 1
                return ast.copy_location(ast.Constant(291000),node)
            return node
    tree = Revision().visit(tree)
    if counts != Counter({**{key:1 for key in REPLACEMENTS},'scope':3}):
        raise ValueError('The exact review revision seams changed: '+str(counts))
    namespace = {'__name__':'_tax_vintage_frozen_shared_review','__file__':__file__}
    exec(compile(ast.fix_missing_locations(tree),str(BASE),'exec'),namespace)
    return namespace


_N = _namespace()
_old_prompt = _N['prompt']


def prompt(mode,role):
    text = _old_prompt(mode,role).replace('93,510','291,000')
    return text+'\nThe new tax-vintage policy is authoritative from the first reported quarter. '+\
        'Review separate ordinary/investment loss pools, FIFO by origin and ID, last-eligible-quarter '+\
        'inclusion, current-quarter loss creation, term-effective caps and birth-locked expiry. '+\
        'Tax assessments retain their assessment-quarter payment lag after a term change. '+\
        'Check actual cash tax, closing payable, net income, cash and balance-sheet liabilities. '+\
        'Tax register and vintage fields are report outputs, not unrequested scratch work.\n'


_N['prompt'] = prompt


def prepare(batch_path,output):
    guard(); batch = _N['read'](batch_path); source = _N['read'](batch['source'])
    public = spec.validate(_N['read'](source['specification']))
    expected = set(dict(spec.points(public)))
    if len(expected) != 291000:
        raise ValueError('Review the complete production tax-vintage inventory')
    bindings = _N['read'](source['bindings'])['financial']
    if set(bindings) != expected:
        raise ValueError('The reviewed financial binding inventory is incomplete')
    for name in ('A','B'):
        result = _N['read'](source['independent_records'][name])
        if any(set(result[k]) != expected for k in ('economic_exact_values','raw_cell_exact_values','typed_2dp_values')):
            raise ValueError('An independent reviewed map has a different complete scope')
    prepared = _N['prepare'](batch_path,output)
    _N['write'](Path(output)/'tax_source_inventory_admission.json',{'kind':'complete_tax_vintage_review_scope',
        'prepared':prepared,'source':batch['source'],'full_fields':len(expected),
        'inventory_implementation':_N['ref'](spec.__file__),'frozen_review_base':_N['ref'](BASE)})
    return prepared


def run(prepared_path):
    guard(); prepared = _N['ref'](prepared_path)
    scope = _N['read'](Path(prepared_path).parent/'tax_source_inventory_admission.json')
    if scope['prepared'] != prepared or scope['frozen_review_base'] != _N['ref'](BASE):
        raise ValueError('The prepared tax review or frozen base changed')
    return _N['run'](prepared_path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',required=True,type=Path); parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--run',action='store_true'); args=parser.parse_args()
    prepared=prepare(args.batch,args.output)
    print(_N['json'].dumps({'prepared':prepared}),flush=True)
    if args.run:
        run(prepared['path'])


if __name__=='__main__':
    main()
