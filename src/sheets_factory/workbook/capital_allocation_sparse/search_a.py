"""Prepare raw public inputs for sparse A; no optimizer runs on import.

The C++ forward is the entire frozen independent A translation unit. Safe integer
bound envelopes are derived from exact Fractions once. A native completed
partition is intermediate evidence until independently checked.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from . import bounds, spec

TEMPLATE = Path(__file__).resolve().parent.parent / 'capital_allocation_scaled/search_a.cpp'
TEMPLATE_SHA256 = 'f69ccd8846b3b7a53b3e0c9a26dadd0ee605a21ab47b1885ef25116caaa8180d'
KERNEL = Path(__file__).with_suffix('.cpp')


def reference(path):
    path=Path(path).absolute();data=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def assert_template():
    result=reference(TEMPLATE)
    spec.require(result['sha256']==TEMPLATE_SHA256,'The independent frozen A forward template changed')
    return result


def integer_envelope(public,branch_order=None):
    """Return conservative ceil objective/floor resource bounds, not a proof."""
    public=spec.load_spec(public);model=bounds.prepare_bounds(public)
    ids=tuple(model.project_ids)
    order=ids if branch_order is None else tuple(branch_order)
    spec.require(len(order)==len(ids) and set(order)==set(ids) and len(set(order))==len(ids),
                 'A complete unique public branch order is required')
    ceil=lambda x:-((-x.numerator)//x.denominator)
    floor=lambda x:x.numerator//x.denominator
    coefficients=[[ceil(model.coefficients[s][j]) for s in range(3)] for j in range(len(ids))]
    cuts=[{'id':c.id,'capacity':ceil(c.capacity),'weights':[floor(x) for x in c.weights]} for c in model.cuts]
    for number in [*[ceil(x) for x in model.constants],*[x for a in coefficients for x in a],
                   *[x for c in cuts for x in [c['capacity'],*c['weights']]]]:
        spec.require(type(number) is int and abs(number)<2**62,'A safe integer bound exceeds the audited signed64 envelope')
    # Native updates add at most N contributions. Require an absolute aggregate
    # bound instead of assuming an individual signed64 input cannot overflow.
    spec.require(all(abs(ceil(model.constants[s]))+sum(abs(coefficients[j][s]) for j in range(len(ids)))<2**62 for s in range(3))
                 and all(abs(c['capacity'])+sum(abs(x) for x in c['weights'])<2**62 for c in cuts),
                 'The complete conservative integer sums exceed their signed64 envelope')
    return {'kind':'public_derived_sparse_integer_bound_envelope','version':1,'binding':model.binding(),
        'branch_project_order':list(order),'constants':[ceil(x) for x in model.constants],
        'coefficients_by_project':coefficients,'necessary_cuts':cuts,
        'objective_rounding':'ceil each constant and coefficient',
        'necessary_cut_rounding':'floor weights and ceil capacity',
        'region_bounds_or_optimum_verified':False}


def _public_wire(public):
    rows=['CAPITAL_SPARSE_A_RAW_V1',str(len(public['projects']))]
    root=[public[k] for k in ('opening_cash_pence','minimum_cash_pence','lp_commitment_pence','facility_limit_pence',
                             'advance_rate_p12','tax_rate_p12','tax_loss_carry_years')]
    rows.append(' '.join(map(str,root)))
    annual=lambda a:' '.join(str(a[str(y)]) for y in spec.YEARS)
    rows.append(annual(public['discount_factors_p12']))
    for p in public['projects']:
        rows.append(' '.join(str(p[k]) for k in ('commission_year','sale_year','acquisition_cost_pence','depreciation_years','sale_proceeds_pence')))
        rows.extend(annual(p[k]) for k in ('annual_revenue_pence','annual_opex_pence'))
    for s in public['scenarios']:
        rows.extend(annual(s[k]) for k in ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12','bank_rates_p12','haircuts_p12'))
    return '\n'.join(rows)+'\n'


def _bound_wire(envelope):
    order=envelope['branch_project_order'];indices={key:i for i,key in enumerate(envelope['binding']['project_order'])}
    rows=['CAPITAL_SPARSE_SAFE_INTEGER_BOUNDS_V1',str(len(order)),
          ' '.join(str(indices[key]) for key in order),' '.join(map(str,envelope['constants']))]
    rows.extend(' '.join(map(str,a)) for a in envelope['coefficients_by_project'])
    rows.append(str(len(envelope['necessary_cuts'])))
    for cut in envelope['necessary_cuts']:
        rows.append(cut['id']+' '+str(cut['capacity'])+' '+' '.join(map(str,cut['weights'])))
    return '\n'.join(rows)+'\n'


def prepare_inputs(public,directory,*,branch_order=None):
    """Create a new private execution directory, never run/compile the kernel."""
    template=assert_template();public=spec.load_spec(public);directory=Path(directory).absolute()
    spec.require(not directory.exists(),'A fresh preparation directory is required')
    envelope=integer_envelope(public,branch_order)
    directory.mkdir(parents=True)
    files={'public.json':json.dumps(public,sort_keys=True,indent=2)+'\n',
           'public_a.txt':_public_wire(public),'safe_integer_bounds.json':json.dumps(envelope,sort_keys=True,indent=2)+'\n',
           'safe_integer_bounds.txt':_bound_wire(envelope)}
    for name,text in files.items():
        with (directory/name).open('x') as stream:stream.write(text)
    result={'kind':'prepared_sparse_capital_A_raw_execution','version':1,'public_spec_sha256':spec.canonical_sha(public),
        'project_count':len(public['projects']),'complete_plan_count':str(1<<len(public['projects'])),
        'branch_project_order':envelope['branch_project_order'],'raw_files':{name:reference(directory/name) for name in files},
        'implementation':reference(__file__),'native_kernel':reference(KERNEL),'frozen_financial_forward':template,
        'bounds_implementation':reference(bounds.__file__),'schema_implementation':reference(spec.__file__),
        'compiler_runs':0,'optimizer_runs':0,'model_calls':0,'LO_calls':0,'source_workbooks':0,
        'optimisation_or_unique_optimum_certified':False,'source_quality_or_difficulty_certified':False}
    with (directory/'preparation.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    return result


def read_partition_wire(path,project_count):
    """Stream the native intermediate wire, rejecting partial or malformed rows."""
    spec.project_ids(project_count)
    with Path(path).open() as stream:
        for line in stream:
            spec.require(line.endswith('\n'),'A partition record was truncated')
            fields=line[:-1].split('\t');kind=fields[0]
            spec.require(kind in ('I','B','L') and len(fields)==(7 if kind=='L' else 3),
                         'A complete typed intermediate partition record is required')
            prefix='' if fields[1]=='-' else fields[1]
            spec.require(len(prefix)<=project_count and all(c in '01' for c in prefix),'Invalid binary partition prefix')
            if kind=='L':
                spec.require(len(prefix)==project_count,'A native leaf must fix every project')
                spec.require(len(fields[2])==18 and fields[2].startswith('0x')
                             and all(c in '0123456789abcdef' for c in fields[2][2:]) and int(fields[2],16)<1<<project_count,
                             'A native leaf mask must be a canonical bounded string')
                spec.require(fields[3] in tuple(str(x) for x in range(8)),'Invalid scenario feasibility flags')
                for s,text in enumerate(fields[4:]):
                    if text=='null':spec.require(not(int(fields[3])&(1<<s)),'A feasible scenario lacks its NPV')
                    else:
                        spec.require(str(int(text))==text and bool(int(fields[3])&(1<<s)),'An NPV or its feasibility flag is invalid')
            elif kind=='B':spec.require(str(int(fields[2]))==fields[2],'A canonical safe integer upper bound is required')
            else:spec.require(fields[2] in {f'{s}.{y}.{k}' for s in spec.SCENARIO_IDS for y in spec.YEARS for k in ('facility','collateral')},'Unknown necessary-cut witness')
            yield {'prefix':prefix,'kind':{'L':'leaf','B':'bound','I':'infeasible'}[kind],
                   'evidence':{'intermediate_native_wire_fields':fields[2:],'semantic_validation_pending':True}}
