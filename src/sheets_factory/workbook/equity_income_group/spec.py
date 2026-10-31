"""Public, synthetic management-group specification; no original workbook seed."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import re

KIND = 'synthetic_equity_income_management_group'
VERSION = 1
ENTITY_METRICS = ('revenue','cash_opex','depreciation','interest','operating_profit','standalone_pretax',
    'equity_income','pretax_profit','opening_loss','taxable_profit','current_tax','net_income','closing_loss',
    'opening_cash','operating_cashflow','capex','closing_cash','opening_ppe','closing_ppe',
    'opening_investment','closing_investment','opening_retained','closing_retained','paid_in_capital','debt',
    'assets','liabilities_and_equity','balance_residual')
GROUP_METRICS = ('revenue','cash_opex','depreciation','interest','standalone_pretax','entity_equity_income',
    'equity_income_elimination','reported_entity_net_income','current_tax','external_net_income',
    'operating_cashflow','capex','opening_cash','closing_cash','closing_ppe','entity_investments',
    'investment_elimination','debt','combined_capital','assets','liabilities_and_capital',
    'balance_residual','profit_reconciliation_residual','cash_reconciliation_residual')
ENTITY_FIELDS = ('id','name','tax_rate','annual_interest_rate','debt','opening_cash','opening_ppe',
    'opening_investment','opening_retained','paid_in_capital','opening_loss')
INPUT_FIELDS = ('revenue','cash_opex','depreciation','capex')
POLICY = (
    'All money is GBP thousands. Each scenario starts from the supplied opening balances and runs independently; quarters are in chronological order.',
    'During the forecast, each entity recognizes its signed ownership share of each investee\'s current-quarter after-tax profit or loss. No dividends, ownership changes, or other equity-accounting adjustments occur.',
    'For this planning tax policy, recognized equity results enter ordinary taxable profit. Each entity uses its own opening loss carryforward against positive pretax profit; unused losses carry forward without expiry, losses receive no refund, and there is no inter-entity tax sharing.',
    'Interest is fixed debt times the nominal annual rate divided by four. Revenue, cash operating expenses, interest, current tax, and CapEx settle in their stated quarter; there are no working-capital changes or other cash flows. Debt and paid-in capital stay fixed.',
    'Investments roll forward by signed recognized equity income; retained earnings roll forward by net income; PPE rolls forward by CapEx less depreciation. Supplied cases must retain nonnegative cash, PPE, and investment carrying amounts.',
    'The management group combines 100% of the listed entities and eliminates all within-network equity income and investment balances. Combined capital equals total paid-in capital plus retained earnings less investment carrying amounts; no statutory control or ownership-weighted allocation is modeled.',
    'Keep simultaneous results and all later rollforwards unrounded. Display monetary answers to two decimals using round-half-up. The historical quarter precedes the investment arrangements and has zero recognized equity results.',
)


def require(value, message):
    if not value: raise ValueError(message)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def amount(value):
    require(type(value) is str and len(value) < 50, 'Financial inputs must be bounded decimal strings')
    try: parsed = Fraction(value)
    except (ValueError, ZeroDivisionError) as error: raise ValueError('Invalid decimal input') from error
    require('/' not in value and abs(parsed) <= 10**9, 'Use finite decimal input amounts')
    return parsed


def validate(value):
    public = deepcopy(value)
    require(set(public) == {'kind','version','source_type','official_workbook_seed_used','policy','entities','periods','ownership','scenarios','history'},
        'Use only the declared synthetic business inputs')
    require(public.get('kind') == KIND and type(public.get('version')) is int and public['version'] == VERSION
        and public.get('source_type') == 'new_synthetic' and public.get('official_workbook_seed_used') is False,
        'Use the new synthetic specification')
    entities,periods,scenarios = public['entities'],public['periods'],public['scenarios']
    n = len(entities); require(1 <= n <= 8 and 1 <= len(periods) <= 24 and 1 <= len(scenarios) <= 3, 'Unsupported bounded dimensions')
    ids = [row['id'] for row in entities]
    require(ids == [f'E{i+1:02d}' for i in range(n)] and [s['id'] for s in scenarios] == [f'S{i+1:02d}' for i in range(len(scenarios))], 'Use the declared ordered entity and scenario census')
    require(all(type(p) is str and re.fullmatch(r'[0-9]{4}-Q[1-4]',p) for p in periods), 'Use explicit calendar quarters')
    indices = [int(p[:4])*4+int(p[-1])-1 for p in periods]
    require(indices == list(range(indices[0],indices[0]+len(indices))), 'Quarters must be consecutive and chronological')
    require(len(set(ids)) == n and len(set(periods)) == len(periods)
        and len({row['id'] for row in scenarios}) == len(scenarios), 'Duplicate entity, period or scenario')
    require(public['policy'] == list(POLICY), 'The complete public business policy changed')
    for row in entities:
        require(set(row) == set(ENTITY_FIELDS), 'The complete opening input schema is required')
        for key in ENTITY_FIELDS[2:]: amount(row[key])
        require(0 <= amount(row['tax_rate']) <= 1 and 0 <= amount(row['annual_interest_rate']) <= 1, 'Rates must be between zero and one')
        require(all(amount(row[k]) >= 0 for k in ENTITY_FIELDS[4:]), 'Opening amounts must be nonnegative')
        require(sum(amount(row[k]) for k in ('opening_cash','opening_ppe','opening_investment'))
            == sum(amount(row[k]) for k in ('debt','paid_in_capital','opening_retained')), 'Opening balance sheet does not balance')
    h = public['ownership']; require(len(h) == n and all(len(row) == n for row in h), 'Complete directed ownership matrix required')
    for i,row in enumerate(h):
        require(all(amount(v) >= 0 for v in row) and amount(row[i]) == 0
            and sum(map(amount,row)) <= Fraction(35,100), 'Ownership must have zero diagonal and each row sum at most .35')
    require(all(sum(amount(h[i][j]) for i in range(n)) <= 1 for j in range(n)), 'An investee cannot have more than 100% ownership allocated')
    for scenario in scenarios:
        require(set(scenario) == {'id','name','inputs'} and set(scenario['inputs']) == set(ids), 'Complete independent scenario inputs required')
        for rows in scenario['inputs'].values():
            require(len(rows) == len(periods), 'Every entity needs every quarter')
            for row in rows:
                require(set(row) == set(INPUT_FIELDS) and all(amount(row[k]) >= 0 for k in INPUT_FIELDS), 'Forecast operating inputs must be complete and nonnegative')
    require(set(public['history']) == set(ids) and all(set(row) == {'revenue','cash_opex','depreciation','interest','equity_income'}
        and row['equity_income'] == '0' and all(amount(v) >= 0 for v in row.values()) for row in public['history'].values()), 'Complete historical inputs with zero equity results required')
    return public


def build_spec(*, entities=6, quarters=12, scenarios=3):
    """One deterministic business fixture; dimensions are explicit, never tiled."""
    require(1 <= entities <= 8 and 1 <= quarters <= 24 and 1 <= scenarios <= 3, 'Unsupported dimensions')
    from decimal import Decimal
    def s(value): return format(Decimal(value), 'f')
    names=('Harbor','Orchard','Foundry','Meadow','Pioneer','Summit','Willow','Brook')
    rows=[]; history={}
    for i in range(entities):
        eid=f'E{i+1:02d}';cash=25000+i*1200;ppe=15000+i*500;investment=10000+i*300;debt=2000+i*200
        rows.append({'id':eid,'name':names[i], 'tax_rate':('0.24','0.19','0.28','0.22','0.25','0.20','0.23','0.26')[i],
            'annual_interest_rate':s(Decimal('.04')+Decimal('.005')*(i%4)), 'debt':str(debt), 'opening_cash':str(cash),
            'opening_ppe':str(ppe),'opening_investment':str(investment),'opening_retained':'0',
            'paid_in_capital':str(cash+ppe+investment-debt),'opening_loss':str((i%3)*125)})
        history[eid]={'revenue':str(2600+i*180),'cash_opex':str(1900+i*140),'depreciation':str(100+i*10),
            'interest':s(Decimal(debt)*Decimal(rows[-1]['annual_interest_rate'])/4),'equity_income':'0'}
    h=[['0' for _ in rows] for _ in rows]
    if entities > 1:
        for i in range(entities):
            for step,stake in ((1,Decimal('.13')+Decimal('.01')*(i%3)),(2,Decimal('.08')),(entities-1,Decimal('.04'))):
                j=(i+step)%entities
                if j != i: h[i][j]=s(Decimal(h[i][j])+stake)
    cases=[]
    for z in range(scenarios):
        inputs={}
        for i,row in enumerate(rows):
            forecasts=[]
            for q in range(quarters):
                revenue=Decimal(2400+i*220+q*45+(q%4)*60)*[Decimal('1'),Decimal('.78'),Decimal('1.12')][z]
                restructuring=Decimal(1000+i*40) if q in (i%3,6+i%2) else Decimal(0)
                opex=revenue*Decimal('.58')+Decimal(850+i*40)+restructuring
                forecasts.append({'revenue':s(revenue),'cash_opex':s(opex),'depreciation':str(100+i*10),'capex':str(140+i*15)})
            inputs[row['id']]=forecasts
        cases.append({'id':f'S{z+1:02d}','name':('Plan','Stress','Recovery')[z],'inputs':inputs})
    return validate({'kind':KIND,'version':VERSION,'source_type':'new_synthetic','official_workbook_seed_used':False,
        'policy':list(POLICY),'entities':rows,'periods':[f'{2027+q//4}-Q{q%4+1}' for q in range(quarters)],
        'ownership':h,'scenarios':cases,'history':history})
