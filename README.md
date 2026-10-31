# sheetsFactory

从公开财务工作簿自动构造可审计的财务补全与公式调试任务。

上一轮已完成 20 道 Financial Modeling、20 道 Debugging 的质量验收并保留冻结发布包；该批次没有通过难度验收。当前正在迭代两类各至少 10 题，构造与诊断使用 Codex CLI `gpt-6-sol` / `high`，难度门禁固定使用 Codex CLI `gpt-6.1-sol` / `xhigh`，累计工具执行时间严格小于 1800 秒，排除模型思考与生成时间，冻结确认集 Overall Pass@1 ≤ 0.2。新执行合同另有不计模型失败的运行保护时限；旧合同及成绩保留，详见 [评测要求](docs/evaluation_requirements.md)。未完成最终确认前，不作难度达标声明。

截至 2026-10-31 05:01 UTC，正式难度交付仍为 **0 Financial Modeling + 0 Debugging**。异构合同来源已通过三次实际重算、三次完整独立验算和两次全部类型稳定性检查（274,750 个公式、211,968 个财务字段）。首个无计算辅助表的补全开发版本有 99,835 处实际变化、五项本地对照全部通过，第一次最强模型测试正在进行。并行公开审查在模型终态之前发现了资产投产月折旧的实际口径缺口；该版本保留首测并暂停准出，后续修订仅补业务政策并移除 864 个内部计数目标，正在重新实际构造。局部调试首版的 12 处错误均可从现存正确模板恢复，因此停止其强测，改为研究固定政策分支特化后的任务。组合投资调试的最新已完成首测为原始 reward=1、保守工具上界 178.718841612 秒，未扩产。方法、公开案例校准与证据边界见 [失败机制与任务设计](docs/failure_driven_task_design.md)。根目录 `SpreadsheetEval/` 仍待完整确认后发布。

截至 2026-10-31 03:34 UTC，最终难度交付计数仍为 0。最新两项开发实验均被解出：原生业务呈现的多实体调试题 reward=1，工具执行 371.134196162 秒；40 项投资补全题原始 reward=1，计时解析保留原未知状态，另经完整独立复核得到累计工具时间保守上界 736.178024916 秒。两者均不扩为最终题集，不重新采样。40 项来源现已通过完整实际源准入，不能据此继承题目质量。百万公式多实体来源与 30 项共同投资决策来源均已通过完整实际源表验算。30 项决策首题完成前六个正常节点和五项实际本地控制后，冻结独立开发快照，首次原生 `gpt-6.1-sol` / `xhigh` 实测正常得到 reward=1，累计工具执行 79.772238266 秒；实际 agent 与 verifier 均满足固定的 2 CPU、32 GiB 和镜像约定，无计时缺失、基础设施异常、工具预算耗尽或运行保护截断。该版本未达到难度要求，保留首次成绩，不重新采样或扩同模板十题；剩余生成侧质量流程已协作停止，没有继续调用诊断模型。多实体首题首次最强模型开发测试也正常得到 reward=1，累计工具执行 363.930959625 秒，完整 261,457 处变化集合全部正确；实际资源和计时均有效。已停止该容易版本的剩余质量流程：协作停止等待超过 30 分钟后，只终止精确识别的原生产者，实际退出 143，原数据库和不完整检查均保留，生成侧模型调用为 0。这不计为质量通过或模型失败。首道明确场景输入优先级的 Financial Modeling 修复版通过了 11 项适用质量检查（Q08 留待整组确认），真实 Harbor oracle=1、nop=0；最强模型首次开发测试正常得到 reward=0，工具执行 226.613269849 秒。但该输出只是新增了隐藏辅助表：独立实际重算后，原 75 张表的全部值及 46,466 处应修改集合都与参考一致。公开说明没有充分明确辅助表和辅助单元格的提交边界，故该版本按新发现的 Q03 问题暂停准出，不作为财务算术难度证明。旧成绩、诊断与文件保持不变。证据位于本地 `outputs/research/C01_priority_r1_output_forensics_20261030T182500Z/final_forensic_conclusion.json`；精确导出版本的 Harbor 控制证据位于 `outputs/research/C01_priority_r1_exact_Harbor_20261030T181500Z/verification_addendum.json`。

后续 revision 002 已明确原有工作表名称、顺序和禁止新增辅助单元格的提交边界，数值参考、业务规则和目标保持不变；它重新通过五项实际本地控制、仅公开输入的独立恢复，以及同一正常导出版本的真实 Harbor oracle=1、nop=0。新版本的 `gpt-6.1-sol` / `xhigh` 首次开发测试正常得到 reward=1，累计工具执行 482.967168152 秒，无基础设施异常、计时缺失或运行保护截断。这是单题开发结果，不是完整 20 题的 Overall Pass@1；停止扩大同一财务输出遮蔽模板，继续开发包含合同状态和控制计算的完整补全任务。实际控制收据为 `outputs/research/C01_scope_r2_actual_harbor_20261030T190700Z/actual_control_receipt.json`，开发测试位于 `outputs/difficulty/composite-cohort-C01-scope-r2-20261030T190400Z/evaluation/`。

新的 Financial Modeling 方案在同一固定十源顺序中遮蔽财务输出及合同、租约、分配和契约状态，每题 60,193 个目标，较前版增加 13,854 个状态计算。十源离线核对均通过原五类独立审计与公开恢复程序的覆盖检查，源工作簿未改变；这不代替十题各自的真实恢复、质量或难度验收。离线证据位于 `outputs/research/composite_full_state_fm_offline_v4_20261030T194100Z/preflight_manifest.json`。首源在 `outputs/runs/20261030T195000Z-financial-full-state-dev/` 已完成单题质量验收：完整应修改集合 60,193，五项真实本地控制和独立公开恢复通过，12 项检查全部覆盖、11 项 clear、Q08 not_applicable，实际 Harbor oracle=1、nop=0，无未知检查或阻塞问题。质量终态证据为 `outputs/research/financial_full_state_quality_terminal_20261030T201800Z/receipt.json`；该记录也验证了真实控制任务的文件校验和与实际导出版本。相同实际导出版本的首次最强模型开发测试已正常结束：`gpt-6.1-sol` / `xhigh` 得到 reward=1，累计工具执行 234.131532611 秒，无基础设施异常、计时缺失或运行保护截断；原始评分保留于 `outputs/difficulty/financial-full-state-C01-20261030T200100Z/evaluation/`。该成功说明扩大状态补全仍不足以达到难度要求，不在相同版本重新采样，也不据此扩充同模板十题。下一财务方案把共同投资选择与跨情景融资、税务及抵押约束联合起来：首份 K01 的 262,144 个投资组合已经两套独立实现完整核对，最优解唯一；实际生成的 15 表工作簿连续三次 LibreOffice 重算均通过全部 53,741 个计算值的独立审计。这些是参考模型的构建证据。首题的正常质量运行现位于 `outputs/runs/20261030T213457Z-capital-K01-quality-dev/`，待补项包含 19,031 个财务计算和 18 个共同投资决策，辅助公式的全部联动值同样纳入验收；该题仅公开信息的独立恢复已 verified。首次最强模型开发测试正常得到原始 reward=0，累计工具 63.660244024 秒，无基础设施异常或计时缺失；但独立复核确认，提交的 18 个投资选择、三情景全部年度与税务计算以及最优 NPV 都正确。零分来自未标注的汇总字段位置，以及未说明项目明细应保留未入选项目的独立候选现金流。该版本按具体 Q02 证据暂停，不把这个零分算为难度证明，不在相同版本重新采样；后续 revision 001 已明确公开字段约定，保留全部数值参考和目标，并完成 12 项检查覆盖、11 项 clear、Q08 not_applicable、独立公开恢复、五项实际本地控制与真实 Harbor oracle=1、nop=0；终态证据为 `outputs/research/capital_K01_r1_quality_terminal_20261030T233825Z/receipt.json`。该新版本没有新的最强模型成绩，旧版零分不转移，不将其列为难度合格题。原始评分位于 `outputs/difficulty/capital-allocation-K01-first-20261030T215100Z/evaluation/`，独立完整值复核位于 `outputs/research/capital_K01_first_development_forensics_20261030T220438Z/final_addendum.json`。整组难度确认仍未完成。完整枚举证明位于 `outputs/research/capital_allocation_search_K01_20261030T210854Z/search_result.json`，源审计位于 `outputs/research/capital_allocation_source_K01_20261030T212600Z/seed_manifest.json`。此测试的 1800 秒累计工具限制与 14400 秒运行保护分开；常规 600 秒轨迹采样的截断不作难度失败。新任务没有继承旧任务的修复授权，质量合格不代表整个确认集难度达标。

资本分配扩维实现已支持 26、28、30 个共同决策，公开模板从开始即标明汇总列、候选明细和未入选项目的展示约定。两套独立搜索实现在原 18 决策案例的全部 262,144 种组合上逐条一致，并与原始完整枚举结果一致；完整财务输出另经 Decimal 双重记账核对。已预先固定 13 份输入：26/28 决策各一个工程样本、30 决策首个开发样本 D01，以及十个后续确认候选 G01–G10。D01 两套实际全量搜索现已完成，各自验证全部 1,073,741,824 条有序记录、状态编码、分块摘要和完整排名，两份各 32 GiB 的记录完全一致，最优方案唯一，领先次优 234,397 便士；最优、次优及九个固定方案另通过 Decimal 财务验算。完整双实现终态证据为 `outputs/research/capital_scaled_30_D01_dual_actual_20261030T224835Z/receipt.json`，输入清单为 `outputs/research/capital_scaled_public_specs_20261030T224900Z/catalog_manifest.json`。实际生成的 15 表工作簿也已通过三次 LibreOffice 重算、每次全部 77,513 个公式值独立审计及两次完整类型稳定性比较，来源清单为 `outputs/research/capital_scaled_30_D01_source_20261031T000800Z/seed_manifest.json`。待补内容含 25,511 个财务计算和 30 个共同决策。首次质量启动在任何模型或 LibreOffice 调用之前发现校验缓存混入其他文件记录，已保留失败、以独立源校验会话修复，并在新目录 `outputs/runs/20261031T003000Z-scaled-30-D01-quality-dev-v2/` 重新准备与启动；原失败记录为 `outputs/research/scaled_D01_quality_startup_failure_20261031T002600Z/receipt.json`。D01 五项真实本地控制依次为 1/0/1/0/0，完整应修改集合为 30,660，含 5,119 个联动变化的辅助单元格。精确冻结的首次最强模型开发测试于 00:47 UTC 启动，采用累计工具执行严格小于 1800 秒及独立的 14400 秒运行保护，正常得到 reward=1、工具执行 79.772238266 秒；记录位于 `outputs/difficulty/scaled-D01-first-development-20261031T004300Z/evaluation/`，独立资源及计时复核为 `outputs/research/scaled_D01_first_development_terminal_readonly_20261031T005822Z/receipt.json`。模型实际编写带上界的分支剪枝，只访问 3,407 个节点、889 个叶节点即可用界覆盖全部十亿方案，再正确补全所有财务值；没有逐个执行十亿次前向。只读方法分析为 `outputs/research/scaled_D01_strategy_readonly_20261031T010031Z/receipt.json`。该版本不继续扩产，其独立公开恢复、后续质量诊断与 Harbor 控制未完成，不能称为质量准出；协作停止保留全部部分工作，记录为 `outputs/research/scaled_D01_quality_stop_after_valid_success_20261031T005955Z/stop_request_receipt.json`，不把取消计为模型失败。绝大多数组合可行、最佳方案只选两个项目，均不能证明单项约束不活跃或题目困难；规模和原生程序耗时不代替最强模型实测。只读经济结构记录为 `outputs/research/capital_scaled_D01_geometry_readonly_20261030T235124Z/receipt.json`。

另有固定顺序的 30-D02 开发输入及 H01–H10 后续候选，只调整预先公开的现金流、融资容量和场景参数，保留原财务数学与 D01 记录。D02 的全部 44 个预声明固定方案已经 A、B、Decimal 三实现逐项一致，39 个方案在全部情景可行；真实触发融资追缴、抵押上限、亏损使用及到期。原来预声明的三对比较没有发生排序反转，工程门槛仍保留为未全部通过。对同一 44 个已计算方案的全部 946 对作只读扩展比较，另发现 122 对跨场景排序反转；这不倒改原检查，也不是难度成绩。实际固定方案证据为 `outputs/research/constrained_capital_D02_fixed_actual_20261031T001535Z/receipt.json`，完整扩展比较为 `outputs/research/constrained_D02_pairwise_readonly_20261031T002052Z/receipt.json`。D02 双实现全量计算于 00:36 UTC 启动、01:25 UTC 完成：各自全部 1,073,741,824 条记录完全一致，最优解唯一，领先次优 1,026,481 便士；终态位于 `outputs/research/constrained_capital_D02_dual_actual_20261031T004200Z/attempts/20261031T003604Z-79d19f1bc558/receipt.json`。此前模型在 D01 写出的公开分支剪枝程序，在相同 2 CPU、32 GiB 镜像中处理 D02 只用 74.624947982 秒；其最优、次优、三情景 NPV 及间隔随后与完整双证明精确一致，比对收据为 `outputs/research/D02_public_search_global_proof_readonly_comparison_20261031T013543Z/receipt.json`。这是复用既存公开算法的工程回放，没有新的模型成绩，也没有 D02 工作簿、质量或难度准出。停止在相同 30 项结构上直接扩题。

新的独立命名空间已支持 40、48、56 项决策、精确字符串掩码，以及完整财务公式和独立账本核对；实际测试工作簿分别包含 97,323、113,171、129,019 个公式。稀疏前缀覆盖检查与有理数上界分别验证覆盖和剪枝条件，不能单独证明最优解。新规模的两个首轮有界工程搜索均未完成：A 达到 5,000 万节点上限，B 达到 20 万队列上限，不能声称得到全局最优。同一公开数据、同一数学实现的后续实际运行已完成：约 147 秒产生完整 40 维前缀记录，36,905,895 条记录覆盖全部 2^40 个组合；独立整数验证器检查每个剪枝，另一财务实现重新计算全部 1,311,256 个实际叶子，完整结果逐字节一致。最优与次优另经 Decimal 核对，最优唯一。实际工作簿有 15 张表、97,323 个公式，三次 LibreOffice 全公式独立验算通过，两次类型稳定性比较通过。参考收据为 `outputs/research/sparse_40_J01_complete_reference_verification_20261031T025500Z/actual/reference_proof.json`，不把一次完整分区加逐叶复算描述成两次完整搜索。首道补全题遮蔽 30,951 个财务字段与共同决策，完整变化集合 38,304，输入无原生错误，五项本地控制全部通过；首次最强模型开发实测位于 `outputs/difficulty/sparse-40-J01-first-development-20261031T025800Z/evaluation/`，原始 reward=1；原生时钟的两处不一致使旧解析结果保留 evidence_incomplete，独立完整覆盖复核确认保守工具上界为 736.178024916 秒，实际资源合格。这不计作模型失败，复核收据为 `outputs/research/sparse_40_first_development_timing_forensic_20261031T032500Z/timing_reconciliation.json`。完整来源另已实际准入，收据为 `outputs/research/sparse_40_J01_source_admission_actual_20261031T031825Z/admitted_source.json`。公开恢复、完整正常质量、Harbor 控制及冻结确认仍待完成，不计作难度达标。并行研究以公开失败轨迹中的目标定位、异构口径、漏修和保护区误改为依据，为后续候选选择可检验的组合维度。 D01 公开信息与实际解题路径的只读复核为 `outputs/research/public_guidance_evidence_20261031T014229Z/memo.md`：完整实施字典、重复 JSON 输入和带语义的最终金额辅助字段，均降低了重建成本；没有发现公开最优投资答案，输入规模本身不代表困难。后续变更分别测量数据呈现和业务交互的作用，保留必要政策和提交范围。

206 根 Debugging 已被最强模型解出，累计工具执行 285.472 秒；后续完整四族、1,666 根版本也正常得到 reward=1，工具执行 159.403807054 秒，因此均不扩为最终题集。固定 10+10 配额保持不变；这些成功版本均保留原始成绩，停止同模板批量造题，继续开发包含未知投资决策的新财务模型。源表、单题验收和最终交付分别计数。根目录 `SpreadsheetEval/` 将在完整确认和发布核验后创建；历史质量发布包的位置见下文。

完整财务依赖图的调试构造已实际注入 20,895 处公式修改，连续两次 LibreOffice 重算得到完全相同的类型化值。20,534 个被编辑位置发生值变化，完整应修改集合覆盖 20,758 个单元格；361 处未产生值变化的公式修改单列，不计作必须修改的值。该任务按共同修复整个财务模型的契约验收，另行保留可选的单根反事实诊断，不把公式修改数量当作独立根因数量或难度证明。完整常规流程的实际控制为 oracle=1、nop=0、equivalent=1、missed_root=1、extra_change=0：首处单独漏改在参考背景下没有值变化，因而该负控不合格。生产者已让在途修复正常结束后退出，真实结果不覆盖；后续必须使用明确绑定的新控制选择阶段，重新执行五项实际控制及其余正常验收，该失败版本没有启动强模型测试。失败记录为 `outputs/research/full_graph_joint_local_control_hold_20261030T194149Z/receipt.json`。

上述完整依赖图另有固定顺序的 10 个派生场景，全部通过源表的独立财务复核、每源 3 次实际 LibreOffice 计算及公开时序输入核对；这 30 次计算累计 443.584 秒。批次记录为 `outputs/research/composite_full_source_batch_20261030T181750Z/batch_manifest.json`。这些是同两个原始公开工作簿的派生场景，尚未完成单题质量检查和难度测试，不计作合格题。

另有独立的 V3 缺陷提供器组合真实账户、期间、计量、边界和优先级错误，原财务来源及其审计不变。主样本和原 10 个场景的全部非零目标均离线编译通过，没有删除或截断目标；主样本实际注入 20,895 处公式修改，两次重算稳定，完整变化集合为 20,225，其中 20,069 个被编辑位置有值变化，826 个无值变化的公式修改单列。源表无错误，注入后有 2 个错误值；这 2 次工程计算只证明构造、稳定性和完整变化集合，不证明独立恢复、质量或难度。工程记录位于 `outputs/research/semantic_graph_v3_engineering_20261030T192657Z/`，离线交接位于 `outputs/research/composite_semantic_v3_batch_20261030T190830Z/handoff.json`。固定顺序的十个场景随后也实际完成全部 20 次 V3 工程重算，均稳定，累计计算 262.993 秒；记录为 `outputs/research/semantic_v3_fixed_ten_actual_20261030T205000Z/batch_manifest.json`。由于首题仍被最强模型解出，不继续同模板的十题质量扩产；这些工程来源不计入合格题。

两种完整调试提供器已分别进入新的实际质量运行：`outputs/runs/20261030T200048Z-joint-controls-v2-dev/` 与 `outputs/runs/20261030T200335Z-joint-controls-v3-dev/`。这些阶段仅明确替换负控选择节点，按固定顺序实际执行单漏改候选，首个真实零分才能成为负控，并保留所有失败尝试。两版实际五项控制均为 1/0/1/0/0，独立公开恢复均已 verified。V2 已完成完整单题质量验收：12 项检查全部覆盖、11 项 clear、Q08 not_applicable，无阻塞或未知项，真实 Harbor oracle=1、nop=0。根校验复核了实际任务目录哈希、文件及与首次强测完全相同的冻结导出，证据位于 `outputs/research/joint_v2_quality_terminal_20261030T204704Z/receipt.json`。V3 也已完成同等单题质量验收和真实 Harbor oracle=1、nop=0，精确导出与控制任务哈希经独立核对，证据为 `outputs/research/joint_v3_quality_terminal_20261030T210322Z/receipt.json`。精确冻结输入的首次最强模型开发测试均已正常结束：V2 reward=1、累计工具执行 295.482089056 秒，V3 reward=1、累计工具执行 382.012271739 秒；两次均无基础设施异常、计时缺失、工具预算耗尽或运行保护截断。原始成绩分别位于 `outputs/difficulty/joint-v2-first-20261030T202933Z/evaluation/` 和 `outputs/difficulty/joint-v3-first-20261030T203605Z/evaluation/`。两版均不在原版本重新采样，也不扩为最终十题。候选、单题验收与完整确认集分别计数，不把新阶段启动或离线通过计为难度合格。

新的多实体 Debugging 方向按固定投资计划，组合 24 个法律实体、120 个月、3 个情景，以及内部借贷、共享融资、税务批次、汇率和下月契约状态。首源独立整数账本全部可行，14 类机制均有日期证据。按币种汇总未舍入的汇率计算后，完整公式数为 1,100,346、非空单元格 2,222,012、账务字段 987,570；没有删除字段或改变逐项交易的舍入顺序。三次真实小规模重算的 2,802 个公式值、2,376 个账务字段全部匹配，实际容器的 2 CPU、8 GiB 已核验。完整规模最初暴露逐公式扫描全部旧行的生成瓶颈；停止并保留该次运行后，改为连续行号，完整表达式和字段绑定流逐项摘要均保持相同。随后完整工作簿在 130.875 秒内生成，但第一次实际 LibreOffice 计算在保存时退出，尚未通过源表验收；同源 32 GiB 容量测试实际生成了重算文件，内存采样峰值至少为 8.406 GiB；探针记录退出状态的步骤出现缺失，原失败与只读补证均保留。新容量配置在造题、解题及验证角色统一使用 2 CPU、32 GiB，严格累计工具限制仍为 1800 秒。完整来源已在新版本重新运行：生成耗时 133.113 秒，三次真实重算耗时分别为 166.573、164.213、166.438 秒。三次全量审计均通过 1,100,346 个公式和 1,030,770 个账务字段；两次完整类型稳定性检查均核对 2,222,012 个非空单元格，差异为零。完整源已验收，首道实际调试题继续在 `outputs/runs/20261030T234800Z-entity-G01-quality-dev/` 进行正常质量检查。实际联合修复证明已经通过：60,480 处物理公式修改、两次真实重算，完整变化集合为 261,457；其中 27,488 个被编辑位置发生值变化，另外 32,992 处未产生值变化的修改单列，不作独立根因活动声明。为提前筛除容易版本，另以完全相同的输入、目标和普通 InstructionNode 题面生成过程冻结仅开发快照；首次 `gpt-6.1-sol` / `xhigh` 实测于 02:07 UTC 正常结束，reward=1，累计工具执行 363.930959625 秒，无基础设施异常、计时缺失或预算截断；完整变化集合 261,457 处匹配，没有少改、多改或值错。实际 agent、verifier 的 2 CPU、32 GiB 和镜像层已复核。快照与实测位于 `outputs/difficulty/entity-G01-first-development-20261031T014200Z/`。正常五项控制、公开恢复、全部质量检查与 Harbor 控制仍待完成；实际首次成功已足以停止该模板扩产。02:10 UTC 请求协作停止后，活动前置检查持续占用 CPU 超过 30 分钟；随后精确核对生产者 PID 与启动身份，只终止该生产者，实际退出 143。数据库完整性检查通过，生成侧模型调用为 0；原状态仍如实保留为不完整，独立终态位于 `outputs/research/G01_quality_targeted_termination_20261031T024100Z/terminal.json`。开发终态只读证据位于 `outputs/research/entity_G01_first_development_terminal_readonly_20261031T021200Z/receipt.json`。这些工程运行不能记为模型失败或合格任务。当前完整源失败记录为 `outputs/research/entity_group_G01_linear_source_20261030T224840Z/private/build_attempts/47fa51a4ea3e4a77b616a86a1e5c950f/terminal.json`，全量范围对照为 `outputs/research/entity_group_G01_linear_count_20261030T224830Z/receipt.json`，小规模实际审计为 `outputs/research/entity_group_current_fx_resource_toy_20261030T224100Z/receipt.json`。新的完整来源运行位于 `outputs/research/entity_group_G01_capacity_v2_source_20261030T230300Z/`，一次容量测试的只读补证位于 `outputs/research/entity_group_G01_capacity32_actual_20261030T225700Z/readonly_output_addendum.json`。

大表工程另有两个独立实现：前置标签索引保持全部画像字段不变，在同一真实资本来源上从原节点约 287 秒降至约 10 秒；稀疏评分器保持完整值与修改集合比较，在每本 10 万非空单元格的实际对照中，内存峰值约 41 MiB，对照原版约 253 MiB，评分完全一致。这些性能证据不代表生产大表已通过，新实现没有更换当前冻结题目的评分器。独立的小规模新资源导出另已实际通过 Harbor oracle=1、nop=0；四个实际解题及验证容器均核实为 2 CPU、32 GiB，构建镜像的底层镜像层也与固定基础镜像一致。证据为 `outputs/research/resource_harbor_actual_toy_controls_provider_default_20261030T232505Z/receipt.json`；这只是运行链路测试，没有增加合格题。七类真实财务缺陷的另一小规模样本经两次实际重算稳定，126 处公式编辑、完整值变化集合 531、原生错误为零；它没有经过最强模型测试，不能称为难度证明。

资源评测现有独立的 17 文件导出、开发快照、强模型入口和实际容器观察器，旧 13 文件评测与成绩保持不变。观察器仅读取当前试验的实际容器 ID、CPU/内存约束和镜像层，缺失覆盖或资源不符时暂停发布，不改模型原始分数。新观察器已在同一真实小任务完成 oracle=1、nop=0，两个试验的 agent 与 verifier 共四个容器均实际满足 2 CPU、32 GiB 和基础镜像约定；终态证据为 `outputs/research/resource_observer_actual_toy_smoke_20261031T002931Z/receipt.json`。该烟测不调用模型，也不替代生产题的质量、资源证据或整体难度确认。

具体失败机制与新实验设计见 [业务任务设计说明](docs/failure_driven_task_design.md)。官方论文案例与当前公开输入已逐项核对；公开完整轨迹缺失的地方明确保留证据边界。两道固定公开研究案例另以相同最强配置、一次尝试和工具预算复测，不作为构造来源或交付任务。两道公开案例均已正常终态：银行补全在本项目精确评分与原官方评分下均为 1，工具执行 61.750037806 秒；重复计入调试两种评分均为 0，工具执行 189.579431906 秒。官方调试修改准确率为 0.743、回归准确率为 0.9706，逐项轨迹复核确认模型修复了全部三类、15 个原始重复计入公式，又修改了 592 个原表定义并调整融资、费用和估值政策。原题包含全面审计要求，故不能把所有额外改动一概认定为财务错误；原官方零分也不能仅用新增辅助表解释。实际资源、计时与零重试均已核实。官方后处理收据为 `outputs/research/external_pair_official_postscore_20261031T025757Z/receipt.json`。多实体数据呈现实验保留全部必要假设与财务计算，去除重复 JSON 和程序字段路径；输入、参考分别实际重算后各有 1,111,028 个非呈现单元格逐项完全一致。另重新遍历四份工作簿，完整变化集合仍为 261,457。新版本首次最强模型开发测试已经正常结束，reward=1，累计工具执行 371.134196162 秒，全部 261,457 处变化集合匹配，无基础设施或计时缺失。实测位于 `outputs/difficulty/entity-G01-native-presentation-first-development-20261031T025200Z/evaluation/`；它没有继承旧版本质量、公开恢复或难度成绩，后续不扩充相同模板。

配置位于 `config/`，角色提示词位于 `prompts/`，节点与模板位于 `src/sheets_factory/`，输入位于 `data/`，运行数据和面板审计位于 `outputs/`。密钥仅保存在环境变量或被忽略的 `.secrets/`。

Git 仓库包含代码、配置、提示词、测试、文档和来源清单。下载的种子、`outputs/` 实验产物与运行凭据不纳入版本控制；下文历史题目发布包的 `outputs/` 链接指向原运行机器上的本地产物。固定运行镜像另已上传为私有 GitHub Release 附件。新检出仓库可按启动命令重新构造任务。

## 构建方法

```text
财务来源 → LibreOffice 规范化与画像 → LLM 业务计划 / 业务模板 → 公式遮蔽 / 缺陷注入
→ 仅公开信息的程序化恢复 → 不评分的自然尝试 → 全部质量检查与问题路由
→ 有限预算修复 → 真实 Harbor oracle/nop → 文件哈希与版本绑定 → 冻结发布
```

历史质量批次采用 EUSES financial 工作簿；难度迭代另外评估 NYU Damodaran 公开模型及明确声明为假设场景的派生财务模型，不复用官方 benchmark 题目。原始文件与规范化 baseline 保持不可变；画像记录多表结构、真实跨表依赖和重算结果。LLM 选择业务模块、补全规则与调试缺陷，程序据计划构造 input 和 reference；Financial Modeling 遮蔽待补公式，Debugging 注入有明确业务修复目标的错误。检查覆盖完整的下游值变化，避免把来源自带的业务错误当作正确答案。

`business_pilot.yaml` 使用简短业务题面、工作簿中的假设与政策摘要。已识别并独立验算的项目模型可使用 `project_template` 自动选择完整计算系列，其他来源仍由 LLM 规划；同一套构造、变化集合、诊断和运行控制继续执行。内部财务实现规范与公开任务分开，公开题面不重复逐步计算教程或调试根节点。`prompts/*_business.md` 分别控制规划、恢复、诊断与修复。

独立恢复者只能读取公开题面和 input，产出程序后在无网络的新容器重放，再由 LibreOffice 重算并与 reference 比较。自然尝试另行记录完整或部分轨迹，不按求解成功与否决定题目质量。公开信息、参考正确性、执行健康等启用检查均须给出结果。当前难度管线在候选阶段检查适用的复杂度约束与实际捷径，在完整候选集通过质量验收后另做冻结开发测试和独立确认；候选阶段没有未来的整体分数，不代表难度验收通过。确证内容问题进入新版本修复，证据不足进入补证，基础设施故障单列重试，三类预算分开且有限；修订后重新经过全部准出步骤。

主评分比较重算后的类型化单元格值：数字保留两位小数、日期归一化，公式文本不要求相同。全工作簿的提交修改集合必须与 GT 相同，期望位置的值也须匹配；多改、少改或值错均 reward=0。真实 Harbor 控制结果绑定任务版本和导出文件哈希，不能沿用已修改任务的旧成绩。

## 启动

需要 Python 3.12、uv、Docker 和可用的 Codex CLI 原生二进制。`config/llm.yaml` 配置二进制位置；密钥使用环境变量 `SHEETS_FACTORY_API_KEY` 或 `.secrets/api_key`，服务端点使用配置文件或 `.secrets/metadata.json`。

```bash
./scripts/run.sh --config config/pipelines/quality40.yaml

# 指定输入路径和总题量；默认平分两类
./scripts/run.sh --seeds /path/to/workbooks --count 40

# 无图形环境仍启动面板，结束后自动退出
./scripts/run.sh --headless --exit-on-finish

# 难度迭代：来源筛选、完整质量门禁、开发测试、独立确认、根目录发布
./scripts/run_difficulty.sh --config config/pipelines/hard20.yaml \
  --seed-manifest data/manifests/hard_financial_sources.json

# 派生模型路线：先构建并独立验算种子，使用实际输出的 manifest.json
.venv312/bin/python scripts/build_derived_scenarios.py \
  --output outputs/research/my_derived_seeds
./scripts/run_difficulty.sh --config config/pipelines/derived_hard20.yaml \
  --seed-manifest outputs/research/my_derived_seeds/manifest.json
```

每次运行会输出实际面板地址和审计目录。端口占用时自动分配空闲端口。默认结束后保留面板，Ctrl+C 关闭。

EUSES 下载与候选筛选可单独执行：

```bash
.venv312/bin/python scripts/fetch_euses.py --help
```

## 查看历史运行

```bash
.venv312/bin/python scripts/serve_dashboard.py \
  --run outputs/runs/<run_id> --port 8765
```

历史面板只读 SQLite，不读取 API 密钥、不重新调用模型，也不改变审计状态。

## 输出与统计

`outputs/runs/<run_id>/` 包含 SQLite、事件、配置快照、公开题面与 input、私有参考与恢复证据、逐项诊断、修复历史和真实 Harbor 控制结果。最终 Harbor 目录是该运行下的 `SpreadsheetEval/`。

候选只有在独立公开信息恢复、质量诊断、本地正反例和真实 Harbor oracle/nop 全部通过后才计为质量合格。检查默认全启用；只有历史 `quality40.yaml` 批次明确延后了正式难度要求。当前难度管线还必须通过整个冻结集的最强模型确认，才能发布到仓库根目录。单纯模型做对/做错不决定诊断或放行。

统计分开记录源使用数、有产出源数、候选数和最终题量。源转化率、候选转化率及每源产量各自说明分母。Token 来自实际 CLI 事件；费用没有可靠证据时显示未知。

2026-10-30 的组合难度迭代另有只读核算快照：12:30 UTC 起的明确实验范围、主生产轮、八个开发样题及六个后续质量运行截至 23:39 UTC 合计 68 次逻辑模型调用，已知 token 下界为 74,044,524，20 次调用的核心用量未知，30 次调用有未报告或可能未报告的尾部；所列开发测试和质量流程均已终止，不能将未知部分算为零。没有可归因的精确供应商账单，运行器按本地价格表计算的估价不作供应商实付。该范围排除更早的项目、组合资产与循环模型实验，不与下面的历史 40 题统计混加。逐调用去重清单位于本地 `outputs/research/composite_accounting_20261030T233933Z/receipt.json`，原快照保留。加入 D01 首次最强模型终态后，同一范围更新为 69 次逻辑调用、已知 token 下界 75,604,383（输入 74,905,269、输出 699,114）；20 次核心用量未知和 30 次尾部不完整标记继续保留，缓存与推理 token 是子集，不重复相加。更新收据为 `outputs/research/composite_accounting_69_D01_terminal_20261031T010747Z/receipt.json`。D01 单次运行器估价为 $0.6396668，供应商实际费用仍未知。 G01 首次最强模型终态已单独扩展为 70 次逻辑调用、已知 token 下界 79,035,224（输入 78,317,772、输出 717,452），历史未知标记保持不变；新收据为 `outputs/research/composite_accounting_70_G01_terminal_20261031T023900Z/receipt.json`。G01 单次运行器估价为 $1.8637332，供应商实际费用未知。两道公开案例的外部研究调用使用单独范围，不进入本转换分母。 两次外部调用另有完整原生终态用量收据：输入 3,477,753、输出 50,232，合计 3,527,985 token；缓存与推理子集不重复计入，运行器两次估价合计 $1.454434，供应商账单未知。独立范围收据为 `outputs/research/external_pair_final_usage_20261031T030740Z/receipt.json`；随后 40 项补全、原生呈现调试与组合调试均已终止。本范围现为 73 次逻辑调用，已知 token 下界 90,840,128；20 次核心用量未知、30 次尾部不完整标记保留，供应商累计账单未知。更新收据为 `outputs/research/composite_accounting_73_compound_terminal_20261031T041200Z/receipt.json`。外部两例仍以独立范围统计。

完成运行 `20261029T121133Z-7bf764`：实际使用 49 个来源工作簿，创建 83 个候选，合格 40 题（两类各 20 题），拒绝 43 个候选。候选转化率为 40/83 = 48.19%；22 个来源贡献合格题，源转化率为 22/49 = 44.90%。离线画像数量、种子池数量与正式使用数量分别统计。

- [完整 40 题发布包](outputs/releases/20261029T121133Z-7bf764-20x2-20261029T174511192721Z-fb8d5b9c/SpreadsheetEval.tar.gz)；[逐题证据清单](outputs/releases/20261029T121133Z-7bf764-20x2-20261029T174511192721Z-fb8d5b9c/release_manifest.json)；[SHA256](outputs/releases/20261029T121133Z-7bf764-20x2-20261029T174511192721Z-fb8d5b9c/SpreadsheetEval.tar.gz.sha256)。40 次真实 oracle 均为 1，40 次真实 nop 均为 0。
- [首批 10+10 发布包](outputs/releases/20261029T121133Z-7bf764-10x2-20261029T163454051052Z-749ae051/SpreadsheetEval.tar.gz) 保留，后续发布没有覆盖该阶段成果。
- [本轮运行报告](outputs/runs/20261029T121133Z-7bf764/reports/report.zh-CN.md)：正式 CLI 调用 349 次，已记录 77,182,426 token，另有 9 次调用核心用量未知。端到端运行 5 小时 25 分钟。共享凭据请求时间窗观测费用 $92.347700，包含试跑和其他流量，不能作为本次正式管线的精确费用。
- [Financial Modeling 专业审计索引](outputs/validation/final_financial_business_audit_index_20261029T174729Z.md)：当前 20 题的全部 818 个变化单元格另有独立验算，逐题绑定当前版本及五类工件 SHA；不把复现来源自带公式当作业务正确性证据，也不认证变化集合之外的原始工作簿。

运行报告位于 `outputs/runs/<run_id>/reports/` 下的 `report.json`、`report.zh-CN.md` 和 `report.html`，重新生成时更新快照；完整批次另建发布目录和清单。时间、来源分母与共享凭据费用的定义见 [核算说明](docs/accounting.md)。

## 失败案例与修复边界

| 观察 | 处理及结论 |
| --- | --- |
| BBC 来源的原生月净利扣减了年折旧，进一步污染 annualCF；编辑根节点正确仍可能得到错误的下游财务结果。 | 原候选被 Q04/Q09 拦截。后续候选选择安全的资产负债表累计折旧模块，重新通过检查；没有修改来源 baseline 来迎合参考答案。 |
| 租赁来源的资产负债表累计折旧遗漏第二笔资产投入；独立复原出原公式仍不代表业务正确。 | 原版本被 Q04/Q09 拒绝，新版本改选可完整验证的销售 pipeline 收入模块。原生缺陷登记为精确单元格区域，发布时再次检查实际完整值变化集合。 |
| 来源有多张表，却不存在真实跨表公式依赖。 | 画像阶段早拒，不用增加无业务意义的跨表引用补齐条件。 |
| 题面要求“其他值全部不变”，同时目标公式又必须触发下游重算。 | Q03 最小修补仅修改公开说明，区分保留未编辑的公式/字面输入与允许其计算结果联动；新版本重跑恢复、诊断和真实 Harbor，旧控制仅作历史记录。 |
| 600 秒诊断执行超时，与自然求解中的业务理解或公式错误混在一起会误判质量或难度。 | 前者按执行健康问题记录并有限重试；普通 solver 错误交给诊断分析，有进展但未完成的自然尝试保留部分轨迹。两者都不能替代必须成功的独立程序化恢复。 |
| 一次新模型开发尝试得到零分，但 31 处不匹配全部是本金辅助行采用负数现金支出，其他经济结果匹配。 | 该版本缺少辅助行符号约定，不能把此零分当作难度成果。保留真实结果并退回造题；公开契约补齐正数支付金额、带符号现金流和营运资金变化方向后，才允许新版本进入验收。 |

更多证据边界与修复记录见 [独立审查说明](docs/review_notes.md)。

## 模型与评估口径

| 对象 | 当前证据 | 可以说明什么 |
| --- | --- | --- |
| 真实 Harbor oracle / nop | 完整冻结 40 题逐题得到 1 / 0，原始结果与发布清单绑定。 | 参考产物可被接受、原样不作答会被拒绝；这是正反控制，不是模型能力分数。 |
| `gpt-6-sol` / `high` 自然 trajectory | 已用于构建过程中的诊断，包含不同版本和部分尝试。 | 不汇总为正式冻结任务集的 Overall Pass@1；成功与失败都不是题目质量的单独判据。 |
| `gpt-6.1-sol` / `xhigh` 旧 40 题开发筛查 | 主动早停前已有 13 次正常成功；40 题整体通过率下界为 32.5%，未完成的测试没有记零。 | 旧批次不满足 ≤20%；这不是完整批次的正式 Overall Pass@1。新来源和新模块正在迭代。 |
| `gpt-6.1-sol` / `xhigh` 首轮新模块试验 | 3 道预质量验收 Financial Modeling 开发样例全部得到正常 reward=1。 | 这次模块扩展仍太简单，不能作为交付集；因此转向完整的融资、税务、资产和现金分配联动模型。 |
| `gpt-6.1-sol` / `xhigh` 契约与准备金原型 | 1 道开发样题在 607 秒内正常得到 reward=1，完整单题预算仍为 1800 秒。 | 跨期测试、分红锁与偿债准备金联动仍不足以证明难度；该结果不作难度准出。 |

正式模型分数在事先冻结的任务集上逐题做一次独立求解，按二值 reward 的算术平均计算 Overall Pass@1；开发测试与重新独立调用的确认测试分开。基础设施异常单列，仅确证的基础故障可以受限恢复，有效的零分不会重测；正常时间预算耗尽须复核原始执行、模型用量和独立评分证据。当前难度迭代还在运行，最终真实 `SpreadsheetEval/` 目录和完整 oracle 执行结果将在确认通过后交付。

累计工具耗时从原生 Codex 执行记录复算，排除模型思考及生成回答的时间；并行执行分别累加，异步轮询不重复计算同一进程。达到或超过 1800 秒时，有效奖励为 0，同时保留原始工作簿评分。计时证据缺失时记录为未知，不能记作模型失败或据此重新采样；发布前重新核对计时记录及其哈希。

结构扩展实验使用相同最强配置和单次开发尝试，结果如下。各行不是一个预先冻结的整体测试集，不能将这些分数汇总为最终 Overall Pass@1。

| 开发方向 | 实际结果 | 解释 |
| --- | --- | --- |
| 12 项目、171 sheets、遮蔽 59,165 个公式 | 正常 reward=1；工具累计 60.514 秒 | 扩大同类结构后仍可程序化完成。 |
| 唯一固定点循环融资 | 旧合同原始 reward=0；工具累计 19.966 秒 | 旧版整段时限触发，不能按现行 1800 秒累计工具合同计为难度失败。 |
| 循环融资 × 高级税务 | 正常 reward=1；工具累计 6.952 秒 | 有真实跨期结转和反馈，仍不足以达到难度目标。 |
| 20 年监管资本、税基与收入回收款 | 正常 reward=1；工具累计 47.469 秒 | 独立监管模型仍未达到难度目标，保留唯一有效开发结果。 |
| 12 项目 × 564 个已验证活跃调试根节点 | 正常 reward=1；工具累计 46.820 秒 | 大量同类公式可被统一修复，未计入难度达标。 |
| 跨实体现金池与抵押融资 | 原始 reward=0，但辅助行有约定歧义 | 保留原结果；排除该零分的难度证明，另建明确约定的新修订。 |
| 完整财务与合同状态补全，60,193 个目标 | 正常 reward=1；工具累计 234.131532611 秒 | 质量及实际 oracle/nop 通过；停止扩充相同补全模板。 |
| 完整依赖图 Debugging V2，20,895 处公式修改 | 正常 reward=1；工具累计 295.482089056 秒 | 正常完整修复，保留成功记录，停止同模板批量。 |
| 完整依赖图 Debugging V3，组合账户、期间与边界错误 | 正常 reward=1；工具累计 382.012271739 秒 | 多种缺陷组合仍被解出，尚未形成难度达标题集。 |
| 18 项共同投资决策 × 三情景融资税务 | 原始 reward=0；工具累计 63.660244024 秒 | 投资选择与财务计算实际正确；公开汇总字段及候选项目约定不完整，Q02 暂停，不作难度证明。 |

旧循环任务的工具耗时来自保留原文件的只读补充复算；新评测直接冻结计时规则。已评分的相同版本不重新采样；旧整段时限结果与现行累计工具合同分开。

## 派生财务模型的来源与验算

`scripts/build_derived_scenarios.py` 从一个公开来源的数值锚点构造 10 个明确的假设场景。原始锚点来自 [NYU Damodaran 的 FCFF 模型](https://pages.stern.nyu.edu/~adamodar/pc/fcffginzu.xlsx)，下载文件的 SHA 和取值位置写入每个种子的来源清单；项目期限、建设期、贷款、周转与分红规则均为公开的假设条件，不冒充来源公司的真实预测。

每个场景有 12 张表、3,882 个公式。独立的 Decimal 双重记账程序与 Excel 公式生成器分别实现计算，检查 3,937 个绑定单元格、试算平衡、资产负债、现金、债务和税务关系，再以真实 LibreOffice 验证所有公式及两次重算稳定性。场景还必须实际触发各自的机制，例如贷款清偿、年内到期、跨年投产、亏损抵扣上限或折旧耗尽；只改参数却没有触发预定机制的文件不能进入种子清单。

这只证明种子财务模型可用于造题。完整题目仍需独立公开恢复、逐项诊断、真实 oracle/nop 和最强模型确认。统计时分别报告“1 个原始来源”“10 个派生场景文件”和实际候选题数，不把派生文件计作 10 个独立原始来源，也不把大量重复公式当作难度证据。

高级项目模型另外包含契约与准备金状态，以及税务折旧、到期亏损批次、利息抵扣结转和递延税三表桥接。首个真实构建的高级模型有 14 张表、5,262 个公式，5,334 个绑定单元格通过独立记账与 LibreOffice 验算；这仍只是种子验证。`config/derived_advanced_tax_scenarios_v1.json` 预先声明各场景应触发的机制，适配器按实际计算结果筛选，分别记录亏损到期、批次竞争、利息结转、递延税变化及现金约束。只有真实执行产生证据的案例才进入造题清单。

组合模型的构建入口为 `scripts/build_portfolio_source.py`，参数位于 `config/derived_portfolio_v1.json`。它保留 12 个明确的假设项目及各自政策，再加入集团汇总报表，共 171 张表、66,293 个公式；实际源验证检查了 67,157 个单元格，覆盖所有公式，并执行两次 LibreOffice 重算与稳定性比较。来源仍计为 1 个原始祖源。首次开发实验遮蔽 59,165 个公式，最强配置单次正常得分为 1；规模与公式数量本身不构成难度证明，该实验不能作为达标题交付。

```bash
.venv312/bin/python scripts/build_portfolio_source.py --output data/seeds/portfolio --recalculate
.venv312/bin/python -m sheets_factory.cli --config config/pipelines/portfolio_scale.yaml
```

`portfolio_scale.yaml` 使用完整公式系列和独立财务参考复核。该证据模式要求全部 12 项检查，Q01–Q04 必须有明确支持，且参考、变化集合、诊断与运行控制均绑定当前文件哈希；它不声称执行了独立公开恢复。默认流水线继续使用独立公开恢复。调试可选择依赖分离证明：在原始与注入后的完整依赖图中排除所有根节点间依赖，再用真实联合重算的逐根值差异证明单独及边际影响，避免重复启动数百次相同计算。证明不成立时拒绝候选。

循环融资模型具有真实的债务规模—利息—税款—现金流反馈，独立有限档位检查验证唯一固定点。迭代运行镜像位于 [runtime-lo-24.2-iterative-v1 Release](https://github.com/ZhaoyangHan04/sheetsFactory/releases/tag/runtime-lo-24.2-iterative-v1)，保留 LibreOffice 24.2.7.2，镜像 ID 为 `sha256:5c74b8a362305b20d736bdbad041a12a6159e31f3bde4a0a068a7ee71d6937d6`。镜像仅对启用迭代的工作簿执行有界的完整使用区域收敛检查；普通工作簿保持一次计算。附件 SHA256 与实际重新加载后的镜像身份均已验证。

新的异构组合来源把四类租约的重估和终止、监管资本与税基、延迟且受限的回收款，以及母公司的有限出资和抵押融资连接起来。项目投资保留原 USD 币种及 2027–2029 日历，母公司按明确的假设汇率和 4 月至次年 3 月年度归集。原 [Ofgem ED2 模型](https://www.ofgem.gov.uk/guidance/ed2-price-control-financial-model) 是已提供的公开背景，新增政策明确为假设场景；原模型可公开下载的公式不作为新增难度。单纯恢复这些公开公式的调试方案已因可下载捷径淘汰。

首份组合来源实际有 69 张表，四个独立记账实现分别核对 49,100、6,440、5,334、2,020 项，合计 62,894 项全部匹配真实 LibreOffice，后续两次重算稳定。它证明源表可用于造题，还没有证明题目难度。构建入口如下；配置引用已经审计的公开来源缓存和项目来源 manifest，缺失时拒绝运行，不自动以其他表替换。

首道组合候选遮蔽 59,279 个公式，通过五项本地控制、仅公开输入的隔离独立恢复，以及真实 Harbor oracle=1、nop=0 且无执行异常。最强模型正常达到单题总时限，输出得到原始 reward=0；逐项复核 1,203 处差异后发现，主要经济结果一致，差异来自事件辅助量、抵销展示符号及小计阶段定义，不能据此认定模型未能完成财务建模。原始工具轨迹末尾还有未完成记录，原评分清单保留 evidence_incomplete，不补写精确工具时间、不把该次计作有效难度失败。组合场景批量计划只完成独立记账预检，未扩为十份真实源表或十道达标题。后续新版本单独明确展示口径，并加入影响实际现金、税款和回收额的当年反馈；原冻结题和试验记录保留。

六类业务版本由 `config/derived_composite_finance_v4.json` 声明，在上述四类模型上加入当年回收收入与浮动租金、税额的真实循环，以及 LP/GP 回本、优先收益、追补与次年生效的分成切换。公开条款完整列明金额、顺序、日期和舍入规则。循环唯一性按每年完整序列验证，双端点在整个合同费用网格上汇合才接受；24 个预先声明的参数场景中 13 个通过两种回收政策的完整检验，保留全部拒绝。实际来源有 75 张表、63,744 个公式，五份独立财务审计合计核对 63,816 个值全部匹配 LibreOffice，两次后续计算稳定。六类业务使用五份审计，因为浮动租金循环同时进入监管记账，并未虚增独立审计数量。

该来源的 Financial Modeling 候选只遮蔽 46,339 个数字财务输出，提供事件、期限和阶段辅助计算；33 个矩形覆盖 26 张计算表。五项本地控制、公开恢复及真实 Harbor oracle=1/nop=0 已通过；最强模型正常结束但没有生成提交，开发 reward=0，工具执行 11.825 秒。该结果不证明某个财务计算错误；同接口小型正例实际成功，尚无证据将此次正常结束归为基础设施故障。质量私有诊断首次超时后，第二次独立补证正常完成，适用单题质量检查通过；Q08 的候选阶段结论为不适用，整体难度尚待完整冻结集确认。

另一个 Debugging 候选的 206 个根节点通过 19 批、38 次真实计算验证，精确版本另有实际 Harbor oracle=1/nop=0。旧强模型测试仅被总时限截断，不能用作工具预算下的难度证据；新合同测试正常得到 reward=1。最初计时解析未能归属混合进程轮询中的文件改动，原评估清单如实保留为 evidence_incomplete；修复严格归属后，只读重新解析原轨迹，35 次命令及 4 次文件改动完整覆盖，累计工具执行精确为 285.472099256 秒，有效 reward=1，未重跑模型、未覆盖旧清单。补充清单位于 `outputs/research/composite_debug_timing_reconciliation_20261030T161100Z/manifest.json`。私有诊断补证另发生流式连接中断，质量结论仍不完整。根节点规模、已知邻行公式和公开恢复成功均不代替难度实测。

六类业务的冻结批次实际检查 20 个预声明参数场景，16 个通过独立记账预检，按原顺序选择的 10 个全部完成真实源表构建、财务审计和两次稳定性计算；recipe 哈希保持一致。这些是两个原始公开工作簿的十个派生场景，不是十个独立公司来源或十道合格题目。逐源清单位于本地 `outputs/research/composite_six_batch_20261030T144200Z/seed_manifest.json`。调试根有效性另有可选 `shadow_roots` 验证：完整纯静态联合无环图加两次实际影子计算，证明逐根单独及联合边际影响的非空下界，不声称执行了逐根工作簿或得到完整逐根变化集合。206 根实际校准与原 38 次计算的结果全部一致；默认严格验证保持原样。

四类业务的另一批次实际检查 16 个预声明场景，其中 10 个通过预检并全部完成源表构建、四项财务审计及两次稳定计算，记录于 `outputs/research/composite_four_dbg_batch_20261030T151900Z/seed_manifest.json`。两批共 20 个派生工作簿仍来自相同两个原始来源，尚未转化为 20 道合格题。主生产旧轮在任何模型调用前发生主机临时盘空间不足，保留失败记录；修复将临时文件限定到本轮数据盘目录，实际保存与 LibreOffice 重算烟测通过后，以同一冻结来源顺序启动 `outputs/runs/20261030T161600Z-composite-quality20-data-temp/`。这属于基础设施修复，不计为新模型尝试或难度失败。

后续独立复核发现六类业务公开说明的真实冲突：11 份基础及派生来源中有 10 份的数值参数为一年回收滞后，而 `Reopener Brief!A21` 保留了两年描述。逐源扫描位于 `outputs/research/six_source_public_lag_audit_20261030T171423Z/receipt.json`，源工作簿未改。C01 数值反证另分别按一年、两年完整重放 20 个年度，两种解释各自都有唯一结果；自然轨迹声称的双固定点来自另一组前序状态，并含资产表顺序替代合同要求的投运年度 FIFO 的错误。因此保留 Q02 的公开冲突阻断，同时保留 Q04 具体反证被否定的数值证据，不用原质量通过标记压过新发现，也不把有任务缺陷的早期强测用于难度准出。新题面将程序化明确数值输入对描述性默认值的优先级，并重新经过全部检查。审计位于 `outputs/research/C01_economic_counterexample_audit_20261030T170700Z/`。

完整租约四族调试版本通过新源精确值等价、独立租约审计与其余模块明确的传递覆盖、1,666 根双上下文影响证明、完整变化集合 16,756 处及五项本地控制。最强模型正常解出，真实累计工具执行 159.403807054 秒；成绩位于 `outputs/difficulty/lease-family-v2-20261030T164700Z/evaluation/evaluation_manifest.json`。它证明清除完整相邻公式模板仍不够，保留的金融子计算也可能支持快速重建；下一构造方向覆盖完整业务依赖子图，不能把根节点数量替代实测难度。

```bash
.venv312/bin/python -m sheets_factory.workbook.composite_finance.build \
  --config config/derived_composite_finance_v1.json \
  --output outputs/research/composite_source_new
.venv312/bin/python scripts/prepare_composite_probe.py \
  --source-manifest outputs/research/composite_source_new/seed_manifest.json \
  --output outputs/runs/composite_probe_new
```

组合计算使用独立镜像 `sheetsfactory-lo:24.2-iterative-openpyxl315-v1`，其构建器与依赖 SHA 位于 `runtime/lo24.2-iterative-openpyxl315-v1/`。精确镜像已上传至 [私有 runtime Release](https://github.com/ZhaoyangHan04/sheetsFactory/releases/tag/runtime-lo-24.2-iterative-openpyxl315-v1)，新下载后的归档 SHA 和实际 Docker 加载身份均已验证，具体命令见该 runtime 目录说明。它保留已审计的 LibreOffice 与迭代实现，只更新工作簿解析库以读取公开模型的合法命名样式；旧题目和旧镜像不变。

## 打包交付

发布脚本只从当前实际 qualified 且报告核验通过的集合选题，再复核原始 oracle/nop 结果、文件哈希、诊断和恢复证据。公开诊断缓存与私有参考诊断分别绑定来源和内容，私有诊断必须审阅当前恢复证据。每类数量不足时严格拒绝生成发布包。

```bash
# 第一批：Financial Modeling 10 道 + Debugging 10 道
.venv312/bin/python scripts/package_release.py --run outputs/runs/<run_id> --per-mode 10

# 完整批次：两类各 20 道，另建新发布，不覆盖第一批
.venv312/bin/python scripts/package_release.py --run outputs/runs/<run_id> --per-mode 20
```

命令会输出新发布目录、`SpreadsheetEval.tar.gz` 和 SHA256 的绝对路径。解压后，先在发布目录准备运行镜像，再执行 Harbor 控制：

```bash
./prepare_runtime.sh
harbor run --path SpreadsheetEval --agent oracle
harbor run --path SpreadsheetEval --agent nop
```

发布包附带白名单内的最小 `runtime/` 构建上下文、准备脚本和操作说明；清单记录本次运行实际使用的镜像 ID、LibreOffice 版本和 recipe 文件哈希。默认不附大型镜像；apt 间接依赖与仓库可能变化，重新构建不保证得到原镜像 ID。私有诊断和请求日志不进入发布包。

最终根目录发布后，必须在仓库根目录执行任务书的原命令 `harbor run -p SpreadsheetEval -a oracle`，并对 nop 执行完整控制。不能用某一题、历史运行或成功退出码代替全量结果。可用只读审计工具核验实际 job 中的每个任务、文件哈希、执行身份、完整覆盖、异常和二值奖励；它不会重新运行评测，也不会生成奖励：

```bash
.venv312/bin/python scripts/audit_harbor_job.py \
  --dataset SpreadsheetEval --job jobs/<actual_oracle_job> --agent oracle \
  --command-cwd "$PWD" --output outputs/validation/final_oracle.json
```

已将[固定运行镜像、SHA 和校验清单](https://github.com/ZhaoyangHan04/sheetsFactory/releases/tag/runtime-lo-24.2-d2e00cbc)上传至私有仓库附件，并验证重新载入可得到原镜像 ID。持有仓库权限的环境可直接获取相同镜像，避免依赖未来的 apt 仓库状态：

```bash
gh release download runtime-lo-24.2-d2e00cbc --repo ZhaoyangHan04/sheetsFactory \
  --pattern 'sheetsfactory-lo-24.2-d2e00cbc.tar.gz*' --dir outputs/runtime-downloads
(
  cd outputs/runtime-downloads
  sha256sum -c sheetsfactory-lo-24.2-d2e00cbc.tar.gz.sha256
  docker load -i sheetsfactory-lo-24.2-d2e00cbc.tar.gz
)
```

镜像名为 `sheetsfactory-lo:24.2`，LibreOffice 为 `24.2.7.2`；压缩包 SHA256 为 `0abd761bc55f230332a0ee37e6a2dce3ce75dae0179a94f4a00adb91559a4e77`。本地也保留了[镜像校验清单](outputs/releases/runtime/runtime_manifest.json)。代码按功能分阶段提交，远程仓库为 [ZhaoyangHan04/sheetsFactory](https://github.com/ZhaoyangHan04/sheetsFactory)，当前为私有仓库。

## 测试

```bash
./scripts/test.sh -q
SF_TEST_LIBREOFFICE=1 ./scripts/test.sh tests/test_workbook.py -q
```

测试报告必须区分模拟 Provider、真实 Codex、LibreOffice 与 Harbor。部署与评测约束见 [docs/architecture.md](docs/architecture.md)、[docs/evaluation_requirements.md](docs/evaluation_requirements.md)、[docs/review_notes.md](docs/review_notes.md)。代码按功能和测试里程碑分批提交。
