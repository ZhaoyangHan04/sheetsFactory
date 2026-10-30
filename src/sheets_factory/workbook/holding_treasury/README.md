Annual holding partnership adapter
==================================

The parent owns the regulatory programme and a minority interest in the provided
operating project. The programme is consolidated; the operating interest uses
equity-method accounting. Public custom policies are emitted in `Holding Brief`.
All source references remain live formulas. Neither implementation imports the
other implementation or its financial helpers.

Integration
-----------

* Load an explicit public JSON spec. The measured development case is
  `config/derived_holding_treasury_v2.json`; v1 remains a rejected mechanism case
  because it did not produce a mandatory margin repayment.
* `ledger.simulate_parent(spec, programme_bridge, operating_ledger, operating_spec)`
  accepts the regulatory `annual_bridge` dictionary keyed by FY, or its rows.
  The operating ledger is independently replayed from the original public project
  spec. Its original January 2027–December 2029 dates must remain unchanged.
* `excel.emit_parent(book, spec, programme_annual_refs, operating_refs)` appends
  five holding sheets. Annual programme references use the fields listed in
  `schema.PROGRAMME_FIELDS`. Each reference is an absolute Excel reference,
  without a leading equals sign.
* `operating_refs` contains `equity_paid_in`, `equity_exit`, and a chronological
  `monthly` list of 36 records containing `date`, `net_income`, and `dividend`
  references. The live project equity exit must be after its final dividend.
* `validate.audit_workbook(recalculated_path, holding_ledger,
  emitted['bindings'], spec=spec)` checks all 2,020 new formulas, typed dates,
  public numeric controls, full formula coverage, native errors and independent
  journal reconciliations. `expected_cells(ledger, bindings)` supplies the exact
  independent `(sheet, cell) -> value` mapping to an outer builder.

Accounting boundaries
---------------------

The programme already pays lease cash. Its owner calls and distributions are the
only programme cash transactions at the parent. The parent never pays those
lease amounts again. Nominal GBP RAV and eligible claims secure parent debt only
after subtracting programme debt and lease liabilities. A fixed forecast GBP per
USD assumption applies to the original USD associate; no project dates move.

The annual settlement funds all cash uses before payment. Funding-stage deficits
are requirements, not an unlisted overdraft. Exhausted finite LP commitments
raise an error independently and produce `NA()` in the Excel model. Each posted
monetary line is rounded to cents. FY2043 retains the continuing programme's
actual closing assets and liabilities.

The parent journal independently records equity-method income, OCI, dividends,
investment costs and disposal. Consolidation explicitly removes programme
investment/equity, duplicated earnings/OCI and both internal cash-flow legs in
their original categories. The operating associate remains an investment.

Validation status
-----------------

Seven small numerical tests cover calendar mapping, separate USD/GBP posting,
finite LP exhaustion, senior collateral claims, changing haircuts and future
interest, journal balance, elimination and uncached-workbook rejection. A small
provided-input fixture passed real LibreOffice 24.2/openpyxl 3.1.5 for all 2,020
formula bindings and a second typed-stability calculation. This fixture is not a
production source or task qualification. The combined source must independently
replay every operating, lease, programme and holding ledger, then pass complete
actual LibreOffice audit and stability checks.
