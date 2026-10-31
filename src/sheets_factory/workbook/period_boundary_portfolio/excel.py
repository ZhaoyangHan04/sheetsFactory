"""Independent native formula emitter. It imports no financial oracle."""
from datetime import date

from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from .spec import load_spec, RULES, FAULTS

SHEETS = ('Business Policies', 'Assumptions', 'Fiscal Calendar', 'Operations', 'Debt Service', 'Equity Cashflow', 'Valuation')
MONEY = '#,##0.00;[Red](#,##0.00)'


def emit_workbook(book, value, *, faults=()):
    s=load_spec(value);faults=set(faults);assert faults<=set(FAULTS)
    assert not any(ws._cells for ws in book.worksheets), 'Use a fresh workbook'
    for ws in list(book.worksheets):book.remove(ws)
    for name in SHEETS:book.create_sheet(name)
    book.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True)
    bindings={'kind':'synthetic_period_boundary_private_bindings','version':1,'derived':[],'inputs':[]}
    def literal(sheet,cell,value,kind='text',path=None):
        c=book[sheet][cell];c.value=value
        if kind=='date':c.number_format='dd-mmm-yyyy'
        elif kind=='money_pence':c.number_format=MONEY
        elif kind=='rate':c.number_format='0.00%'
        if path is not None:bindings['inputs'].append({'sheet':sheet,'cell':cell,'kind':kind,'path':path,'worksheet_scale':100 if kind=='money_pence' else 1})
    def formula(sheet,cell,text,path,kind='money_pence'):
        if kind=='money_pence':text=f'ROUND({text},2)'
        c=book[sheet][cell];c.value='='+text;c.number_format='dd-mmm-yyyy' if kind=='date' else MONEY if kind=='money_pence' else '0'
        bindings['derived'].append({'sheet':sheet,'cell':cell,'formula':'='+text,'expected_path':path,'kind':kind,'worksheet_scale':100 if kind=='money_pence' else 1})
    def header(sheet,row,labels):
        for i,text in enumerate(labels,1):literal(sheet,f'{get_column_letter(i)}{row}',text)
    def q(sheet,cell):return f"'{sheet}'!{cell}"
    A=lambda cell:q('Assumptions',cell)
    literal('Business Policies','A1','Synthetic financial forecast — business policies')
    for i,text in enumerate(RULES,3):literal('Business Policies',f'A{i}',text);book['Business Policies'][f'A{i}'].alignment=Alignment(wrap_text=True);book['Business Policies'].row_dimensions[i].height=60
    literal('Assumptions','A1','Operating and financing assumptions (GBP)')
    for row,label,key,kind in [(3,'Forecast starts','start_month','date'),(4,'Calendar months','months','integer'),(5,'Terminal collection lag (days)','terminal_settlement_lag_days','integer'),(6,'Annual equity discount rate','discount_rate','rate'),(7,'Cash tax rate','tax_rate','rate'),(8,'Initial project expenditure','initial_project_expenditure_pence','money_pence')]:
        v=s[key];v=date.fromisoformat(v) if kind=='date' else v/100 if kind=='money_pence' else float(v) if kind=='rate' else v
        literal('Assumptions',f'A{row}',label);literal('Assumptions',f'B{row}',v,kind,[key])
    header('Assumptions',11,['Business','Fiscal end month','Monthly revenue (GBP)','Operating margin','Annual growth','Receivable days','Payable days','Opening NWC (GBP)'])
    bfields=['name','fiscal_end_month','monthly_revenue_pence','operating_margin','annual_growth','receivable_days','payable_days','opening_working_capital_pence']
    for bi,b in enumerate(s['businesses']):
        for ci,k in enumerate(bfields,1):
            kind='money_pence' if k.endswith('_pence') else 'rate' if k in ['operating_margin','annual_growth'] else 'integer' if type(b[k]) is int else 'text'
            v=b[k]/100 if kind=='money_pence' else float(b[k]) if kind=='rate' else b[k]
            literal('Assumptions',f'{get_column_letter(ci)}{12+bi}',v,kind,['businesses',bi,k])
    facility_header=15+len(s['businesses']);fr=facility_header+1
    header('Assumptions',facility_header,['Facility','Repayment type','Opening debt (GBP)','Annual rate','ACT basis','Maturity date','Quarterly principal (GBP)'])
    ffields=['name','type','opening_principal_pence','annual_rate','day_count_basis','maturity_date','quarterly_principal_pence']
    for fi,f in enumerate(s['facilities']):
        for ci,k in enumerate(ffields,1):
            kind='money_pence' if k.endswith('_pence') else 'rate' if k=='annual_rate' else 'date' if k=='maturity_date' else 'integer' if type(f[k]) is int else 'text'
            v=f[k]/100 if kind=='money_pence' else float(f[k]) if kind=='rate' else date.fromisoformat(f[k]) if kind=='date' else f[k]
            literal('Assumptions',f'{get_column_letter(ci)}{fr+fi}',v,kind,['facilities',fi,k])
    columns=['Period starts','Month end','Days in month']
    for b in s['businesses']:columns.extend([b['name']+' fiscal year end','Days in fiscal year','Revenue growth years'])
    header('Fiscal Calendar',4,columns)
    op_rows={};debt_rows={};calendar_columns={}
    for bi,b in enumerate(s['businesses']):
        cc=[get_column_letter(4+3*bi+j) for j in range(3)];calendar_columns[b['id']]=cc
        start=5+bi*(s['months']+5);op_rows[b['id']]=start
        literal('Operations',f'A{start-2}',b['name']);header('Operations',start-1,['Month end','Revenue','Operating costs','Operating profit','Receivables','Payables','Net working capital','Cash investment in NWC'])
    for fi,f in enumerate(s['facilities']):
        start=5+fi*(s['months']+5);debt_rows[f['id']]=start
        literal('Debt Service',f'A{start-2}',f['name']);header('Debt Service',start-1,['Month end','Opening principal','Accrual days','Cash interest','Principal repaid','Closing principal','Cash debt service','Debt balance check'])
    header('Equity Cashflow',4,['Month end','Revenue','Operating profit','Cash interest','Cash tax','Principal repaid','Investment in NWC','Equity cash flow','Cash-flow check'])
    for i in range(s['months']):
        r=5+i;cal=lambda col:q('Fiscal Calendar',f'{col}{r}')
        formula('Fiscal Calendar',f'A{r}',f'EDATE({A("$B$3")},{i})',['periods',i,'start'],'date')
        end=f'DATE(YEAR(A{r}),MONTH(A{r})+1,1)' if 'next_month_start' in faults else f'EOMONTH(A{r},0)'
        formula('Fiscal Calendar',f'B{r}',end,['periods',i,'end'],'date')
        formula('Fiscal Calendar',f'C{r}',f'B{r}-A{r}+1',['periods',i,'days'],'integer')
        for bi,b in enumerate(s['businesses']):
            bc=12+bi;cy,cd,cg=calendar_columns[b['id']];fm=A(f'$B${bc}')
            end=f'DATE(YEAR(B{r}),12,31)' if 'calendar_year_fiscal_basis' in faults else f'EOMONTH(DATE(YEAR(B{r})+IF(MONTH(B{r})>{fm},1,0),{fm},1),0)'
            path=['businesses',b['id'],i]
            formula('Fiscal Calendar',f'{cy}{r}',end,path+['fiscal_year_end'],'date')
            formula('Fiscal Calendar',f'{cd}{r}',f'{cy}{r}-EOMONTH(EDATE({cy}{r},-12),0)',path+['fiscal_year_days'],'integer')
            initial=f'YEAR({A("$B$3")})' if 'calendar_year_fiscal_basis' in faults else f'YEAR({A("$B$3")})+IF(MONTH({A("$B$3")})>{fm},1,0)'
            formula('Fiscal Calendar',f'{cg}{r}',f'YEAR({cy}{r})-({initial})',path+['growth_years'],'integer')
            z=op_rows[b['id']]+i;last=f'G{z-1}' if i else A(f'$H${bc}')
            expressions={'A':(cal('B'),'period_end','date'),'B':(f'ROUND({A(f"$C${bc}")}*(1+{A(f"$E${bc}")})^{cal(cg)},2)','revenue_pence','money_pence'),
                'D':(f'ROUND(B{z}*{A(f"$D${bc}")},2)','profit_pence','money_pence'),'C':(f'B{z}-D{z}','costs_pence','money_pence'),
                'E':(f'ROUND(B{z}*12*{A(f"$F${bc}")}/{cal(cd)},2)','receivables_pence','money_pence'),
                'F':(f'ROUND(C{z}*12*{A(f"$G${bc}")}/{cal(cd)},2)','payables_pence','money_pence'),
                'G':(f'E{z}-F{z}','working_capital_pence','money_pence'),'H':(f'G{z}-{last}','investment_pence','money_pence')}
            for col,(text,field,kind) in expressions.items():formula('Operations',f'{col}{z}',text,path+[field],kind)
        for fi,f in enumerate(s['facilities']):
            z=debt_rows[f['id']]+i;fc=fr+fi;mat=A(f'$F${fc}');opening=f'F{z-1}' if i else A(f'$C${fc}');path=['facilities',f['id'],i]
            days=f'{cal("B")}+1-{cal("A")}' if 'unclipped_maturity' in faults else f'MIN({cal("B")}+1,{mat})-{cal("A")}'
            expressions={'A':(cal('B'),'period_end','date'),'B':(opening,'opening_principal_pence','money_pence'),
                'C':(f'IF(B{z}>0,MAX(0,{days}),0)','accrual_days','integer'),
                'D':(f'ROUND(B{z}*{A(f"$D${fc}")}*C{z}/{A(f"$E${fc}")},2)','interest_pence','money_pence'),
                'E':(f'IF({mat}<={cal("B")},B{z},IF(AND({A(f"$B${fc}")}="Quarterly principal",MOD(MONTH({cal("B")}),3)=0),MIN(B{z},{A(f"$G${fc}")}),0))','principal_paid_pence','money_pence'),
                'F':(f'B{z}-E{z}','closing_principal_pence','money_pence'),'G':(f'D{z}+E{z}','cash_service_pence','money_pence'),
                'H':(f'F{z}-B{z}+E{z}','balance_check_pence','money_pence')}
            for col,(text,field,kind) in expressions.items():formula('Debt Service',f'{col}{z}',text,path+[field],kind)
        sums=lambda sheet,col,rows:'SUM('+','.join(q(sheet,f'{col}{start+i}') for start in rows.values())+')'
        expressions={'A':(cal('B'),'date','date'),'B':(sums('Operations','B',op_rows),'revenue_pence','money_pence'),
            'C':(sums('Operations','D',op_rows),'profit_pence','money_pence'),'D':(sums('Debt Service','D',debt_rows),'interest_pence','money_pence'),
            'E':(f'ROUND(MAX(0,C{r}-D{r})*{A("$B$7")},2)','tax_pence','money_pence'),'F':(sums('Debt Service','E',debt_rows),'principal_pence','money_pence'),
            'G':(sums('Operations','H',op_rows),'investment_pence','money_pence'),'H':(f'C{r}-D{r}-E{r}-F{r}-G{r}','equity_cash_pence','money_pence'),
            'I':(f'H{r}-(C{r}-D{r}-E{r}-F{r}-G{r})','cash_check_pence','money_pence')}
        for col,(text,field,kind) in expressions.items():formula('Equity Cashflow',f'{col}{r}',text,['cashflows',i,field],kind)
    literal('Valuation','A1','Equity cash-flow valuation (GBP)')
    for r,label in [(3,'Valuation date'),(4,'Opening equity cash flow'),(5,'Terminal NWC collection date'),(6,'Terminal NWC receipt'),(7,'Equity net present value')]:literal('Valuation',f'A{r}',label)
    formula('Valuation','B3',f'{A("B3")}-1',['valuation','valuation_date'],'date')
    opens='SUM('+','.join(A(f'H{12+i}') for i in range(len(s['businesses'])))+')'
    draws='SUM('+','.join(A(f'C{fr+i}') for i in range(len(s['facilities'])))+')'
    formula('Valuation','B4',f'-({A("B8")}+{opens}-{draws})',['valuation','opening_equity_cash_pence'])
    lag='' if 'immediate_terminal_settlement' in faults else '+'+A('B5')
    formula('Valuation','B5',q('Fiscal Calendar',f'B{4+s["months"]}')+lag,['valuation','settlement_date'],'date')
    terminal='SUM('+','.join(q('Operations',f'G{start+s["months"]-1}') for start in op_rows.values())+')'
    formula('Valuation','B6',terminal,['valuation','terminal_working_capital_pence'])
    header('Valuation',11,['Cash-flow date','Equity cash flow (GBP)','Days from valuation','Present value (GBP)','Description'])
    for i in range(s['months']+1):
        r=12+i;terminal=i==s['months'];source=5+i
        formula('Valuation',f'A{r}','$B$5' if terminal else q('Equity Cashflow',f'A{source}'),['valuation','items',i,'date'],'date')
        formula('Valuation',f'B{r}','$B$6' if terminal else q('Equity Cashflow',f'H{source}'),['valuation','items',i,'cash_pence'])
        formula('Valuation',f'C{r}',f'A{r}-$B$3',['valuation','items',i,'elapsed_days'],'integer')
        formula('Valuation',f'D{r}',f'ROUND(B{r}/(1+{A("$B$6")})^(C{r}/365),2)',['valuation','items',i,'pv_pence'])
        literal('Valuation',f'E{r}','Terminal working capital' if terminal else f'Forecast month {i+1}')
    formula('Valuation','B7',f'B4+SUM(D12:D{12+s["months"]})',['valuation','equity_value_pence'])
    for ws in book:
        ws.freeze_panes='B5';ws.sheet_view.showGridLines=False
        for col in range(1,max(ws.max_column,2)+1):ws.column_dimensions[get_column_letter(col)].width=23
        ws.column_dimensions['A'].width=35
        for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17365D')
    book['Business Policies'].column_dimensions['A'].width=130
    bindings['sheetnames']=list(SHEETS);bindings['formula_count']=len(bindings['derived'])
    return bindings
