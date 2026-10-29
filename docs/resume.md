# 同一运行的终态续跑

本实现支持一个运行结束后的第二阶段补充构造。保留原 run_id、审计目录、起始时间、已有题目和用量，不拼接两个独立运行冒充一批结果。

```bash
./scripts/run.sh --resume outputs/runs/RUN_ID \
  --extra-manifest /path/to/explicit_fallback_sources.json \
  --max-candidates-per-seed 5 \
  --resume-reason '补充真实财务模型模块，继续原定20+20题目标' \
  --headless --exit-on-finish
```

每次续跑仍启动面板。目标题量、模型/provider 配置及 max_steps、补证和基础设施预算不能被续跑参数偷偷改变。增加 max_candidates_per_seed 是显式增加新的候选变体，不会让旧 task_id 获得新的修复预算。

## 前置条件

- run 状态必须为 completed、shortfall、failed 或 cancelled。
- 不允许存在 scheduled/running 等未完成任务、节点或调用记录。
- 生产者文件锁必须空闲。旧 CLI 若尚未采用文件锁，还检查 PID/进程持有的本运行 SQLite 文件，防止两个生产者同时写入。
- qualified、ready、rejected 的旧任务 ID 默认全部跳过。只有显式 `--repair-task` 授权的确认缺陷例外；仍不重置计数。

这是有意选择的最小可靠续跑边界：**不自动恢复被中断 agent 的半成品上下文**。发现未完成记录会明确拒绝，而不是猜测原有预算或把旧任务从第零轮重新执行。

## 补充来源

补充清单支持顶层 selected 或 sources 数组，每项至少有 local_path/source_path。声明 sha256/source_sha256 时必须与文件实际字节一致；未声明时计算并保存。只接收已存在的 xls/xlsx 文件。

清单被规范化后复制到本运行 private/resume 目录，并保存原清单哈希。原有种子池与补充池按 source SHA-256 合并。已有来源可以贡献新的业务模块变体，但不会成为新的来源分母。

financial_modeling_eligible、safe_modules、source_business_issues 等明确证据作为种子元数据保留。它们只影响候选规划，不能取代后续质量检查、独立恢复和真实 Harbor 控制。

## 保留和去重

- 已有 qualified/ready 题目仍占原配额，ready 题目继续等待真实控制验证。
- 从审计 targets 或对应最终版本的 private/plan.json 恢复已接受目标集合，防止新变体复制旧题。
- 旧 rejected task_id 不会隐式重试。需要不同模块时使用新的 vN task_id，保留相同 source_id；需要修复原题时使用下面的显式外审修复入口。
- 若无法恢复已接受题目的来源或目标集合，拒绝续跑，不取消去重保护。

## 可追溯性

写入 run.resumed 与 run.amended 事件，记录原因、前后配置哈希、额外来源清单哈希、保留任务数、剩余配额及代码阶段。续跑前后配置均保存独立快照。

累计 wall_seconds 是各实际执行阶段的墙钟之和，不把两阶段中间的空闲间隔算成计算时间。原始起始时间及 resumed_at 保留，用于还原完整日历时间线。

最终报告展示所有提示词澄清、配置/来源扩展与代码阶段事件。运行中的提示词变化不能被最终单一 Git SHA 隐藏；尤其是 /app 最终交付路径与 /workspace 临时诊断路径澄清，要保留前后 SHA 和实际原因。

## 显式修复已经终态的原题

```bash
./scripts/run.sh --resume outputs/runs/RUN_ID \
  --repair-task fm-EXISTING_ID --repair-task fm-ANOTHER_ID \
  --config /path/to/continuation_patch.yaml \
  --resume-reason '按已保存的外审编号修复原题，保留原来源和修复预算' \
  --headless --exit-on-finish
```

默认读取每题目录 `external_quality_review.json`，也可重复传入 `--repair-review /path/to/review.json`。支持单个 issue 对象或带 issues 数组的审阅对象。每个有效 issue 必须有 issue_id、problem_id、certainty=confirmed、claim、非空 evidence 和与路由表一致的 route_id/repair_route；提供 revision 时必须与当前版本一致。suspected、补证/基础设施路由、无证据或用尽 max_steps 的题目不能通过此入口重试。

启动前读取原始清单或已审计的补充清单，验证原来源 SHA-256，恢复原 plan、最新 diagnosis、标准化 baseline 和原计数。旧任务先进入 repair_pending，不再占 ready/qualified 配额；旧导出移入隔离目录，旧 Harbor 成绩只保存为历史。外审内容、原状态和原预算复制到本次续跑私有清单，并逐项写审计事件。

修复只运行 Normalize/Profile 恢复事实，不重新运行 PlanNode。RepairNode 先按外审 issue 编号提出修订；接受内容改动后 revision 加一，重新执行构造、独立公开恢复、轨迹诊断、导出和真实 Harbor。新版本不会继承旧版本的 qualified 或控制成绩。max_steps 固定，旧轮的补证/基础设施次数进入历史；只有真实进入新版本才开始该版本自己的计数。

Q03 的修复仅能修改 public_instruction，其他 plan 字段必须完全相同，标准化 baseline 的哈希也必须保持不变。修复 proposal 写入 external_repairs 子目录，避免覆盖已关闭版本的文件。若面板或凭据预检失败，尚未开始的 repair_pending 明确转为 rejected，保留原预算，之后仍可显式授权修复。

## 续跑并发与变体选择

配置补丁可调整 `run.max_parallel_sources` 和正整数 `agents.max_parallel_calls`；除调用并发外，agents 下的 model、reasoning_effort、roles、provider、timeout 等配置继续冻结。前后并发值写入 run.amended。

`run.variant_modes` 默认是 `[financial_modeling]`。显式配置为 `[financial_modeling, debugging]` 后，debugging 变体仅来自该模式已有 ready/qualified 的来源或显式 debugging_eligible=true 的来源。没有有效产出的坏来源不会盲目重试。financial modeling 仍要求正向模型资格或该模式已有有效产出；两种模式均按各自剩余配额调度、保留 source_id，并沿用目标集合重合度去重。
