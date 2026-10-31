"""Independent sparse B raw preparation and intermediate partition reader.

No A helper, candidate flow or answer is imported. Both searches explicitly use
the shared public exact-bound policy. B's unmodified frozen financial forward
constructs its own raw candidate flows; its optimiser uses a bounded priority
queue and its proof pass an ordered stack. Preparation executes neither.
"""
import hashlib
import json
from pathlib import Path
import re

from . import bounds,spec

KERNEL=Path(__file__).with_suffix('.cpp')
TEMPLATE=Path(__file__).resolve().parent.parent/'capital_allocation_scaled/search_b.cpp'
TEMPLATE_SHA256='a2d3dd6ea5c94492fff1bc4ac28b26780612519aa0e1b1716fb1ab276157af01'


def reference(path):
    path=Path(path).absolute();spec.require(path==path.resolve() and path.is_file(),'B evidence must be a real nonsymlink file')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def assert_template():
    value=reference(TEMPLATE);spec.require(value['sha256']==TEMPLATE_SHA256,'The frozen independent B financial template changed');return value


def integer_envelope(public,branch_order=None):
    """Recompute safe integer public envelopes, without using A's serializer."""
    public=spec.load_spec(public);model=bounds.prepare_bounds(public);ids=list(model.project_ids)
    order=list(reversed(ids)) if branch_order is None else list(branch_order)
    spec.require(len(order)==len(ids) and all(type(x) is str for x in order) and len(set(order))==len(ids) and set(order)==set(ids),
                 'B requires a complete unique branch order')
    upward=lambda value:-((-value.numerator)//value.denominator)
    downward=lambda value:value.numerator//value.denominator
    constants=[upward(x) for x in model.constants]
    gains=[[upward(scenario[j]) for scenario in model.coefficients] for j in range(len(ids))]
    cuts=[{'id':row.id,'capacity':upward(row.capacity),'weights':[downward(x) for x in row.weights]} for row in model.cuts]
    spec.require(all(abs(constants[s])+sum(abs(gain[s]) for gain in gains)<1<<62 for s in range(3))
        and all(abs(row['capacity'])+sum(abs(x) for x in row['weights'])<1<<62 for row in cuts),
        'B complete integer bound sums exceed the audited signed envelope')
    return {'kind':'independently_serialized_B_public_integer_bound_envelope','version':1,'binding':model.binding(),
        'branch_project_order':order,'constants':constants,'coefficients_by_project':gains,'necessary_cuts':cuts,
        'objective_rounding':'ceil each constant and coefficient','necessary_cut_rounding':'floor weights and ceil capacity',
        'shared_public_exact_bound_policy':True,'A_helper_or_answer_used':False,'region_bounds_or_optimum_verified':False}


def _raw(public):
    rows=['CAPITAL_SPARSE_B_RAW_V1',str(len(public['projects']))]
    rows.append(' '.join(str(public[name]) for name in ('opening_cash_pence','minimum_cash_pence','lp_commitment_pence',
        'facility_limit_pence','advance_rate_p12','tax_rate_p12','tax_loss_carry_years')))
    def yearly(values):rows.append(' '.join(str(values[str(year)]) for year in spec.YEARS))
    yearly(public['discount_factors_p12'])
    for project in public['projects']:
        rows.append(' '.join(map(str,(project['commission_year']-2024,project['sale_year']-2024,
            project['acquisition_cost_pence'],project['depreciation_years'],project['sale_proceeds_pence']))))
        yearly(project['annual_revenue_pence']);yearly(project['annual_opex_pence'])
    for scenario in public['scenarios']:
        for name in ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12','bank_rates_p12','haircuts_p12'):yearly(scenario[name])
    return '\n'.join(rows)+'\n'


def _safe(envelope):
    ids=envelope['binding']['project_order'];positions={pid:index for index,pid in enumerate(ids)}
    rows=['CAPITAL_SPARSE_B_SAFE_BOUND_V1',str(len(ids)),
        ' '.join(str(positions[pid]) for pid in envelope['branch_project_order']),
        ' '.join(map(str,envelope['constants']))]
    rows.extend(' '.join(map(str,row)) for row in envelope['coefficients_by_project'])
    rows.append(str(len(envelope['necessary_cuts'])))
    for row in envelope['necessary_cuts']:rows.append(row['id']+' '+str(row['capacity'])+' '+' '.join(map(str,row['weights'])))
    return '\n'.join(rows)+'\n'


def prepare_inputs(public,directory,*,branch_order=None):
    """Freeze raw public inputs only. No compiler, search, ledger or subprocess."""
    template=assert_template();public=spec.load_spec(public);envelope=integer_envelope(public,branch_order)
    directory=Path(directory).absolute();spec.require(directory==directory.resolve() and not directory.exists(),'A fresh real B directory is required')
    directory.mkdir(parents=True)
    files={'public.json':json.dumps(public,sort_keys=True,indent=2)+'\n','public_b.txt':_raw(public),
        'safe_integer_bounds.json':json.dumps(envelope,sort_keys=True,indent=2)+'\n','safe_integer_bounds.txt':_safe(envelope)}
    for name,text in files.items():
        with (directory/name).open('x') as stream:stream.write(text)
    value={'kind':'prepared_sparse_capital_B_raw_execution','version':1,'project_count':len(public['projects']),
        'public_spec_sha256':spec.canonical_sha(public),'complete_plan_count':str(1<<len(public['projects'])),
        'branch_project_order':envelope['branch_project_order'],'raw_files':{name:reference(directory/name) for name in files},
        'implementation':reference(__file__),'native_kernel':reference(KERNEL),'frozen_financial_forward':template,
        'bounds_implementation':reference(bounds.__file__),'schema_implementation':reference(spec.__file__),
        'shared_public_exact_bound_policy':True,'A_helper_or_answer_used':False,
        'native_arguments':['public_b.txt','safe_integer_bounds.txt','PARTITION','SUMMARY','MAX_NODES','MAX_MS','MAX_FRONTIER'],
        'compiler_runs':0,'optimizer_runs':0,'model_calls':0,'LO_calls':0,'source_workbooks':0,
        'optimisation_or_unique_optimum_certified':False,'source_quality_or_difficulty_certified':False}
    with (directory/'preparation.json').open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
    return value


def read_partition_wire(path,project_count):
    """Parse B's shared intermediate protocol; no semantic certificate claim."""
    spec.project_ids(project_count)
    with Path(path).open() as stream:
        for line in stream:
            spec.require(line.endswith('\n'),'A B partition row is truncated')
            fields=line[:-1].split('\t');kind=fields[0]
            spec.require(kind in ('I','B','L') and len(fields)==(7 if kind=='L' else 3),'Malformed B partition row')
            prefix='' if fields[1]=='-' else fields[1]
            spec.require(len(prefix)<=project_count and all(c in '01' for c in prefix),'Invalid B partition prefix')
            if kind=='L':
                spec.require(len(prefix)==project_count and re.fullmatch(r'0x[0-9a-f]{16}',fields[2]) is not None
                    and int(fields[2],16)<1<<project_count,'The B leaf mask or full prefix is invalid')
                spec.require(fields[3] in tuple(map(str,range(8))),'Invalid B feasibility flags')
                for index,text in enumerate(fields[4:]):
                    feasible=bool(int(fields[3])&(1<<index))
                    spec.require((text=='null' and not feasible) or (feasible and re.fullmatch(r'0|-?[1-9][0-9]*',text) is not None),
                        'B scenario NPV and feasibility flag disagree')
            elif kind=='B':spec.require(re.fullmatch(r'0|-?[1-9][0-9]*',fields[2]) is not None,'Invalid B integer upper')
            else:spec.require(fields[2] in {f'{sid}.{year}.{kind}' for sid in spec.SCENARIO_IDS for year in spec.YEARS
                for kind in ('facility','collateral')},'Unknown B necessary-cut witness')
            yield {'prefix':prefix,'kind':{'I':'infeasible','B':'bound','L':'leaf'}[kind],
                'evidence':{'intermediate_native_wire_fields':fields[2:],'semantic_validation_pending':True}}
