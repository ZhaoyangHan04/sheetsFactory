"""Extract public programme assumptions from the published, cached Ofgem model."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import hashlib
import json
import openpyxl
from .schema import ANNUAL_INPUT_FIELDS


def _d(value):return Decimal(str(value))
def _q(value,places=2):return value.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)


def apply_annual_overrides(annual, overrides):
    """Apply only explicitly dated hypothetical inputs, never forecast outputs."""
    if not isinstance(overrides, dict):
        raise ValueError('Annual overrides must be an explicit year-to-input mapping')
    years={str(row['year']) for row in annual}
    if any(not isinstance(year,str) or year not in years for year in overrides):
        raise ValueError('Annual overrides contain an unknown reporting year')
    result=[]
    for original in annual:
        row=dict(original);patch=overrides.get(str(row['year']),{})
        if not isinstance(patch,dict) or set(patch)-set(ANNUAL_INPUT_FIELDS):
            raise ValueError('Annual overrides may change only public annual inputs')
        for field,value in patch.items():
            if isinstance(value,bool) or not isinstance(value,(str,int)):
                raise ValueError('An explicit exact decimal annual override is required')
            amount=_d(value)
            if not amount.is_finite() or amount<0:
                raise ValueError('Annual overrides must be finite and nonnegative')
            if field=='price_index' and amount<=0:
                raise ValueError('The price index must be positive')
            if field=='tax_rate' and amount>=1:
                raise ValueError('The tax rate must be below one')
            if field in {'general_transfer_fraction','general_rate','special_rate'} and amount>1:
                raise ValueError('Tax pool fractions must not exceed one')
            if field in {'collection_cap_nominal','disallowance_real'} and amount!=_q(amount):
                raise ValueError('Annual cash limits and disallowances must be posted pennies')
            row[field]=str(amount)
        result.append(row)
    return result


def prepare_spec(source,config):
    source=Path(source)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!=config['source_sha256']:raise ValueError('Published baseline SHA mismatch')
    book=openpyxl.load_workbook(source,data_only=True,keep_links=False)
    try:
        years=list(range(config['first_year'],config['last_year']+1));batches=[];anchors=[]
        for year in range(2024,2029):
            column=year-1980
            for category in config['categories']:
                cell=book['Totex'].cell(category['source_row'],column)
                amount=_d(cell.value)
                cost=_q(amount*1_000_000*_d(category['share']))
                index=_q(_d(book['Annual Inflation'].cell(32,column).value),8)
                identity=str(year)+'-'+category['id']
                batches.append({'id':identity,'paid_year':year,'commission_year':year+category['commission_lag'],
                    'regulatory_life':category['regulatory_life'],'tax_pool':category['tax_pool'],
                    'real_cost':str(cost),'nominal_cost':str(_q(cost*index)),
                    'source_address':'Totex!'+cell.coordinate,'source_millions':str(amount),
                    'programme_share':category['share']})
                anchors.append({'address':'Totex!'+cell.coordinate,'value':str(amount),'unit':'GBP million 2020/21 prices'})
        last_index=_q(_d(book['Annual Inflation'].cell(32,48).value),8)
        prior_index=_q(_d(book['Annual Inflation'].cell(32,43).value),8)
        annual=[]
        for year in years:
            col=min(year,2028)-1980
            index=(_q(_d(book['Annual Inflation'].cell(32,col).value),8) if year<=2028 else
                   _q(last_index*(1+_d(config['long_run_inflation']))**(year-2028),8))
            real_wacc=(_q(_d(book['Return&RAV'].cell(12,col).value),12) if year<=2028 else _d(config['long_run_real_wacc']))
            revenue=_d(book['Revenue'].cell(22,col).value)*1_000_000
            annual.append({'year':year,'price_index':str(index),'real_wacc':str(real_wacc),
                'tax_rate':config['tax_rate_after'] if year>=config['tax_rate_change_year'] else config['tax_rate_before'],
                'claim_carry_rate':str(_q((1+real_wacc)*index/prior_index-1,12)),
                'debt_rate':config['debt_rate'],'collection_cap_nominal':str(_q(revenue*_d(config['incremental_tariff_fraction'])*index)),
                'disallowance_real':config['disallowance_real'] if year==config['disallowance_year'] else '0',
                'general_rate':config['general_rate'],'special_rate':config['special_rate'],
                'general_transfer_fraction':config['general_transfer_fraction'] if year==config['transfer_year'] else '0'})
            prior_index=index
        if 'annual_input_overrides' in config:
            annual=apply_annual_overrides(annual,config['annual_input_overrides'])
        return {'contract_version':1,'scenario_id':config['scenario_id'],'years':years,'batches':batches,
            'annual_inputs':annual,'parameters':{k:config[k] for k in ('gearing','loss_carry_years','loss_use_cap','claim_lag_years','structures_tax_life')},
            'source':{'path':str(source.resolve()),'sha256':digest,'official_url':config['official_url'],
                'selected_company':str(book['UserInterface']['E30'].value),'anchors':anchors}}
    finally:book.close()
