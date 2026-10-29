# sheetsFactory

从 EUSES financial 种子自动构造可审计的财务补全与公式调试任务。

当前目标：20 道 Financial Modeling、20 道 Debugging。构造、诊断与自然尝试使用 Codex CLI `gpt-6-sol` / `high`。本轮明确暂缓难度门禁，保留其他质量门禁与真实 oracle/nop 验证。

配置位于 `config/`，角色提示词位于 `prompts/`，节点与模板位于 `src/sheets_factory/`，输入位于 `data/`，运行数据和面板审计位于 `outputs/`。密钥仅保存在环境变量或被忽略的 `.secrets/`。

## 构建方法

```text
财务来源 → LibreOffice 规范化与画像 → LLM 业务计划 → 公式遮蔽 / 缺陷注入
→ 仅公开信息的程序化恢复 → 不评分的自然尝试 → 全部质量检查与问题路由
→ 有限预算修复 → 真实 Harbor oracle/nop → 文件哈希与版本绑定 → 冻结发布
```

来源采用 EUSES financial 工作簿，不复用官方 benchmark 题目。原始文件与规范化 baseline 保持不可变；画像记录多表结构、真实跨表依赖和重算结果。LLM 选择业务模块、补全规则与调试缺陷，程序据计划构造 input 和 reference；Financial Modeling 遮蔽待补公式，Debugging 注入有明确业务修复目标的错误。检查覆盖完整的下游值变化，避免把来源自带的业务错误当作正确答案。

独立恢复者只能读取公开题面和 input，产出程序后在无网络的新容器重放，再由 LibreOffice 重算并与 reference 比较。自然尝试另行记录完整或部分轨迹，不按求解成功与否决定题目质量。公开信息、参考正确性、执行健康等启用检查均须给出结果；Q08 难度门禁本轮明确延后。确证内容问题进入新版本修复，证据不足进入补证，基础设施故障单列重试，三类预算分开且有限；修订后重新经过全部准出步骤。

主评分比较重算后的类型化单元格值：数字保留两位小数、日期归一化，公式文本不要求相同。全工作簿的提交修改集合必须与 GT 相同，期望位置的值也须匹配；多改、少改或值错均 reward=0。真实 Harbor 控制结果绑定任务版本和导出文件哈希，不能沿用已修改任务的旧成绩。

## 启动

需要 Python 3.12、uv、Docker 和可用的 Codex CLI 原生二进制。`config/llm.yaml` 配置二进制位置；密钥使用环境变量 `SHEETS_FACTORY_API_KEY` 或 `.secrets/api_key`，服务端点使用配置文件或 `.secrets/metadata.json`。

```bash
./scripts/run.sh --config config/pipelines/quality40.yaml

# 指定输入路径和总题量；默认平分两类
./scripts/run.sh --seeds /path/to/workbooks --count 40

# 无图形环境仍启动面板，结束后自动退出
./scripts/run.sh --headless --exit-on-finish
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

候选只有在独立公开信息恢复、质量诊断、本地正反例和真实 Harbor oracle/nop 全部通过后才计为 qualified。Q08 本轮明确延后；其他检查默认全启用。单纯模型做对/做错不决定诊断或放行。

统计分开记录源使用数、有产出源数、候选数和最终题量。源转化率、候选转化率及每源产量各自说明分母。Token 来自实际 CLI 事件；费用没有可靠证据时显示未知。

里程碑快照：运行 `20261029T121133Z-7bf764` 已核验 27 题（10 Financial Modeling、17 Debugging），仍在续跑至两类各 20 题。首批两类各 10 题已冻结为 [20 题发布包](outputs/releases/20261029T121133Z-7bf764-10x2-20261029T163454051052Z-749ae051/SpreadsheetEval.tar.gz)，该发布的 20 次 oracle 均为 1、20 次 nop 均为 0。这是阶段成果，不代表 40 题目标或难度目标已经完成。

运行报告位于 `outputs/runs/<run_id>/reports/` 下的 `report.json`、`report.zh-CN.md` 和 `report.html`，重新生成时更新快照；完整批次另建发布目录和清单。时间、来源分母与共享凭据费用的定义见 [核算说明](docs/accounting.md)。

## 失败案例与修复边界

| 观察 | 处理及结论 |
| --- | --- |
| BBC 来源的原生月净利扣减了年折旧，进一步污染 annualCF；编辑根节点正确仍可能得到错误的下游财务结果。 | 原候选被 Q04/Q09 拦截。后续候选选择安全的资产负债表累计折旧模块，重新通过检查；没有修改来源 baseline 来迎合参考答案。 |
| 来源有多张表，却不存在真实跨表公式依赖。 | 画像阶段早拒，不用增加无业务意义的跨表引用补齐条件。 |
| 题面要求“其他值全部不变”，同时目标公式又必须触发下游重算。 | Q03 最小修补仅修改公开说明，区分保留未编辑的公式/字面输入与允许其计算结果联动；新版本重跑恢复、诊断和真实 Harbor，旧控制仅作历史记录。 |
| 600 秒诊断执行超时，与自然求解中的业务理解或公式错误混在一起会误判质量或难度。 | 前者按执行健康问题记录并有限重试；普通 solver 错误交给诊断分析，有进展但未完成的自然尝试保留部分轨迹。两者都不能替代必须成功的独立程序化恢复。 |

更多证据边界与修复记录见 [独立审查说明](docs/review_notes.md)。

## 模型与评估口径

| 对象 | 当前证据 | 可以说明什么 |
| --- | --- | --- |
| 真实 Harbor oracle / nop | 首批冻结 20 题逐题得到 1 / 0，原始结果与发布清单绑定。 | 参考产物可被接受、原样不作答会被拒绝；这是正反控制，不是模型能力分数。 |
| `gpt-6-sol` / `high` 自然 trajectory | 已用于构建过程中的诊断，包含不同版本和部分尝试。 | 不汇总为正式冻结任务集的 Overall Pass@1；成功与失败都不是题目质量的单独判据。 |
| 后续 `gpt-6.1-sol` / `xhigh` 难度评估 | 尚未执行。 | `Overall Pass@1 <= 0.2` 尚未验证，不作达标声明。 |

正式模型分数应在冻结任务集上逐题做一次独立求解，按二值 reward 的算术平均计算 Overall Pass@1；基础设施异常需单列。本轮报告产量与质量控制，难度评估留待后续运行。

## 打包交付

发布脚本只从当前实际 qualified 且报告核验通过的集合选题，再复核原始 oracle/nop 结果、文件哈希、诊断和恢复证据。每类数量不足时严格拒绝生成发布包；命令示例不表示当前已经达到目标。

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

## 测试

```bash
./scripts/test.sh -q
SF_TEST_LIBREOFFICE=1 ./scripts/test.sh tests/test_workbook.py -q
```

测试报告必须区分模拟 Provider、真实 Codex、LibreOffice 与 Harbor。部署与评测约束见 [docs/architecture.md](docs/architecture.md)、[docs/evaluation_requirements.md](docs/evaluation_requirements.md)、[docs/review_notes.md](docs/review_notes.md)。代码按功能和测试里程碑分批提交。
