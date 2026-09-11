# Phase 1 基线封存清单 (Task 01 Freeze Inventory v1.0)

- **任务项**：Phase 1.5 Task 01（封存基线）
- **执行规范**：《Phase 1.5 执行文件 v1.1》§2 Task 01 & §4.3
- **报告日期**：2026-09-11
- **状态**：**已完成 (CLOSED)**

---

## 1. Git 基线标签

- **Tag 名称**：`phase1-final`
- **目标 Commit**：`53b1024415485fbafc79ec325251ab685c8f71ec` (`feat(audit): deliver M0' settlement station audit and 6-factor scorecard v1.1`)
- **标签信息**：Phase 1 final baseline tag (M0' settlement station audit closeout)
- **校验命令**：`git show phase1-final --no-patch`

---

## 2. 审计产物冻结清单 (`docs/frozen/phase1/`)

依据《ADR-0007》及《项目方案 (v2.6)》，M0' 阶段产出的 18 份权威审计报告与附录已全部移入只读冻结区 `docs/frozen/phase1/`，并统一注入只读声明头：

```markdown
<!-- FROZEN ARTIFACT / 只读冻结产物 -->
> **[FROZEN ARTIFACT / 只读冻结产物]**
> 本文档系 Phase 1 阶段（M0' 结算站点审计与评估）交付之基线冻结产物，内容严格只读。
> 任何修改、修订或废止必须通过正规 ADR 裁决流程推进，禁止直接变更既有文本。
```

| 序号 | 冻结产物文件路径 | 原始属性 / 作用 |
| :---: | :--- | :--- |
| 1 | `docs/frozen/phase1/settlement-station-mapping-v1.0.md` | 结算站点中央映射权威表 v1.0 |
| 2 | `docs/frozen/phase1/appendix-a-settlement-semantics-memo.md` | 附录 A：结算语义与官方裁决备忘录 |
| 3 | `docs/frozen/phase1/appendix-b-source-era-timeline.md` | 附录 B：真值源历史 Era 分层时间线 |
| 4 | `docs/frozen/phase1/appendix-c-13-station-candidate-pool.md` | 附录 C：候选站点宇宙全量画像 |
| 5 | `docs/frozen/phase1/station-audit-comprehensive-report-v1.1.md` | M0' 站点审计综合报告 v1.1 |
| 6 | `docs/frozen/phase1/station-scorecard-v1.0.md` | 站点六要素准入评分卡 v1.0 |
| 7 | `docs/frozen/phase1/market-inventory-v1.0.md` | Polymarket 历史气温市场全量盘点 |
| 8 | `docs/frozen/phase1/global-temperature-settlement-inventory-v1.0.md` | 全球气温市场结算源盘点 |
| 9 | `docs/frozen/phase1/settlement-semantics-memo-v0.1.md` | 结算语义初版备忘录 |
| 10 | `docs/frozen/phase1/iem-mesowest-dependency-audit.md` | IEM/MesoWest 依赖可用性审计 |
| 11 | `docs/frozen/phase1/nws-wrh-precision-audit-verdict.md` | NWS WRH 精度裁决报告 |
| 12 | `docs/frozen/phase1/nws_wrh_precision_audit_verdict.md` | NWS WRH 精度裁决附录 |
| 13 | `docs/frozen/phase1/v1.0-flatline-root-cause-analysis.md` | v1.0 气温平线根因分析 |
| 14 | `docs/frozen/phase1/zspd-data-availability-report-v1.0.md` | ZSPD 可用性报告 v1.0 |
| 15 | `docs/frozen/phase1/zspd-data-availability-report-v1.1.md` | ZSPD 可用性报告 v1.1 |
| 16 | `docs/frozen/phase1/zspd-data-availability-report-v1.2.md` | ZSPD 可用性报告 v1.2 |
| 17 | `docs/frozen/phase1/zspd_data_availability_report_v0.9.md` | ZSPD 可用性报告 v0.9 |
| 18 | `docs/frozen/phase1/zspd_temperature_comparison_report.md` | ZSPD 气温多源比对报告 |

---

## 3. Legacy 疑似污染数据隔离清单 (`data/legacy-v1-suspect/`)

根据严格安全规则：**严禁将 `data/legacy-v1-suspect/` 任何数据接入训练、Floor 构建或验收入口（管道级物理隔离，非约定级）**。旧版 Wunderground 观测库与局部旧裁剪数据已完成隔离：

| 隔离路径 | 原路径 | 说明与标记 |
| :--- | :--- | :--- |
| `data/legacy-v1-suspect/wunderground.db` | `data/wunderground.db` | 旧版 Wunderground SQLite 观测库（整度截断，已作废） |
| `data/legacy-v1-suspect/raw/wunderground/` | `data/raw/wunderground/` | 旧版网页爬虫历史落盘数据 |
| `data/legacy-v1-suspect/processed/features/` | `data/processed/features/` | 旧版基于 Wunderground/旧 GEFS 生成的特征 |
| `data/legacy-v1-suspect/processed/gefs/` | `data/processed/gefs/` | 旧版 41x41 局部裁剪预报数据 |
| `data/legacy-v1-suspect/processed/observations/` | `data/processed/observations/` | 旧版中间观测切片 |
| `data/legacy-v1-suspect/processed/training/` | `data/processed/training/` | Phase 1 历史训练集切片 |
| `data/legacy-v1-suspect/processed/validation/` | `data/processed/validation/` | Phase 1 历史验证集切片 |
| `data/legacy-v1-suspect/processed/zspd_daily_diff.csv` | `data/processed/zspd_daily_diff.csv` | 旧版日差比对数据 |

---

## 4. 项目元数据与文档同步

1. **`STATUS.md`**：已更新状态行，标记 Task 01 封存基线与 Task 09 均已结项闭环，全面转入 Task 02。
2. **`README.md`**：已消除旧版“上海 + 丹佛”两站架构表述，全面升级为 12 站宇宙体系与 IEM ASOS (T 组 0.1°C) / GEFS 全球再预报特征工程规范。
