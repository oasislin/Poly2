# Handoff 文档 · 波次三（W3）任务转交书

> **文书编号**：`P7-W3-HANDOFF-R1`  
> **签发方**：W2 会话 Agent（依据用户指令与《终验封卷令 P7-W2-FINAL-SEAL-R1》交接标准）  
> **接收方**：W3 会话 Agent（新独立会话）  
> **交接时刻**：`2026-10-11 14:05:00 UTC`  
> **交接状态**：W2 全线圆满封卷结项；W3 已完成阶段 0/4（环境冻结与预注册框架草案）；零未提交脏数据；全库干净。

---

## 一、 新会话身份与治理铁律（W3 会话必读）

你在“预注册先行 + 冻结封卷 + 委员会裁决”治理模式下工作。核心纪律：
1. **预注册先行（最高铁律）**：一切跑数、联调、API 接入或代码编写动作之前，必须先有委员会与用户审议获批的预注册规格书——判据、阈值、门禁、禁触清单全部先冻结后执行；
2. **严禁未经明确授权擅自修改代码（最高铁律）**：任何时候，在用户/委员会没有给出明确的代码编写指令之前，绝对不得擅自创建或修改项目代码；
3. **判据两步分离**：门禁判定禁止跳过原始值直接给结论。固定格式：`原始观测值 = <原样值>；判定阈值 = <目标值>；结论 = 通过/不通过`；
4. **C5 红线全程刚性生效**：W3 全程仅使用公开只读行情 API，**真实资金变动严格为 $0.00，生产私钥加载严格为 0 次，任何形态的真实下单接口调用即 ERROR 级违令**；
5. **遇边界疑问**：停止、记录、呈报，不得临场裁量；
6. **Git Push 严格遵从人工指令**：已完成的工单工件交付时执行受控 commit & push（范围限 W3 工单工件），严禁自行 merge 到 `main`（主干合并令由委员会单独签发）。

---

## 二、 项目现状快照与资产基线

1. **仓库地址**：`github.com/oasislin/Poly2`
2. **工作分支**：`fix/p7-w2-shortloop`（禁止自行 merge 到 `main`）
3. **主干基线**：PR #132 合流指针 `5c4a4c9`（HEAD `f7a3da4` 尾随文档）
4. **当前分支 HEAD 指针**：
   - 本地与远端一致处于：`a99b14d39f8541558642949f96d2d0d0298ad52b`
   - W3 起步环境冻结指针：`c718802`
   - W3 框架草案提交指针：`1f6f75e`
5. **依赖环境现状**：
   - Python: `3.13.5`
   - numpy: `1.26.4`, scipy: `1.17.1`, pandas: `3.0.3`, pytest: `8.3.4`
6. **全量测试基准**：
   - `pytest tests/ -q` 严格全绿：**`1043 passed, 10 skipped, 3 warnings in 1605.68s`**（退出码 0）；
   - 10 项 skipped 清白证明已核验（3 个冷存储未挂载 + 6 个网络测试默认关闭 + 1 个 WU 历史隔离资产）。
7. **挂账旗状态**：
   - 🚩 `KMIA_12h`（加权 ECE 0.018318，下游强制带旗 `COMPLETED_ECE_FLAGGED` 并折剪 50% 仓位）；
   - ⚠️ `FAILSAFE` 粗粒度资产降级强制执行 `FAILSAFE_DEGRADED_READONLY`（只读观察，禁出交易信号）；
   - 📌 R2 §8.2.3 四项已知分桶缺陷带旗沿用。

---

## 三、 W2 已完成工作与遗留资产索引（已冻结历史）

W2（短闭环实现与纸面盘观测）已 100% 封卷归档，核心工件如下：
1. **规格书**：[`docs/w2_shortloop_preregistration.md`](docs/w2_shortloop_preregistration.md)（Rev.1.1 经 C3 勘误修正版）；
2. **实现代码**：
   - `src/pipeline/stream_confluence_pipeline.py`（单调合流与两权分离豁免通道）；
   - `src/prediction/temperature_sanitizer.py`（特报纯温门禁与 WRH 迟到极值豁免通道）；
   - `src/pricing/ev_engine.py`（微观结构 EV 引擎、FAILSAFE 只读降级、KMIA 12h 折剪）；
3. **审计与观测报告**：
   - [`evidence/p7_w2_shortloop_audit_report.md`](evidence/p7_w2_shortloop_audit_report.md)（C1~C6 自动化审计门禁全绿报告）；
   - [`evidence/p7_w2b_48h_observation_report.md`](evidence/p7_w2b_48h_observation_report.md)（48h 纸面观测报告，O1~O6 实证达标）；
   - [`evidence/p7_w2_final_sealing_report.md`](evidence/p7_w2_final_sealing_report.md)（终审封卷呈报书）。

---

## 四、 W3 当前所处进度与已完成工作（重要衔接点）

**注意：当前会话已启动并完成了 W3 的阶段 0/4（工单 `P7-W3-KICKOFF-001`）**：

1. **已产出工件一：环境冻结报告**
   - 路径：[`evidence/p7_w3_env_freeze.md`](evidence/p7_w3_env_freeze.md)
   - 状态：已 commit & push（在 commit `1f6f75e` 中）；
   - 内容：完整记录了基线 HEAD、1043 passed / 0 failed / 10 skipped 证据、依赖版本、C5 声明。
2. **已产出工件二：W3 预注册规格书框架（Rev.0.1 草案）**
   - 路径：[`docs/w3_polymarket_ingestion_preregistration.md`](docs/w3_polymarket_ingestion_preregistration.md)
   - 状态：已 commit & push（在 commit `1f6f75e` 中）；
   - 内容：骨架框架已搭好，包含：
     - CLOB API 只读通道契约（零私钥、零认证、公网端点）；
     - 快照频次与延迟容忍（保留 `[PENDING_COMMITTEE_SPECIFICATION]` 占位）；
     - 2°F 几何分桶到 Polymarket Token 映射定义与 VWAP 深度穿透；
     - 真实 EV 定价与资产治理判据（保留占位）；
     - 数据性质法定标注条款（显式标注 `POLYMARKET_LIVE_CLOB` vs `SYNTHETIC_INJECTED_REPLAY`）；
     - C-W3-1 ～ C-W3-5 门禁占位表；
     - C5 红线首次确认声明。

---

## 五、 新会话 W3 Agent 的紧接任务（位次 1/4）

新会话 Agent 启动后的下一步动作：
1. **引用工单与文书**：
   - 凭 `P7-W3-KICKOFF-001` 与本交接书 `P7-W3-HANDOFF-R1` 对账；
2. **议定判据数值并完善规格书（核心任务）**：
   - **绝对纪律**：**判据数值必须由用户与委员会审定输入，Agent 严禁擅自胡乱捏造填入**；
   - 协同用户将 [`docs/w3_polymarket_ingestion_preregistration.md`](docs/w3_polymarket_ingestion_preregistration.md) 中的所有 `[PENDING_COMMITTEE_SPECIFICATION]` 占位符填定为法定数值，形成 Rev.1.0 终稿；
3. **呈报委员会审批**：
   - 呈报规格书终稿，等待委员会签发《W3 规格书批复》与《W3-A 实现放行令》；
4. **代码禁止令**：
   - 在批文正式下发前，**严格执行零生产代码编写纪律**。

---

## 六、 档案自检与交接凭证

```text
$ git log -n 3 --oneline
a99b14d docs(audit): deliver Phase 2 Task 01 Fix issue closure audit report (P7-T01FIX-AUDIT-001)
1f6f75e docs(w3): add environment freeze report and preregistration framework draft (P7-W3-KICKOFF-001)
c718802 docs(w2): add final sealing report and closure chain index (P7-W2-FINAL-001)

$ git status
On branch fix/p7-w2-shortloop
Your branch is up to date with 'origin/fix/p7-w2-shortloop'.
nothing to commit, working tree clean
```

交接完成，W2 会话正式关闭。请在新会话中直接粘贴本文档开启 W3！
