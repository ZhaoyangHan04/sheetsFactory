# 当前发布状态

更新于2026-11-01 06:36 UTC。当前正在进行**业务逻辑难度修订**：目标10道Financial Modeling＋10道Debugging，已保留原材料5＋5，仍需新增5＋5；新修订尚未准出。

| 本次修订 | Financial Modeling | Debugging | 合计 |
| --- | ---: | ---: | ---: |
| 目标 | 10 | 10 | 20 |
| 原材料保留 | 5 | 5 | 10 |
| 新题待完成 | 5 | 5 | 10 |

保留FM：F11、F12、F13、F14、F17；保留Debugging：S11、S14、S17、S19、S20。它们均有超出已知舍入边界的联营收益报告值差异；这说明存在业务字段差异，不推定每次运行的唯一推理过程。原来仅两处舍入边界不同的另外10题，在新清单中标记`superseded_for_new_business_difficulty_criterion`，原始0分不变。

[业务修订清单](../reports/operating_report_factory_business_revision_status.json)绑定原发布报告、完整失败摘要及20题处置；[保留材料历史清单](../reports/history/operating_report_factory_business_retained_v1.json)绑定5＋5的原输入、参考、题面及完整任务文件哈希。根目录`SpreadsheetEval/`暂不改动，原20题报告及资格保留。新题需要超出浮点边界或纯格式差异的业务错误证据，主评分合同保持不变；`business_failure_evidence`将作为可插拔、默认启用的新增准出门禁接入。

新的投资业务桥已有两套独立实现，并已完成B04、B05各三次真实来源验算及两种输入验算。每次完整核对93,510个财务字段，无主评分舍入边界差异，给定值和结构保持；FM各遮蔽88,676个公式，DBG实际分别影响24,086和23,288个位置。B04的两次原生最强模型开发首测与四次普通模型语义审查正在运行。新增准出数仍为0，工程通过不作为难度通过。方法及执行入口见[投资业务修订](associate_bridge_business_revision.md)。

## 原20题发布证据

以下为原发布快照，不代表本次业务逻辑修订已经补齐或完成新冻结确认。原20题是FM10＋Debugging10，最强模型原生Codex CLI `gpt-6.1-sol/xhigh`的新上下文确认成功0/20；真实完整目录oracle20/20为1、nop20/20为0。

| 项目 | 原批次证据 |
| --- | --- |
| 来源 | 1个独立生成的虚构业务来源；200实体、8分部、211工作表；不同候选共享同一健康参考 |
| 来源正确性 | 两套独立财务实现完整核对93,510字段；三轮真实来源计算和两次稳定性比较 |
| 新材料 | FM20＋Debugging20，共40份不同输入；不按40个独立来源计数 |
| 每材料工程 | 40/40真实原生输入重算；完整变化集合符合冻结计划，零原生错误，原始事实和结构保留 |
| 共享语义审查 | 每模式公开/私有各一次，共4次 `gpt-6-sol/high`；逐项保留真实结论，并追加每材料实际证据 |
| 开发 | 40/40原始/有效0，计时及实际资源完整；开发成绩用于选择，不当作最终确认 |
| 冻结选择 | 根据开发结果事前选择10＋10，并在新确认调用之前固定材料和清单 |
| 新确认 | 原始0/20；有效成绩及计时结论为20/20计时及实际资源证据完整，有效成功0/20；F11依据追加只读计时证明消费，原UNKNOWN保留 |
| 全目录oracle | 实际 `harbor run -p SpreadsheetEval -a oracle`，20/20 reward1 |
| 全目录nop | 实际 `harbor run -p SpreadsheetEval -a nop`，20/20 reward0 |
| 最终十二项质量 | 20/20材料全部完成Q01–Q12；Q08在候选质量层为not_applicable，独立冻结难度门禁已完成 |
| 原批次发布 | 原20题发布报告qualified=true；原Overall Pass@1＝0%，满足当时合同；新业务修订尚未准出 |

发布报告：[operating_report_factory_release.json](../reports/operating_report_factory_release.json)。冻结任务清单：[dataset_manifest.json](../SpreadsheetEval/dataset_manifest.json)。完整根目录控制：[operating_report_factory_controls.json](../reports/operating_report_factory_controls.json)。完整失败摘要：[operating_report_factory_failure_summary.json](../reports/operating_report_factory_failure_summary.json)。

F11的原生计时解析器未识别一处纯日志展示语法，原始计时为UNKNOWN，原汇总状态为`infrastructure_failed`。本次发布只读追加同一次尝试的22个完整工具执行包装证据，得到累计工具时间上界126.614143299秒，严格低于1800秒。原始UNKNOWN、原汇总状态、原协议及所有日志保持原样；没有新模型、LibreOffice或Harbor调用。发布报告的`timing_interpretation`绑定原记录、补充证明和追加消费程序，最终有效确认成绩为0/20。

原始计时未知、日志和先前失败保留。计时补充只读分析同一次尝试，不能重跑模型、修改材料或回写原协议记录。最终报告的 `timing_interpretation` 说明追加解释及其工件绑定；计时证据完整之后才可报告有效通过率或授予准出。

## 失败分布的实际含义

| 确认类型 | 仅两处数值边界 | 其他实际差异 |
| --- | ---: | --- |
| Financial Modeling | 5题 | 5题各有800个联营收益展示位置差异，并有两处边界差异 |
| Debugging | 5题 | 4题有800个联营收益展示位置差异及两处边界；1题有800个展示位置差异 |

Debugging后五题同时有800个应改位置未发生变化。缺改与错值列表可能指向相同坐标，不能直接相加成不同单元格数。摘要没有从诊断位置推定模型的唯一推理过程；这些零分包括数值边界与财务展示差异，不能统称金融推理失败。

主评分合同保留：重算后两位小数类型值、完整修改集合和二值reward。显示或舍入导致的实际零分保留；是否属于财务推理错因与评分有效性分别记录。

## 转化率与用量

原批次构造40份材料，当时交付20份，候选转化率50%（20/40）。本批次共享来源数为1，不能用材料数量替代来源分母。

| 范围 | 调用数 | 已知token |
| --- | ---: | ---: |
| 最强模型开发 | 40 | 57,322,512 |
| 最强模型新确认 | 20 | 29,403,926 |
| 普通模型共享语义审查 | 4 | 770,508 |
| 本批合计 | 64 | 87,496,946 |

缓存输入和推理token是上述记录的子集，不重复累加。供应商实际账单未知。统计范围不包括历史生产、官方200题研究、来源试验及更早正常质量运行；旧下界和未知用量没有被覆盖或并入本批。

本批次原FM材料工程完成后的审计汇总曾出现字段重名异常，真实材料、原生计算及导出已经落盘，随后只读恢复20份记录，没有重跑引擎。首次确认的一处纯日志显示语法留下计时未知，原记录也完整保留；追加解释和最终消费必须显式连接同一次原始尝试。

最终发布前的状态见[2026-11-01 04:06状态快照](history/current_development_status_20261101_0406.md)。更早的状态见[历史README快照](legacy_readme_20261101.md)、[开发记录](development_history.md)、[历史候选恢复](historical_candidate_recovery.md)和[官方复测研究](official_calibration_study.md)。这些记录保持各自来源与统计范围，不作为当前发布数。
