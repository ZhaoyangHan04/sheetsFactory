# 产量、时间与费用核算

报告器只读 SQLite 审计库和实际产物，不更新任务、不补跑模型，也不改变准出结论。输出 JSON、中文 Markdown 和可离线打开的独立 HTML。

```bash
.venv312/bin/python scripts/report_run.py outputs/runs/RUN_ID \
  --engineering-dir outputs/runs/PILOT_ID \
  --billing-scope-note '凭据计费窗口包含工程与试跑重叠及未记录的取消请求，不能逐调用归因。'
```

接口为 `generate_report(run_dir, ...) -> dict` 和 `write_reports(run_dir, output_dir=None, ...) -> dict`。后者返回三个输出路径及结构化报告。

## 产量的不同分母

| 指标 | 定义 |
| --- | --- |
| 归档扫描数 | 来源清单中实际扫描的不同工作簿数；本批 EUSES 为 720 |
| 种子池数 | 经过结构筛选而选入的来源数；本批为 70 |
| 预处理尝试数 | 单独的数据准备阶段尝试规范化和画像的来源数；本批为 70 |
| 可读取画像数 | 预处理成功得到可读取画像的数量；不能把尝试数当成功数 |
| 正式运行使用种子数 | 正式运行创建过候选任务的不同 source_id，包含早期拒绝 |
| 构造节点到达种子数 | 至少一题实际运行过 construct 节点的不同 source_id |
| 产题种子数 | 至少贡献一道已核验合格任务的不同 source_id |
| 候选题数 | 审计表中不同 task_id 的数量，变体分别计数 |
| 已核验合格题数 | 标记 qualified，且有合格诊断、实际 Harbor oracle/nop 和独立恢复产物证据 |

候选转化率 = 合格题数 / 候选题数。

源转化率 = 产题种子数 / 正式运行使用种子数。

每种子产题数 = 合格题数 / 正式运行使用种子数。

同一来源的 v1、v2 变体不是新的种子。两类任务也不能把同一工作簿重复算成两个来源。分母为零时显示未知，不输出虚假的 0% 或 100%。

## 准出证据

Harbor 读取 `harbor_controls.json` 或审计中的逐题控制记录。oracle 必须实际为 1，nop 必须实际为 0，matched 为 true，且没有异常。缺控制文件不是通过。

独立恢复检查对应最终版本的 `private/independent_recovery.json`：公开信息隔离标记、程序重放成功和重算值比较成功均需存在。诊断还需有同版本的可放行报告和完整的启用检查结果。

审计标记 qualified 与证据不一致时，报告分别保留“审计标记合格”和“已核验合格”，写出一致性警告，不修改原任务。

## 时间

- 正式运行墙钟时间使用 run.wall_seconds。
- 运行中的快照可显示从实际启动时间至报告时间的已过时间，并标为 live。
- 节点累计时间是所有执行尝试耗时之和，包括重试；并发时可能大于墙钟时间。
- 数据准备累计时间另列。未记录的预处理总墙钟保持未知。
- 报告展示时间使用 Asia/Shanghai，原始时间戳仍保留时区。

## Token

优先使用 CLI/Provider 实际返回的 input_tokens、output_tokens、cached_input_tokens 和 reasoning_output_tokens。缓存输入属于输入子集，推理输出属于输出子集，不再加入输入加输出总数。

每个字段保存已知合计、已知调用数、未知调用数和完整性标记。取消、超时或供应商未报告用量的调用不能算作零消耗。已知部分之和只是下限信息，不能在存在未知调用时称为完整总消耗。

可显式提供工程与试跑目录；这些调用按 call_id 去重，并排除正式运行中已出现的调用。工程用量独立展示，不混入正式管线用量。

## 网关账单

读取 `private/billing_start.json` 与 `private/billing_end.json`。金额计算为：

```text
USD = (结束 total_used - 开始 total_used) / quota_per_unit
```

只有币种明确为 USD、单位一致且计数单调时才计算。本环境 quota_per_unit 为 500000；这来自实际快照元信息，代码不把它当通用常量。不额外乘 usd_exchange_rate，也不把 quota 当作 token 数。

两个快照只证明整个凭据在该时间窗口的消耗。并行工程、试跑、取消请求及窗口外的正式调用都可能影响归因，故 `production_cost_usd` 始终保持未知，除非将来接入逐调用账单证据。

开始快照晚于管线启动时，报告明确指出未覆盖的秒数。可在 `private/billing_context.json` 保存 `scope_note` 和带时区的 `overlap_ended_at`；本次已知工程/试跑重叠持续至 UTC 12:14，应显示为北京时间 20:14。不得把该凭据窗口费用写成精确的正式运行费用。

## 诊断、修复与难度

最终问题实例、各版本诊断观测、检查执行状态和拒绝原因分别统计。多标签拒绝原因之和可能超过拒绝候选总数。重试不等于内容修订，内容修复按版本递增单独统计。

本轮目标 20 道 Financial Modeling 加 20 道 Debugging。难度及后续低通过率 gate 明确延后；报告不把开发尝试完成率写成正式 Pass@1。
