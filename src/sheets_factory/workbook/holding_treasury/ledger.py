"""Independent annual GBP double-entry model. Does not import the Excel emitter."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from .schema import PROGRAMME_FIELDS

D=Decimal
ZERO=D(0)


def money(value):return D(str(value)).quantize(D('.01'),rounding=ROUND_HALF_UP)


def posted(value):
    value=D(str(value))
    if not value.is_finite() or value!=money(value):
        raise ValueError('External monetary inputs must already be finite posted cents')
    return value


def _date(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    return date.fromisoformat(str(value)[:10])


def operating_bridge(spec,project_ledger,project_spec):
    """Keep original project dates; translate each posted minority share separately."""
    p=spec['parameters'];share=D(str(p['operating_ownership']));fx=D(str(p['gbp_per_usd']))
    if not ZERO<share<1 or fx<=0:raise ValueError('Minority ownership and explicit positive USD/GBP assumption are required')
    rows=project_ledger['monthly']
    if len(rows)!=36:raise ValueError('The original thirty-six monthly project periods are required')
    start=_date(project_spec['parameters']['start_date'])
    if start!=date(2027,1,1):raise ValueError('Do not silently shift the original January 2027 project')
    result=[]
    for i,source in enumerate(rows):
        actual=_date(source['date']);expected=date(2027+i//12,i%12+1,1)
        if actual!=expected:raise ValueError('Operating project month calendar changed or is incomplete')
        income=money(posted(source['net_income'])*share);dividend=money(posted(source['dividend'])*share)
        acquisition=money(posted(project_spec['parameters']['equity_paid_in'])*share) if i==0 else ZERO
        sale=money(posted(project_ledger['valuation']['equity_exit'])*share) if i==35 else ZERO
        result.append({'date':actual.isoformat(),'fiscal_year':actual.year+(actual.month>=4),
          'income_usd':income,'dividend_usd':dividend,'acquisition_usd':acquisition,'sale_usd':sale,
          'income_gbp':money(income*fx),'dividend_gbp':money(dividend*fx),
          'acquisition_gbp':money(acquisition*fx),'sale_gbp':money(sale*fx)})
    return result


def simulate_parent(spec,programme_annual,project_ledger,project_spec,*,waterfall_spec=None):
    with localcontext() as context:
        context.prec=50
        return _simulate(spec,programme_annual,project_ledger,project_spec,waterfall_spec)


def _simulate(spec,programme_annual,project_ledger,project_spec,waterfall_spec=None):
    years=list(spec['years']);p=spec['parameters'];inputs={int(r['year']):r for r in spec['annual_inputs']}
    if years!=list(range(2024,2044)) or len(spec['annual_inputs'])!=20 or set(inputs)!=set(years):raise ValueError('Twenty complete April–March reporting years FY2024–2043 are required')
    programme_rows=list(programme_annual.values()) if isinstance(programme_annual,dict) else list(programme_annual)
    programme={int(r['year']):r for r in programme_rows}
    if len(programme_rows)!=20 or set(programme)!=set(years):raise ValueError('Programme bridge does not cover the same reporting horizon')
    op=operating_bridge(spec,project_ledger,project_spec)
    annual=[];group=[];journal=[];accounts=defaultdict(lambda:ZERO);regimes=defaultdict(list)
    checks={'journal_balanced':True,'parent_balance_sheets':True,'parent_cash':True,
            'programme_investment':True,'consolidated_balance_sheets':True,
            'consolidated_income':True,'consolidated_cash':True,'finite_capital':True,
            'no_balance_plug':True,'programme_cash':True,'cash_settlement_nonnegative':True}
    def post(year,label,**entries):
        entries={key:posted(value) for key,value in entries.items() if value}
        if sum(entries.values(),ZERO):raise ValueError('Unbalanced holding journal: '+label)
        for key,value in entries.items():accounts[key]+=value
        if accounts['cash']<0:raise ValueError('Unfunded cash use in annual settlement: '+label)
        journal.append({'year':year,'label':label,'debit_positive_entries':entries})
    opening=posted(p['opening_cash']);minimum=posted(p['minimum_cash']);commitment=posted(p['additional_lp_commitment'])
    if opening<minimum or minimum<0 or commitment<0:raise ValueError('Opening cash and finite capital contract are infeasible')
    if posted(p['facility_limit'])<0 or any(not ZERO<=D(str(p[k]))<=1 for k in ('rav_advance_rate','claim_advance_rate')):
        raise ValueError('Facility limit and collateral advance rates are invalid')
    post(2023,'Opening paid-in partner capital',cash=opening,capital=-opening)
    partner_state=None;partner_annual=[]
    if waterfall_spec is not None:
        from ..partner_waterfall.ledger import initial_state,allocate_year
        if posted(waterfall_spec['opening_capital'])!=opening:
            raise ValueError('Partner opening contribution must equal actual parent opening cash')
        partner_state=initial_state(waterfall_spec)
        checks['partner_capital_reconciled']=True
    called=ZERO
    for year in years:
        external=programme[year];inp=inputs[year]
        if any(key not in external for key in PROGRAMME_FIELDS):raise ValueError('Programme bridge omits a required explicit field')
        if (_date(external['period_start'])!=date(year-1,4,1)
                or _date(external['period_end'])!=date(year,3,31)):
            raise ValueError('Programme fiscal dates must remain April–March')
        s={key:posted(external[key]) for key in PROGRAMME_FIELDS}
        if s['total_assets']-s['debt_close']-s['lease_liability_close']!=s['total_equity']:
            raise ValueError('Programme liabilities do not explain its actual balance sheet')
        if s['total_equity']<0:raise ValueError('This holding case requires nonnegative programme equity carrying value')
        previous_cash=posted(programme[year-1]['cash_close']) if year>years[0] else ZERO
        if s['cash_close']-previous_cash!=s['cfo']+s['cfi']+s['cff']:
            raise ValueError('Programme supplied cash-flow report does not reconcile')
        r={'cash_open':accounts['cash'],'bank_open':-accounts['bank'],
           'programme_investment_open':accounts['programme'],'operating_investment_open':accounts['operating'],
           'capital_open':-accounts['capital'],'retained_open':-accounts['retained'],
           'oci_open':-accounts['oci'],'lp_called_open':called}
        selected=[v for v in op if v['fiscal_year']==year]
        for name,key in [('operating_income','income_gbp'),('operating_dividend','dividend_gbp'),
                         ('operating_acquisition','acquisition_gbp'),('operating_sale','sale_gbp')]:
            r[name]=sum((v[key] for v in selected),ZERO)
        carrying=r['operating_investment_open']+r['operating_acquisition']+r['operating_income']-r['operating_dividend']
        if carrying<0:raise ValueError('Operating minority carrying value became negative')
        r['operating_sale_carrying']=carrying if year==2030 else ZERO
        r['operating_sale_gain']=r['operating_sale']-r['operating_sale_carrying']
        r['operating_investment_close']=carrying-r['operating_sale_carrying']
        r['programme_income']=s['net_income'];r['programme_oci']=s['asset_revaluation']
        r['programme_capital']=s['owner_capital'];r['programme_distribution']=s['owner_distribution']
        r['programme_investment_close']=(r['programme_investment_open']+s['owner_capital']+s['net_income']
                                        +s['asset_revaluation']-s['owner_distribution'])
        r['programme_investment_check']=r['programme_investment_close']-s['total_equity']
        if r['programme_investment_check']:raise ValueError('Programme equity-method roll-forward does not match actual net assets')
        rate=D(str(inp['bank_rate']));haircut=D(str(inp['claim_haircut']))
        if not ZERO<=haircut<=1 or rate<0:raise ValueError('Invalid explicit haircut or borrowing rate')
        r['bank_interest']=money(r['bank_open']*rate);r['management_fee']=posted(inp['management_fee'])
        if r['management_fee']<0:raise ValueError('Management fee must be nonnegative')
        r['rav_collateral']=money(s['closing_rav_nominal']*D(str(p['rav_advance_rate'])))
        r['claims_after_haircut']=money(s['claims_close']*(1-haircut))
        r['claims_collateral']=money(r['claims_after_haircut']*D(str(p['claim_advance_rate'])))
        r['senior_obligations']=s['debt_close']+s['lease_liability_close']
        r['borrowing_base']=min(posted(p['facility_limit']),max(ZERO,r['rav_collateral']+r['claims_collateral']-r['senior_obligations']))
        r['funding_before_repayments']=(r['cash_open']-r['bank_interest']-r['management_fee']
            +r['operating_dividend']+r['operating_sale']-r['operating_acquisition']
            +r['programme_distribution']-r['programme_capital'])
        r['mandatory_margin']=max(ZERO,r['bank_open']-r['borrowing_base'])
        r['funding_after_margin']=r['funding_before_repayments']-r['mandatory_margin']
        r['optional_repayment']=min(r['bank_open']-r['mandatory_margin'],max(ZERO,r['funding_after_margin']-minimum))
        r['funding_after_repayments']=r['funding_after_margin']-r['optional_repayment']
        r['bank_headroom']=max(ZERO,r['borrowing_base']-r['bank_open']+r['mandatory_margin']+r['optional_repayment'])
        need=max(ZERO,minimum-r['funding_after_repayments']);r['bank_draw']=min(need,r['bank_headroom'])
        r['lp_required']=max(ZERO,need-r['bank_draw'])
        if r['lp_required']>commitment-called:raise ValueError('Finite holding LP capital exhausted in FY'+str(year))
        r['lp_capital']=r['lp_required'];called+=r['lp_capital'];r['lp_called_close']=called;r['lp_remaining']=commitment-called
        # Finance the complete annual settlement before cash uses are posted.
        post(year,'Draw committed parent bank facility',cash=r['bank_draw'],bank=-r['bank_draw'])
        post(year,'Call finite additional partner commitments',cash=r['lp_capital'],capital=-r['lp_capital'])
        post(year,'Receive operating project dividends',cash=r['operating_dividend'],operating=-r['operating_dividend'])
        post(year,'Recognize operating share of earnings',operating=r['operating_income'],income=-r['operating_income'])
        post(year,'Sell minority interest after December 2029 dividends',cash=r['operating_sale'],
             operating=-r['operating_sale_carrying'],income=-r['operating_sale_gain'])
        post(year,'Recognize programme equity income',programme=r['programme_income'],income=-r['programme_income'])
        post(year,'Recognize programme revaluation OCI',programme=r['programme_oci'],oci=-r['programme_oci'])
        post(year,'Receive programme owner distribution',cash=r['programme_distribution'],programme=-r['programme_distribution'])
        post(year,'Purchase original January 2027 minority interest',operating=r['operating_acquisition'],cash=-r['operating_acquisition'])
        post(year,'Fund programme owner capital',programme=r['programme_capital'],cash=-r['programme_capital'])
        post(year,'Pay opening parent debt interest',interest=r['bank_interest'],cash=-r['bank_interest'])
        post(year,'Pay holding management fee',fee=r['management_fee'],cash=-r['management_fee'])
        repayment=r['mandatory_margin']+r['optional_repayment']
        post(year,'Settle mandatory margin and optional principal',bank=repayment,cash=-repayment)
        r['net_income']=r['programme_income']+r['operating_income']+r['operating_sale_gain']-r['bank_interest']-r['management_fee']
        post(year,'Close holding annual income',income=r['programme_income']+r['operating_income']+r['operating_sale_gain'],
             interest=-r['bank_interest'],fee=-r['management_fee'],retained=-r['net_income'])
        partner_distribution=ZERO
        if waterfall_spec is not None:
            allocation=allocate_year(waterfall_spec,partner_state,year,r['lp_capital'],max(ZERO,accounts['cash']-minimum))
            partner_state=allocation['state'];partner_annual.append(allocation['annual'])
            for entry in allocation['journal']:
                account_map={'paid_in_capital':'capital','retained_earnings':'retained','cash':'cash'}
                post(year,entry['label'],**{account_map[k]:v for k,v in entry['debit_positive_entries'].items()})
            partner_distribution=allocation['annual']['total_distribution']
            if partner_state['lp_unreturned']+partner_state['gp_unreturned']!=-accounts['capital']:
                raise ValueError('Partner capital claims do not match parent paid-in capital')
        r.update(cash_close=accounts['cash'],bank_close=-accounts['bank'],capital_close=-accounts['capital'],
                 retained_close=-accounts['retained'],oci_close=-accounts['oci'])
        r['assets']=r['cash_close']+r['programme_investment_close']+r['operating_investment_close'];r['liabilities']=r['bank_close']
        r['equity']=r['capital_close']+r['retained_close']+r['oci_close'];r['balance_check']=r['assets']-r['liabilities']-r['equity']
        r['cfo']=r['operating_dividend']+r['programme_distribution']-r['bank_interest']-r['management_fee']
        r['cfi']=r['operating_sale']-r['operating_acquisition']-r['programme_capital']
        r['cff']=r['bank_draw']-repayment+r['lp_capital']-partner_distribution;r['cash_check']=r['cash_close']-r['cash_open']-r['cfo']-r['cfi']-r['cff']
        g={'cash_open':r['cash_open']+(posted(programme[year-1]['cash_close']) if year>years[0] else ZERO),
           'cash_close':r['cash_close']+s['cash_close'],'parent_assets':r['assets'],'programme_assets':s['total_assets'],
           'investment_elimination':r['programme_investment_close'],'parent_liabilities':r['liabilities'],
           'programme_bank_debt':s['debt_close'],'programme_lease_liability':s['lease_liability_close'],
           'parent_equity':r['equity'],'programme_equity':s['total_equity'],'equity_elimination':s['total_equity'],
           'parent_income':r['net_income'],'programme_income':s['net_income'],'income_elimination':r['programme_income'],
           'parent_oci':r['programme_oci'],'programme_oci':s['asset_revaluation'],'oci_elimination':r['programme_oci'],
           'owner_capital_elimination':s['owner_capital'],'owner_distribution_elimination':s['owner_distribution']}
        g['assets']=g['parent_assets']+g['programme_assets']-g['investment_elimination']
        g['liabilities']=g['parent_liabilities']+g['programme_bank_debt']+g['programme_lease_liability']
        g['equity']=g['parent_equity']+g['programme_equity']-g['equity_elimination'];g['balance_check']=g['assets']-g['liabilities']-g['equity']
        g['net_income']=g['parent_income']+g['programme_income']-g['income_elimination']
        g['income_check']=g['net_income']-(s['net_income']+r['operating_income']+r['operating_sale_gain']-r['bank_interest']-r['management_fee'])
        g['oci']=g['parent_oci']+g['programme_oci']-g['oci_elimination']
        g['cfo']=r['cfo']+s['cfo']-s['owner_distribution'];g['cfi']=r['cfi']+s['cfi']+s['owner_capital']
        g['cff']=r['cff']+s['cff']-s['owner_capital']+s['owner_distribution']
        g['cash_check']=g['cash_close']-g['cash_open']-g['cfo']-g['cfi']-g['cff']
        if (sum(accounts.values(),ZERO) or r['balance_check'] or r['cash_check'] or g['balance_check']
                or g['cash_check'] or g['income_check'] or r['cash_close']<minimum
                or not ZERO<=r['bank_close']<=r['borrowing_base'] or accounts['programme']!=r['programme_investment_close']
                or accounts['operating']!=r['operating_investment_close']):
            raise ValueError('Independent holding journal, cash or consolidation reconciliation failed')
        r['year']=year;g['year']=year;annual.append(r);group.append(g)
        for key,value in [('bank_draw',r['bank_draw']),('mandatory_margin',r['mandatory_margin']),
                          ('optional_repayment',r['optional_repayment']),('lp_call',r['lp_capital']),
                          ('operating_acquisition',r['operating_acquisition']),('operating_exit',r['operating_sale'])]:
            if value:regimes[key].append(year)
        if r['bank_draw']>0 and r['lp_capital']>0:regimes['borrowing_base_binding'].append(year)
    result={'annual':annual,'consolidated':group,'operating_monthly_bridge':op,'journal':journal,
            'checks':checks,'observed_regimes':dict(regimes)}
    if waterfall_spec is not None:
        from ..partner_waterfall.ledger import observed_regimes
        result.update(partner_waterfall=partner_annual,waterfall_state=partner_state,
                      observed_waterfall_regimes=observed_regimes(partner_annual),
                      partner_opening=[{'lp_net_cashflow':partner_state['lp_cashflows'][0]['amount'],
                                        'gp_net_cashflow':partner_state['gp_cashflows'][0]['amount']}])
    return result
