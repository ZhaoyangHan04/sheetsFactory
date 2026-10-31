# 当前开发状态

更新于 2026-10-31 17:17 UTC。正式难度交付为 **0 Financial Modeling + 0 Debugging**；旧质量批次的 20+20 原样保留。根目录 `SpreadsheetEval/` 尚未发布。下面的开发材料不能代替最终冻结集成绩或全目录 oracle 结果。此前实验的详细记录另见[历史开发记录](development_history.md)。

当前首要工作是完整官方 FM100/DBG100 首次测试与实际错因迁移。该时点本轮已有 17 道新终态：FM10 题官方通过6题；DBG7题原始均0，其中1题协议状态 UNKNOWN。原有两道结果另行保留，不重复抽取。逐题完整差异、政策与缓存边界、新原型和真实测试结果见[官方复测研究](official_calibration_study.md)。

周期边界新原型已实际验证657个输出，补全D657、调试D397，五项对照和资源检查通过；两次首次最强模型均完整解出，工具耗时4.924819813/4.588457148秒，没有难度资格。独立控制新原型含546个输出及全部3×3状态，真实工程验证尚待执行。N360 P01原两类工程视图已经通过并共同准备模型快照；FM已启动首次原生模型，DBG首次启动在模型调用前发生共享登记锁冲突，保留原始失败后延后执行同一未使用尝试，不能把该启动故障计成模型失败或新抽样。

## 证据分层

| 材料 | 已完成 | 尚未完成 |
| --- | --- | --- |
| 官方 FM / Debugging 完整复测 | 原2次保留；200题和230个工作簿固定；198次首测登记；四进程执行；该时点17道新终态及六道实际逐题归因；周期边界新题已实际首测 | 完整200结果与完整归因仍进行；新日期原型两类均被解出，独立控制原型未实测，不声称迁移难度已成功 |
| H01 两类任务视图 | 来源完整财务验算；补全七次、调试十一次实际计算；五项本地对照；真实 Harbor 两类均 oracle=1、nop=0；两类实际公开恢复完整通过 | 十二项正常质量诊断、有效最强模型成绩、最终确认；目前停止继续投入此容易来源 |
| M02 两类任务视图 | 来源和两类实际视图完整验算；两份首次最强模型尝试均已结束；补全原始 verifier=1、完整目标正确 | 两次 CLI 断流均导致正式分数为空；补全不是困难度失败，不重采样；公开恢复、十二项质量、真实 Harbor、最终确认未完成 |
| P01–P20 原 240 项池 | 原合同全部自然结束；20/20 完整独立财务与矩阵核对；P01/P02/P04/P05/P06/P07/P08/P09/P10/P20 十份完整参考及冷复核通过；32 次实际搜索的资源与所属清理均通过 | P03/P11–P19 十份按原 best 或 runner 限时拒绝，不重试；没有新增来源工作簿、任务或模型资格 |
| L360-P01–P20 新 360 项池 | 原始合同先固定；20/20财务与完整矩阵核对；已至少十份参考通过；P01/P02来源及两类工程视图通过；各自18次任务计算、完整D及五项对照通过；P01两类首测快照在调用前共同固定 | 参考批次其余原调用仍收尾；P01首次模型开发正在执行；正常质量、真实Harbor和最终冻结难度尚未通过 |
| 八类原生业务组合 | 50 张表、4,430 个公式三轮原生等价检查；766 个任务输出独立财务覆盖；修订版十四次任务计算与五项对照通过；两次首次最强测试已完成，调试 reward=1、补全原始 reward=0 | 调试没有难倒模型；补全有公开范围缺陷与诊断口径歧义，零分不能作难度证据；已准备正常质量流程但明确暂停未执行；没有正常质量、真实 Harbor 或最终难度资格 |
| M01 参考研究 | best 原生 OPTIMAL，双矩阵、财务和实际资源通过 | 排除完整赢家后的 runner 在原 3600 秒终态仅 FEASIBLE，不能证明唯一性；停止该轮，不构造来源 |

H01 的两次首次最强模型尝试均因服务连接中断自然结束，`NetworkConnectionError`、reward=null、计分题数 0。10:50 UTC 服务重新返回正常的未授权鉴权响应，只说明服务可响应鉴权，不证明推理连接稳定。M02 调试于 11:08 UTC 因原生 CLI 连接恢复耗尽而终止，`NonZeroAgentExitCodeError`、reward=null、计分题数 0，原始 verifier=0 来自没有提交文件。M02 补全随后也因原生断流结束，但其已经提交的工作簿得到原始 verifier=1，全部 1,015,908 处目标匹配。原始零重试终态、无正式分数状态与用量全部保留；不将补全当成难题失败或重新采样。工具时钟的原始不一致状态仍为 UNKNOWN，原生日志中的约 1661 秒时长合计只是诊断信息，不能冒充预算证书。

M02 的两个预声明工程尝试分别用 SCIP 和 CP-SAT，在与模型相同的 2 CPU/32 GiB 下各运行原定 1800 秒。最终精确目标分别为 826,282,354 与 826,029,020 便士，均未达到已知正确值 826,417,506；两套完整约束、实际资源与所属容器清理通过。原生日志的圆整显示及行连接解析限制另行更正保留。这是默认程序路线的工程信号，不能充当最强模型失败或难度准出。

## 产线实现

正常质量入口是 `scripts/run_linear_capital_quality.py`，默认配置为 `config/pipelines/linear_capital_quality_v1.yaml`，节点注册为 `config/task_adapters/linear_capital_portfolio_nodes.yaml`。它复用原调度、轨迹诊断、编号检查和修复路由，默认启用全部十二项检查；候选试解成功与否均需诊断。来源与实际视图经过完整冷验证后，以当前进程中的不透明凭据复用，持久化 JSON 标记不能自行授予资格。

公开恢复只接收公开工作簿、题面和通用程序，独立容器没有私有参考挂载。参考生产与公开恢复的离线资源单独声明；模型和评分仍采用 2 CPU、32 GiB，以及严格少于 1800 秒的累计工具时间。H01 两类首次实际工程恢复已全部通过：两次公开求解、四次实际 LibreOffice 重算，两次各 1,184,646 处完整类型稳定性均零差异；分别完整匹配 1,015,908 和 297,064 处变化，缺失、多改、错值均为零。六个所属容器已确认移除，面板和租约正常关闭。统一交接为 `outputs/research/linear_H01_public_recovery_engineering_pair_20261031T110000Z/handoff.json`。本轮没有 LLM、轨迹或 Harbor 调用，不代替全部十二项质量检查，现停止 H01 后续调用。

首轮真实只读接入预检在任何模型、求解或 LibreOffice 调用前拒绝：递归证据遍历误把容器内 `/app/solver.log` 当成宿主文件。原失败保留，已增加受实际容器挂载和宿主完整文件清单约束的路径映射；任意缺失宿主证据仍必须拒绝。59 项针对性检查、真实 H01 证据图的 100 份宿主文件与 10 个映射通过。完整接入预检修订版于 10:58 UTC 通过，用时 1311.30 秒，未调用模型、求解或 LibreOffice；它完整复核了已有实际证据，不是新一轮任务计算。此前审查发现的导出必填审计参数遗漏已修复，针对性四项测试通过。

P01–P20 参考批处理入口是 `scripts/run_linear_capital_reference_batch.py`，配置为 `config/research/linear_capital_reference_P01_P20_v1.json`。完整有序清单先于任何求解固定，最多四个并行来源，不重试；每份仍需最佳与完整赢家排除后的次佳均为原生 OPTIMAL，保留全部超时与拒绝。新的纯编排及原参考检查合计 35 项测试通过。

## 失败机制与设计

完整官方复测已于 16:16 UTC 启动，父进程 PID 837960，面板 `http://127.0.0.1:38947/`。实际目录为 `outputs/research/spreadsheetbench2_all200_first_attempt_cohort_20261031T161800Z/`；目录名称不代替 `started.json` 中的实际启动时间。准备文件 SHA `68320b130f7e324992ec3f8ff008525270d2df3edb4f35a4cde75d6c4cfeba49`，根级事前声明 SHA `f26b0f08d8fd8358561cf47ab6b7844780351d975219c85a8eed6bdf5df44bbe`。入口代码提交 `4349fd3`，20 项针对性检查通过；配置固定每题一次、并发四路、零额外兼容性 LibreOffice 前置调用。首批 FM01_01/DBG01_01/FM01_02/DBG01_02 已有独立进程与真实试验配置，运行中不等于解题完成。方法与原有两道成绩边界见[官方复测研究](official_calibration_study.md)。

新原生组合的补全错因只读复核指出，146 处缺失中 Agency Production/Statistical 共 140 处、Budget Services 2 处不在明确公开任务范围内；7 处非空错值中，预算汇总偏差来自未补 Services，另外四处 DCF 诊断涉及再投资符号及占比基数的合理口径差异。调试提交则准确修复全部 8 个注入公式根，附近保留了直接模板或业务桥接。两者都不能支持困难题准出。工程快照保持原样，正常质量准备目录追加 `post_development_hold.json`，未执行原任务。

生产迭代范围现为 83 个终态逻辑调用、0 个在途，已知 token 下界 113,423,852；历史 20 项核心用量未知和至少 34 项尾部不完整标记保留，供应商实付未知。新两次完整原生调用合计 4,171,877 token，缓存和推理子集没有重复计入；审计为 `outputs/research/heterogeneous_native_first_pair_usage_accounting_83_revision2_20261031T160411Z/receipt.json`，SHA `3fa2bde31578d1db9cf07fb1f7e6af7a45254d826c31d7eb6a7ebeb5ef0c4365`。官方研究 200 题使用独立用量范围，不进入上述生产转换分母。

公开案例、当前最强配置的两次外部校准以及具体设计要求见[失败机制与任务设计](failure_driven_task_design.md)。重点是跨表漏修、修复范围扩大、相邻指标口径混淆及异构布局定位；必要自定义业务政策仍须公开，计算教程、答案值和调试根位置不进入工作请求。原成功版本不重复采样凑零分。

数学研究表明：已证明最佳目标 W 后，完整排除赢家的有效上界 U<W 足以证明唯一性，无须知道真正次佳值。另一个新工程查询在完整原约束上同时要求目标至少为 W 并排除完整赢家；若原生求解证明不可行，也足以支持唯一性。两种结论均未修改当前最佳/次佳双 OPTIMAL 门禁、已冻结材料或历史结果。M01 的两次新可行性查询已按各自 16 CPU/900 秒结束，CP-SAT、SCIP 均为 UNKNOWN，未获得唯一性证明；资源与清理已独立复核，不新增来源或模型分数。

对八份已完整通过的参考日志另作只读核对，首次找到最终正确方案通常早于 OPTIMAL 证明完成。记录分别保存首次正确方案、最佳证明与次佳证明时间；这些是离线 16 CPU 工程数据，不能按 CPU 比例换算，也不能替代最强模型实测。证据为 `outputs/research/linear_capital_completed_eight_incumbent_timing_20261031T112213Z/receipt.json`。

M02 原生补全轨迹解释了默认工程探针的盲区：模型缩放目标和约束、移除重复行后使用 HiGHS，其原生日志在 75.5 秒即显示最终正确目标，800 秒结束时仍未证明最优；随后尝试两种 SCIP 方式并提交正确工作簿。因此，不能以默认 CP-SAT/SCIP 未找到正确值推断模型困难。追加只读核对绑定了实际执行代码、完整赢家向量和提交文件，见 `outputs/research/linear_M02_FM_strategy_tooltime_readonly_20261031T114802Z/receipt.json`。

下一版在独立的 `linear_capital_scaled` 命名空间实现 360 项共同决策、60 组站点、120 条前置关系，保留全局共享容量与原财务规则，旧代码及运行记录不改。P02 实际来源已确认 370 张表、1,247,328 个公式、1,522,187 个财务与选择目标，公式没有截断。规模仍不构成难度证据。

该版完整二十份原始合同先于实际财务计算共同固定，全部财务核对已通过：每份 1,080 条项目情景路径、年度金额、FIFO 税损、NPV、18 个预声明组合与完整优化矩阵。实现级全场景计算为八十次，共 86,400 条项目情景路径；全部 6,775,200 对整数系数一致。360 个诊断方案中 95 个集团可行、265 个集团不可行，均原样保留。批次耗时 207.123 秒，工作进程累计 CPU 约 648.95 秒；这些不是模型工具时间。没有模型、优化、LibreOffice 或 Harbor 调用。交接清单为 `outputs/research/linear_scaled_N360_finance_actual_20261031T121400Z/handoff.json`。

新参考批次 `scripts/run_linear_capital_scaled_reference_batch.py` 的二十份有序准备均已完成，prospective 为 `outputs/research/linear_scaled_N360_reference_actual_20261031T122900Z/prospective.json`。实际生产仍需最佳与完整排除赢家后的次佳均为 OPTIMAL、全部整数行与独立财务核验、实际资源与所属容器清理。先行小型实际传输修订版已通过；原首次小型夹具的行标识错误保留，未修改原数学或运行程序。

该批参考生产已实际启动，面板为 `http://127.0.0.1:35949/`。P02 第一份完整参考通过，选中 145 项，最佳与次佳差 32,151 便士，两个完整 941 行整数验算、独立财务、实际资源和清理均通过；总耗时 511.164 秒。这不构成模型难度证据。P02 实际来源验收和冷复核均通过，清单为 `outputs/research/linear_scaled_N360_P02_source_actual_20261031T130900Z/source_manifest.json`，SHA `5304f7c65d5425a96b3d824fe0155413f5f42398d37d3505fffb6cf4c037874b`。三次实际计算约为 108.41、98.60、103.21 秒，三轮全量财务审计零差异；两次比较各完整覆盖 1,773,566 个非空单元格，类型和值均稳定，所属容器清理通过。来源资格只属于该文件，不代替任务、公开恢复、质量或难度资格。

P02 两类视图的单次实际配对验收已固定并启动，目录为 `outputs/research/linear_scaled_N360_P02_view_pair_actual_20261031T135300Z/`，prospective SHA `d95c9290fe8798c91740d53a140288b1cc57adc405656dfad9d35547f5e74ef7`。新池通用入口 `scripts/prepare_linear_capital_scaled_pool_view_pair.py` 只扩展固定成员身份核验，保留先冻结两类视图及两份验证准备、再执行补全七次和调试十一次原有计算的顺序与完整检查。P01 仍为预声明的首个模型开发候选，未替换或启动模型。

P01 完整参考也已通过：选中 139 项，两次原生状态均为 OPTIMAL，最佳与次佳差 2,843 便士，全部 941 行、财务与资源核对及所属清理通过，终态 SHA `df23daf7ab2f83eb2ca5a40b06b419bacb612a9aa1208e8b9d54ed95e61e56d0`。其三轮实际来源验收及 261.531 秒完整冷复核已通过，来源 SHA `6b64c6df44d3a8bfae760e2435a4eac8ac0a07efc34c7aea46ec560511156d04`，全部三个所属容器已确认不存在。原来源面板已关闭。之前一次仅在复制驱动的字符串计数断言处失败，未准备来源或调用服务；失败单独保留，不计实际重试。

新增 `scripts/prepare_linear_capital_scaled_cached_view_pair.py` 将未来每个进程中同一来源的十次重复冷验证改为一次真实验证，后续通过原有进程内不透明凭据守护全部证据、文件与代码身份。私有函数命名空间保留原配对和视图验证字节码，不修改运行中的 P02。七次/十一次实际计算、完整变化集合、稳定性、五项对照及资源检查不减少。91 项新旧针对性检查通过，包括来源中途变更后仍保留失败终态。该入口已用于原首选 P01，单次来源冷准入用时 249.542 秒，随后进入两类视图构造，来源验证确实仅执行一次；面板为 `http://127.0.0.1:43641/`。声明为 `outputs/research/linear_scaled_N360_P01_cached_view_pair_execution_20261031T150000Z/prospective.json`，SHA `d5954f6fb7cf04b6ae3664c06c162b618e5c9249f27bbb331596b6fdfad1507b`。完整说明见[进程内来源复用](linear_capital_scaled_cached_view_pair.md)。

P02 补全的原七次实际计算和独立冷复核均已完成，终态 SHA `bad0eb2c53984e37a69a1a82de3f1be22eca20a68a67f4523a96f3086cd8d2b1`。完整变化集合为 1,522,188，包含与选择相关的新增位置；类型稳定性通过，五项对照为 1/0/1/0/0。七次实际调用耗时合计 649.853 秒，独立冷复核 330.943 秒；所属容器均已确认不存在。交接为 `outputs/research/linear_scaled_N360_P02_view_pair_execution_20261031T135300Z/financial_modeling_cold_handoff.json`，SHA `60c5f9e7b1f5a8d9ca8f8185256c38c926dab6afd06916509551690ab9c25f52`。这不授予正常质量、Harbor 或难度资格；P01 仍为首次模型开发对象。

新来源、实际视图、开发测试和正常质量入口均已接通并增量提交。`scripts/validate_linear_capital_scaled_task_view.py` 保留完整七次/十一次计算及五项控制；`scripts/prepare_linear_capital_scaled_development.py` 在第一次尝试前固定原生连接恢复配置、累计工具时限与完整历史，防止同题重复启动。`scripts/run_linear_capital_scaled_quality.py` 保留默认全部十二项诊断、编号修复路由、公开恢复及真实 Harbor 对照。相关功能测试通过，只说明代码接通；该版任务验收已如上启动，质量服务和模型尚未启动。另已实现不输入答案的缩放 HiGHS 工程筛选，实际小型兼容检查与 P01 搜索分开记录。

HiGHS 两次先行小型实际检查均在搜索前因接口适配被拒绝：首次便捷方法 `setMaximize()` 不返回状态；API-v2 的诊断 LP 导出未通过旧的单状态检查。原文件、失败与零搜索边界保留。新 API-v3 使用明确返回状态的目标接口，诊断导出仅允许成功或警告并同时要求新鲜非空文件，记录精确状态，不改数学或求解配置。十二项针对性测试及新小型实际计算均通过；后者确认该 LP 导出确实返回警告。随后只执行一次原定 P01 搜索。

该 P01 工程搜索在 2 CPU/32 GiB、800 秒、无答案输入和零重试下正常达到时间限制，得到选中 137 项的方案，全部原始 941 条约束的精确整数核验通过，目标 1,180,875,081 便士。它未证明最优。搜索结束后才对照已完成 CP best，后者为 1,180,912,348 便士，两方案相差 16 个选择，目标差 37,267 便士；没有额外优化或模型调用。完整 best/runner 参考仍需另行通过，工程结果不构成最强模型难度证据。收据分别位于 `outputs/research/linear_scaled_P01_highs_completed_readonly_20261031T134100Z/` 与 `outputs/research/linear_scaled_P01_completed_plan_comparison_20261031T135702Z/`。

八类业务的原生工作簿组合已完成一次纯合并和三次实际 LibreOffice 检查：50 张表、4,430 个物理公式，保留各自布局、单位、期间、政策、图表、注释及数据验证，不跨无关币种或期间相加。每次原始来源与合并文件到实际结果的全表比较覆盖 22,854 个单元格，按任务书两位小数规则、日期、文本、公式与字面值身份全部一致；128 处原始浮点差异最大为 1e-10，未称为原始数值精确等价。两次后续比较覆盖各 22,790 个原生单元格，连原始数值也完全稳定。全部三次实际资源、线程上限及所属清理通过，运行共 55.260 秒；76 条原注释、54 条图表引用与原图像二进制另经完整只读核对。

上述组合没有自动取得整个财务来源或任务资格。旧七份审计覆盖 421 个不同地址，NYU 的 112 项主模型另扩展了 97 个独立业务计算与 134 个直接引用；再加两个可独立确定为 1 的比率，766 个任务位置全部获得独立期待值。343 项 NYU 范围的旧来源与实际原生文件均通过完整核对；数值计算从业务输入和独立锚点推导，不执行原公式。财务声明仍不覆盖全部 4,430 个公式。公开请求已移除逐个故障机制的教程提示，保留必要自定义政策和业务范围。

首版两类计划与验证准备均在实际计算前固定，补全于第三次 goal1 计算后按门禁停止，没有继续控制或调试。唯一两处差异是展示页 H6/K6 对已批准说明文字的直接引用缓存；数值、原始浮点和公式身份均无差异，766 个任务财务值仍全部一致。这两处在任务范围之外。原失败和代码保留，另建只声明这两处缓存文字传递的修订版，并重新执行完整实际流程，不继承控制通过状态。只读诊断为 `outputs/research/heterogeneous_review_first_pair_prepared_20261031T150720Z/post_terminal_readonly_failure_diagnostic.json`，SHA `a873b1aaa96e759d65ce5bb6c4e70ed996c83dee16f997110e1529e16892e38a`。

修订版已全部通过十四次实际任务计算与各自冷复核，实际调用共 17 次包含原失败的三次，零重试。补全 D766 的八族变化为 105/165/62/36/12/343/16/27；调试 D43 为 2/2/1/12/2/19/2/3。两份均五项对照为 1/0/1/0/0，全部实际资源和所属清理通过，完整原始数值、公式与类型稳定性通过。实际耗时分别 112.79 与 107.53 秒。这是任务工程资格，不是正常质量或模型成绩。完成交接为 `outputs/research/heterogeneous_review_first_pair_v2_prepared_20261031T151900Z/completed_readonly_handoff.json`，SHA `7be773aa3f0b84d88c1b487323dc4df9c5742d6d22db3f53f40a34113d90b400`。

两份首次开发快照在任一模型调用前共同冻结，十七文件各自完整绑定，模型均为 `gpt-6.1-sol/xhigh`，严格累计工具时间小于 1800 秒、操作保护 14400 秒、外层零重试。共同声明为 `outputs/research/heterogeneous_native_first_development_pair_prospective_20261031T152900Z/prospective.json`，SHA `2e91636ecb4b7d0fbcfc7e0e7621e88396997889420c01271d9f1a91fed3e612`。补全面板 `http://127.0.0.1:36141/`，调试面板 `http://127.0.0.1:39543/`；当前运行中，没有分数，不因参考正确或公式数而提前声称难度通过。

正常质量接入 `scripts/run_heterogeneous_native_quality.py` 已实现，相关针对性及未变回归共 74 项通过，但未实际运行质量服务。它采用既有 `reference_review` 政策，完整检查任务独立期待值、原始错误清单与完整变化集合，全部十二项正常诊断和真实 Harbor 均不可省略；不声称另一个公开解题器已经成功。正常报告绑定精确 goal SHA；真实 Harbor 结束后另验证 oracle/nop 的两角色 CPU、内存、镜像祖源与原始任务绑定，缺证时撤回当前资格并隔离导出，保留原始奖励。财务范围或输入变更必须先另行实际验证，只有明确的题面问题可走有限轮文字修复。入口说明见[范围化质量验证](heterogeneous_native_quality.md)。

组合实现及来源界限见[八业务组合](heterogeneous_native_review_pack.md)，原始实际交接为 `outputs/research/heterogeneous_native_review_pack_native_validation_prepared_20261031T142000Z/completed_readonly_handoff.json`。

## 用量与审计位置

截至此状态记录，生产原生调用为 **81 个终态，另有 2 个首次开发尝试在运行**；已终态调用的已知 token 下界 **109,251,975**，在途用量另列待终态核算，不能填零。20 个历史调用核心用量不完整，至少 34 个尾部不完整。M02 调试增加 3 个去重响应、47,322 tokens；补全增加 33 个去重响应、2,375,417 tokens，均与各自原生聚合一致，cached input 和 reasoning output 不重复相加。失败请求的尾部未知。供应商账单未知，原生估算费用不作为实付金额。外部公开样题校准的两次调用单列，不并入生产分母。这些调用覆盖历史迭代，不能当作本批二十份原始候选的转化率。

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
- `outputs/research/linear_scaled_N360_P02_source_execution_20261031T130900Z/`：P02 实际来源构建的单次声明、通过交接与清理证据。
- `outputs/research/linear_scaled_N360_P02_view_pair_execution_20261031T135300Z/`：P02 两类视图的原单次声明与后续阶段计时。
- `outputs/research/linear_scaled_P01_highs_screen_prepared_20261031T125838Z/`：原小型接口失败、零搜索边界及所属清理。
- `outputs/research/linear_scaled_P01_highs_screen_api_v2_prepared_20261031T131042Z/`：第二次搜索前接口拒绝，原文件未改。
- `outputs/research/linear_scaled_P01_highs_screen_api_v3_prepared_20261031T132301Z/`：小型实际计算和单次 P01 工程搜索的完整实际终态。
- `outputs/research/linear_M01_completed_nonoptimal_readonly_20261031T102700Z/`：未满足唯一参考门禁的原终态复核。

最终发布仍必须另行冻结合格任务清单，执行新的最强模型确认，并在真实根目录运行 `harbor run -p SpreadsheetEval -a oracle`，逐题全部得到 1。
