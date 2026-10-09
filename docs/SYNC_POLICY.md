# 受控出域通道与证据同步政策 (SYNC_POLICY.md)

> **版本**：v1.0.0  
> **生效日期**：2026-10-10  
> **立项依据**：工单 `P7-SYNC-BRIDGE`（委员会核准令）  
> **修订历史**：
> - `v1.0.0` (2026-10-10): 初始立法，确立出域白名单、分层存储规则、主干纪律、同步节奏、事故熔断预案及核心纪律修订（依据工单 `P7-SYNC-BRIDGE`）

---

## 一、 核心纪律修订声明 (Statutory Discipline Revision)

> ⚠️ **【重要纪律修订】**  
> 历史开发模板中的“绝对零 push”红线，自工单 `P7-SYNC-BRIDGE` 验收通过之日起正式修订为：  
> **“未验收不出域，验收必出域”**。  
> 严禁未经委员会验收的草稿代码与中间工件出域；凡经委员会正式关门验收并完成 SHA 挂账的工件，必须执行受控出域同步，彻底消除“证据链只有一份本地物理拷贝”的单点灭失风险。

---

## 二、 第一条：出域白名单 (Egress Whitelist)

允许执行 Git Push / 远端同步的资产**严格且仅限于**以下三类：

1. **第一类：已验收状态与法定文档**  
   - 包含：`STATUS.md`、`EVIDENCE_INDEX.md`、`docs/SEALING_GATE.md`、以及委员会签署关门的阶段性质检/审计法定报告（如 `evidence/p4_audit_*.md`、`evidence/p6_*.md` 等）。
2. **第二类：已验收并申报 SHA 的工具与契约测试**  
   - 包含：通过验收的诊断脚本（如 `scripts/diag_p6_heavytail.py`）、批处理执行引擎、以及在 `tests/` 下建立的契约测试夹具（如 `tests/unit/modeling/test_p6_zero_drift_gate.py`、`test_evt_path_validation.py`）。
3. **第三类：主干 PR 合流工件**  
   - 包含：经委员会在 GitHub 界面审核通过并点击 Merge 的主干合流提交。

⛔ **红线禁令**：未验收代码、未完成入账格子的临时预测表、挂起中单据的未裁决草稿工件——**一律不出域，严禁擅自推送**。

---

## 三、 第二条：分层存储与 LFS 规则 (Storage Tiering & Git LFS)

1. **分层存储界限**：
   - **小文件（$< 1 \text{ MiB}$）**：所有 Markdown 文档、轻量 Python 脚本、JSON 状态摘要等直接纳入标准 Git 对象库。
   - **大文件与数据资产（$\ge 1 \text{ MiB}$ 或指定模式）**：未来 `evidence/` 下的所有 Parquet 文件、`cells/` 下的折内模型参数及逐折预测表统一通过 Git LFS 进行跟踪管理。
2. **`.gitattributes` 法定跟踪模式**：
   ```gitattributes
   evidence/**/*.parquet filter=lfs diff=lfs merge=lfs -text
   evidence/**/cells/**/*.parquet filter=lfs diff=lfs merge=lfs -text
   evidence/**/cells/**/*.json filter=lfs diff=lfs merge=lfs -text
   data/processed/**/*.parquet filter=lfs diff=lfs merge=lfs -text
   ```
3. **历史大文件不追溯原则**：
   - 既往提交（如 `ec3acf4` 及更早历史）中已收录的大文件直接作为历史快照冻结保留，**严禁使用 `filter-branch`、`bfg` 或 `rebase` 重写 Git 历史**。
4. **SHA256 账本哈希不变性定律（最高铁律）**：
   - [`EVIDENCE_INDEX.md`](../EVIDENCE_INDEX.md) 中登记的 SHA256 校验和**必须恒定指向物理文件真实解压内容的 SHA256**。
   - Git LFS 仅改变文件在远端的底层物理存储方式，**绝对不改变文件内容本身的哈希**。严禁将 Git LFS 指针文件的哈希（Pointer SHA）混淆或误填为工件哈希。
5. **证据自含快照要求**：
   - 每次提交时，模型代码、测试脚本与对应的证据工件必须在同一分支、同一 Commit 中成对提交，确保 Git 历史任一节点均具备完整独立的自验证证据闭环。

---

## 四、 第三条：主干纪律与分支规范 (Mainline Discipline)

1. **主干只进 PR（机械化约束）**：
   - 主干 `main` 分支禁止任何直接 push 操作；
   - 所有合流必须从受控 feature/fix 分支发起 Pull Request；
   - PR 描述必须详述工作量摘要、完整性检验结论与仓库体检读数；
   - **合入动作严格由委员会人工在 GitHub 界面点击确认**。
2. **零 force-push 与零历史重写**：
   - 已推送至远端的提交历史即为法定时序证据，改写历史等同于伪造或篡改账本；
   - 严禁任何形式的 `git push --force` 或破坏性 rebase。

---

## 五、 第四条：同步节奏与频率 (Synchronization Cadence)

1. **工单验收闭环同步**：
   - 每轮工单通过委员会评审且完成 SHA 挂账后，在同一工作会话内追加“受控出域同步”步骤，将代码、报告与账本同步推送。
2. **状态文件定期对账**：
   - 维持每周核对本地与远端 `STATUS.md`；若发现两端差异超过 3 个工作日，必须立即提交对齐 PR。
3. **长任务每日收工同步**：
   - 在推进 92 格全网格跑数等长周期运算期间，每日收工前必须将最新的 `evidence/fullgrid_tmax/PROGRESS.json` 与当日完成格的审计工件推送至远端 feature 分支，实现进度每日物理异地容灾备份。

---

## 六、 第五条：事故预案与熔断机制 (Incident Contingency & Circuit Breaker)

1. **熔断触发条件**：
   - 任何时候若发现“本地文件内容 SHA256 $\neq$ 远端对应文件 SHA256”或“远端文件 SHA256 $\neq$ EVIDENCE_INDEX 挂账值”（三方一致性破缺）；
   - 或发现远端证据被未授权覆盖、篡改。
2. **应急响应动作**：
   - **立即停止（熔断）**：系统与 Agent 立即终止一切 Push 和合并动作；
   - **故障定级**：该事故定级为一级数据完整性事故，其修复优先级高于一切模型与研发主线；
   - **呈报审查**：生成三方差分比对报告，正式呈报评审委员会介入裁决，直至证据链恢复可信。

---

## 七、 第六条：政策修订程序 (Amendment Clause)

1. 本政策的任何条款修订必须经评审委员会全体书面审议通过；
2. 修订执行时，必须递增版本号（Major/Minor/Patch），并在文件头部修订历史中完整登记修订日期与依据单号。
