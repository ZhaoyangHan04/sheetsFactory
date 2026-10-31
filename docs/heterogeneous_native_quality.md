# 原生业务模型的范围化质量验证

入口是 `scripts/run_heterogeneous_native_quality.py`，两类任务复用正常 Factory 调度、节点计时、自然解题轨迹、十二项编号诊断、问题路由、有限轮修复和实际 Harbor 对照。默认启用全部检查；此路线的 `reference_review` 政策要求 Q01–Q04 给出绑定当前版本的、受证据支持的结论，不能只提交通过标记。

准备输入必须是新的原生任务实际验证终态，且通过真正的冷复核。程序绑定实际重算后的 input、goal、题面、全部值变化集合、766 个独立验算位置、五项正反对照、两份完整类型稳定性与实际资源证据。内存中的不透明对象承担准入，持久化 JSON 不承担准入。源文件、代码、规则、审计和目标集合发生变化即停止；不会将旧开发成绩转移成质量成绩。

财务声明只覆盖已验算的任务输出。已知的原始上下文错误保留且必须与完整变化集合分离；调试中的一个有业务含义的空白另有独立期待值。正常构造节点重新检查全部已审计期待值、完整变化集合及固定错误清单，保存范围化证明供 Q04/Q09 审查。这不声称工作簿全部公式正确，也不声称所有语法依赖路径均无错误。模型仍可从原始政策、备注、历史数据和正常情景上下文推导结果。

`reference_review` 不运行另一套公开解题器。公开诊断必须建立任务范围与信息充分性，私有诊断必须检查参考工作簿、独立财务计算和完整改动集合。正常轨迹无论成功与否都会进入诊断。只允许已确认的 Q01–Q03 问题修订题面；财务、输入或故障范围需要修订时，必须另建实际验证过的任务版本。

每个正常版本重新执行等价解、漏修和额外改动三个真实重算对照。构造与对照采用 OOXML 局部改写，保留无关图表、备注和其他文件部分。导出必须是完整的十七文件资源约束 Harbor 格式，调度器随后实际执行 oracle/nop；本地对照不能代替该步骤。最强模型难度与最终冻结集确认仍是后续独立门禁。

```bash
.venv312/bin/python scripts/run_heterogeneous_native_quality.py \
  --actual-terminal /absolute/path/to/FM/actual/terminal.json \
  --actual-terminal /absolute/path/to/DBG/actual/terminal.json \
  --output /absolute/path/to/fresh/normal_run

.venv312/bin/python scripts/run_heterogeneous_native_quality.py \
  --prepared /absolute/path/to/fresh/normal_run --run
```

准备操作不启动模型、LibreOffice 或 Harbor；运行操作开启实时面板和正常生产者租约。此文说明入口契约，不表示已经得到正常质量合格题或最终交付题。
