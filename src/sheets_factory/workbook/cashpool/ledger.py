"""Independent cent-posted double-entry cashpool journal; no Excel calls."""
from __future__ import annotations
from decimal import Decimal,ROUND_HALF_UP

D=lambda v:Decimal(str(v))
CENT=Decimal('.01')
def money(v):return D(v).quantize(CENT,rounding=ROUND_HALF_UP)


def simulate_pool(spec,project_ledgers,project_specs):
    members=spec['members'];terms=spec['treasury'];ids=[m['id'] for m in members]
    states={};accounts={i:{} for i in ids+['Treasury']};journal=[]
    def post(entity,month,debit,credit,amount,reason):
        amount=money(amount)
        if amount<0:debit,credit,amount=credit,debit,-amount
        if amount==0:return
        a=accounts[entity];a[debit]=a.get(debit,D(0))+amount;a[credit]=a.get(credit,D(0))-amount
        journal.append({'entity':entity,'month':month,'debit':debit,'credit':credit,'amount':str(amount),'reason':reason})
    for member in members:
        i=member['id'];invest=sum((money(D(project_specs[p]['parameters']['equity_paid_in'])*D(member['ownership'])) for p in member['projects']),D(0))
        cash=D(member['opening_cash']);capital=invest+cash
        states[i]={'cash':cash,'deposit':D(0),'loan':D(0),'note':D(0),'investment':invest,'capital':capital,'retained':D(0),'called':D(0)}
        post(i,0,'investment','capital',invest,'Opening associate equity investment');post(i,0,'cash','capital',cash,'Opening liquid capital')
    tcash=D(terms['opening_cash']);bank=D(0);tret=D(0)
    post('Treasury',0,'cash','capital',tcash,'Opening treasury capital')
    months=[];stages=[];group=[];regimes={key:[] for key in spec['required_regimes']}
    for month in range(1,37):
        terminal=month==36;rows={};old={i:dict(s) for i,s in states.items()}
        t={'cash_open':tcash,'bank_open':bank,'retained_open':tret,'capital':D(terms['opening_cash']),
           'bank_interest':money(bank*D(terms['bank_rate'])/12),'fee':D(terms['monthly_fee'])}
        for member in members:
            i=member['id'];s=old[i];share=D(member['ownership'])
            earnings=sum((money(project_ledgers[p]['monthly'][month-1]['net_income']*share) for p in member['projects']),D(0))
            dividends=sum((money(project_ledgers[p]['monthly'][month-1]['dividend']*share) for p in member['projects']),D(0))
            proceeds=sum((money(project_ledgers[p]['valuation']['equity_exit']*share) for p in member['projects']),D(0)) if terminal else D(0)
            presale=s['investment']+earnings-dividends
            if presale<0:raise ValueError('Negative equity-method carrying amount requires another contract')
            coupon=money(s['note']*D(member['note_rate'])/12);purchase=D(member['note_purchases'].get(str(month),0));redemption=s['note'] if terminal else D(0)
            di=money(s['deposit']*D(terms['deposit_rate'])/12);li=money(s['loan']*D(terms['borrowing_rate'])/12)
            fee=D(member['monthly_fee']);reserve=D(member['minimum_cash'])
            if member['contract']=='term_depositor' and not terminal:
                reserve+=sum((D(member['note_purchases'].get(str(k),0)) for k in range(month+1,min(36,month+int(member['forward_reserve_months']))+1)),D(0))
            navcap=min(D(member['loan_limit']),money(presale*D(member['advance_rate']))) if member['contract']=='nav_borrower' else D(member['loan_limit'])
            if terminal:navcap=D(0)
            row={'cash_open':s['cash'],'deposit_open':s['deposit'],'loan_open':s['loan'],'note_open':s['note'],'investment_open':s['investment'],
                 'capital_open':s['capital'],'retained_open':s['retained'],'called_open':s['called'],'project_income':earnings,'project_dividend':dividends,
                 'project_sale':proceeds,'investment_presale':presale,'investment_close':D(0) if terminal else presale,
                 'sale_gain':proceeds-presale if terminal else D(0),'note_purchase':purchase,'note_redemption':redemption,'note_coupon':coupon,
                 'note_close':s['note']+purchase-redemption,'fee':fee,'deposit_interest':di,'loan_interest':li,'reserve_floor':D(0) if terminal else reserve,'nav_cap':navcap}
            row['cash_pre']=s['cash']+dividends+proceeds+coupon-purchase+redemption-fee+di-li
            row['term_request']=s['deposit'] if member['contract']=='term_depositor' and month in member['release_months'] and not terminal else D(0)
            post(i,month,'investment','profit_loss',earnings,'Associate profit under equity method');post(i,month,'cash','investment',dividends,'Associate dividend')
            if terminal:
                post(i,month,'cash','investment',presale,'Dispose associate carrying amount');post(i,month,'cash','profit_loss',proceeds-presale,'Realized associate sale gain')
            post(i,month,'note','cash',purchase,'Committed external note investment');post(i,month,'cash','note',redemption,'Note principal redemption');post(i,month,'cash','profit_loss',coupon,'External note coupon')
            post(i,month,'profit_loss','cash',fee,'Management expense');post(i,month,'cash','profit_loss',di,'Deposit interest receipt');post(i,month,'profit_loss','cash',li,'Pool borrowing interest')
            post('Treasury',month,'cash','profit_loss',li,'Member loan interest');post('Treasury',month,'profit_loss','cash',di,'Member deposit interest')
            rows[i]=row
        t['loan_interest']=sum((r['loan_interest'] for r in rows.values()),D(0));t['deposit_interest']=sum((r['deposit_interest'] for r in rows.values()),D(0))
        post('Treasury',month,'profit_loss','cash',t['bank_interest'],'External bank interest');post('Treasury',month,'profit_loss','cash',t['fee'],'Treasury management fee')
        cash=tcash+t['loan_interest']-t['deposit_interest']-t['bank_interest']-t['fee'];bank_current=bank
        events=[]
        def pay(kind,i,request):
            nonlocal cash,bank_current
            request=money(request);available=max(D(0),cash-D(terms['minimum_cash']))
            draw=min(max(D(0),request+D(terms['minimum_cash'])-cash),D(terms['bank_limit'])-bank_current)
            paid=min(request,max(D(0),cash+draw-D(terms['minimum_cash'])))
            if kind in ('term','withdraw') and paid!=request:raise ValueError('Treasury cannot honor a deposit withdrawal')
            event={'kind':kind,'member':i,'request':request,'cash_before':cash,'bank_before':bank_current,'bank_draw':draw,'paid':paid,'cash_after':cash+draw-paid,'bank_after':bank_current+draw}
            cash,bank_current=event['cash_after'],event['bank_after'];events.append(event)
            post('Treasury',month,'cash','bank_debt',draw,'Bank liquidity draw for '+kind)
            if kind in ('term','withdraw'):
                post(i,month,'cash','deposit',paid,'Pool deposit principal returned');post('Treasury',month,'deposit_liability','cash',paid,'Member deposit returned')
            else:
                post(i,month,'cash','loan',paid,'Pool loan advance');post('Treasury',month,'loan_asset','cash',paid,'Member loan advance')
            if draw>0:regimes['bank_draw'].append(month)
            if kind=='withdraw' and paid>0 and not terminal:regimes['demand_withdrawal'].append(month)
            if kind=='loan' and paid>0:regimes['member_loan_draw'].append(month)
            return paid
        for i in ids:rows[i]['term_return']=pay('term',i,rows[i]['term_request'])
        for member in members:
            i=member['id'];r=rows[i];s=old[i];r['cash_after_term']=r['cash_pre']+r['term_return'];r['deposit_available']=s['deposit']-r['term_return'] if member['contract']!='term_depositor' or terminal else D(0)
            r['margin_required']=s['loan'] if terminal else max(D(0),s['loan']-r['nav_cap'])
            need=max(D(0),r['margin_required']-r['cash_after_term']) if terminal else max(D(0),D(member['minimum_cash'])+r['margin_required']-r['cash_after_term']-r['deposit_available'])
            r['capital_margin']=min(D(member['capital_commitment'])-s['called'],need) if r['margin_required']>0 else D(0)
            r['withdraw_request']=s['deposit']-r['term_return'] if terminal else min(r['deposit_available'],max(D(0),D(member['minimum_cash'])+r['margin_required']-r['cash_after_term']-r['capital_margin']))
            # Terminal loans are paid from realized investment cash before deposit returns.
            if terminal:
                if r['cash_after_term']+r['capital_margin']<s['loan']:raise ValueError('Terminal member cannot settle its loan')
                cash+=s['loan'];post(i,month,'loan','cash',s['loan'],'Terminal pool loan settlement');post('Treasury',month,'cash','loan_asset',s['loan'],'Terminal member loan settlement')
        for i in ids:rows[i]['withdrawal']=pay('withdraw',i,rows[i]['withdraw_request'])
        for member in members:
            i=member['id'];r=rows[i];s=old[i];r['cash_after_withdrawal']=r['cash_after_term']+r['capital_margin']+r['withdrawal']
            r['margin_paid']=r['margin_required']
            r['surplus_repayment']=D(0) if terminal else min(s['loan']-r['margin_paid'],max(D(0),r['cash_after_withdrawal']-r['margin_paid']-r['reserve_floor']))
            r['loan_after_repayment']=s['loan']-r['margin_paid']-r['surplus_repayment'];r['cash_after_repayment']=r['cash_after_withdrawal']-r['margin_paid']-r['surplus_repayment']
            if not terminal:
                amount=r['margin_paid']+r['surplus_repayment'];cash+=amount;post(i,month,'loan','cash',amount,'Mandatory margin and surplus principal repayment');post('Treasury',month,'cash','loan_asset',amount,'Member principal repayment')
            r['new_deposit']=D(0) if terminal else max(D(0),r['cash_after_repayment']-r['reserve_floor']);cash+=r['new_deposit']
            post(i,month,'deposit','cash',r['new_deposit'],'New pool deposit');post('Treasury',month,'cash','deposit_liability',r['new_deposit'],'Member cash deposit')
            r['cash_after_deposit']=r['cash_after_repayment']-r['new_deposit'];r['loan_request']=D(0) if terminal else max(D(0),D(member['minimum_cash'])-r['cash_after_deposit'])
            r['loan_capacity']=max(D(0),r['nav_cap']-r['loan_after_repayment']);r['loan_capped_request']=min(r['loan_request'],r['loan_capacity'])
        for i in spec['funding_order']:rows[i]['loan_advance']=pay('loan',i,rows[i]['loan_capped_request'])
        t['bank_draw']=sum((e['bank_draw'] for e in events),D(0));t['cash_before_bank_repayment']=cash
        t['bank_repayment']=bank_current if terminal else min(bank_current,max(D(0),cash-D(terms['minimum_cash'])))
        if cash<t['bank_repayment']:raise ValueError('Treasury cannot repay terminal bank debt')
        cash-=t['bank_repayment'];post('Treasury',month,'bank_debt','cash',t['bank_repayment'],'External bank principal repayment')
        t['bank_close']=bank_current-t['bank_repayment'];t['cash_before_dividend']=cash;t['owner_dividend']=cash if terminal else D(0);cash-=t['owner_dividend']
        t['cash_close']=cash;t['net_income']=t['loan_interest']-t['deposit_interest']-t['bank_interest']-t['fee'];t['retained_close']=tret+t['net_income']-t['owner_dividend']
        post('Treasury',month,'profit_loss','retained',t['net_income'],'Close monthly income');post('Treasury',month,'retained','cash',t['owner_dividend'],'Terminal owner distribution')
        for member in members:
            i=member['id'];r=rows[i];s=old[i]
            r['capital_cash']=min(D(member['capital_commitment'])-s['called']-r['capital_margin'],max(D(0),(D(0) if terminal else D(member['minimum_cash']))-r['cash_after_deposit']-r['loan_advance']))
            r['capital_contribution']=r['capital_margin']+r['capital_cash'];post(i,month,'cash','capital',r['capital_contribution'],'Draw on finite partner capital commitment')
            pre=r['cash_after_deposit']+r['loan_advance']+r['capital_cash'];r['cash_before_dividend']=pre;r['owner_dividend']=pre if terminal else D(0)
            r['cash_close']=pre-r['owner_dividend'];r['deposit_close']=s['deposit']-r['term_return']-r['withdrawal']+r['new_deposit'];r['loan_close']=r['loan_after_repayment']+r['loan_advance']
            r['net_income']=r['project_income']+r['sale_gain']+r['note_coupon']+r['deposit_interest']-r['loan_interest']-r['fee']
            r['capital_close']=s['capital']+r['capital_contribution'];r['retained_close']=s['retained']+r['net_income']-r['owner_dividend'];r['called_close']=s['called']+r['capital_contribution']
            r['capital_remaining']=D(member['capital_commitment'])-r['called_close'];r['assets']=r['cash_close']+r['deposit_close']+r['note_close']+r['investment_close'];r['liabilities']=r['loan_close'];r['equity']=r['capital_close']+r['retained_close'];r['balance_check']=r['assets']-r['liabilities']-r['equity']
            r['cash_gap']=max(D(0),(D(0) if terminal else D(member['minimum_cash']))-r['cash_close'])
            post(i,month,'profit_loss','retained',r['net_income'],'Close monthly income');post(i,month,'retained','cash',r['owner_dividend'],'Terminal owner distribution')
            if r['balance_check'] or r['cash_gap'] or r['capital_remaining']<0:raise ValueError('Member financial constraints failed: '+i+'/'+str(month))
            checks={'cash':r['cash_close'],'deposit':r['deposit_close'],'loan':-r['loan_close'],'note':r['note_close'],'investment':r['investment_close'],'capital':-r['capital_close'],'retained':-r['retained_close'],'profit_loss':D(0)}
            if any(accounts[i].get(k,D(0))!=v for k,v in checks.items()):raise ValueError('Independent double-entry member reconciliation failed: '+i+'/'+str(month))
            states[i]={'cash':r['cash_close'],'deposit':r['deposit_close'],'loan':r['loan_close'],'note':r['note_close'],'investment':r['investment_close'],'capital':r['capital_close'],'retained':r['retained_close'],'called':r['called_close']}
            if r['margin_paid']>0 and not terminal:regimes['nav_margin_payment'].append(month)
            if r['capital_contribution']>0:regimes['capital_call'].append(month)
            if r['margin_paid']+r['surplus_repayment']>0 and not terminal:regimes['member_loan_repayment'].append(month)
            if member['contract']=='term_depositor' and r['deposit_open']>0 and r['term_return']==0 and r['loan_advance']>0:regimes['term_locked_borrowing'].append(month)
            if member['contract']=='term_depositor' and r['term_return']>0:regimes['term_release'].append(month)
            if member['contract']=='nav_borrower' and r['loan_advance']>0 and r['loan_request']>r['loan_advance'] and r['loan_advance']==r['loan_capacity']:regimes['nav_cap_binding'].append(month)
        t['member_loans']=sum((r['loan_close'] for r in rows.values()),D(0));t['member_deposits']=sum((r['deposit_close'] for r in rows.values()),D(0));t['assets']=t['cash_close']+t['member_loans'];t['liabilities']=t['bank_close']+t['member_deposits'];t['equity']=t['capital']+t['retained_close'];t['balance_check']=t['assets']-t['liabilities']-t['equity']
        checks={'cash':t['cash_close'],'loan_asset':t['member_loans'],'deposit_liability':-t['member_deposits'],'bank_debt':-t['bank_close'],'capital':-t['capital'],'retained':-t['retained_close'],'profit_loss':D(0)}
        if t['balance_check'] or t['bank_close']<0 or t['bank_close']>D(terms['bank_limit']) or (not terminal and t['cash_close']<D(terms['minimum_cash'])) or any(accounts['Treasury'].get(k,D(0))!=v for k,v in checks.items()):raise ValueError('Independent treasury journal reconciliation failed')
        g={'cash_open':sum((r['cash_open'] for r in rows.values()),D(0))+t['cash_open'],'cash_close':sum((r['cash_close'] for r in rows.values()),D(0))+t['cash_close'],
           'gross_assets':sum((r['assets'] for r in rows.values()),D(0))+t['assets'],'gross_liabilities':sum((r['liabilities'] for r in rows.values()),D(0))+t['liabilities'],
           'eliminate_loans':t['member_loans'],'eliminate_deposits':t['member_deposits'],'equity':sum((r['equity'] for r in rows.values()),D(0))+t['equity'],
           'net_income':sum((r['net_income'] for r in rows.values()),D(0))+t['net_income'],'capital_contribution':sum((r['capital_contribution'] for r in rows.values()),D(0)),
           'owner_dividend':sum((r['owner_dividend'] for r in rows.values()),D(0))+t['owner_dividend']}
        g['assets']=g['gross_assets']-g['eliminate_loans']-g['eliminate_deposits'];g['liabilities']=g['gross_liabilities']-g['eliminate_loans']-g['eliminate_deposits'];g['balance_check']=g['assets']-g['liabilities']-g['equity']
        g['external_income']=sum((r['project_income']+r['sale_gain']+r['note_coupon']-r['fee'] for r in rows.values()),D(0))-t['bank_interest']-t['fee'];g['income_elimination_check']=g['net_income']-g['external_income']
        g['cfo']=sum((r['project_dividend']+r['note_coupon']-r['fee'] for r in rows.values()),D(0))-t['bank_interest']-t['fee'];g['cfi']=sum((r['project_sale']+r['note_redemption']-r['note_purchase'] for r in rows.values()),D(0));g['cff']=t['bank_draw']-t['bank_repayment']+g['capital_contribution']-g['owner_dividend'];g['cash_check']=g['cash_open']+g['cfo']+g['cfi']+g['cff']-g['cash_close']
        if g['balance_check'] or g['income_elimination_check'] or g['cash_check']:raise ValueError('Independent consolidated identity failed')
        if sum(accounts[i].values(),D(0))!=0:raise ValueError('Unbalanced journal')
        if t['bank_repayment']>0 and not terminal:regimes['bank_repayment'].append(month)
        if any(r['new_deposit']>0 for r in rows.values()) and any(r['loan_advance']>0 for r in rows.values()):regimes['cross_member_funding'].append(month)
        months.append(rows);stages.append({'treasury':t,'events':events});group.append(g);tcash,bank,tret=t['cash_close'],t['bank_close'],t['retained_close']
    return {'monthly':months,'treasury':stages,'group':group,'journal':journal,'regimes':{k:sorted(set(v)) for k,v in regimes.items()},
            'checks':{'all_double_entry_balanced':all(sum(a.values(),D(0))==0 for a in accounts.values()),'all_subsidiary_balances':True,'all_treasury_balances':True,'all_group_balances':True,'all_group_cash_balances':True,'all_group_income_eliminations':True,'no_balance_plug':True,'terminal_cash':str(tcash),'terminal_bank_debt':str(bank)}}
