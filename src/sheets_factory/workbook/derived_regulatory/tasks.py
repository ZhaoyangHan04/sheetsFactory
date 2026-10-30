"""Automatically select complete new business schedules; no cell answers in text."""
from pathlib import Path
import openpyxl
from .schema import SHEETS


def propose_task(baseline):
    book=openpyxl.load_workbook(baseline,data_only=False,keep_links=False)
    try:
        ranges=[]
        for key in ('rav','tax','claims','losses','annual'):
            sheet=book[SHEETS[key]]
            formulas=[cell for cell in sheet._cells.values() if cell.data_type=='f']
            if not formulas:raise ValueError('Missing hypothetical business formula family')
            lo_r,hi_r=min(c.row for c in formulas),max(c.row for c in formulas)
            lo_c,hi_c=min(c.column for c in formulas),max(c.column for c in formulas)
            for row in sheet.iter_rows(min_row=lo_r,max_row=hi_r,min_col=lo_c,max_col=hi_c):
                if any(cell.data_type!='f' for cell in row):raise ValueError('Nonformula cell in complete business schedule rectangle')
            ranges.append({'sheet':sheet.title,'range':sheet.cell(lo_r,lo_c).coordinate+':'+sheet.cell(hi_r,hi_c).coordinate,
                'reason':'Reconstruct the complete additional programme schedule.',
                'business_rule':'Apply the public hypothetical programme policies and preserve the upstream forecast.'})
        instruction=('Complete the hypothetical incremental capital programme model for the regulatory years shown in the workbook. '
            'Read Reopener Brief and use the provided annual assumptions, investment batches and published forecast context. '
            'Reconstruct the missing asset, tax-basis, loss-vintage, revenue-claim and financial-statement schedules. '
            'The completed model must reflect commissioning, disallowances, tax reclassification, tax allowance, delayed receipts and owner funding consistently, '
            'including the closing balances at the end of the stated horizon. Preserve the provided inputs and upstream forecast. '
            'Save the completed workbook to the required output path.')
        return {'public_instruction':instruction,
            'public_rules':['Use the provided inputs and the explicit hypothetical policies in Reopener Brief for every reconstructed programme schedule.'],
            'reference_evidence':'All new financial outputs are independently reproduced by a penny-posted Decimal journal, then checked against actual LibreOffice calculation and two further stable normalizations; the published upstream forecast is provided context, not the answer to the new policy model.',
            'edits':[],'mask_ranges':ranges,'scenario_inputs':[]}
    finally:book.close()
