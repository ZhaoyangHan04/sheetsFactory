"""Independent chronological Decimal posting ledger for the frozen contract."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from . import schema

D = Decimal


class _Safety:
    def __init__(self): self.maximum=0; self.witness=''; self.checked=0

    def mark(self, value, label):
        value=D(value)
        schema.require(value.is_finite() and value==value.to_integral_value(),'An integer posting intermediate was lost: '+label)
        integer=int(value); self.checked+=1
        schema.require(abs(integer)<schema.INTEGER_LIMIT,'An exact financial integer reaches 2**53: '+label)
        if abs(integer)>self.maximum: self.maximum=abs(integer); self.witness=label
        return value

    def add(self, *values, label='sum'): return self.mark(sum(values,D(0)),label)
    def sub(self, a, b, label='difference'): return self.mark(a-b,label)
    def mul(self, a, b, label='product'): return self.mark(a*b,label)

    def post(self, numerator, denominator, label):
        n=self.mark(numerator,label+'/numerator'); d=self.mark(denominator,label+'/denominator')
        schema.require(d>0,'A posting denominator must be positive')
        return self.mark((n/d).quantize(D(1),rounding=ROUND_HALF_UP),label+'/posted')


def _tier(cash, lp_gap, gp_bp, safety):
    """Decimal closed-form largest penny satisfying the capped LP threshold.

    Round-half-up(C*LP/10000)<=gap iff 2*C*LP < (2*gap+1)*10000.
    This independent strict endpoint is not a search through another oracle.
    """
    s=safety; cash=s.mark(cash,'tier/cash'); gap=s.mark(lp_gap,'tier/gap')
    lp_bp=s.sub(D(10000),D(gp_bp),'tier/lp_bp')
    schema.require(cash>=0 and gap>=0 and lp_bp>0,'Invalid promote-tier quantities')
    if gap==0 or cash==0:return D(0),D(0),D(0)
    strict_bound=s.mul(s.add(s.mul(D(2),gap),D(1)),D(10000),'tier/strict_numerator')
    numerator=s.sub(strict_bound,D(1),'tier/inclusive_integer_bound')
    denominator=s.mul(D(2),lp_bp,'tier/endpoint_denominator')
    endpoint=s.mark((numerator/denominator).to_integral_value(rounding=ROUND_FLOOR),'tier/maximum_cash')
    paid=min(cash,endpoint)
    lp=s.post(s.mul(paid,lp_bp,'tier/lp_product'),D(10000),'tier/lp_payment')
    gp=s.sub(paid,lp,'tier/gp_balancing_payment')
    schema.require(lp<=gap and gp>=0,'A capped tier overpaid its LP threshold')
    return paid,lp,gp


def solve(public):
    public=schema.validate_spec(public)
    rows={}; aggregates={}; order=[]; s=_Safety(); faults=[]
    states={name:0 for name in ('historical_zero_preference','capital_shortfall','preference_accrues','preference_paid',
                               'catchup_paid','tier1_active','tier2_active','tier3_active')}
    with localcontext() as context:
        context.prec=60
        for f in public['funds']:
            # This source's opening balances explicitly separate returned capital and profit.
            initial={k:s.mark(v,f['id']+'/'+k) for k,v in f.items() if k.endswith('_pence')}
            schema.require(initial['opening_cumulative_lp_distributions_pence']>=initial['opening_cumulative_lp_profit_pence'],
                           'Opening LP profit cannot exceed opening LP distributions')
            previously_returned=s.sub(initial['opening_cumulative_lp_distributions_pence'],initial['opening_cumulative_lp_profit_pence'])
            schema.require(initial['opening_unreturned_capital_pence']==s.sub(initial['opening_cumulative_lp_paid_in_pence'],previously_returned),
                           'Opening contributed and unreturned capital do not reconcile')
            for scenario in f['scenarios']:
                cash=initial['opening_cash_pence']; capital=initial['opening_unreturned_capital_pence']
                unpaid=initial['opening_unpaid_preference_pence']; paidin=initial['opening_cumulative_lp_paid_in_pence']
                lp_cash=initial['opening_cumulative_lp_distributions_pence']; lp_profit=initial['opening_cumulative_lp_profit_pence']
                gp_profit=initial['opening_cumulative_gp_profit_pence']
                for period in scenario['periods']:
                    key=f"{f['id']}/{scenario['id']}/{period['year']}"; order.append(key)
                    r={name:s.mark(period[name+'_pence'],key+'/'+name) for name in
                       ('lp_call','asset_investment','operating_receipts','realization_receipts','management_fee','operating_cost','reserve')}
                    r.update(opening_cash=cash,opening_unreturned_capital=capital,opening_unpaid_preference=unpaid)
                    r['cumulative_lp_paid_in']=s.add(paidin,r['lp_call'],label=key+'/cumulative_paidin')
                    incoming=s.add(cash,r['lp_call'],r['operating_receipts'],r['realization_receipts'],label=key+'/cash_in')
                    outgoing=s.add(r['asset_investment'],r['management_fee'],r['operating_cost'],label=key+'/cash_out')
                    r['cash_before_distribution']=s.sub(incoming,outgoing,key+'/cash_before_distribution')
                    schema.require(r['cash_before_distribution']>=0,'Negative unfunded fund cash: '+key)
                    r['available_cash']=max(D(0),s.sub(r['cash_before_distribution'],r['reserve']))
                    year=period['year']; finish=date(year+1,1,1)
                    full_days=D((finish-date(year,1,1)).days); call_days=D((finish-date.fromisoformat(period['call_date'])).days)
                    base=s.add(s.mul(capital,full_days,key+'/opening_capital_days'),
                               s.mul(r['lp_call'],call_days,key+'/call_capital_days'),label=key+'/capital_days')
                    if f['compound_unpaid_preference']:
                        base=s.add(base,s.mul(unpaid,full_days,key+'/opening_unpaid_days'),label=key+'/compounded_base_days')
                    rate=D(0 if year in public['historical_years'] else f['preferred_rate_bp'])
                    r['preference_accrual']=s.post(s.mul(rate,base,key+'/preference_rate_days'),D(3650000),key+'/preference_accrual')
                    r['capital_entitlement']=s.add(capital,r['lp_call'],label=key+'/capital_entitlement')
                    r['preference_entitlement']=s.add(unpaid,r['preference_accrual'],label=key+'/preference_entitlement')
                    r['capital_paid']=min(r['available_cash'],r['capital_entitlement'])
                    r['after_capital_cash']=s.sub(r['available_cash'],r['capital_paid'])
                    r['preference_paid']=min(r['after_capital_cash'],r['preference_entitlement'])
                    r['after_preference_cash']=s.sub(r['after_capital_cash'],r['preference_paid'])
                    r['lp_profit_before_catchup']=s.add(lp_profit,r['preference_paid'])
                    r['gp_profit_before_catchup']=gp_profit
                    carry=D(f['base_gp_carry_bp']); carry_den=s.sub(D(10000),carry)
                    target=s.post(s.mul(r['lp_profit_before_catchup'],carry,key+'/catchup_target_product'),carry_den,key+'/catchup_target')
                    r['catchup_entitlement']=max(D(0),s.sub(target,gp_profit))
                    r['catchup_paid']=min(r['after_preference_cash'],r['catchup_entitlement'])
                    r['after_catchup_cash']=s.sub(r['after_preference_cash'],r['catchup_paid'])
                    rest=r['after_catchup_cash']; lp_at_tier=s.add(lp_cash,r['capital_paid'],r['preference_paid'])
                    for tier in (1,2,3):
                        gp_bp=D(f['promote_gp_bp'][tier-1])
                        if tier<3:
                            threshold=s.post(s.mul(r['cumulative_lp_paid_in'],D(f['lp_distribution_multiple_threshold_bp'][tier-1]),key+f'/tier{tier}_threshold_product'),D(10000),key+f'/tier{tier}_threshold')
                            gap=max(D(0),s.sub(threshold,lp_at_tier))
                            tc,tl,tg=_tier(rest,gap,gp_bp,s)
                        else:
                            tc=rest; tl=s.post(s.mul(tc,s.sub(D(10000),gp_bp),key+'/tier3_lp_product'),D(10000),key+'/tier3_lp_payment'); tg=s.sub(tc,tl)
                        r[f'tier{tier}_cash'],r[f'tier{tier}_lp'],r[f'tier{tier}_gp']=tc,tl,tg
                        rest=s.sub(rest,tc); lp_at_tier=s.add(lp_at_tier,tl)
                    r['lp_promote_cash']=s.add(*(r[f'tier{i}_lp'] for i in (1,2,3)))
                    r['gp_promote_cash']=s.add(*(r[f'tier{i}_gp'] for i in (1,2,3)))
                    r['lp_total_distribution']=s.add(r['capital_paid'],r['preference_paid'],r['lp_promote_cash'])
                    r['gp_total_distribution']=s.add(r['catchup_paid'],r['gp_promote_cash'])
                    r['fund_total_distribution']=s.add(r['lp_total_distribution'],r['gp_total_distribution'])
                    r['closing_cash']=s.sub(r['cash_before_distribution'],r['fund_total_distribution'])
                    r['closing_unreturned_capital']=s.sub(r['capital_entitlement'],r['capital_paid'])
                    r['closing_unpaid_preference']=s.sub(r['preference_entitlement'],r['preference_paid'])
                    r['cumulative_lp_distributions']=s.add(lp_cash,r['lp_total_distribution'])
                    r['cumulative_lp_profit']=s.add(lp_profit,r['preference_paid'],r['lp_promote_cash'])
                    r['cumulative_gp_profit']=s.add(gp_profit,r['gp_total_distribution'])
                    share=D(f['lp1_share_bp'])
                    r['lp1_call']=s.post(s.mul(r['lp_call'],share,key+'/LP1_call_product'),D(10000),key+'/LP1_call')
                    r['lp2_call']=s.sub(r['lp_call'],r['lp1_call'])
                    r['lp1_distribution']=s.post(s.mul(r['lp_total_distribution'],share,key+'/LP1_distribution_product'),D(10000),key+'/LP1_distribution')
                    r['lp2_distribution']=s.sub(r['lp_total_distribution'],r['lp1_distribution'])
                    for i in (1,2):r[f'lp{i}_net_cashflow']=s.sub(r[f'lp{i}_distribution'],r[f'lp{i}_call'])
                    r['gp_net_cashflow']=r['gp_total_distribution']
                    r['fund_cash_residual']=s.sub(s.sub(r['cash_before_distribution'],r['fund_total_distribution']),r['closing_cash'])
                    r['recipient_cash_residual']=s.sub(r['fund_total_distribution'],s.add(r['lp1_distribution'],r['lp2_distribution'],r['gp_net_cashflow']))
                    r['principal_residual']=s.sub(s.sub(r['capital_entitlement'],r['capital_paid']),r['closing_unreturned_capital'])
                    r['preference_residual']=s.sub(s.sub(r['preference_entitlement'],r['preference_paid']),r['closing_unpaid_preference'])
                    schema.require(set(r)==set(schema.ROW_FIELDS) and all(r[k]==0 for k in schema.INVARIANT_FIELDS),
                                   'A complete posting row or cash/balance reconciliation failed: '+key)
                    schema.require(all(r[k]>=0 for k in schema.ROW_FIELDS if k not in ('lp1_net_cashflow','lp2_net_cashflow')), 'A cash allocation or entitlement became negative')
                    row={k:int(s.mark(r[k],key+'/'+k)) for k in schema.ROW_FIELDS}
                    row['lp_distribution_multiple']={'numerator':row['cumulative_lp_distributions'],'denominator':row['cumulative_lp_paid_in']}
                    row['capital_and_pref_shortfall']=row['closing_unreturned_capital']>0 or row['closing_unpaid_preference']>0
                    rows[key]=row
                    for name,condition in [('historical_zero_preference',year in public['historical_years'] and r['preference_accrual']==0),
                        ('capital_shortfall',r['closing_unreturned_capital']>0),('preference_accrues',r['preference_accrual']>0),
                        ('preference_paid',r['preference_paid']>0),('catchup_paid',r['catchup_paid']>0),
                        *[(f'tier{i}_active',r[f'tier{i}_cash']>0) for i in (1,2,3)]]: states[name]+=int(condition)
                    if year>=2027:
                        faults.append({'key':key+'/after_preference_cash','correct_pence':row['after_preference_cash'],
                            'faulty_local_pence':int(s.add(r['after_capital_cash'],r['preference_paid'])),
                            'immediate_impact_pence':int(s.mul(D(2),r['preference_paid'])),
                            'zero_immediate_impact':r['preference_paid']==0})
                    cash,capital,unpaid= r['closing_cash'],r['closing_unreturned_capital'],r['closing_unpaid_preference']
                    paidin,lp_cash,lp_profit,gp_profit=r['cumulative_lp_paid_in'],r['cumulative_lp_distributions'],r['cumulative_lp_profit'],r['cumulative_gp_profit']
        aggregate_order=[]
        for sid in public['scenario_ids']:
            for year in public['years']:
                key=f'{sid}/{year}'; aggregate_order.append(key)
                aggregates[key]={name:int(s.add(*(D(rows[f"{f['id']}/{sid}/{year}"][name]) for f in public['funds']),label=key+'/'+name)) for name in schema.AGGREGATE_FIELDS}
    return {'kind':schema.RESULT_KIND,'version':1,'implementation':'A','specification_sha256':schema.canonical_sha256(public),
        'row_order':order,'rows':rows,'aggregate_order':aggregate_order,'aggregates':aggregates,
        'proof':{'integer_limit_strict':schema.INTEGER_LIMIT,'maximum_absolute_integer':s.maximum,'maximum_witness':s.witness,
                 'integer_intermediates_checked':s.checked,'all_residuals_zero':True,'state_counts':states,
                 'declared_forecast_fault_count':len(faults),'forecast_faults':faults,
                 'zero_immediate_impact_roots':[x['key'] for x in faults if x['zero_immediate_impact']],
                 'row_field_count':len(rows)*len(schema.ROW_FIELDS),'aggregate_field_count':len(aggregates)*len(schema.AGGREGATE_FIELDS),
                 'rounding':'Decimal precision60, posting once to whole penny ROUND_HALF_UP; no worksheet or other oracle execution'},
        'qualified':False,'model_LO_solver_calls':0}
