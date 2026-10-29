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
- qualified、ready、rejected 的旧任务 ID 全部跳过，不重新创建上下文，不重置计数。

这是有意选择的最小可靠续跑边界：**不自动恢复被中断 agent 的半成品上下文**。发现未完成记录会明确拒绝，而不是猜测原有预算或把旧任务从第零轮重新执行。

## 补充来源

补充清单支持顶层 selected 或 sources 数组，每项至少有 local_path/source_path。声明 sha256/source_sha256 时必须与文件实际字节一致；未声明时计算并保存。只接收已存在的 xls/xlsx 文件。

清单被规范化后复制到本运行 private/resume 目录，并保存原清单哈希。原有种子池与补充池按 source SHA-256 合并。已有来源可以贡献新的业务模块变体，但不会成为新的来源分母。

financial_modeling_eligible、safe_modules、source_business_issues 等明确证据作为种子元数据保留。它们只影响候选规划，不能取代后续质量检查、独立恢复和真实 Harbor 控制。

## 保留和去重

- 已有 qualified/ready 题目仍占原配额，ready 题目继续等待真实控制验证。
- 从审计 targets 或对应最终版本的 private/plan.json 恢复已接受目标集合，防止新变体复制旧题。
- 旧 rejected task_id 不再重试；需要不同模块时使用新的 vN task_id，保留相同 source_id。
- 若无法恢复已接受题目的来源或目标集合，拒绝续跑，不取消去重保护。

## 可追溯性

写入 run.resumed 与 run.amended 事件，记录原因、前后配置哈希、额外来源清单哈希、保留任务数、剩余配额及代码阶段。续跑前后配置均保存独立快照。

累计 wall_seconds 是各实际执行阶段的墙钟之和，不把两阶段中间的空闲间隔算成计算时间。原始起始时间及 resumed_at 保留，用于还原完整日历时间线。

最终报告展示所有提示词澄清、配置/来源扩展与代码阶段事件。运行中的提示词变化不能被最终单一 Git SHA 隐藏；尤其是 /app 最终交付路径与 /workspace 临时诊断路径澄清，要保留前后 SHA 和实际原因。
