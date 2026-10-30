# sheetsFactory

从公开财务工作簿自动构造可审计的财务补全与公式调试任务。

上一轮已完成 20 道 Financial Modeling、20 道 Debugging 的质量验收并保留冻结发布包；该批次没有通过难度验收。当前正在迭代两类各至少 10 题，构造与诊断使用 Codex CLI `gpt-6-sol` / `high`，难度门禁固定使用 Codex CLI `gpt-6.1-sol` / `xhigh`、每题 1800 秒，要求冻结确认集 Overall Pass@1 ≤ 0.2。未完成最终确认前，不作难度达标声明。

配置位于 `config/`，角色提示词位于 `prompts/`，节点与模板位于 `src/sheets_factory/`，输入位于 `data/`，运行数据和面板审计位于 `outputs/`。密钥仅保存在环境变量或被忽略的 `.secrets/`。

Git 仓库包含代码、配置、提示词、测试、文档和来源清单。下载的种子、`outputs/` 实验产物与运行凭据不纳入版本控制；下文指向 `outputs/` 的链接是原运行机器上的本地产物，当前未上传为 GitHub 附件。新检出仓库可按启动命令重新构造任务。

## 构建方法

```text
财务来源 → LibreOffice 规范化与画像 → LLM 业务计划 → 公式遮蔽 / 缺陷注入
→ 仅公开信息的程序化恢复 → 不评分的自然尝试 → 全部质量检查与问题路由
→ 有限预算修复 → 真实 Harbor oracle/nop → 文件哈希与版本绑定 → 冻结发布
```

历史质量批次采用 EUSES financial 工作簿；难度迭代另外评估 NYU Damodaran 公开模型及明确声明为假设场景的派生财务模型，不复用官方 benchmark 题目。原始文件与规范化 baseline 保持不可变；画像记录多表结构、真实跨表依赖和重算结果。LLM 选择业务模块、补全规则与调试缺陷，程序据计划构造 input 和 reference；Financial Modeling 遮蔽待补公式，Debugging 注入有明确业务修复目标的错误。检查覆盖完整的下游值变化，避免把来源自带的业务错误当作正确答案。

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

正式模型分数在事先冻结的任务集上逐题做一次独立求解，按二值 reward 的算术平均计算 Overall Pass@1；开发测试与重新独立调用的确认测试分开。基础设施异常单列，仅确证的基础故障可以受限恢复，有效的零分不会重测；正常时间预算耗尽须复核原始执行、模型用量和独立评分证据。当前难度迭代还在运行，最终真实 `SpreadsheetEval/` 目录和完整 oracle 执行结果将在确认通过后交付。

## 派生财务模型的来源与验算

`scripts/build_derived_scenarios.py` 从一个公开来源的数值锚点构造 10 个明确的假设场景。原始锚点来自 [NYU Damodaran 的 FCFF 模型](https://pages.stern.nyu.edu/~adamodar/pc/fcffginzu.xlsx)，下载文件的 SHA 和取值位置写入每个种子的来源清单；项目期限、建设期、贷款、周转与分红规则均为公开的假设条件，不冒充来源公司的真实预测。

每个场景有 12 张表、3,882 个公式。独立的 Decimal 双重记账程序与 Excel 公式生成器分别实现计算，检查 3,937 个绑定单元格、试算平衡、资产负债、现金、债务和税务关系，再以真实 LibreOffice 验证所有公式及两次重算稳定性。场景还必须实际触发各自的机制，例如贷款清偿、年内到期、跨年投产、亏损抵扣上限或折旧耗尽；只改参数却没有触发预定机制的文件不能进入种子清单。

这只证明种子财务模型可用于造题。完整题目仍需独立公开恢复、逐项诊断、真实 oracle/nop 和最强模型确认。统计时分别报告“1 个原始来源”“10 个派生场景文件”和实际候选题数，不把派生文件计作 10 个独立原始来源，也不把大量重复公式当作难度证据。

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

本次另存了[实际运行镜像](outputs/releases/runtime/sheetsfactory-lo-24.2-d2e00cbc.tar.gz)和[镜像校验清单](outputs/releases/runtime/runtime_manifest.json)，已验证重新载入得到原镜像 ID。可先执行 `docker load -i <镜像文件>`，再按发布包说明运行。代码按功能分阶段提交，远程仓库为 [ZhaoyangHan04/sheetsFactory](https://github.com/ZhaoyangHan04/sheetsFactory)，当前为私有仓库。

## 测试

```bash
./scripts/test.sh -q
SF_TEST_LIBREOFFICE=1 ./scripts/test.sh tests/test_workbook.py -q
```

测试报告必须区分模拟 Provider、真实 Codex、LibreOffice 与 Harbor。部署与评测约束见 [docs/architecture.md](docs/architecture.md)、[docs/evaluation_requirements.md](docs/evaluation_requirements.md)、[docs/review_notes.md](docs/review_notes.md)。代码按功能和测试里程碑分批提交。
