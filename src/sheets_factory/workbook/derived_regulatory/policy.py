"""Versioned public business policy text, without forecast values or recipes."""
from pathlib import Path


def public_policy(*, include_leases=False):
    text=Path(__file__).with_name('POLICY.md').read_text().split('## Final financial outputs and oracle')[0]
    if not include_leases:return text
    replacements={
      'This is a fictional incremental resilience investment programme, not a statement of current UK law or an amendment to any licensee\'s actual allowed revenue.':
      'This is a fictional incremental resilience investment and lease programme, not a statement of current UK law or an amendment to any licensee\'s actual allowed revenue.',
      'All programme spending qualifies; no opening programme balances, disposals or operating expenses exist.':
      'All capital programme spending qualifies; no opening programme balances or capital disposals exist. Leases follow their separate explicit public contracts.',
      'Pre-allowance taxable profit is nominal regulatory depreciation revenue plus nominal allowed return plus claim carrying interest, less cash debt interest and tax capital allowances.':
      'Pre-allowance taxable profit is nominal regulatory depreciation revenue plus nominal allowed return plus claim carrying interest plus the eligible regulatory lease allowance, less cash capital-debt interest, tax capital allowances and the total current lease cash tax deduction. Lease book depreciation, lease book interest and signed lease gains are excluded from this direct notional-tax computation; the lease cash deduction replaces them.',
      'Each year creates one claim for nominal regulatory depreciation plus nominal allowed return plus that year\'s tax allowance.':
      'Each year creates one claim for nominal regulatory depreciation plus nominal allowed return plus that year\'s tax allowance plus the eligible regulatory lease allowance. The public lease allowable fraction applies to the separately supplied total regulatory lease expense, rounded once to pennies. This lease allowance shares the same claim vintage, two-year collection lag, carrying interest, annual cap and FIFO collection priority as capital recovery.',
      'Owner capital supplies exactly a negative residual cash requirement after actual customer receipts, capital spending, debt draws/repayments, interest and current tax; positive residual cash is distributed.':
      'Owner capital supplies exactly a negative residual cash requirement after actual customer receipts, capital spending, capital-debt draws/repayments, capital-debt interest, current tax and total actual lease cash; positive residual cash is distributed.'}
    for before,after in replacements.items():
        if before not in text:raise ValueError('Public regulatory policy version does not match lease amendment')
        text=text.replace(before,after)
    return text+('\n\n## Lease book and cash reporting bridge\n\n'
      'Use the supplied lease model opening/closing ROU assets and lease liabilities without indexation. '
      'Programme net income deducts lease book depreciation and lease book interest and adds signed lease termination gains, '
      'in addition to the capital programme income and expenses. Total assets include closing lease ROU; total liabilities '
      'include both capital debt and lease liabilities. Lease recognition, modifications and terminations are noncash except '
      'the stated total cash amounts; the independent net ROU/liability bridge must reconcile with depreciation, interest, '
      'total lease cash and signed gains. No extra lease cash is deducted for a displayed subcomponent.\n\n'
      'For this hypothetical regulatory cash report, all total lease cash, including direct costs and termination fees, is '
      'classified as operating. Customer receipts less capital-debt cash interest, current tax and total lease cash are CFO. '
      'Capital spending is investing. Capital-debt principal and programme owner contributions/distributions are financing. '
      'This is an explicit reporting convention for the programme, not an assertion of IFRS cash-flow classification. '
      'The three cash-flow sections reconcile to the programme cash movement. Parent funding and investments follow '
      'their separately supplied contracts and do not change these programme definitions.\n')
