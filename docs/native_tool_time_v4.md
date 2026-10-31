# Prospective native tool-clock policy 4

The version-four modules are a separate namespace. They preserve every earlier
policy, result, score, reservation and recipe. A source must declare
`tool_time_policy_version: 4` before selection; version-three selections cannot
enter the new runner. Model/effort, the strict tool SUM below 1800 seconds,
exclusion of model response time, the 14400-second operational guard, resources,
17-file export and the existing factory stream-retry8 profile remain unchanged.

`clock_resource_frontier_v4.account_trial_tool_time_v4` first retains the complete
version-three measurement. A known exact or supported stop bound is reused. If
that is unknown, the new complete-clock route requires one normal native tail,
one normal CLI-stream tail, all ordered command/file signatures, statuses and
exit codes, balanced wrapper outputs, and unique static ownership. Missing,
ambiguous, dynamic or unsupported evidence remains unknown. The only grammar
extension is optional lowercase `i` on the already restricted read-only metadata
regex. The literal dispatch/fanout limit stays 32; dynamic dispatch is refused.

The conservative arithmetic uses integer nanoseconds. For primitive endpoints
`s,e`, reported duration `d`, and margin `m=2ms`, its upper bound is
`max(d,e-s)+m`. Missing FileChange durations use the entire endpoint span and
cannot earn overlap credit. A primitive whose two clocks differ by more than
the frozen 5ms threshold also earns no overlap credit.

For an eligible primitive, the common interior is:

```
[max(s,e-d)+m, min(e,s+d)-m]
```

This intersects the endpoint span and both possible endpoint anchors of the
reported duration, then shrinks the endpoints. Under the retained clock model
(millisecond-quantized endpoints and the observed duration/span envelope), only
this common interior may remove duplicate wrapper coverage. It does not claim
to repair arbitrary system-clock errors or recover an exact duration.

For each wrapper, intersect those interiors with its own interval after
shrinking both endpoints by2ms. Only a uniquely owned launch or a literal poll
of that owned native process is eligible. Take the **union** of intersections
within that wrapper. Subtract that union from its full wall upper bound. All
uncovered wrapper time stays charged; concurrently running unrelated tools
cannot supply credit. Every primitive upper is still summed separately, so
parallel work never becomes overall wall time.

```
upper = SUM(primitive uppers)
      + SUM(wrapper wall +2ms - proved owned overlap union)
```

An upper bound strictly below the budget is `verified_owned_overlap_bound`.
An upper at or above it is unknown, never a demonstrated budget failure. Bound
receipts retain `cumulative_tool_seconds=None` and `cumulative_exact_ns=None`.
They include native/stream coverage, all interval-credit proofs, the preserved
version-three receipt and complete source hashes.

The retained N360 P01 FM diagnostic separately demonstrates a conservative
1772.694115012-second upper bound from 64 primitives and 59 wrappers. Its original
raw reward 0, effective reward null and version-three unknown are unchanged.
Future attempts must freeze the new policy prospectively. This feature launches
no model and grants no quality, financial, difficulty or release qualification.
