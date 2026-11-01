# Investment-policy business revision

The current revision retains the ten materials listed in [the retained manifest](../reports/history/operating_report_factory_business_retained_v1.json). Their task bytes and original execution results stay unchanged. The other ten materials from the earlier release retain their historical scores but do not meet this revision's business-error admission criterion. [Current disposition](../reports/operating_report_factory_business_revision_status.json) distinguishes these decisions from primary rewards.

## Construction mechanism

The new source retains the 200 hypothetical businesses, six report layouts and 211-sheet management-report structure. It adds an investment posting feed with a separate currency scale and a year-specific sign convention. Equity-method and cost-method income, cash dividends, capital returns and three explicit hypothetical parent-tax classes determine the economic bridge. A wrong interpretation can therefore change investment income, tax, net income, cash, investment carrying value and retained earnings.

The workbook supplies these rules in ReadMe and each entity's policy line. A separate labelled cash-receipt schedule identifies dividend and capital-return receipts. The cash-bridge output is labelled **Net cash before owner distributions**; it includes investment cash receipts and does not claim to be an operating-cash-flow subtotal. Private internal field identifiers retain the earlier report vocabulary.

All eight raw B01–B08 cases were frozen before production financial forwards or model calls. B01 introduces upstream sign interpretation; B02 mixes accounting methods; B03 mixes tax treatments; B04 also separates feed/report scales and changes direction between forecast years. B05–B08 add capital-return classifications and different deterministic policy assignments. These are different contracts over a shared business backbone, not eight unrelated public spreadsheet sources.

## Independent reference and task engineering

The A oracle uses a chronological Decimal calculation; B independently uses a rational cumulative journal. Each reuses its own earlier operating oracle for unchanged operating facts. Neither reads the other bridge implementation or Excel formulas. Their full economic, raw report and two-decimal maps must agree across all 93,510 financial fields.

The emitter creates an uncalculated workbook without seeded formula values. Three actual bounded LibreOffice calculations check the complete financial inventory, supplied literals and repeated-value stability. The resulting native goal remains private. Source audits retain any floating-boundary observations separately; these cannot establish business difficulty.

Financial Modeling removes all 88,676 financial formulas while preserving source facts, policies, labels and nonapplicable literals. Debugging changes income recognition, taxable earnings, cash-receipt and investment-rollforward formulas. Its actual modified-value set is measured after recalculation and includes downstream effects; injected formula count and affected value count are reported separately.

Both task modes use the existing seventeen-file Harbor export and 2-CPU/32-GiB runtime. The first engineered cases are B04 and B05. Their source checks cover all 93,510 fields and contain zero primary boundary observations. Their actual task changes are respectively 88,676/24,086 and 88,676/23,288 cells for completion/repair. Engineering completion does not confer difficulty or final release qualification.

## Difficulty and semantic diagnosis

The new native development entry reserves each material before its single Codex CLI `gpt-6.1-sol/xhigh` attempt. It shares the earlier permanent material registry, makes zero outer retries, and retains actual role-resource and cumulative-tool evidence. Primitive tools must sum to less than 1,800 seconds; model response time is excluded. A 14,400-second operational guard cannot supply a model-failure score.

The auxiliary `business_failure_evidence` check is enabled by default in [its profile](../config/business_difficulty_v1.yaml). It consumes the complete native-recalculated input, reference and submission maps, with exact workbook, receipt, semantic-binding and monetary-scale references. It requires a primary-value mismatch in a core financial field and a raw economic difference beyond its declared absolute and relative numerical thresholds. Display rows, pure growth/ratio differences, missing fields and type changes receive separate diagnostic categories.

This auxiliary decision never rewrites the primary OJ reward. A primary zero caused only by floating-point boundaries cannot qualify a new business-difficulty task. Missing execution, timing or resource evidence remains unknown. An economic witness records an observed business-value error; it does not claim to establish a unique internal reasoning cause.

Public and reference semantic reviews run in separate workspaces with Codex CLI `gpt-6-sol/high`. They review the new source and policies directly. Shared template reviews and individual engineering/execution evidence have distinct scopes. Final publication still requires actual controls and the declared difficulty evidence.

## Entry points

```bash
.venv312/bin/python scripts/build_associate_bridge_business_batch.py \
  --raw-manifest /path/to/frozen/raw/manifest.json --case B04 \
  --output outputs/research/new_business_engineering

.venv312/bin/python scripts/run_business_revision_frontier.py prepare \
  --batch outputs/research/new_business_engineering/engineered_batch.json \
  --output outputs/difficulty/new_business_development --run --concurrency 2

.venv312/bin/python scripts/diagnose_associate_bridge_business_attempts.py \
  --batch outputs/research/new_business_engineering/engineered_batch.json \
  --terminal outputs/difficulty/new_business_development/terminal.json \
  --output outputs/research/new_business_diagnosis
```

Each entry starts its own audit dashboard. Construction, raw model traces and independent financial records remain private under `outputs/`. These commands use fresh output directories and do not overwrite earlier runs.
