# Phase 2 波次三 (W3) 环境冻结报告

> **文书编号**：`P7-W3-ENV-FREEZE-R1`  
> **任务编号**：`P7-W3-KICKOFF-001` (事项 ①)  
> **报告时间**：`2026-10-11 13:28:00 UTC`  
> **当前位次**：**0/4（环境冻结与规格书预注册框架）**  
> **签发方**：W3 会话 Agent  
> **呈报对象**：技术裁决委员会  
> **工作分支**：`fix/p7-w2-shortloop`（禁止自行 merge 到 `main`）  
> **核心结论**：**ENVIRONMENT_FROZEN_VALIDATED (基线与环境全绿冻结，零未提交代码，回归测试 1043 passed / 0 failed / 10 skipped 达标)**

---

## 一、 Git 基线指针与工作区状态

### 1.1 Git 基线指针
- **`git rev-parse HEAD` 原样输出**：
  ```text
  c718802c7050f0fced81c9ba5ad7acfda27d8188
  ```
  *(注：该 commit 为 W2 终审封卷呈报书入库 commit，包含 W2-B 结项 `2cabfc0` 及其终验声明)*

### 1.2 Git 工作区干净证明
- **`git status` 原样输出**：
  ```text
  On branch fix/p7-w2-shortloop
  Your branch is up to date with 'origin/fix/p7-w2-shortloop'.

  nothing to commit, working tree clean
  ```

---

## 二、 Python 运行时及关键科学计算依赖版本

通过标准环境检查命令获取之客观原样版本输出：
```text
Python: 3.13.5 | packaged by Anaconda, Inc. | (main, Jun 12 2025, 11:23:37) [Clang 14.0.6 ]
numpy: 1.26.4
scipy: 1.17.1
pandas: 3.0.3
pytest: 8.3.4
```

---

## 三、 全量回归测试套件客观执行凭证 (`pytest tests/ -q`)

- **执行命令**：`python -m pytest tests/ -q`
- **总用例收集数**：`1053 items`
- **退出码**：`0`
- **测试结果输出末尾关键片段**：
  ```text
  tests/unit/verification/test_reliability_check.py ........               [ 97%]
  tests/unit/verification/test_reliability_modes_and_gates.py ...          [ 98%]
  tests/unit/verification/test_reliability_synthetic_acceptance.py ...     [ 98%]
  tests/unit/verification/test_resampling.py ...                           [ 98%]
  tests/unit/verification/test_settlement_hit_probability.py ......        [ 99%]
  tests/unit/verification/test_weather_metrics.py .........                [100%]

  =============================== warnings summary ===============================
  ../../../../../opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:31
    /opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:31: DeprecationWarning: Herbie: Custom model templates in the config path is deprecated. Please use a Herbie plugin: https://github.com/blaylockbk/herbie-plugin-tutorial
      import herbie.models as model_templates

  tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message
  tests/unit/data_acquisition/test_gefs_fetcher.py::test_network_reforecast_single_message
    /opt/miniconda3/lib/python3.13/site-packages/herbie/core.py:390: Pandas4Warning: Timestamp.utcnow is deprecated and will be removed in a future version. Use Timestamp.now('UTC') instead.
      assert self.date < pd.Timestamp.utcnow().tz_localize(None), (

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  ========== 1043 passed, 10 skipped, 3 warnings in 1605.68s (0:26:45) ===========
  ```
- **10 项 Skipped 用例清白证明（主干基线既有）**：
  - 3 项：离线冷数据盘 `/Volumes/EricSSD` 未挂载；
  - 6 项：默认断网保护（需 `RUN_NETWORK_TESTS=1` 显式开启）；
  - 1 项：历史 `wunderground.db` 隔离资产。

---

## 四、 C5 终验声明与安全红线基线确认

```text
[C5 环境冻结基线安全核准]
外部真实资金变动 = $0.00
生产私钥加载次数 = 0 次
生产网络下单尝试 = 0 次
当前模式：REDEFINED_READ_ONLY
```

本环境已全面冻结，随时准备进入 W3 预注册流程。
