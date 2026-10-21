# P8-CLASS1-LAUNCH-CHK-08 · 复呈验收与 gh 发布指令确认（Step 5 收尾）

> **日期**：2026-10-21
> **工单（B 线）**：`P8-CLASS1-LAUNCH`
> **核验单**：`P8-CLASS1-LAUNCH-CHK-08`（父工单第 8 号核验单，复呈验收）
> **复核对象**：
> 1. `P8-CLASS1-LAUNCH-TASK-INVENTORY_Task01-07状态盘点与处置建议表_20261021.md`（P-1~P-5 修正版）
> 2. `P8-CLASS1-LAUNCH-TICKETS-PLAN_Task08拆票方案草案_20261021.md`（去 Group 层定稿）
> 3. `docs/audit/gh_publish_task08_issues.sh`（gh 发布命令脚本）
> **复核人**：技术审核 Agent（只读；对修正版逐项抽查原文，对 gh 脚本全文通读）

---

## 一、 复核结论

| 复核项 | 核验动作 | 结论 |
| :-- | :-- | :-- |
| 盘点表 P-1 | 抽查原文：Task 01 定稿为**收窄口径 Close**，「留作未来横向训练回归」标注落位；余量审计范围（8 站 TMax + 10 站 TMin = 480 格）写明 | **通过** |
| 盘点表 P-2 | 抽查原文：落盘实测写为**顶层 1200 + legacy 800 = 2000**，960 标注规格基准，manifest 含 1200 哈希，240 差值归因为 6h 池化回退层与密集插值模型 | **通过** |
| 盘点表 P-3 | 抽查原文：三处测试均附命令 + 输出末尾片段 + 通过数 + 退出码 0（10 passed / 11 passed / 11 passed） | **通过**（见 §二 复核边界） |
| 盘点表 P-5 | 抽查原文：Task 04 定稿「收口 Close + EV 移交 Task 08」，对齐 U-9 | **通过** |
| 拆票定稿 | 全文确认：**Group 层级彻底删除**，24 票直接挂 Task 08；全拼标题 `Phase 2 Task 08 - Ticket ZZ: type(scope): 描述`；分组仅阅读辅助；mermaid 依赖拓扑无环；ADR 引用为 0019；Ticket 04 标注新建包装脚本；Ticket 08 标注承接 Task 04 交易 EV | **通过** |
| gh 脚本 | 全文通读：Spec 主 Issue 标题/正文 ✓；24 票标题全拼 ✓；标签 `ready-for-agent,phase-2` 与 `spec,phase-2` ✓；Blocked by 以正文声明（T01 Frontier → T02/T03 → T04 → T05；T06→T07→T08→T09；T10/T11→T12→T13；T14→T15→T16→T17；T07→T18；T15/T18→T19；T08→T20；T08/T16/T19/T20→T21→T22；T16/T21→T23；T22/T23→T24），依赖链无环、无孤儿 | **通过** |
| 脚本安全 | 仅 `gh issue create` + echo，`set -euo pipefail`；无 push、无删除、无改写类操作 | **通过** |

## 二、 复核边界说明（诚实披露）

- **P-3 测试未由复核方重跑**：本地复核环境（sandbox runtime）未安装 pytest（`No module named pytest`），无法复现开发端实测输出。P-3 证据**以开发端实测为准**（命令+输出片段+通过数+退出码齐全，形式上符合铁律）；复核方不做「复核方重跑通过」声明。
- 本地为同步副本（非 git 仓库），代码/模型/文档只读核验与开发端一致；git 操作仍归开发端。

## 三、 发布指令（交用户执行，agent 不代跑 gh）

1. 在**项目根目录**的 bash 环境（Git Bash / WSL / 其他 bash 终端）执行：
   ```bash
   bash docs/audit/gh_publish_task08_issues.sh
   ```
   （或逐条复制脚本内 `gh issue create` 命令执行；Windows 下无需 chmod。）
2. 执行完毕后，将 **Spec 主 Issue 编号**与 **24 张 Ticket Issue 编号**（或执行输出）回传开发端。

## 四、 执行后衔接（开发端待办）

1. 回填 issue 编号至本地相关文档与 `specs/` 目录；
2. 按 TDD 工作流启动首张 Frontier 票 **Phase 2 Task 08 - Ticket 01**（参数消费契约 Schema）；
3. 每票完成按 AGENTS.md 铁律附执行证据（命令+输出片段+通过数+判定）。

## 五、 红线重申

不代跑 gh；push 凭用户明确指令；不重训、不改 EMOS 参数、不落定值（F-2 锁）；观测值以原件为准。
