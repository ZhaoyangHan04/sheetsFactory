# sheetsFactory

任务书要求的目录位于仓库根目录：[SpreadsheetEval/](SpreadsheetEval)。当前固定候选集包含 **10道 Financial Modeling＋10道 Debugging**，新修订正在验收，尚未宣布准出。

原有5＋5道题的材料和历史成绩保留；新增5＋5道资本配置题已完成真实输入验算并导出，全部在最强模型新上下文中并行确认。根目录已安装这20题，完整oracle/nop命令正在验证。材料按[冻结清单](SpreadsheetEval/dataset_manifest.json)绑定，后续不依据确认结果替换个别题目。

| 组成 | FM | Debugging | 工作簿结构 |
| --- | ---: | ---: | --- |
| 保留经营报表题 | 5 | 5 | 每题211张sheet、200家虚构企业及分部/集团报表 |
| 新增资本配置题 | 5 | 5 | 每题741张sheet、两个各360项目的投资组合及集团报告 |

新增FM每题有3,044,678个实际变化位置；新增Debugging每题有约897,200个实际变化位置，注入172,800处公式错误和720个暂定项目选择。业务错误包括利息使用期末债务、税损在最后合法年度提前失效，以及情景冲击错误反馈到下一期收入基数，影响税、现金流和LP/GP估值。两个投资组合的预算、资源、地点和前置项目约束均需在各情景满足，选择按已入账S01 LP NPV最大化。

新来源由六份已独立验算的本地投资模型组合为五份健康工作簿。五份组合不是五个互不相关的公开数据集。每份组合核对两套完整财务结果和原始整数约束，组合最佳/次佳证书，并完成三次真实LibreOffice计算、完整财务/公式/原始数据审计和两次数值稳定性比较。每份新输入也另有真实重算和完整修改集合检查。

最强模型采用原生Codex CLI `gpt-6.1-sol` / `xhigh`。累计工具执行严格小于1800秒，模型响应时间不计入，并行工具分别累加；14400秒是运行保护时限。已完成的首组开发测试两份方案均达到金融最优值，但工具累计1828.02秒和1807.29秒，均违反工具预算。它们不是金融最优解错误的证据。新增十题的正式确认尚未结束；旧十题历史成绩与新十题确认将分开报告。

主评分比较重算后两位小数类型值与完整修改集合：多改、少改或应改值不正确均得0。完整20题的准出通过率按此主评分计算，须不超过0.2。错因分类用于解释结果，不另加准出阈值，也不改变原始评分。独立验证的工具预算失败按显式执行合同记失败；未知基础设施或计时不算模型失败。

公开与参考质量审查覆盖全部五组新题，十二项检查均保留。首轮四次审查超时，结论及用量保持UNKNOWN；补充四次审查已完成，未发现阻塞性的题意、业务假设或答案泄漏问题，实际资源检查通过。审查使用从实际原表提取的完整业务政策、明确标记的结构样本和绑定的完整程序审计；完整目录控制与难度仍待实际结果。

## 运行交付题集

需要 Python3.12、uv、Docker，以及仓库锁定的 Harbor0.25.0依赖。从仓库根目录执行：

```bash
UV_PROJECT_ENVIRONMENT=.venv312 uv sync --frozen --extra test --python 3.12
source .venv312/bin/activate
```

加载精确运行镜像 `sheetsfactory-lo:24.2-iterative-openpyxl315-v1`，步骤见 [运行镜像说明](runtime/lo24.2-iterative-openpyxl315-v1/README.md)。镜像含 LibreOffice24.2.7.2 和 openpyxl3.1.5，镜像ID为 `sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043`。仓库权限持有者可从该说明链接的私有 Release 下载并校验镜像归档。

任务书要求的完整目录命令是：

```bash
harbor run -p SpreadsheetEval -a oracle
```

完整负例控制：

```bash
harbor run -p SpreadsheetEval -a nop
```

当前固定20题的两条完整目录命令正在实际验证；新一轮结果尚未齐全，暂不声明当前目录已经全部通过。每个任务声明 `/app/input.xlsx` 和 `/app/output.xlsx`；运行现有题集的oracle/nop不需要模型API密钥。最终目录及逐题文件由 [dataset_manifest.json](SpreadsheetEval/dataset_manifest.json) 绑定。

## 使用构造管线

通用管线可从一个 `.xls` / `.xlsx` 种子目录启动：

```bash
./scripts/run.sh --seeds /path/to/workbooks --count 40
```

构造和诊断使用 `gpt-6-sol` / `high`。密钥通过 `SHEETS_FACTORY_API_KEY` 或被忽略的 `.secrets/api_key` 提供，端点配置位于 `config/llm.yaml` / 本地密钥元数据。每次运行自动启动面板，实时记录节点、事件、时间、token和产量；终端输出实际地址。

本批次的专用路线使用冻结的虚构业务来源、完整公式遮蔽或已知非零缺陷计划、每材料原生验算、开发筛选、事前冻结、新上下文确认及完整根目录控制。来源和构造审计保存在本地 `outputs/`；这些私有证据没有作为公开解题输入，也不随Git发布。已交付题集的运行不依赖这些构造审计。

| 目录 | 内容 |
| --- | --- |
| `SpreadsheetEval/` | 当前20题Harbor任务与冻结清单 |
| `config/` | 模型、代理、管线、任务适配和资源配置 |
| `prompts/` | 计划、题面、诊断及修复提示词 |
| `data/` | 种子与来源清单 |
| `src/sheets_factory/` | 节点抽象、继承实现、管线及工作簿构造 |
| `scripts/` | 一键启动、原生验算、模型评测、控制、只读审计和发布 |
| `outputs/` | 本地运行、审计、面板及私有构造证据，Git忽略 |
| `reports/` | 当前发布摘要和失败摘要 |
| `tests/` | 代码与证据合同测试 |


原20题发布、0/20历史确认及当时oracle/nop证据见[历史发布说明](docs/history/README_operating_report_factory_20261101.md)和[历史发布报告](reports/operating_report_factory_release.json)。这些原批次结果不代表当前新目录的确认成绩。[当前状态](docs/current_development_status.md)与[组合确认协议](docs/ringfenced_replacement_confirmation.md)说明证据边界。
