# legacy/v1-strategy 目录说明（只读考古参照区）

> ⚠️ **【红线警示：物理与运行时绝对隔离】**  
> 本目录内所有代码、配置与脚本为 **只读考古参照物**，唯一用途是证明算法理论谱系与供方案拷问审查。  
> 
> **法定约束（最高铁律）**：
> 1. **历史定性**：v1 策略在实盘与回测中表现不佳、数理逻辑并不完美且不完整，充斥历史选择性偏差与粗粒度假设；
> 2. **禁止执行**：严禁在任何环境下直接运行本目录内的任何代码或脚本；
> 3. **禁止 import**：项目生产代码（`src/`）、仿真与评测脚本（`scripts/`）严禁以任何形式 `import` 本目录内的任何模块；
> 4. **不进测试与构建**：本目录严禁被纳入全库测试集（`tests/`）、CI/CD 自动化流水线或 Docker 生产镜像构建。

---

## 1. 资产来源与入库背景

- **来源路径**：`/Users/ericlin/SynologyDrive/Project/Polymarket天气套利/`（原外部独立 v1 策略工程）
- **入库日期**：2026-10-12
- **入库授权**：工单 `P7-ALGO-1B`（任务 1）
- **入库动机**：依据工单 `P7-ALGO-1` 考古卷宗结论，v1 曾实现过完整的 Minimax 最坏情况概率投影、双边 YES/NO 稳健凯利、Dutch Book 锁利与对冲预算豁免、以及基于 `prob_cache` 的两步反事实标定法。为了保留完整算法演化证据链，防止记忆断代并供后续架构审计对照，将 v1 策略代码与配置无损入库归档。

---

## 2. 目录结构概览

```
legacy/v1-strategy/
├── README.md                                          # 本说明文件（法定隔离声明）
├── README_V1_ORIGINAL.md                              # 原 v1 工程自述文件
├── Polymarket天气套利参数标定与算法说明文档.md         # v1 原始标定说明文档
├── baseline_sigma_optimization_proposal.md            # v1 物理噪声标定提案
├── config/
│   ├── config.yaml                                    # v1 终极参数配置文件（参数现值事实源）
│   └── cities.json                                    # v1 站点与气候带配置
├── src/
│   ├── strategy.py                                    # v1 核心投注策略（含 Minimax、Dutch Book、动态费率）
│   ├── calibrator.py                                  # v1 物理纠偏窗口与 20th Percentile 标定
│   ├── analyst.py                                     # v1 CHSM 蒙特卡洛与偏置纠正分析器
│   ├── bias_corrector.py                              # v1 滑动窗口偏置修正器
│   └── ...                                            # 其余 v1 支撑模块
├── scratch/
│   ├── calibrate_financial_params.py                  # v1 两步标定第二步（反事实 sizing 模拟与 prob_cache）
│   ├── calibrate_sigma_brier.py                       # v1 两步标定第一步（Brier Score 物理标定）
│   └── ...                                            # 其余历史调试与反事实测试脚本
└── tests/                                             # v1 历史单测用例
```
