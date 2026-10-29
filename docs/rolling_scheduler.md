# Rolling 来源调度

随附 `quality40.yaml` 显式使用 `run.scheduler: rolling`：已完成来源可以进入下一合格 variant，同时其他来源的旧候选继续诊断或修复。旧配置缺少该字段时，代码仍使用 `source_batches`，保留全首轮和逐 variant 的批次 barrier。此选项只改变任务派发顺序。

```bash
./scripts/run.sh --resume outputs/runs/RUN_ID \
  --config config/pipelines/quality40_rolling_continue.yaml \
  --resume-reason '启用rolling调度，保持原配额和修复预算' \
  --headless --exit-on-finish
```

只允许已终态且没有活动任务/节点/调用的 run 续跑。现有 ProducerLease 仍阻止第二个 producer；scheduler 变更前后值写入 `run.amended`，模型、配额及修复预算不能随此开关改变。

## 执行边界

- `FactoryPipeline._construct_rolling()` 使用既有来源线程池和 `FIRST_COMPLETED`，每次来源完成后补投。优先级仍为较低 variant、原种子顺序。
- `busy_sources` 按完整来源 SHA 保证同源仅一个 future；该 future 的所有 modes 串行执行，再允许下一 variant。Normalize/Profile 与 `task_plans_vN.json` 因而没有同源并发 writer。
- 外部授权修复仍先结算，之后进入普通构造；不会与同来源新 variant 并行。
- `process_task.reserve()` 是唯一新候选占位者。配额按 `ready/qualified IDs ∪ inflight IDs` 计数，同一 ready task 不再重复占 active slot。
- 配额暂满返回 `quota_deferred`，不创建候选或消耗 variant。调度器根据已存在 ID 推导下一工作，不靠只增不减的来源游标。
- 任意已有 ID 都被跳过，旧 revision、补证、infra 和内容修复计数保持；新 variant 使用新 ID，仍必须满足目标重合度与完整质量检查。
- `_context()` 失败也会释放 permit。协调线程退出时等待已提交 source job 结算；不会把中断 context 冒充可恢复终态。

## Harbor 与补量

续跑启动先验证已有 ready/qualified，再开始新构造。rolling 的 ready 只是临时配额 credit；最终产量只统计 qualified。构造排空后由单一协调线程执行真实 Harbor。验证失败时，旧 ID 保持 rejected，可继续选择其他未创建的合格候选，直到达额或有限候选空间耗尽。

`_validate_exports()` 在整个“读取累计证明、staging、真实控制、写回”期间持有同 run 的 `harbor_validation.lock`。主流程和 sidecar 必须调用这个包装入口；锁文件保留，不删除。task ID、revision、revision hash、当前导出及 staging 的前后绑定检查全部保留，旧 proof 不能替代新版本验证。

## 审计与验证

`run.construction_started` 记录 scheduler；`scheduler.source_dispatched/completed` 记录来源、variant、modes 和实际任务；`scheduler.quota_deferred` 记录未获配额的意图；`scheduler.refill_after_harbor` 与 `scheduler.exhausted` 记录回补或真实耗尽。`source_jobs_inflight` 投影当前来源并发。转化率仍以实际 tasks 表为候选分母。

离线测试集中在 `tests/test_rolling_scheduler.py`：异来源 straggler、同源串行、配额并发与释放、旧预算/新身份、Harbor启动先验与失败补量、旧批次模式、线程/进程验证文件锁、resume 枚举审计。真实 Harbor 证明标准由原有 Harbor batch 测试继续验证。
