"""One prospective raw generation; this module never imports either oracle."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from . import schema

RESERVATIONS = schema.ROOT / 'outputs/private_waterfall_raw_reservations'
GENERATION_KIND = 'frozen_exogenous_waterfall_portfolios_raw_assumptions'


def _ref(path):
    p = Path(path).resolve(); data = p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def _write(path, value):
    with Path(path).open('x') as f:
        json.dump(value,f,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False); f.write('\n')
    return _ref(path)


def _draw(seed, fund_id, field, year, scenario, maximum):
    payload = f'{seed}|{fund_id}|{field}|{year}|{scenario}'.encode('ascii')
    return int.from_bytes(hashlib.sha256(payload).digest(),'big') % (maximum+1)


def _post(numerator, denominator=10000):
    # Private exogenous-input posting only, not shared financial oracle logic.
    assert type(numerator) is int and numerator >= 0 and denominator > 0
    return (2*numerator+denominator)//(2*denominator)


def build_spec(*, dimension_mode='production', fund_numbers=None, years=None, scenario_ids=None):
    """Build only exogenous assumptions. Production callers use freeze_spec once."""
    c = schema.contract(); seed = c['seed']
    if dimension_mode == 'production':
        schema.require(fund_numbers is years is scenario_ids is None,'Production dimensions and original seed are fixed')
        numbers, yy, scenarios = list(range(1,25)),list(schema.YEARS),list(schema.SCENARIOS)
    else:
        schema.require(dimension_mode=='toy','Declare an explicit toy')
        numbers=list(fund_numbers or [1]); yy=list(years or [2025,2026,2027,2028]); scenarios=list(scenario_ids or ['BASE'])
        schema.require(1<=len(numbers)<=4 and 1<=len(yy)<=4,'Keep mathematical toys small')
    public={'kind':schema.SPEC_KIND,'version':1,'dimension_mode':dimension_mode,'contract':_ref(schema.CONTRACT_PATH),
        'contract_sha256':schema.CONTRACT_SHA256,'seed':seed,'years':yy,
        'historical_years':[y for y in yy if y in schema.HISTORICAL_YEARS], 'scenario_ids':scenarios,'funds':[]}
    for i in numbers:
        schema.require(type(i) is int and 1<=i<=24,'Use a declared fund number')
        fid=f'F{i:03d}'; kind=schema.FUND_TYPES[(i-1)%4]
        commitment=100000000+1000000*_draw(seed,fid,'commitment_pence',0,'COMMON',1400)
        paid=_post(commitment*(2000+100*((i-1)%11)))
        opening_cash=_post(commitment*200)
        f={'id':fid,'number':i,'type':kind,'layout':schema.LAYOUTS[((i-1)//4)%4],
            'fund_ledger_sign':'signed_cash_uses' if i%2 else 'positive_deduction_uses',
            'lp1_share_bp':3500+500*((i-1)%6),'preferred_rate_bp':600+50*((i-1)%7),
            'compound_unpaid_preference':i%2==0,'base_gp_carry_bp':1000+500*((i-1)%3),
            'promote_gp_bp':[2000,3000,4000],'lp_distribution_multiple_threshold_bp':[12500,17500],
            'call_month':[1,4,7,10][(i-1)%4],'commitment_pence':commitment,
            'opening_cash_pence':opening_cash,'opening_investment_book_cost_pence':paid-opening_cash,
            'opening_unreturned_capital_pence':paid,'opening_unpaid_preference_pence':0,
            'opening_cumulative_lp_paid_in_pence':paid,'opening_cumulative_lp_distributions_pence':0,
            'opening_cumulative_lp_profit_pence':0,'opening_cumulative_gp_profit_pence':0,'scenarios':[]}
        for sid in scenarios:
            multiplier=c['identity_axes']['scenario_receipts_multiplier_bp'][sid]; periods=[]
            for year in yy:
                call=_post(commitment*c['raw_generation']['year_call_bp_of_commitment'].get(str(year),0))
                schedule=c['raw_generation']['realization_schedule_bp_of_commitment'][kind]
                realization_bp=(schedule['each_year_bp'] if schedule.get('start_year',0)<=year<=schedule.get('end_year',-1)
                                else schedule.get(str(year),0))
                operating_bp=80+_draw(seed,fid,'annual_operating_receipt_bp',year,sid,50)
                cost_bp=15+_draw(seed,fid,'annual_operating_cost_bp',year,sid,5)
                periods.append({'year':year,'call_date':f"{year}-{f['call_month']:02d}-01",'lp_call_pence':call,
                    'asset_investment_pence':_post(call*7000),
                    'operating_receipts_pence':_post(commitment*operating_bp*multiplier,10000**2),
                    'realization_receipts_pence':_post(commitment*realization_bp*multiplier,10000**2),
                    'management_fee_pence':_post(commitment*25),'operating_cost_pence':_post(commitment*cost_bp),
                    'reserve_pence':0 if year==2044 else _post(commitment*100)})
            f['scenarios'].append({'id':sid,'periods':periods})
        public['funds'].append(f)
    return schema.validate_spec(public)


def freeze_spec(output, *, dimension_mode='production', fund_numbers=None, years=None, scenario_ids=None):
    """Reserve the full logical raw identity before any numerical generation.

    The permanent private reservation survives failure and directory renaming.
    No forward or optimizer is imported, called, or used to select raw inputs.
    """
    output=Path(output).absolute()
    schema.require(not output.exists() and output==output.resolve(),'Use a fresh real raw output directory')
    c=schema.contract()
    axes={'dimension_mode':dimension_mode,'fund_numbers':fund_numbers,'years':years,'scenario_ids':scenario_ids}
    if dimension_mode=='production':
        schema.require(fund_numbers is years is scenario_ids is None,'Keep the full original raw pool')
        axes.update(fund_numbers=list(range(1,25)),years=list(schema.YEARS),scenario_ids=list(schema.SCENARIOS))
    else:
        schema.require(dimension_mode=='toy','Declare production or an explicit toy')
        axes.update(fund_numbers=list(fund_numbers or [1]),years=list(years or [2025,2026,2027,2028]),scenario_ids=list(scenario_ids or ['BASE']))
    recipe={str(p.resolve()):_ref(p) for p in [Path(__file__),Path(schema.__file__),Path(__file__).with_name('__init__.py'),schema.CONTRACT_PATH]}
    identity={'contract_sha256':schema.CONTRACT_SHA256,'seed':c['seed'],'axes':axes}
    roots=[f'F{i:03d}/{s}/{y}/after_preference_cash' for i in axes['fund_numbers'] for s in axes['scenario_ids'] for y in axes['years'] if y>=2027]
    prospective={'kind':'prospective_single_waterfall_raw_generation','version':1,'identity':identity,
        'logical_raw_identity':schema.canonical_sha256(identity),'output':str(output),'recipe':recipe,
        'raw_hash_recipe':'SHA256 UTF8 decimal(seed)|Fnnn|field|decimal(year)|scenario; whole SHA integer modulo(maximum+1). Commitment uses year0/scenarioCOMMON. Annual receipt/cost draws use their actual year and scenario. No oracle or research-file reads.',
        'declared_future_debug_roots':roots,'financial_forward_calls':0,'model_LO_solver_calls':0,
        'qualified':False,'created_at':datetime.now(timezone.utc).isoformat()}
    RESERVATIONS.mkdir(parents=True,exist_ok=True)
    reserved=RESERVATIONS/(prospective['logical_raw_identity']+'.json')
    # Exclusive create is deliberately before build_spec and no failed reservation is removed.
    _write(reserved,prospective)
    output.mkdir(parents=True)
    prospective_ref=_write(output/'prospective.json',prospective)
    try:
        kwargs={} if dimension_mode=='production' else {k:axes[k] for k in ('fund_numbers','years','scenario_ids')}
        public=build_spec(dimension_mode=dimension_mode,**kwargs)
        specification=_write(output/'specification.json',public)
        value={'kind':GENERATION_KIND,'version':1,'specification':specification,
            'specification_sha256':schema.canonical_sha256(public),'prospective':prospective_ref,'permanent_reservation':_ref(reserved),
            'recipe':recipe,'all_funds_retained':True,'no_oracle_or_selected_plan_inputs':True,'debug_root_count':len(roots),
            'financial_forward_calls':0,'model_LO_solver_calls':0,'qualified':False}
        return _write(output/'preparation.json',value)
    except BaseException as error:
        _write(output/'failure.json',{'kind':'failed_single_waterfall_raw_generation','error_type':type(error).__name__,
            'prospective':prospective_ref,'permanent_reservation':_ref(reserved),'qualified':False})
        raise
