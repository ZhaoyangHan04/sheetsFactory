# 当前发布状态

更新于 2026-11-01 09:45 UTC。当前已准出 **10道Financial Modeling＋10道Debugging**，交付路径为仓库根目录 [SpreadsheetEval/](../SpreadsheetEval)。

| 组成 | FM | Debugging | 合计 |
| --- | ---: | ---: | ---: |
| 历史材料及原成绩保留 | 5 | 5 | 10 |
| 新材料、新上下文确认 | 5 | 5 | 10 |
| 当前交付 | 10 | 10 | 20 |

最强模型为原生Codex CLI `gpt-6.1-sol/xhigh`。新增十题原始9错1对；保留十题历史全0，完整20题原始通过率 **1/20＝5%**。FM为0/10，Debugging为1/10。没有根据确认结果更换任何固定材料，也没有把历史十题描述为本轮新调用。

工具执行严格小于1800秒，模型响应时间排除、并行执行求和。新十题计时2条完整、8条UNKNOWN，原始记录全部保留。预算调整分数不大于原始分数：实际原始0的区间为[0,0]，唯一原始1且计时未知的区间为[0,1]。故完整20题预算调整通过率在 **[0%,5%]**，最有利模型上界5%已满足0.2门槛；不声称全部计时通过或精确预算调整点成绩。规则见[主评分准出合同](ringfenced_primary_release.md)。

两条任务书目录命令均已真实完成：

```bash
harbor run -p SpreadsheetEval -a oracle
harbor run -p SpreadsheetEval -a nop
```

oracle20/20 reward1，nop20/20 reward0。实际agent/verifier资源及精确归属容器清理通过，工作簿和清单在两次完整命令中保持不变。[控制报告](../reports/ringfenced_business_revision_controls.json)保存逐题奖励和实际命令引用。

十二项质量证据已连接独立财务验算、真实原生工程、四次完成的公开/参考语义审查和完整目录控制；Q08在候选质量层为not_applicable，独立难度门槛通过。四次早期超时审查的未知记录保留。

保留题每题211个sheet、200个实体；新增题每题741个sheet，包含两个各360项目的独立投资组合和集团报表。新增FM每题实际变化3,044,678格；Debugging约897,200格。财务模型涉及债务利息、税损有效期、情景收入、现金流及LP/GP估值；选择需满足全部情景的整数约束。五个组合健康工作簿复用六个本地来源，组合之间共享来源，不按五个独立公开数据集计数。

本次修订构造18份候选材料（8原型＋10新材料），新增准出10份，**10/18＝55.56%**；另保留历史10份。它是本次修订的材料转化率。

主产线已知74,280,115 tokens。包含辅助验收后，本次38次CLI请求已知消耗下界 **76,897,970 tokens**，另6次用量未知；缓存输入为输入token子集。实际账单未知。新十题确认使用42,625,243 tokens，Harbor估算约$11.05，该数值不是实际支付金额。更早生产和官方研究与本次统计分开。

最终证据：

- [正式发布报告](../reports/ringfenced_business_revision_release.json)
- [完整目录控制](../reports/ringfenced_business_revision_controls.json)
- [分项消耗报告](../reports/ringfenced_business_revision_consumption.json)
- [固定材料清单](../SpreadsheetEval/dataset_manifest.json)
- [原生产历史报告](../reports/operating_report_factory_release.json)

完整工作簿、oracle及验证器均随任务目录交付；运行oracle/nop不依赖本地私有构造记录或模型API密钥。
