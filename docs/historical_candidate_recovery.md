# 历史候选恢复

2026-11-01 的回查覆盖88次真实最强配置开发尝试、84份不同材料。按输入、参考与题面身份查重，并检查压缩包内部内容，重新打包不产生一道新题。旧106条生产核算实际是50次最强开发尝试与56次生成侧调用；用量仍按原混合范围报告。

确认有4道因为额外要求“必须证明财务推理错误”而被错误排除，现恢复为候选。有效评分、失败原因和题目质量分别记录。

| 材料 | 类别 | 原有效分数与失败表现 | 恢复后仍需处理 |
| --- | --- | --- | --- |
| 六业务组合 | Financial Modeling | 0；正常结束但未提交，工具11.825秒 | 同材料全十二项质量及真实Harbor已有；旧最强运行缺实际资源观察证据 |
| 四实体报告 | Financial Modeling | 0；1,368个目标全对，另填3个非适用格，工具4.063秒 | 正常质量及真实Harbor待验；公开提交范围单独复核 |
| 200实体C00原版 | Debugging | 0；18,240个目标全对，另有2个舍入差异，工具190.858秒 | 该调试材料的全部正常质量及真实Harbor待验，不能继承同来源FM的资格 |
| SG4000 | Debugging | 0；4,000处修改集合正确，2个数值边界差异，工具100.901秒 | 全部正常质量、真实oracle1/nop0、实际资源及同材料证据已通过，待最终冻结确认 |

回查另修复了P01正常验收报告的结构兼容问题。原批次保存五字段的导出身份，资源检查器返回七字段；新报告核对双方完整资源结构，再连接原五字段身份，同时保留全部17个导出文件、同材料、十二项质量、真实oracle/nop和两类容器实际资源检查。真实只读恢复证书已通过，未新增模型、重算、Harbor或Docker调用，未修改原数据库、导出或成绩。

当前有完整正常质量、真实Harbor及实际资源证据的开发零分候选为 **1道FM＋2道Debugging**，分别为C00 FM、P01 Debugging及SG4000。P01 FM原有效分数仍为UNKNOWN；追加只读计时得到1,756.461–1,772.694秒的完整界，且正常验收与最强输入、参考、题面字节一致，作为补证潜在候选单列。所有候选仍需预先冻结的整组新确认。

SG4000的正常验收保留原输入、参考和502字节题面。全十二项及支持参考审查通过，真实oracle为1、nop为0；正常与原最强尝试的两种容器角色资源和镜像证据重新核对，六个所属容器已不存在。原报告有一处冗余字段遗漏：证据提供完整goal文件引用，没有另写平铺的goal摘要。新的只读验证器仅允许在该平铺字段缺失时核对完整当前goal引用；字段存在却错误、引用冲突或材料变化仍拒绝。未重跑原最强尝试、表格引擎或Harbor，也未改写原报告。

原C00调试的独立正常流程使用 `config/pipelines/operating_reports_200_debug_quality_context_v1.yaml`，实际已启动。它通过 `prompt_overrides` 选择 `prompts/diagnosis_professional_review_v1.md`。检查依据完整工作簿、保留公式及常规财务解释；声称有歧义时才需给出有依据的两种解释。全十二项、固定评分、参考审查、真实Harbor及资源配置保持完整。新提示词和配置有9项实际接线测试，原C00入口有70项无服务测试。

历史18份零分材料中，13份正常结束且原工具计时有效，分为FM9、Debugging4。首份审计暂挂4份质量风险；随后独立复核将现金池FM恢复为质量待验：公开Read Me B11已有偿债、准备金、融资、归集和分红顺序，Cash Flow也有阶段标签，既有例子不足以证明规格冲突。八业务FM也恢复待验：公开文字没有禁止填写支持表，Agent Entry列出了相关表，且Budget Summary依赖Services已有的可读输入。不能把缺少逐步教程或任务只点名部分报表当作已证实的缺陷。K01原版则确有无标签汇总位置：若干目标格的格式相同、没有名称、校验或公式消费者，公开信息无法确定这些不同输出应放哪一格；只保留这个具体问题。

两项复核后，原有效0的待补证候选上界为 **FM7、Debugging4**；追加旧计时证据另有潜在FM4、Debugging1，最乐观合计FM11、Debugging5，旧UNKNOWN不回写。该上界包含尚未通过质量或资源核对的材料，不能当作准出数。相对首份不可变审计的修正另存新收据，不覆盖原18行分层表。

这些材料仍不足以直接组成10＋10且通过率不高于0.2的集合。尤其Debugging即使计入追加预算证据也只有5份潜在零分；10道Debugging至少会贡献5个成功，已经超过整个20题允许的4个成功。不能用重复材料、基础设施异常或改题后继承旧分补足。

本地不可变证据：

- 完整逐题表：`outputs/research/historical_zero_salvage_readonly_20261101T034500Z/terminal.json`，SHA256 `cfa0d3189725f9edace6e2b03707194557ad2b3cbff72e5639a7b364cb6c68a5`。
- P01只读恢复证书：`outputs/research/P01_normal_append_only_recovery_revision4_20261101T034100Z/prepared/certificate.json`，SHA256 `0626c646483d911147565fe711be41dddcb5553a55faa5e32a53b0ecc47247d3`。
- 混合调用口径纠正：`outputs/research/historical_zero_salvage_readonly_20261101T034500Z/production106_scope_correction.json`，SHA256 `c9505ad0d4440456ea847fe20b7052b05a817b590b60d870eaae4a2d485712ce`。
- 现金池独立复核：`outputs/research/historical_K01_cashpool_independent_review_20261101T034947Z/receipt.json`，SHA256 `1dec2650b490d9b4adc9d896685618a2c8cdb79d264e1ba6ad89483f0a7f6d57`。
- 八业务与K01独立复核：`outputs/research/historical_K01_eightnative_professional_scope_review_20261101T035445Z/receipt.json`，SHA256 `503273a7adf180e4c39068578c2547749b51c53bbb49895d4fb34b55198c634e`。
- SG4000完整验收连接：`outputs/research/SG4000_normal_append_only_verification_20261101T040100Z/certificate/certificate.json`，SHA256 `eaa0fecd2babc6fb843c8fc22acd35a1569b727d3f23d93db238ee478fb9a379`。

恢复实现为 `scripts/recover_linear_capital_scaled_P01_normal_evidence_revision4.py`，12项无服务测试通过，并已用真实旧证据执行一次完整证书恢复。历史文件与旧失败证书保持原样。
