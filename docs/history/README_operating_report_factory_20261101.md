# sheetsFactory

当前正在推进**业务逻辑难度修订**，目标为10道 Financial Modeling＋10道 Debugging。原批次中超出两处舍入边界的 **5道FM＋5道Debugging保持原材料和原成绩保留**；还需新增5道FM＋5道Debugging。仅有舍入边界差异的另外10题不计入本次目标，其原始评分不变。当前新修订尚未准出。

新题需要有超出浮点边界或纯格式差异的业务计算/约束错误证据；完整修改集合和两位小数值比较的主评分合同保持不变。进度与逐题处置见[业务修订清单](reports/operating_report_factory_business_revision_status.json)，保留材料见[历史保留清单](reports/history/operating_report_factory_business_retained_v1.json)。

新业务模型的构造、独立账簿、原生验算与业务错误门禁见[投资业务修订方法](docs/associate_bridge_business_revision.md)。首两份场景已完成工程校验；模型首测与语义审查的结果另行记录，尚未增加本次准出数量。

## 原20题发布快照

以下记录原批次的20题、0/20确认结果及真实oracle/nop控制。根目录`SpreadsheetEval/`目前仍完整保留这批原材料，未用新题替换；这些历史结果不代表新修订已经完成。

原批次交付目录是仓库根目录的 [SpreadsheetEval/](SpreadsheetEval)，包含10道 Financial Modeling 和10道 Debugging。每题有211张工作表，覆盖200家虚构企业、八个业务分部及集团汇总。它们来自 **1个共享的独立生成财务来源**；40份不同候选材料均使用同一已验算的健康参考工作簿，不能按40个独立数据源统计。

| 原批次统计 | 数量 |
| --- | ---: |
| 共享来源 / 独立验算业务字段 | 1 / 93,510 |
| 不同候选材料 | 40：FM20＋Debugging20 |
| 最终交付 | 20：FM10＋Debugging10 |
| 候选转化率 | 50%（20/40） |
| 最强模型开发 / 新上下文冻结确认 | 40 / 20次 |
| 普通模型共享语义审查 | 4次 |
| 本批次模型调用 / 已知token总量 | 64 / 87,496,946 |

原生Codex CLI `gpt-6.1-sol` / `xhigh` 的新上下文冻结确认：

| 类型 | 成功 / 题数 | Pass@1 |
| --- | ---: | ---: |
| Financial Modeling | 0 / 10 | 0% |
| Debugging | 0 / 10 | 0% |
| Overall | 0 / 20 | 0% |

实际成绩、逐题计时、用量及工件绑定见 [发布报告](reports/operating_report_factory_release.json)；完整目录实际控制及逐题资源见 [控制报告](reports/operating_report_factory_controls.json)；逐格失败分布见 [失败摘要](reports/operating_report_factory_failure_summary.json)。本批次用量分别记录60次 `gpt-6.1-sol` / `xhigh` 与4次 `gpt-6-sol` / `high`，缓存token是输入token的子集，不重复相加。统计不混入历史生产、官方题研究和更早的来源试验；供应商实际账单未知。

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

本机已实际执行这两条完整目录命令，oracle20/20均为1，nop20/20均为0，agent及verifier的实际资源已核对。每个任务声明 `/app/input.xlsx` 和 `/app/output.xlsx`；运行现有题集的oracle/nop不需要模型API密钥。最终目录及逐题文件由 [dataset_manifest.json](SpreadsheetEval/dataset_manifest.json) 绑定。

## 构造与验收

Financial Modeling 在全部62,322个预测公式之外，遮蔽历史增长计算和成组历史派生行，并补齐这些行的下游历史依赖遮蔽。最终十题各有80,271–88,322个实际变化位置。Debugging 将联营收益展示、增长率、净利率与销售差额的公式错误组合到不同实体组，最终十题各有6,700–8,320个实际变化位置。所有候选在观察模型结果前固定计划；原始事实、业务政策、标签及非适用文字保留。

健康参考由两套独立财务实现核对全部93,510个业务字段，再经过三轮真实LibreOffice计算及稳定性检查。共享业务模板分别接受公开与私有语义审查；每份新材料另有真实输入重算、完整变化集合、零原生错误和事实/结构保护检查。共享审查不能替代每题的实际控制及资源证据。默认十二项检查均启用，最终质量证据逐题绑定所有检查。

评分重算输入I、参考G和提交O，比较两位小数归一化后的类型值。提交的完整修改集合必须恰好等于参考修改集合，且每个应改值正确；多改、少改或值错均为0，公式文本不要求相同。

最终20题依据开发结果选出并冻结后，使用原生Codex CLI `gpt-6.1-sol` / `xhigh`，各启动一次新上下文确认。正式 Overall Pass@1 为 **0%（0/20）**。累计工具执行严格小于1800秒，模型响应时间不计入，独立并行执行分别累加；14400秒只是运行保护时限。基础设施或计时未知不计作模型失败。

F11的原生计时解析器未识别一处纯日志展示语法，原始计时为UNKNOWN，原汇总状态为`infrastructure_failed`。本次发布只读追加同一次尝试的22个完整工具执行包装证据，得到累计工具时间上界126.614143299秒，严格低于1800秒。原始UNKNOWN、原汇总状态、原协议及所有日志保持原样；没有新模型、LibreOffice或Harbor调用。发布报告的`timing_interpretation`绑定原记录、补充证明和追加消费程序，最终有效确认成绩为0/20。

失败摘要显示：确认集10题仅有两处已知两位小数边界差异；另10题涉及800个联营收益展示位置的差异，其中9题同时有两处边界差异。摘要记录实际单元格差异，没有建立每次运行的唯一轨迹因果，不能把全部零分解释成金融推理失败。完整数值、展示符号和评分结果分别保留。

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

[当前发布状态](docs/current_development_status.md)汇总本轮证据；[评测要求](docs/evaluation_requirements.md)说明检查与评分合同；[本批构造方法](docs/operating_report_factory.md)记录共享与逐题证据边界及追加消费命令；[历史README](docs/legacy_readme_20261101.md)保留旧20＋20质量批次与此前实验。历史批次不作为当前20题交付或当前难度成绩。
