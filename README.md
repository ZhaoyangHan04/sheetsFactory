# sheetsFactory

从 EUSES financial 种子自动构造可审计的财务补全与公式调试任务。

当前目标：20 道 Financial Modeling、20 道 Debugging。构造、诊断与自然尝试使用 Codex CLI `gpt-6-sol` / `high`。本轮明确暂缓难度门禁，保留其他质量门禁与真实 oracle/nop 验证。

配置位于 `config/`，角色提示词位于 `prompts/`，节点与模板位于 `src/sheets_factory/`，输入位于 `data/`，运行数据和面板审计位于 `outputs/`。密钥仅保存在环境变量或被忽略的 `.secrets/`。

实施采用分阶段提交；具体命令与最终验证结果随功能实现更新，未执行的检查不会记为通过。
