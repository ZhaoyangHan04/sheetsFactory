"""Excel cashpool formulas. Receives public inputs, never the journal/oracle."""
from __future__ import annotations
from datetime import date
import openpyxl
from openpyxl.utils import get_column_letter as L
from .schema import MEMBER_ROWS as MR,TREASURY_ROWS as TR,GROUP_ROWS as GR,EVENT_START,EVENT_KEYS

RULES=[
 'Four wholly controlled tax-transparent holding partnerships and Treasury form the reporting group. Each holds 25% of three non-controlled project associates with significant influence, accounted for using the equity method. The twelve separate project budgets are provided upstream forecasts, not additional consolidated subsidiaries. Investor-level tax is outside this NAV model; project-level tax is already charged in those budgets. There are no other parent balances, taxes or financing.',
 'Opening internal loans, deposits, notes, bank debt and retained earnings are zero. Treasury paid-in capital equals its opening cash. Pool Scenario capital commitment means additional undrawn partner capital after opening funding, not the opening paid-in amount. Initial associate cost is 25% of each project\'s paid-in equity, funded before month one by partner capital together with opening operating cash. Recognize each associate\'s monthly profit share and dividend separately rounded to cents. Dividends reduce investment carrying amounts. Sell every associate stake at month 36 for its stated project share-sale proceeds times the ownership; recognize proceeds less the updated carrying amount as gain. Negative carrying amounts are not permitted in this case.',
 'External note commitments are paid at the stated month ends, earn the stated annual coupon on opening principal divided by twelve, and redeem at par in month 36. Management fees are cash expenses monthly. All monetary lines post half-up cents before reuse; interest is rounded separately for each account. Treasury, deposit and member loan interest use opening balances, so current draws earn or accrue from the following month.',
 'Demand-provider accounts may deposit and withdraw but cannot borrow. Revolving-borrower accounts use a fixed limit and repay debt from surplus before redepositing. Term-depositor principal cannot be withdrawn until its stated release months; each release returns all opening principal, and later deposits relock until the next release. Its cash sweep protects minimum cash plus the following three months\' note commitments; borrowing may coexist with locked deposits. NAV-borrower exposure cannot exceed the smaller of its fixed limit and the advance rate times current associate carrying value, excluding notes, deposits and cash; reductions create immediate principal margin calls.',
 'In an ordinary month settle cash interest and external investment/operating flows, return maturing term principal, and withdraw available demand deposits needed for minimum cash and margin calls. Only an actual margin call can first invoke committed partner capital after available deposits. Collect margin repayments, then sweep surplus above the applicable reserve to repay opening loans, then accept new deposits. Process new loan requests for remaining minimum-cash shortfalls in the stated funding order, within the member borrowing base. Only then call remaining finite partner commitments for residual cash shortfalls. Unfunded obligations or exhausted commitments make a case infeasible; they are never a balancing plug.',
 'Treasury may draw to meet its own operating minimum after cash interest and fees. Treasury funds each deposit repayment or member advance in order, drawing its bank facility only as needed to preserve its minimum cash and within the stated bank limit. Deposit repayments precede new loan advances. After collecting member repayments and deposits, Treasury uses cash above its minimum to repay bank principal. Internal loans and deposits are separate gross accounts; they are not netted while the pool operates. Interest is paid in cash, not capitalized into internal principal.',
 'The closed-end structures make no owner distributions before month 36. At termination, associates and notes liquidate first. Members settle all opening pool loans from realized cash and any remaining committed capital, then Treasury returns all deposits, repays bank debt, and all entities distribute their remaining cash. No new deposits or internal advances occur. Internal principal and interest balances/flows cancel on consolidation; equity-method project earnings are not counted again as project subsidiary earnings. Dividends received are operating cash flow; associate sales and note principal are investing flows; bank principal, partner capital and owner distributions are financing flows.'
]

SNAPSHOT_RULE = (' Cash before allocation is after cash operating flow, capex and scheduled Loan A/Loan B principal, '
                 'before DSRA transfers and revolving draws or repayments.')
TERMINATION_REPORTING_RULE = (' At termination every borrowing-base display is zero. The ordinary term-release stage is inactive: '
    'term requests and returns are zero and its Treasury snapshots precede opening-loan collections. '
    'All opening loans are then collected before the final withdrawal stage, which returns every account\'s deposits, '
    'including the term account; term release flags do not redirect liquidation repayments.')


def emit_pool(book,spec,source_bindings):
    members=spec['members'];ids=[m['id'] for m in members];terms=spec['treasury'];bindings={}
    rules=list(RULES)
    if spec.get('public_contract_version',9)>=10:
        rules[-1]+=TERMINATION_REPORTING_RULE
        for member in members:
            for project in member['projects']:
                readme=book[project+' Read Me']
                readme['B7']=str(readme['B7'].value)+SNAPSHOT_RULE
    for name in ('Portfolio Index','Pool Scenario','Pool Commitments','Treasury','Group Statements','Group Summary',*[i+' Holding' for i in ids]):
        if name in book:book.remove(book[name])
        book.create_sheet(name)
    index=book['Portfolio Index'];index['A1']='Cross-entity investment-partnership cashpool'
    for n,rule in enumerate(rules,3):index.cell(n,1,rule)
    params=book['Pool Scenario'];params.append(['Entity','Parameter','Provided value'])
    param={};row=2
    def parameter(entity,key,value):
        nonlocal row
        params.cell(row,1,entity);params.cell(row,2,key.replace('_',' '));params.cell(row,3,float(value) if key not in {'contract'} else value)
        param[entity,key]=f"'Pool Scenario'!$C${row}";row+=1
    for key,value in terms.items():parameter('Treasury',key,value)
    for member in members:
        for key in ('ownership','opening_cash','minimum_cash','loan_limit','capital_commitment','monthly_fee','note_rate'):
            parameter(member['id'],key,member[key])
        parameter(member['id'],'advance_rate',member.get('advance_rate',0));parameter(member['id'],'contract',member['contract'])
        for project in member['projects']:
            index.append([member['id'],member['contract'],project+' Scenario',project+' Operations',project+' Equity Value'])
    commits=book['Pool Commitments'];commits.append(['Month']+ids+['Term release'])
    for month in range(1,37):
        commits.cell(month+1,1,month)
        for n,member in enumerate(members,2):commits.cell(month+1,n,member['note_purchases'].get(str(month),0))
        term=next((m for m in members if m['contract']=='term_depositor'),None)
        commits.cell(month+1,6,int(term is not None and month in term['release_months']))
    for n,i in enumerate(spec['funding_order'],40):commits.cell(n,1,'Funding priority');commits.cell(n,2,i)
    def q(sheet,c,row):return f"'{sheet}'!{c}{row}"
    def f(i,k,c):return q(i+' Holding',c,MR[k])
    def t(k,c):return q('Treasury',c,TR[k])
    def P(i,k):return param[i,k]
    def R(x):return 'ROUND('+x+',2)'
    def S(items):return 'SUM('+','.join(items)+')'
    def add(sheet,c,row,expression,key,kind='money'):
        book[sheet][c+str(row)]='='+expression;bindings[sheet+'!'+c+str(row)]={'section':'member' if sheet.endswith(' Holding') else 'treasury' if sheet=='Treasury' else 'group','entity':sheet.split(' ')[0] if sheet.endswith(' Holding') else None,'key':key,'month':openpyxl.utils.column_index_from_string(c)-2,'kind':kind}
        book[sheet][c+str(row)].number_format='#,##0.00;[Red](#,##0.00)'
    for i in ids:
        for key,row in MR.items():book[i+' Holding'].cell(row,1,key.replace('_',' '))
    for key,row in TR.items():book['Treasury'].cell(row,1,key.replace('_',' '))
    for key,row in GR.items():book['Group Statements'].cell(row,1,key.replace('_',' '))
    events=[('term',i) for i in ids]+[('withdraw',i) for i in ids]+[('loan',i) for i in spec['funding_order']]
    eventrow={(kind,i,key):EVENT_START+n*len(EVENT_KEYS)+j for n,(kind,i) in enumerate(events) for j,key in enumerate(EVENT_KEYS)}
    for (kind,i,key),row in eventrow.items():book['Treasury'].cell(row,1,kind+' '+i+' '+key.replace('_',' '))
    def E(kind,i,key,c):return q('Treasury',c,eventrow[kind,i,key])
    for month in range(1,37):
        c=L(month+2);prev=L(month+1);terminal=month==36
        for sheet in ['Treasury','Group Statements',*[i+' Holding' for i in ids]]:
            book[sheet][c+'1']='='+q('T01 Calendar',c,3);book[sheet][c+'1'].number_format='mmm yyyy'
            bindings[sheet+'!'+c+'1']={'section':'date','month':month,'kind':'date'}
        initialcost={}
        for member in members:
            i=member['id'];share=P(i,'ownership');source=source_bindings
            costs=[R(q(p+' Scenario','B',source[p]['parameter_rows']['equity_paid_in'])+'*'+share) for p in member['projects']]
            initialcost[i]=S(costs)
            row={}
            for key,previous in [('cash_open','cash_close'),('deposit_open','deposit_close'),('loan_open','loan_close'),('note_open','note_close'),('investment_open','investment_close'),('capital_open','capital_close'),('retained_open','retained_close'),('called_open','called_close')]:
                first=P(i,'opening_cash') if key=='cash_open' else initialcost[i] if key=='investment_open' else initialcost[i]+'+'+P(i,'opening_cash') if key=='capital_open' else '0'
                row[key]=first if month==1 else f(i,previous,prev)
            row['project_income']=S([R(q(p+' Operations',c,14)+'*'+share) for p in member['projects']]);row['project_dividend']=S([R(q(p+' Cash Flow',c,10)+'*'+share) for p in member['projects']])
            row['project_sale']=S([R(q(p+' Equity Value','B',9)+'*'+share) for p in member['projects']]) if terminal else '0'
            row['investment_presale']=f(i,'investment_open',c)+'+'+f(i,'project_income',c)+'-'+f(i,'project_dividend',c);row['investment_close']='0' if terminal else f(i,'investment_presale',c);row['sale_gain']=f(i,'project_sale',c)+'-'+f(i,'investment_presale',c) if terminal else '0'
            row['note_purchase']=q('Pool Commitments',L(ids.index(i)+2),month+1);row['note_redemption']=f(i,'note_open',c) if terminal else '0';row['note_coupon']=R(f(i,'note_open',c)+'*'+P(i,'note_rate')+'/12');row['note_close']=f(i,'note_open',c)+'+'+f(i,'note_purchase',c)+'-'+f(i,'note_redemption',c)
            row['fee']=P(i,'monthly_fee');row['deposit_interest']=R(f(i,'deposit_open',c)+'*'+P('Treasury','deposit_rate')+'/12');row['loan_interest']=R(f(i,'loan_open',c)+'*'+P('Treasury','borrowing_rate')+'/12')
            reserve=P(i,'minimum_cash')
            if member['contract']=='term_depositor' and not terminal:
                reserve+='+'+S([q('Pool Commitments',L(ids.index(i)+2),k+1) for k in range(month+1,min(36,month+member['forward_reserve_months'])+1)])
            row['reserve_floor']='0' if terminal else reserve
            row['nav_cap']='0' if terminal else 'MIN('+P(i,'loan_limit')+','+R(f(i,'investment_presale',c)+'*'+P(i,'advance_rate'))+')' if member['contract']=='nav_borrower' else P(i,'loan_limit')
            row['cash_pre']=f(i,'cash_open',c)+'+'+f(i,'project_dividend',c)+'+'+f(i,'project_sale',c)+'+'+f(i,'note_coupon',c)+'-'+f(i,'note_purchase',c)+'+'+f(i,'note_redemption',c)+'-'+f(i,'fee',c)+'+'+f(i,'deposit_interest',c)+'-'+f(i,'loan_interest',c)
            row['term_request']=f(i,'deposit_open',c) if member['contract']=='term_depositor' and month in member['release_months'] and not terminal else '0';row['term_return']=E('term',i,'paid',c)
            row['cash_after_term']=f(i,'cash_pre',c)+'+'+f(i,'term_return',c);row['deposit_available']=f(i,'deposit_open',c)+'-'+f(i,'term_return',c) if member['contract']!='term_depositor' or terminal else '0'
            row['margin_required']=f(i,'loan_open',c) if terminal else 'MAX(0,'+f(i,'loan_open',c)+'-'+f(i,'nav_cap',c)+')'
            need='MAX(0,'+f(i,'margin_required',c)+'-'+f(i,'cash_after_term',c)+')' if terminal else 'MAX(0,'+P(i,'minimum_cash')+'+'+f(i,'margin_required',c)+'-'+f(i,'cash_after_term',c)+'-'+f(i,'deposit_available',c)+')'
            row['capital_margin']='IF('+f(i,'margin_required',c)+'>0,MIN('+P(i,'capital_commitment')+'-'+f(i,'called_open',c)+','+need+'),0)'
            row['withdraw_request']=f(i,'deposit_open',c)+'-'+f(i,'term_return',c) if terminal else 'MIN('+f(i,'deposit_available',c)+',MAX(0,'+P(i,'minimum_cash')+'+'+f(i,'margin_required',c)+'-'+f(i,'cash_after_term',c)+'-'+f(i,'capital_margin',c)+'))'
            row['withdrawal']=E('withdraw',i,'paid',c);row['cash_after_withdrawal']=f(i,'cash_after_term',c)+'+'+f(i,'capital_margin',c)+'+'+f(i,'withdrawal',c);row['margin_paid']=f(i,'margin_required',c)
            row['surplus_repayment']='0' if terminal else 'MIN('+f(i,'loan_open',c)+'-'+f(i,'margin_paid',c)+',MAX(0,'+f(i,'cash_after_withdrawal',c)+'-'+f(i,'margin_paid',c)+'-'+f(i,'reserve_floor',c)+'))'
            row['loan_after_repayment']=f(i,'loan_open',c)+'-'+f(i,'margin_paid',c)+'-'+f(i,'surplus_repayment',c);row['cash_after_repayment']=f(i,'cash_after_withdrawal',c)+'-'+f(i,'margin_paid',c)+'-'+f(i,'surplus_repayment',c)
            row['new_deposit']='0' if terminal else 'MAX(0,'+f(i,'cash_after_repayment',c)+'-'+f(i,'reserve_floor',c)+')';row['cash_after_deposit']=f(i,'cash_after_repayment',c)+'-'+f(i,'new_deposit',c)
            row['loan_request']='0' if terminal else 'MAX(0,'+P(i,'minimum_cash')+'-'+f(i,'cash_after_deposit',c)+')';row['loan_capacity']='MAX(0,'+f(i,'nav_cap',c)+'-'+f(i,'loan_after_repayment',c)+')';row['loan_capped_request']='MIN('+f(i,'loan_request',c)+','+f(i,'loan_capacity',c)+')';row['loan_advance']=E('loan',i,'paid',c)
            row['capital_cash']='MIN('+P(i,'capital_commitment')+'-'+f(i,'called_open',c)+'-'+f(i,'capital_margin',c)+',MAX(0,'+('0' if terminal else P(i,'minimum_cash'))+'-'+f(i,'cash_after_deposit',c)+'-'+f(i,'loan_advance',c)+'))';row['capital_contribution']=f(i,'capital_margin',c)+'+'+f(i,'capital_cash',c)
            row['cash_before_dividend']=f(i,'cash_after_deposit',c)+'+'+f(i,'loan_advance',c)+'+'+f(i,'capital_cash',c);row['owner_dividend']=f(i,'cash_before_dividend',c) if terminal else '0';row['cash_close']=f(i,'cash_before_dividend',c)+'-'+f(i,'owner_dividend',c)
            row['deposit_close']=f(i,'deposit_open',c)+'-'+f(i,'term_return',c)+'-'+f(i,'withdrawal',c)+'+'+f(i,'new_deposit',c);row['loan_close']=f(i,'loan_after_repayment',c)+'+'+f(i,'loan_advance',c)
            row['net_income']=f(i,'project_income',c)+'+'+f(i,'sale_gain',c)+'+'+f(i,'note_coupon',c)+'+'+f(i,'deposit_interest',c)+'-'+f(i,'loan_interest',c)+'-'+f(i,'fee',c);row['capital_close']=f(i,'capital_open',c)+'+'+f(i,'capital_contribution',c);row['retained_close']=f(i,'retained_open',c)+'+'+f(i,'net_income',c)+'-'+f(i,'owner_dividend',c);row['called_close']=f(i,'called_open',c)+'+'+f(i,'capital_contribution',c);row['capital_remaining']=P(i,'capital_commitment')+'-'+f(i,'called_close',c)
            row['assets']=S([f(i,k,c) for k in ('cash_close','deposit_close','note_close','investment_close')]);row['liabilities']=f(i,'loan_close',c);row['equity']=f(i,'capital_close',c)+'+'+f(i,'retained_close',c);row['balance_check']=f(i,'assets',c)+'-'+f(i,'liabilities',c)+'-'+f(i,'equity',c);row['cash_gap']='MAX(0,'+('0' if terminal else P(i,'minimum_cash'))+'-'+f(i,'cash_close',c)+')'
            if set(row)!=set(MR):raise ValueError('Incomplete member formula schema')
            for key,expression in row.items():add(i+' Holding',c,MR[key],expression,key)
        # Treasury independent sequential settlement stages.
        row={'cash_open':P('Treasury','opening_cash') if month==1 else t('cash_close',prev),'bank_open':'0' if month==1 else t('bank_close',prev),'retained_open':'0' if month==1 else t('retained_close',prev),'capital':P('Treasury','opening_cash'),
             'bank_interest':R(t('bank_open',c)+'*'+P('Treasury','bank_rate')+'/12'),'fee':P('Treasury','monthly_fee'),'loan_interest':S([f(i,'loan_interest',c) for i in ids]),'deposit_interest':S([f(i,'deposit_interest',c) for i in ids])}
        for n,(kind,i) in enumerate(events):
            previous=events[n-1] if n else None
            cash=(E(*previous,'cash_after',c) if previous else t('cash_open',c)+'+'+t('loan_interest',c)+'-'+t('deposit_interest',c)+'-'+t('bank_interest',c)+'-'+t('fee',c))
            bank=E(*previous,'bank_after',c) if previous else t('bank_open',c)
            if n==4 and terminal:cash+='+'+S([f(j,'margin_paid',c) for j in ids])
            if n==8 and not terminal:cash+='+'+S([f(j,k,c) for j in ids for k in ('margin_paid','surplus_repayment','new_deposit')])
            request=f(i,{'term':'term_request','withdraw':'withdraw_request','loan':'loan_capped_request'}[kind],c)
            values={'request':request,'cash_before':cash,'bank_before':bank,
                    'bank_draw':'MIN(MAX(0,'+E(kind,i,'request',c)+'+'+P('Treasury','minimum_cash')+'-'+E(kind,i,'cash_before',c)+'),'+P('Treasury','bank_limit')+'-'+E(kind,i,'bank_before',c)+')',
                    'paid':'MIN('+E(kind,i,'request',c)+',MAX(0,'+E(kind,i,'cash_before',c)+'+'+E(kind,i,'bank_draw',c)+'-'+P('Treasury','minimum_cash')+'))',
                    'cash_after':E(kind,i,'cash_before',c)+'+'+E(kind,i,'bank_draw',c)+'-'+E(kind,i,'paid',c),
                    'bank_after':E(kind,i,'bank_before',c)+'+'+E(kind,i,'bank_draw',c)}
            for key,expression in values.items():
                rr=eventrow[kind,i,key];book['Treasury'][c+str(rr)]='='+expression;bindings['Treasury!'+c+str(rr)]={'section':'event','index':n,'key':key,'month':month,'kind':'money'}
        last=events[-1];row['bank_draw']=S([E(kind,i,'bank_draw',c) for kind,i in events]);row['cash_before_bank_repayment']=E(*last,'cash_after',c)
        row['bank_repayment']=E(*last,'bank_after',c) if terminal else 'MIN('+E(*last,'bank_after',c)+',MAX(0,'+t('cash_before_bank_repayment',c)+'-'+P('Treasury','minimum_cash')+'))'
        row['bank_close']=E(*last,'bank_after',c)+'-'+t('bank_repayment',c);row['cash_before_dividend']=t('cash_before_bank_repayment',c)+'-'+t('bank_repayment',c);row['owner_dividend']=t('cash_before_dividend',c) if terminal else '0';row['cash_close']=t('cash_before_dividend',c)+'-'+t('owner_dividend',c)
        row['net_income']=t('loan_interest',c)+'-'+t('deposit_interest',c)+'-'+t('bank_interest',c)+'-'+t('fee',c);row['retained_close']=t('retained_open',c)+'+'+t('net_income',c)+'-'+t('owner_dividend',c);row['member_loans']=S([f(i,'loan_close',c) for i in ids]);row['member_deposits']=S([f(i,'deposit_close',c) for i in ids]);row['assets']=t('cash_close',c)+'+'+t('member_loans',c);row['liabilities']=t('bank_close',c)+'+'+t('member_deposits',c);row['equity']=t('capital',c)+'+'+t('retained_close',c);row['balance_check']=t('assets',c)+'-'+t('liabilities',c)+'-'+t('equity',c)
        for key,expression in row.items():add('Treasury',c,TR[key],expression,key)
        g={}
        for key,memberkey,treasurykey in [('cash_open','cash_open','cash_open'),('cash_close','cash_close','cash_close'),('gross_assets','assets','assets'),('gross_liabilities','liabilities','liabilities'),('equity','equity','equity'),('net_income','net_income','net_income'),('owner_dividend','owner_dividend','owner_dividend')]:g[key]=S([f(i,memberkey,c) for i in ids])+ '+'+t(treasurykey,c)
        g['capital_contribution']=S([f(i,'capital_contribution',c) for i in ids]);g['eliminate_loans']=t('member_loans',c);g['eliminate_deposits']=t('member_deposits',c)
        def G(k):return q('Group Statements',c,GR[k])
        g['assets']=G('gross_assets')+'-'+G('eliminate_loans')+'-'+G('eliminate_deposits');g['liabilities']=G('gross_liabilities')+'-'+G('eliminate_loans')+'-'+G('eliminate_deposits');g['balance_check']=G('assets')+'-'+G('liabilities')+'-'+G('equity')
        g['external_income']=S([f(i,'project_income',c)+'+'+f(i,'sale_gain',c)+'+'+f(i,'note_coupon',c)+'-'+f(i,'fee',c) for i in ids])+'-'+t('bank_interest',c)+'-'+t('fee',c);g['income_elimination_check']=G('net_income')+'-'+G('external_income')
        g['cfo']=S([f(i,'project_dividend',c)+'+'+f(i,'note_coupon',c)+'-'+f(i,'fee',c) for i in ids])+'-'+t('bank_interest',c)+'-'+t('fee',c)
        g['cfi']=S([f(i,'project_sale',c)+'+'+f(i,'note_redemption',c)+'-'+f(i,'note_purchase',c) for i in ids]);g['cff']=t('bank_draw',c)+'-'+t('bank_repayment',c)+'+'+G('capital_contribution')+'-'+G('owner_dividend');g['cash_check']=G('cash_open')+'+'+G('cfo')+'+'+G('cfi')+'+'+G('cff')+'-'+G('cash_close')
        for key,expression in g.items():add('Group Statements',c,GR[key],expression,key)
    summary=book['Group Summary'];summary['A1']='Consolidated holding-partnership annual statements'
    for key,row in GR.items():summary.cell(row,1,key.replace('_',' '))
    flows={'net_income','capital_contribution','owner_dividend','external_income','cfo','cfi','cff'}
    for year in range(1,4):
        c=L(year+2);summary[c+'1']=year;first=L(3+(year-1)*12);last=L(14+(year-1)*12)
        for key,row in GR.items():
            expression=S([q('Group Statements',L(k),row) for k in range(3+(year-1)*12,15+(year-1)*12)]) if key in flows else q('Group Statements',first if key=='cash_open' else last,row)
            summary[c+str(row)]='='+expression;bindings['Group Summary!'+c+str(row)]={'section':'annual','year':year,'key':key,'kind':'money'}
    for sheet in book:
        if sheet.title in ('Pool Scenario','Pool Commitments','Portfolio Index') or sheet.title.endswith(' Holding') or sheet.title in ('Treasury','Group Statements','Group Summary'):
            sheet.column_dimensions['A'].width=40;sheet.freeze_panes='C3'
    return {'cells':bindings,'member_rows':MR,'treasury_rows':TR,'group_rows':GR,'parameter_cells':{i+':'+k:v for (i,k),v in param.items()},'public_rules':rules}
