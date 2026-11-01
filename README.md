# sheetsFactory

任务书要求的目录位于仓库根目录：[SpreadsheetEval/](SpreadsheetEval)，包含 **10道 Financial Modeling＋10道 Debugging**。完整目录已实际通过oracle和nop控制，结果见[发布报告](reports/ringfenced_business_revision_release.json)和[控制报告](reports/ringfenced_business_revision_controls.json)。

原有5＋5道题的材料和历史成绩保留；新增5＋5道资本配置题已完成真实输入验算，并在最强模型新上下文中确认。材料按[冻结清单](SpreadsheetEval/dataset_manifest.json)绑定，没有根据确认结果替换个别题目。

| 组成 | FM | Debugging | 工作簿结构 |
| --- | ---: | ---: | --- |
| 保留经营报表题 | 5 | 5 | 每题211张sheet、200家虚构企业及分部/集团报表 |
| 新增资本配置题 | 5 | 5 | 每题741张sheet、两个各360项目的投资组合及集团报告 |

新增FM每题有3,044,678个实际变化位置；新增Debugging每题有约897,200个实际变化位置，注入172,800处公式错误和720个暂定项目选择。业务错误包括利息使用期末债务、税损在最后合法年度提前失效，以及情景冲击错误反馈到下一期收入基数，影响税、现金流和LP/GP估值。两个投资组合的预算、资源、地点和前置项目约束均需在各情景满足，选择按已入账S01 LP NPV最大化。

新来源由六份已独立验算的本地投资模型组合为五份健康工作簿。五份组合不是五个互不相关的公开数据集。每份组合核对两套完整财务结果和原始整数约束，组合最佳/次佳证书，并完成三次真实LibreOffice计算、完整财务/公式/原始数据审计和两次数值稳定性比较。每份新输入也另有真实重算和完整修改集合检查。

最强模型采用原生Codex CLI `gpt-6.1-sol` / `xhigh`。新增十题原始评分为9个0、1个1；加上保留十题的历史0分，完整20题原始通过率为 **1/20＝5%**。FM为0/10，Debugging为1/10；不声称二十题都在本轮重新确认。

累计工具执行严格小于1800秒，模型响应时间不计入，并行工具分别累加；14400秒是运行保护时限。新十题有2条完整计时、8条UNKNOWN，原记录全部保留。预算限制只能减少原始成功数：错误答案无论是否超时都失败，唯一原始正确答案在计时未知时按可能成功计算。因此完整20题预算调整后的通过率区间为 **[0%, 5%]**，最有利于模型的上界仍低于0.2；不声称得到了全部预算调整点成绩或全部计时通过。

主评分比较重算后两位小数类型值与完整修改集合：多改、少改或应改值不正确均得0。错因分类用于解释结果，不另加准出阈值，也不改变原始评分。完整实际验收结果、资源和材料身份必须有效；UNKNOWN本身不作为模型失败依据。

公开与参考质量审查覆盖全部五组新题，十二项检查均保留。四次已完成审查未发现阻塞性的题意、业务假设或答案泄漏问题，实际资源检查通过；其余验收证据连接完整工程审计和实际目录控制。Q08在候选质量层为not_applicable，独立难度门槛已验证。首轮四次超时审查的未知结论和未知用量仍保留。

本次修订构造18份候选材料，其中8份原型、10份最终新增材料；新增准出10份，转化率 **55.56%（10/18）**，另外保留历史10份。它不是项目全部历史转化率。主产线已知74,280,115 tokens；加入辅助验收后，本次38次CLI请求的已知消耗下界为 **76,897,970 tokens**，另有6次用量未知。缓存输入包含在输入token中；实际账单未知。分项见[消耗报告](reports/ringfenced_business_revision_consumption.json)。更早40候选的87,496,946 tokens及官方复测研究不纳入此次修订统计。

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

以上两条完整目录命令已真实运行：**oracle20/20 reward=1，nop20/20 reward=0**，两个角色的实际资源及容器清理均验证通过。每个任务声明 `/app/input.xlsx` 和 `/app/output.xlsx`；运行现有题集的oracle/nop不需要模型API密钥。最终目录及逐题文件由 [dataset_manifest.json](SpreadsheetEval/dataset_manifest.json) 绑定。

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


原20题发布、0/20历史确认及当时oracle/nop证据见[历史发布说明](docs/history/README_operating_report_factory_20261101.md)和[历史发布报告](reports/operating_report_factory_release.json)。这些原批次结果不代表当前新目录的确认成绩。当前规则见[主评分准出合同](docs/ringfenced_primary_release.md)，材料冻结与调用边界见[组合确认记录](docs/ringfenced_replacement_confirmation.md)。
