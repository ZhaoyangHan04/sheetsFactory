# Project rules

Use repository-local Git identity ZhaoyangHan04 <3319926404@qq.com>.
Commit each completed feature or meaningful test milestone; serialize commits.
Never stage .secrets, credentials, outputs, downloaded seed workbooks or raw CLI logs.
The user-authorized final generated benchmark may be tracked under the real root SpreadsheetEval/ directory, with its minimal runtime support. Only publish verified task files; keep construction and solver traces private under outputs/.
Generation and diagnosis use Codex CLI gpt-6-sol with high reasoning.
The earlier quality-only run produced 20 financial_modeling and 20 debugging tasks; preserve that immutable release and its history.
The current user-authorized iteration targets at least 10 financial_modeling and 10 debugging tasks with a frozen-set Overall Pass@1 <= 0.2 using Codex CLI gpt-6.1-sol with xhigh reasoning. Difficulty is now required.
Development scores and fresh confirmation scores must be distinct. Never count infrastructure failures as model failures or select a final set after seeing its confirmation results.
Deliver the actual SpreadsheetEval/ directory, document its location and exact oracle command in README, and run that command on the complete final directory with every oracle reward equal to one.
All quality findings require evidence. Never fabricate oracle/nop, recovery or Harbor results.
Keep public agent files physically isolated from private references and construction logs.
