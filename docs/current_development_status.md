# 当前开发状态

更新于 2026-10-31 12:46 UTC。正式难度交付为 **0 Financial Modeling + 0 Debugging**；旧质量批次的 20+20 原样保留。根目录 `SpreadsheetEval/` 尚未发布。下面的开发材料不能代替最终冻结集成绩或全目录 oracle 结果。此前实验的详细记录另见[历史开发记录](development_history.md)。

## 证据分层

| 材料 | 已完成 | 尚未完成 |
| --- | --- | --- |
| H01 两类任务视图 | 来源完整财务验算；补全七次、调试十一次实际计算；五项本地对照；真实 Harbor 两类均 oracle=1、nop=0；两类实际公开恢复完整通过 | 十二项正常质量诊断、有效最强模型成绩、最终确认；目前停止继续投入此容易来源 |
| M02 两类任务视图 | 来源和两类实际视图完整验算；两份首次最强模型尝试均已结束；补全原始 verifier=1、完整目标正确 | 两次 CLI 断流均导致正式分数为空；补全不是困难度失败，不重采样；公开恢复、十二项质量、真实 Harbor、最终确认未完成 |
| P01–P20 原 240 项池 | 二十份原始合同共同固定；20/20 完整独立财务与矩阵交叉核对；已知 P01/P02/P04/P05/P06/P07/P08/P09/P10 九份完整参考通过 | P03/P11/P12/P14 原 best 达限时仅 FEASIBLE，被拒绝且不重试；其余仍运行；没有来源工作簿或任务资格 |
| L360-P01–P20 新 360 项池 | 全部原始合同先固定；20/20 实际独立财务与 941×360 矩阵核对通过；完整参考池准备与小型实际传输通过 | 最佳及排除赢家后的次佳参考尚待实际终态；来源工作簿、任务视图、模型难度与正常质量均未执行 |
| M01 参考研究 | best 原生 OPTIMAL，双矩阵、财务和实际资源通过 | 排除完整赢家后的 runner 在原 3600 秒终态仅 FEASIBLE，不能证明唯一性；停止该轮，不构造来源 |

H01 的两次首次最强模型尝试均因服务连接中断自然结束，`NetworkConnectionError`、reward=null、计分题数 0。10:50 UTC 服务重新返回正常的未授权鉴权响应，只说明服务可响应鉴权，不证明推理连接稳定。M02 调试于 11:08 UTC 因原生 CLI 连接恢复耗尽而终止，`NonZeroAgentExitCodeError`、reward=null、计分题数 0，原始 verifier=0 来自没有提交文件。M02 补全随后也因原生断流结束，但其已经提交的工作簿得到原始 verifier=1，全部 1,015,908 处目标匹配。原始零重试终态、无正式分数状态与用量全部保留；不将补全当成难题失败或重新采样。工具时钟的原始不一致状态仍为 UNKNOWN，原生日志中的约 1661 秒时长合计只是诊断信息，不能冒充预算证书。

M02 的两个预声明工程尝试分别用 SCIP 和 CP-SAT，在与模型相同的 2 CPU/32 GiB 下各运行原定 1800 秒。最终精确目标分别为 826,282,354 与 826,029,020 便士，均未达到已知正确值 826,417,506；两套完整约束、实际资源与所属容器清理通过。原生日志的圆整显示及行连接解析限制另行更正保留。这是默认程序路线的工程信号，不能充当最强模型失败或难度准出。

## 产线实现

正常质量入口是 `scripts/run_linear_capital_quality.py`，默认配置为 `config/pipelines/linear_capital_quality_v1.yaml`，节点注册为 `config/task_adapters/linear_capital_portfolio_nodes.yaml`。它复用原调度、轨迹诊断、编号检查和修复路由，默认启用全部十二项检查；候选试解成功与否均需诊断。来源与实际视图经过完整冷验证后，以当前进程中的不透明凭据复用，持久化 JSON 标记不能自行授予资格。

公开恢复只接收公开工作簿、题面和通用程序，独立容器没有私有参考挂载。参考生产与公开恢复的离线资源单独声明；模型和评分仍采用 2 CPU、32 GiB，以及严格少于 1800 秒的累计工具时间。H01 两类首次实际工程恢复已全部通过：两次公开求解、四次实际 LibreOffice 重算，两次各 1,184,646 处完整类型稳定性均零差异；分别完整匹配 1,015,908 和 297,064 处变化，缺失、多改、错值均为零。六个所属容器已确认移除，面板和租约正常关闭。统一交接为 `outputs/research/linear_H01_public_recovery_engineering_pair_20261031T110000Z/handoff.json`。本轮没有 LLM、轨迹或 Harbor 调用，不代替全部十二项质量检查，现停止 H01 后续调用。

首轮真实只读接入预检在任何模型、求解或 LibreOffice 调用前拒绝：递归证据遍历误把容器内 `/app/solver.log` 当成宿主文件。原失败保留，已增加受实际容器挂载和宿主完整文件清单约束的路径映射；任意缺失宿主证据仍必须拒绝。59 项针对性检查、真实 H01 证据图的 100 份宿主文件与 10 个映射通过。完整接入预检修订版于 10:58 UTC 通过，用时 1311.30 秒，未调用模型、求解或 LibreOffice；它完整复核了已有实际证据，不是新一轮任务计算。此前审查发现的导出必填审计参数遗漏已修复，针对性四项测试通过。

P01–P20 参考批处理入口是 `scripts/run_linear_capital_reference_batch.py`，配置为 `config/research/linear_capital_reference_P01_P20_v1.json`。完整有序清单先于任何求解固定，最多四个并行来源，不重试；每份仍需最佳与完整赢家排除后的次佳均为原生 OPTIMAL，保留全部超时与拒绝。新的纯编排及原参考检查合计 35 项测试通过。

## 失败机制与设计

公开案例、当前最强配置的两次外部校准以及具体设计要求见[失败机制与任务设计](failure_driven_task_design.md)。重点是跨表漏修、修复范围扩大、相邻指标口径混淆及异构布局定位；必要自定义业务政策仍须公开，计算教程、答案值和调试根位置不进入工作请求。原成功版本不重复采样凑零分。

数学研究表明：已证明最佳目标 W 后，完整排除赢家的有效上界 U<W 足以证明唯一性，无须知道真正次佳值。另一个新工程查询在完整原约束上同时要求目标至少为 W 并排除完整赢家；若原生求解证明不可行，也足以支持唯一性。两种结论均未修改当前最佳/次佳双 OPTIMAL 门禁、已冻结材料或历史结果。M01 的两次新可行性查询已按各自 16 CPU/900 秒结束，CP-SAT、SCIP 均为 UNKNOWN，未获得唯一性证明；资源与清理已独立复核，不新增来源或模型分数。

对八份已完整通过的参考日志另作只读核对，首次找到最终正确方案通常早于 OPTIMAL 证明完成。记录分别保存首次正确方案、最佳证明与次佳证明时间；这些是离线 16 CPU 工程数据，不能按 CPU 比例换算，也不能替代最强模型实测。证据为 `outputs/research/linear_capital_completed_eight_incumbent_timing_20261031T112213Z/receipt.json`。

M02 原生补全轨迹解释了默认工程探针的盲区：模型缩放目标和约束、移除重复行后使用 HiGHS，其原生日志在 75.5 秒即显示最终正确目标，800 秒结束时仍未证明最优；随后尝试两种 SCIP 方式并提交正确工作簿。因此，不能以默认 CP-SAT/SCIP 未找到正确值推断模型困难。追加只读核对绑定了实际执行代码、完整赢家向量和提交文件，见 `outputs/research/linear_M02_FM_strategy_tooltime_readonly_20261031T114802Z/receipt.json`。

下一版在独立的 `linear_capital_scaled` 命名空间实现 360 项共同决策、60 组站点、120 条前置关系，保留全局共享容量与原财务规则，旧代码及运行记录不改。几何投影为 370 张表、1,247,328 个公式、1,522,187 个目标；这是结构估计，尚无实际来源工作簿。

该版完整二十份原始合同先于实际财务计算共同固定，全部财务核对已通过：每份 1,080 条项目情景路径、年度金额、FIFO 税损、NPV、18 个预声明组合与完整优化矩阵。实现级全场景计算为八十次，共 86,400 条项目情景路径；全部 6,775,200 对整数系数一致。360 个诊断方案中 95 个集团可行、265 个集团不可行，均原样保留。批次耗时 207.123 秒，工作进程累计 CPU 约 648.95 秒；这些不是模型工具时间。没有模型、优化、LibreOffice 或 Harbor 调用。交接清单为 `outputs/research/linear_scaled_N360_finance_actual_20261031T121400Z/handoff.json`。

新参考批次 `scripts/run_linear_capital_scaled_reference_batch.py` 的二十份有序准备均已完成，prospective 为 `outputs/research/linear_scaled_N360_reference_actual_20261031T122900Z/prospective.json`。实际生产仍需最佳与完整排除赢家后的次佳均为 OPTIMAL、全部整数行与独立财务核验、实际资源与所属容器清理。先行小型实际传输修订版已通过；原首次小型夹具的行标识错误保留，未修改原数学或运行程序。

新来源、实际视图、开发测试和正常质量入口均已接通并增量提交。`scripts/validate_linear_capital_scaled_task_view.py` 保留完整七次/十一次计算及五项控制；`scripts/prepare_linear_capital_scaled_development.py` 在第一次尝试前固定原生连接恢复配置、累计工具时限与完整历史，防止同题重复启动。`scripts/run_linear_capital_scaled_quality.py` 保留默认全部十二项诊断、编号修复路由、公开恢复及真实 Harbor 对照。相关功能测试通过，只说明代码接通；尚未启动该版实际来源、任务验收、质量服务或模型。另已实现不输入答案的缩放 HiGHS 工程筛选，其实际运行尚待准备。

## 用量与审计位置

截至此状态记录，生产原生调用为 **81 个终态、0 个未终态**，已终态调用的已知 token 下界 **109,251,975**；20 个调用核心用量不完整，至少 34 个尾部不完整。M02 调试增加 3 个去重响应、47,322 tokens；补全增加 33 个去重响应、2,375,417 tokens，均与各自原生聚合一致，cached input 和 reasoning output 不重复相加。失败请求的尾部未知。供应商账单未知，原生估算费用不作为实付金额。外部公开样题校准的两次调用单列，不并入生产分母。这些调用覆盖历史迭代，不能当作本批二十份原始候选的转化率。

P01–P20 财务实际成功为 20/20，但来源和题目转化率尚无完整终态。原财务收据只统计了四十次初始账本执行；编译器内部还各自重核一次完整账本，因此实际为八十次实现级全场景计算。更正追加保存，未覆盖原收据或重算数据。

主要本地审计目录：

- `outputs/research/linear_capital_M02_view_execution_driver_20261031T092600Z/`：来源、两类实际视图、冷复核与所属容器清理的统一交接。
- `outputs/research/linear_M02_first_development_pair_prospective_20261031T100540Z/`：两项首次实测前共同固定的声明。
- `outputs/research/linear_M02_DBG_first_infrastructure_terminal_readonly_20261031T113543Z/`：调试接口断流终态与独立逐响应核算。
- `outputs/research/linear_M02_FM_strategy_tooltime_readonly_20261031T114802Z/`：补全原始正确提交、求解路径、用量及未知工具时钟。
- `outputs/research/linear_H01_first_pair_actual_harbor_controls_20261031T091200Z/`：两类真实 Harbor 控制及独立复核。
- `outputs/research/linear_H01_first_pair_infrastructure_terminal_20261031T091900Z/`：两次连接故障、逐响应去重用量与终态。
- `outputs/research/linear_capital_P01_P20_finance_actual_20261031T100100Z/` 与 `outputs/research/linear_capital_P01_P20_finance_accounting_correction_20261031T101304Z/`：二十份财务通过及追加核算更正。
- `outputs/research/linear_H01_normal_quality_readonly_prepare_20261031T102200Z/`：首个大工作簿接入预检的真实失败。
- `outputs/research/linear_H01_normal_quality_readonly_prepare_revision2_20261031T103800Z/`：修订后完整只读接入预检通过。
- `outputs/research/linear_H01_public_recovery_engineering_pair_20261031T110000Z/`：两类公开恢复的首次实际工程配对。
- `outputs/research/linear_scaled_N360_raw_actual_20261031T121400Z/`：新二十份原始合同与预声明诊断计划。
- `outputs/research/linear_scaled_N360_finance_actual_20261031T121400Z/`：新二十份实际财务、矩阵、资源计量与完整工件清单。
- `outputs/research/linear_scaled_N360_tiny_transport_revision2_actual_20261031T122700Z/`：小型实际原生传输、整数行与清理通过。
- `outputs/research/linear_scaled_N360_reference_actual_20261031T122900Z/`：全二十份参考准备、固定清单与后续实际参考。
- `outputs/research/linear_M01_completed_nonoptimal_readonly_20261031T102700Z/`：未满足唯一参考门禁的原终态复核。

最终发布仍必须另行冻结合格任务清单，执行新的最强模型确认，并在真实根目录运行 `harbor run -p SpreadsheetEval -a oracle`，逐题全部得到 1。
