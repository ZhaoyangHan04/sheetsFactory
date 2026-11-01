from copy import deepcopy
from fractions import Fraction
import pytest
from sheets_factory.workbook.associate_bridge_v1 import spec
from sheets_factory.workbook.operating_reports_200 import schema as old


def toy(count=3):
    entities=[]
    for i in range(count):
        scale=(1,1000,1000000)[i%3];rate_scale=(1,Fraction(1,100),100)[i%3]
        def money(v):return spec._text(Fraction(str(v))/scale)
        entities.append({'id':f'E{i+1:03d}','name':f'Toy business {i+1}','division':'Advisory',
          'layout':'quarter_columns','line_order':'statement_first','money_unit':('GBP','GBP_thousands','GBP_millions')[i%3],
          'rate_unit':('percent_units','fraction','basis_points')[i%3],
          'statement_sign':'positive_deductions'if i%2==0 else'signed_contributions',
          'forecast_reference':'same_quarter_last_year','driver_form_by_year':{'2026':'level_multiple','2027':'level_multiple'},
          'opening':{k:money(v)for k,v in {'cash':10000,'investment':1000,'debt':100,'capital':10000,'retained_earnings':900}.items()},
          'actual_sales':{p:money(v)for p,v in zip(old.QUARTERS[:4],(100,110,120,130))},
          'forecast_sales':{p:'1.1'for p in old.QUARTERS[4:]},
          'direct_cost_rate':spec._text(Fraction(50)*rate_scale),
          'annual_interest_rate':spec._text(Fraction(8)*rate_scale),
          'parent_tax_rate':spec._text(Fraction(25)*rate_scale),
          'cash_opex':{p:money(10)for p in old.QUARTERS},
          'associate_results':{p:money(v)for p,v in zip(old.QUARTERS,[0]*4+[5,-3,7,-2]*2)}})
    return {'kind':old.KIND,'version':1,'seed':old.SEED,'dimension_mode':'toy','years':list(old.YEARS),
      'base_currency':'GBP','provenance':'new hypothetical service businesses; no official workbook seed',
      'public_policy':'Declared original toy business policies.','distribution':{'year':2027,'profit_percent':'20','cagr_percent':'8','q4_yoy_percent':'5'},
      'divisions':['Advisory'],'entities':entities}


def test_build_does_not_change_original_and_all_eight_policies_differ():
    base=toy();before=deepcopy(base);cases=[spec.build(base,c)for c in spec.CASE_IDS]
    assert base==before and all(c['base']==base for c in cases)
    assert len({spec.canonical_sha256(c['policies'])for c in cases})==8
    assert all(spec.validate(c)is c for c in cases)


def test_declared_case_axes_and_historical_zero():
    cases={c:spec.build(toy(),c)for c in spec.CASE_IDS}
    assert {p['method']for p in cases['B01']['policies'].values()}=={'equity'}
    assert {p['tax_class']for p in cases['B02']['policies'].values()}=={'exempt'}
    assert {p['method']for p in cases['B02']['policies'].values()}=={'equity','cost'}
    assert {p['tax_class']for p in cases['B03']['policies'].values()}==set(spec.TAX_CLASSES)
    for case in cases.values():
        for p in case['policies'].values():
            assert all(Fraction(p['share_postings'][q])==Fraction(p['cash_receipts'][q])==0 for q in old.QUARTERS[:4])
    assert any(k=='capital_return'for p in cases['B05']['policies'].values()for k in p['receipt_kind'].values())


def test_feed_scale_and_direction_reconstruct_supplied_profit_exactly():
    public=spec.build(toy(),'B04')
    for e in public['base']['entities']:
        p=public['policies'][e['id']];scale=spec.MONEY_SCALES[e['money_unit']]
        assert p['feed_scale']!=scale
        assert p['direction_by_year']['2026']!=p['direction_by_year']['2027']
        for q in old.QUARTERS:
            sign=-1 if p['direction_by_year'][q[:4]]=='charge_credit'else 1
            assert Fraction(p['share_postings'][q])*p['feed_scale']/scale*sign==Fraction(e['associate_results'][q])


@pytest.mark.parametrize('mutation',[
 lambda p:p['policies']['E001'].__setitem__('feed_scale',True),
 lambda p:p['policies']['E001']['share_postings'].__setitem__('2026Q1','123'),
 lambda p:p['policies']['E001'].__setitem__('tax_class','recognized'),
 lambda p:p['policies']['E001']['cash_receipts'].__setitem__('2025Q1','1'),
 lambda p:p['policies'].pop('E001'),lambda p:p.__setitem__('case_id','B09')])
def test_raw_or_case_assignment_changes_are_rejected(mutation):
    p=spec.build(toy(),'B01');mutation(p)
    with pytest.raises(ValueError):spec.validate(p)
