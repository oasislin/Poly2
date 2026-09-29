# P5 现场盘点报告 (Status Report)

- **报告文件**: `evidence/p5_status_report.md`
- **盘点时间**: 2026-09-27T23:25:00+08:00
- **报告性质**: 现场客观事实盘点，不进行任何代码修复，不代行主控定性。
- **状态三选一标准**: `完成且可验证` / `部分完成（差什么，写具体）` / `未开始`。

---

## 第 1 节：当前实际工作范围

### 1.1 负责的模块清单（文件路径）
在当前代码库中，归属于 P5（逐概率段可靠性与校准对账检验工具）的实际文件清单如下：

1. **核心检验工具与执行脚本**:
   - `scripts/standalone_reliability_check.py`（检验主引擎，支持 insample、cv、blind 三模式）
2. **底层支撑与共享模块**:
   - `src/verification/settlement.py`（落桶期望命中概率解析计算，含 $\pm 0.05^\circ\text{F}$ 均匀抖动处理）
   - `src/verification/resampling.py`（30 天连续块时间序列切分器与 CV 清单生成）
3. **测试用例套件**:
   - `tests/unit/verification/test_reliability_synthetic_acceptance.py`（合成端到端放行测试）
   - `tests/unit/verification/test_settlement_hit_probability.py`（落桶抖动计算单元测试）
   - `tests/unit/verification/test_resampling.py`（块切分与零泄漏断言测试）
   - `tests/unit/verification/test_reliability_modes_and_gates.py`（模式状态机与元数据头测试）
   - `tests/unit/verification/test_reliability_check.py`（基础展开与可靠性表构建单元测试）
4. **历史核验与交付文档**:
   - `evidence/p5_tool_audit_report.md`（14 题自查问卷答卷）
   - `evidence/p5_overhaul_audit_deliverable.md`（R1–R7 改造交付说明）
   - `evidence/p5_reliability_tool_overhaul_and_audit_report.md`（改造执行审计总报告）

### 1.2 手上拥有的规格文档
| 规格文档名称 | 版本 / 路径 | 状态与说明 |
| :--- | :--- | :--- |
| 《任务规格书：训练窗逐概率段可靠性对账检验》 | `specs/spec-reliability-001-strata-verification.md` (v1.0 草案) | 手上存有，最初生成于任务启动期 |
| 《【独立指令】P5 分桶检验工具——现状冻结、实现拷问与调整依据》 | 用户指令（记录于对话上下文与 `evidence/p5_tool_audit_report.md`） | 手上存有，含 14 题核验清单 |
| 《P5 调整稿：14 题核验结论与工具改造令》 | 用户指令（记录于对话上下文） | 手上存有，含 R1~R7 改造优先级与三组合成测试标准 |
| 《P5 统一最终修复规格书》 | **无** | **没有此文档**，尚未接收到主控方合并后的新规格 |

### 1.3 此前向主控汇报过的结论
依据本地记录，此前向主控汇报过以下结论：
1. **14 题核验自查结论（2026-09-23）**：如实承认 Q5（每轮重拟未做）、Q6（抽块未做）、Q7（多轮汇总未做）、Q11（双模式未做）；自曝 Q3（$\sigma$ 塌陷静默无异常）、Q9（终端硬编码高亮 KSFO Summer）。
2. **R1–R7 改造完成结论（2026-09-24）**：汇报已完成 $\sigma$ 硬闸（0.90°F）、映射解耦、抖动口径统一、20 轮 Block-CV 引擎、三模式状态机、删除高亮、元数据头等项；汇报 3 组纯合成测试通过。
3. **真实 20 轮 CV 诊断结论（2026-09-24）**：汇报实跑存量病灶模型，全局主表 7/16（43.8%）超带，分层表 23/63（36.5%）超带，证实模型存在过度自信与方差过窄。

---

## 第 2 节：当前能力实测

### 2.1 能正常跑通的命令、测试与模块

#### 命令 1：合成放行验收测试套件
- **执行命令**:
  ```bash
  python -m pytest tests/unit/verification/test_reliability_synthetic_acceptance.py -v
  ```
- **原始输出**:
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
  plugins: anyio-4.12.1, cov-7.1.0
  collecting ... collected 3 items

  tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_perfect_calibration PASSED [ 33%]
  tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_deliberate_miscalibration PASSED [ 66%]
  tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_collapse_sentinel PASSED [100%]

  ============================== 3 passed in 1.48s ===============================
  ```

#### 命令 2：落桶解析抖动计算单元测试
- **执行命令**:
  ```bash
  python -m pytest tests/unit/verification/test_settlement_hit_probability.py -v
  ```
- **原始输出**:
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
  plugins: anyio-4.12.1, cov-7.1.0
  collecting ... collected 6 items

  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_inside PASSED [ 16%]
  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_outside PASSED [ 33%]
  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_lower_boundary PASSED [ 50%]
  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_upper_boundary PASSED [ 66%]
  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_infinite_bounds PASSED [ 83%]
  tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_partition_unity PASSED [100%]

  ============================== 6 passed in 0.07s ===============================
  ```

#### 命令 3：块切分与零泄漏断言测试
- **执行命令**:
  ```bash
  python -m pytest tests/unit/verification/test_resampling.py -v
  ```
- **原始输出**:
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
  plugins: anyio-4.12.1, cov-7.1.0
  collecting ... collected 3 items

  tests/unit/verification/test_resampling.py::test_generate_30day_blocks PASSED [ 33%]
  tests/unit/verification/test_resampling.py::test_cv_split_zero_leakage_and_reproducibility PASSED [ 66%]
  tests/unit/verification/test_resampling.py::test_get_or_create_cv_manifest_persistence PASSED [100%]

  ============================== 3 passed in 0.12s ===============================
  ```

#### 命令 4：模式状态机与元数据头测试
- **执行命令**:
  ```bash
  python -m pytest tests/unit/verification/test_reliability_modes_and_gates.py -v
  ```
- **原始输出**:
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
  plugins: anyio-4.12.1, cov-7.1.0
  collecting ... collected 3 items

  tests/unit/verification/test_reliability_modes_and_gates.py::test_blind_mode_airgap_guardrail PASSED [ 33%]
  tests/unit/verification/test_reliability_modes_and_gates.py::test_metadata_header_persistence PASSED [ 66%]
  tests/unit/verification/test_reliability_modes_and_gates.py::test_cv_pipeline_dispersion_columns PASSED [100%]

  ============================== 3 passed in 1.25s ===============================
  ```

#### 命令 5：基础展开与对账表测试
- **执行命令**:
  ```bash
  python -m pytest tests/unit/verification/test_reliability_check.py -v
  ```
- **原始输出**:
  ```text
  ============================= test session starts ==============================
  platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
  cachedir: .pytest_cache
  rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
  plugins: anyio-4.12.1, cov-7.1.0
  collecting ... collected 8 items

  tests/unit/verification/test_reliability_check.py::test_evaluate_station_cdf_monotonicity PASSED [ 12%]
  tests/unit/verification/test_reliability_check.py::test_expand_prediction_records_properties PASSED [ 25%]
  tests/unit/verification/test_reliability_check.py::test_compute_binomial_ci_half_width_wilson PASSED [ 37%]
  tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table PASSED [ 50%]
  tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table_empty_strata PASSED [ 62%]
  tests/unit/verification/test_reliability_check.py::test_build_stratified_warning_table PASSED [ 75%]
  tests/unit/verification/test_reliability_check.py::test_compute_brier_skill_scores PASSED [ 87%]
  tests/unit/verification/test_reliability_check.py::test_run_reliability_pipeline PASSED [100%]

  ============================== 8 passed in 1.27s ===============================
  ```

#### 命令 6：主脚本 `--mode insample` 执行
- **执行命令**:
  ```bash
  python scripts/standalone_reliability_check.py --mode insample
  ```
- **原始输出**:
  ```text
  ================================================================================
        SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            
  ================================================================================
  MODE: [INSAMPLE] - IN-SAMPLE SELF-GRADE — 无校准证据效力

  [Artifact 1] Global Reliability Table: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_main_global.csv
  Global Weighted ECE: 0.9313%
  Out-of-CI Rate vs Expected: 8/16 (50.0%) vs nominal 5.0%
   stratum_id stratum_range  sample_count_n  mean_pred_prob  empirical_hit_freq  abs_bias  ci_lower  ci_upper  ci_95_half_width  is_outside_ci  warning_low_n   label
            1  [0.00, 0.05)           36477        0.016758            0.016394  0.000364  0.015141  0.017749          0.001304          False          False  NORMAL
            2  [0.05, 0.10)           29139        0.079929            0.067229  0.012699  0.064411  0.070162          0.002876           True          False  NORMAL
            3  [0.10, 0.15)           30267        0.118055            0.109162  0.008893  0.105698  0.112725          0.003513           True          False  NORMAL
            4  [0.15, 0.20)           25290        0.170831            0.172637  0.001806  0.168029  0.177345          0.004658          False          False  NORMAL
            5  [0.20, 0.25)            4335        0.219718            0.229527  0.009809  0.217251  0.242282          0.012515          False          False  NORMAL
            6  [0.25, 0.30)            3962        0.270463            0.302877  0.032414  0.288766  0.317371          0.014302           True          False  NORMAL
            7  [0.30, 0.35)            6069        0.325280            0.363816  0.038536  0.351802  0.376003          0.012100           True          False  NORMAL
            8  [0.35, 0.40)            1038        0.381653            0.431599  0.049946  0.401775  0.461928          0.030077           True          False  NORMAL
            9  [0.40, 0.45)            2153        0.419434            0.441245  0.021811  0.420394  0.462305          0.020955           True          False  NORMAL
           10  [0.45, 0.50)             107        0.479374            0.523364  0.043991  0.429571  0.615539          0.092984          False          False  NORMAL
           11  [0.50, 0.55)             210        0.528030            0.533333  0.005303  0.465866  0.599603          0.066869          False          False  NORMAL
           12  [0.55, 0.60)             444        0.578727            0.549550  0.029178  0.503043  0.595207          0.046082          False          False  NORMAL
           13  [0.60, 0.65)            1028        0.627959            0.615759  0.012201  0.585646  0.645010          0.029682          False          False  NORMAL
           14  [0.65, 0.70)            2091        0.677586            0.710187  0.032600  0.690370  0.729232          0.019431           True          False  NORMAL
           15  [0.70, 0.75)            2446        0.725878            0.746934  0.021056  0.729326  0.763767          0.017221           True          False  NORMAL
           16  [0.75, 0.80)             544        0.757014            0.762868  0.005853  0.725361  0.796688          0.035663          False          False  NORMAL
           17  [0.80, 0.85)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA
           18  [0.85, 0.90)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA
           19  [0.90, 0.95)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA
           20  [0.95, 1.00]               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA

  [Artifact 2] Stratified Warning Table: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_stratified_station_season.csv
  Stratified Out-of-CI Rate vs Expected: 18/63 (28.6%) vs nominal 5.0%

  [Artifact 3] Brier Skill Score Summary: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_brier_skill.csv
          scope_type scope_name  sample_count_n  bs_model  bs_clim  brier_skill_score  is_skillful
              Global     Global          145600  0.097440 0.138787           0.297919         True
             Station       KORD           48580  0.109193 0.170856           0.360907         True
             Station       KMIA           48580  0.068052 0.112386           0.394476         True
             Station       KSFO           48440  0.115125 0.133103           0.135068         True
  Season (Auxiliary)     Winter           36015  0.099954 0.147776           0.323610         True
  Season (Auxiliary)     Spring           36708  0.097290 0.143671           0.322831         True
  Season (Auxiliary)     Summer           36568  0.096248 0.124344           0.225956         True
  Season (Auxiliary)     Autumn           36309  0.096298 0.139479           0.309589         True

  Execution complete. All artifacts generated successfully without selective display.
  ```

#### 命令 7：主脚本 `--mode cv` 执行（20 轮块交叉验证）
- **执行命令**:
  ```bash
  python scripts/standalone_reliability_check.py --mode cv
  ```
- **原始输出**:
  ```text
  ================================================================================
        SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            
  ================================================================================
  MODE: [CV] - INTERNAL CV DIAGNOSTIC — 受迭代选择影响，仅供方向参考

  [Artifact 1] Global Reliability Table: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_main_global.csv
  Global Weighted ECE: 0.8162%
  Out-of-CI Rate vs Expected: 7/16 (43.8%) vs nominal 5.0%
   stratum_id stratum_range  sample_count_n  mean_pred_prob  empirical_hit_freq  abs_bias  ci_lower  ci_upper  ci_95_half_width  is_outside_ci  warning_low_n   label  dispersion_min  dispersion_median  dispersion_max
            1  [0.00, 0.05)           72300        0.016718            0.016971  0.000253  0.016055  0.017938          0.000942          False          False  NORMAL        0.013012           0.017039        0.021004
            2  [0.05, 0.10)           58170        0.079815            0.067440  0.012375  0.065431  0.069507          0.002038           True          False  NORMAL        0.056576           0.067203        0.077744
            3  [0.10, 0.15)           59652        0.118062            0.110826  0.007236  0.108332  0.113370          0.002519           True          False  NORMAL        0.101483           0.110091        0.119735
            4  [0.15, 0.20)           50251        0.170923            0.173768  0.002844  0.170480  0.177106          0.003313          False          False  NORMAL        0.159551           0.175043        0.187072
            5  [0.20, 0.25)            8540        0.219777            0.225176  0.005399  0.216441  0.234157          0.008858          False          False  NORMAL        0.192802           0.228329        0.242967
            6  [0.25, 0.30)            7763        0.270436            0.297308  0.026872  0.287242  0.307574          0.010166           True          False  NORMAL        0.243590           0.300327        0.330827
            7  [0.30, 0.35)           12220        0.325181            0.357201  0.032020  0.348752  0.365741          0.008495           True          False  NORMAL        0.317881           0.352394        0.420181
            8  [0.35, 0.40)            1999        0.381765            0.421211  0.039446  0.399737  0.442986          0.021624           True          False  NORMAL        0.311111           0.423074        0.533333
            9  [0.40, 0.45)            4309        0.419269            0.425621  0.006352  0.410931  0.440443          0.014756          False          False  NORMAL        0.363636           0.426789        0.497835
           10  [0.45, 0.50)             220        0.478672            0.540909  0.062237  0.474922  0.605492          0.065285          False          False  NORMAL        0.250000           0.500000        0.777778
           11  [0.50, 0.55)             423        0.528523            0.565012  0.036489  0.517392  0.611461          0.047034          False          False  NORMAL        0.315789           0.555556        0.833333
           12  [0.55, 0.60)             904        0.578877            0.557522  0.021355  0.524969  0.589588          0.032310          False          False  NORMAL        0.435897           0.556197        0.634615
           13  [0.60, 0.65)            2028        0.628173            0.632643  0.004470  0.611429  0.653355          0.020963          False          False  NORMAL        0.536232           0.638820        0.747475
           14  [0.65, 0.70)            4153        0.677254            0.706959  0.029705  0.692930  0.720605          0.013838           True          False  NORMAL        0.618557           0.709673        0.754630
           15  [0.70, 0.75)            4871        0.725778            0.747075  0.021296  0.734676  0.759084          0.012204           True          False  NORMAL        0.699634           0.742605        0.796000
           16  [0.75, 0.80)            1038        0.757168            0.749518  0.007650  0.722272  0.774925          0.026326          False          False  NORMAL        0.652174           0.735519        0.881356
           17  [0.80, 0.85)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA             NaN                NaN             NaN
           18  [0.85, 0.90)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA             NaN                NaN             NaN
           19  [0.90, 0.95)               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA             NaN                NaN             NaN
           20  [0.95, 1.00]               0             NaN                 NaN       NaN       NaN       NaN               NaN          False          False NO_DATA             NaN                NaN             NaN

  [Artifact 2] Stratified Warning Table: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_stratified_station_season.csv
  Stratified Out-of-CI Rate vs Expected: 23/63 (36.5%) vs nominal 5.0%

  [Artifact 3] Brier Skill Score Summary: /Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/reliability_check_brier_skill.csv
          scope_type scope_name  sample_count_n  bs_model  bs_clim  brier_skill_score  is_skillful
              Global     Global          288841  0.097766 0.139098           0.297142         True
             Station       KORD           96460  0.110023 0.171810           0.359622         True
             Station       KMIA           96460  0.067995 0.112700           0.396677         True
             Station       KSFO           95921  0.115378 0.132747           0.130845         True
  Season (Auxiliary)     Winter           71022  0.099784 0.147244           0.322322         True
  Season (Auxiliary)     Spring           74067  0.097912 0.144562           0.322698         True
  Season (Auxiliary)     Summer           71197  0.096580 0.124602           0.224889         True
  Season (Auxiliary)     Autumn           72555  0.096804 0.139770           0.307401         True

  Execution complete. All artifacts generated successfully without selective display.
  ```

---

### 2.2 跑不通的命令与报错原文

#### 失败场景 1：盲测模式缺少授权凭据（预期安全拦截）
- **执行命令**:
  ```bash
  python scripts/standalone_reliability_check.py --mode blind
  ```
- **原始完整报错输出**:
  ```text
  ================================================================================
        SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            
  ================================================================================
  Traceback (most recent call last):
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 920, in <module>
      main()
      ~~~~^^
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 808, in main
      raise PermissionError(
      ...<2 lines>...
      )
  PermissionError: Strict 2019 airgap active: authorization flag '/Users/ericlin/SynologyDrive/Project/Poly Way2/evidence/preregistered_2019_authorization.flag' is missing or empty. Blind evaluation on 2019 data is strictly blocked.
  ```

#### 失败场景 2：指定最低温 `--target-type Min`（底层数据资产缺失）
- **执行命令**:
  ```bash
  python scripts/standalone_reliability_check.py --mode insample --target-type Min
  ```
- **原始完整报错输出**:
  ```text
  ================================================================================
        SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            
  ================================================================================
  MODE: [INSAMPLE] - IN-SAMPLE SELF-GRADE — 无校准证据效力
  WARNING: Active dimension not fully certified. Output tagged with [LEGACY-DISEASED].
  Traceback (most recent call last):
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/indexes/base.py", line 3641, in get_loc
      return self._engine.get_loc(casted_key)
             ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^
    File "pandas/_libs/index.pyx", line 168, in pandas._libs.index.IndexEngine.get_loc
    File "pandas/_libs/index.pyx", line 197, in pandas._libs.index.IndexEngine.get_loc
    File "pandas/_libs/hashtable_class_helper.pxi", line 7668, in pandas._libs.hashtable.PyObjectHashTable.get_item
    File "pandas/_libs/hashtable_class_helper.pxi", line 7676, in pandas._libs.hashtable.PyObjectHashTable.get_item
  KeyError: 'obs_tmin_f'

  The above exception was the direct cause of the following exception:

  Traceback (most recent call last):
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 920, in <module>
      main()
      ~~~~^^
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 888, in main
      res = run_reliability_pipeline(
          df_train=df_train,
      ...<11 lines>...
          metadata_headers=metadata_block,
      )
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 754, in run_reliability_pipeline
      df_expanded = expand_prediction_records(
          df_train,
      ...<4 lines>...
          target_obs_col=target_obs_col,
      )
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 319, in expand_prediction_records
      _expand_day_records(row, kappa_evt_map, r6_params, r7_params, cfg, binning_scheme, target_obs_col)
      ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 259, in _expand_day_records
      obs_y = float(row[target_obs_col])
                    ~~~^^^^^^^^^^^^^^^^
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/series.py", line 959, in __getitem__
      return self._get_value(key)
             ~~~~~~~~~~~~~~~^^^^^
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/series.py", line 1046, in _get_value
      loc = self.index.get_loc(label)
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/indexes/base.py", line 3648, in get_loc
      raise KeyError(key) from err
  KeyError: 'obs_tmin_f'
  ```

#### 失败场景 3：指定先导 3 站以外的站点 `--stations KDEN`（输入数组无该站数据）
- **执行命令**:
  ```bash
  python scripts/standalone_reliability_check.py --mode insample --stations KDEN
  ```
- **原始完整报错输出**:
  ```text
  ================================================================================
        SPEC-RELIABILITY-001: RELIABILITY CHECK BY PROBABILITY STRATA            
  ================================================================================
  MODE: [INSAMPLE] - IN-SAMPLE SELF-GRADE — 无校准证据效力
  WARNING: Active dimension not fully certified. Output tagged with [LEGACY-DISEASED].
  Traceback (most recent call last):
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 920, in <module>
      main()
      ~~~~^^
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 888, in main
      res = run_reliability_pipeline(
          df_train=df_train,
      ...<11 lines>...
          metadata_headers=metadata_block,
      )
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 763, in run_reliability_pipeline
      table_stratified = build_stratified_warning_table(df_expanded, num_bins=10, stations=stations_list)
    File "/Users/ericlin/SynologyDrive/Project/Poly Way2/scripts/standalone_reliability_check.py", line 442, in build_stratified_warning_table
      sub = df_expanded[(df_expanded["station"] == st) & (df_expanded["season"] == se)]
                         ~~~~~~~~~~~^^^^^^^^^^^
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/frame.py", line 4378, in __getitem__
      indexer = self.columns.get_loc(key)
    File "/opt/miniconda3/lib/python3.13/site-packages/pandas/core/indexes/range.py", line 525, in get_loc
      raise KeyError(key)
  KeyError: 'station'
  ```

---

### 2.3 没写完的半成品与未实现项（精确到文件与函数）

| 文件路径 | 函数名 / 模块 | 当前状态 | 现状描述（差什么，写具体） |
| :--- | :--- | :---: | :--- |
| `scripts/standalone_reliability_check.py` | `refit_parameters_on_subset` | **部分完成** | 当前内部仅实现了 `johnsonsu`（KMIA 样式）与 `evt`（KSFO 样式）的硬拟合分支。缺少：① 其他分布族（高斯纯参数、Student-t、Skew-Normal）的拟合逻辑；② 该拟合未对齐 P4 最新确立的 5 初猜多起点全局网格搜索协议。 |
| `scripts/standalone_reliability_check.py` | 全维度真值对接逻辑 | **未开始** | 当前脚本默认读取 `2000_2018_training_arrays.parquet`（仅含 KORD, KMIA, KSFO 18h TMAX）。尚未编写对接全量 NWS GHCN-Daily parquet 真值库与任意 lead time 预报数组的动态读取适配器。 |
| `scripts/standalone_reliability_check.py` | FDR 与多重检验校正 | **未开始** | 当前仅机械输出了“超带格子占比 vs 5% 理论期望”，尚未实现 Benjamini-Hochberg (BH) 或 Bonferroni 检验校正算法，亦无检验功效分析与统计势（Statistical Power）判定。 |

---

## 第 3 节：git 证据链

### 3.1 P5 相关 commit 时间线
执行命令：`git log --stat -- scripts/standalone_reliability_check.py src/verification/settlement.py src/verification/resampling.py evidence/p5*`
```text
commit 8115ec23f2c41c5eecd478066941f3f466791906
Author: oasislin <oasis.lin@gemcycle.com>
Date:   Thu Sep 24 00:22:09 2026 +0800

    docs(p5): deliver comprehensive P5 reliability tool overhaul audit report and update manifest

 ...5_reliability_tool_overhaul_and_audit_report.md | 175 +++++++++++++++++++++
 1 file changed, 175 insertions(+)

commit bcfe6682e691096b9b1143dba086c448473e017a
Author: oasislin <oasis.lin@gemcycle.com>
Date:   Thu Sep 24 00:08:24 2026 +0800

    docs(p5): deliver P5 reliability tool overhaul audit report for reviewer agent

 evidence/p5_overhaul_audit_deliverable.md | 106 ++++++++++++++++++++++++++++++
 1 file changed, 106 insertions(+)

commit 41d0701cf65ab158926b6a9165308e7bdced7d64
Author: oasislin <oasis.lin@gemcycle.com>
Date:   Thu Sep 24 00:07:59 2026 +0800

    feat(r2): implement P1 airgap guardrail, P2 asset quarantine, P3 block-cv engine, and draft P4 preregistration

 evidence/p5_tool_audit_report.md        | 263 +++++++++++++++
 scripts/standalone_reliability_check.py | 572 ++++++++++++++++++++++++++++----
 src/verification/resampling.py          | 120 +++++++
 src/verification/settlement.py          |  70 ++++
 4 files changed, 954 insertions(+), 71 deletions(-)

commit 0419b1e0e82afbdc60d9cf1903bd329daec8842f
Author: oasislin <oasis.lin@gemcycle.com>
Date:   Wed Sep 23 23:21:42 2026 +0800

    feat(phase2-task01-fix): 完成 Active 10 站物理模型归正校准、法定结算与模型资产普查审计报告

 scripts/standalone_reliability_check.py | 485 ++++++++++++++------------------
 1 file changed, 217 insertions(+), 268 deletions(-)

commit 445be2158130c7ead998fd8b697454a3088ad84d
Author: oasislin <oasis.lin@gemcycle.com>
Date:   Wed Sep 23 22:28:54 2026 +0800

    chore(manifest): update pilot manifest and include reliability verification artifacts

 scripts/standalone_reliability_check.py | 541 ++++++++++++++++++++++++++++++++
 1 file changed, 541 insertions(+)
```

### 3.2 git status 原文
执行命令：`git status`
```text
On branch feat/r2-r3-ghcn-retraining-and-budget
nothing to commit, working tree clean
```
*逐文件说明未提交改动*: 当前本地工作区为纯净状态（`working tree clean`），无任何未提交改动。

### 3.3 本地有而远端没有的 commit
执行命令：`git log origin/feat/r2-r3-ghcn-retraining-and-budget..HEAD --oneline`
```text
6c2ae95 (HEAD -> feat/r2-r3-ghcn-retraining-and-budget) feat(p4): 完成工作队列五项扫尾与 Block-CV 拟合侧工程干跑验证
```
*说明*: commit `6c2ae95` 为 P4 重训分支的工程扫尾提交，尚未推送到远端 GitHub。其余与 P5 相关的所有 commit（截至 `8115ec2` / `116dfc3`）均已完全推送同步至远端。

---

## 第 4 节：测试真实账目

### 4.1 P5 相关全部测试的 pytest 全量原始输出
执行命令：
```bash
python -m pytest tests/unit/verification/test_reliability_synthetic_acceptance.py tests/unit/verification/test_settlement_hit_probability.py tests/unit/verification/test_resampling.py tests/unit/verification/test_reliability_modes_and_gates.py tests/unit/verification/test_reliability_check.py -v
```
原始输出全量：
```text
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.5.0 -- /opt/miniconda3/bin/python
cachedir: .pytest_cache
rootdir: /Users/ericlin/SynologyDrive/Project/Poly Way2
plugins: anyio-4.12.1, cov-7.1.0
collecting ... collected 3 items                                                             collected 23 items

tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_perfect_calibration PASSED [  4%]
tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_deliberate_miscalibration PASSED [  8%]
tests/unit/verification/test_reliability_synthetic_acceptance.py::test_synthetic_collapse_sentinel PASSED [ 13%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_inside PASSED [ 17%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_fully_outside PASSED [ 21%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_lower_boundary PASSED [ 26%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_exact_upper_boundary PASSED [ 30%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_infinite_bounds PASSED [ 34%]
tests/unit/verification/test_settlement_hit_probability.py::test_hit_probability_partition_unity PASSED [ 39%]
tests/unit/verification/test_resampling.py::test_generate_30day_blocks PASSED [ 43%]
tests/unit/verification/test_resampling.py::test_cv_split_zero_leakage_and_reproducibility PASSED [ 47%]
tests/unit/verification/test_resampling.py::test_get_or_create_cv_manifest_persistence PASSED [ 52%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_blind_mode_airgap_guardrail PASSED [ 56%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_metadata_header_persistence PASSED [ 60%]
tests/unit/verification/test_reliability_modes_and_gates.py::test_cv_pipeline_dispersion_columns PASSED [ 65%]
tests/unit/verification/test_reliability_check.py::test_evaluate_station_cdf_monotonicity PASSED [ 69%]
tests/unit/verification/test_reliability_check.py::test_expand_prediction_records_properties PASSED [ 73%]
tests/unit/verification/test_reliability_check.py::test_compute_binomial_ci_half_width_wilson PASSED [ 78%]
tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table PASSED [ 82%]
tests/unit/verification/test_reliability_check.py::test_build_global_reliability_table_empty_strata PASSED [ 86%]
tests/unit/verification/test_reliability_check.py::test_build_stratified_warning_table PASSED [ 91%]
tests/unit/verification/test_reliability_check.py::test_compute_brier_skill_scores PASSED [ 95%]
tests/unit/verification/test_reliability_check.py::test_run_reliability_pipeline PASSED [100%]

============================== 23 passed in 1.83s ==============================
```

### 4.2 测试清单对账
| 测试文件 | 测试函数名 | 当前状态 | 判定 |
| :--- | :--- | :---: | :---: |
| `test_reliability_synthetic_acceptance.py` | `test_synthetic_perfect_calibration` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_synthetic_acceptance.py` | `test_synthetic_deliberate_miscalibration` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_synthetic_acceptance.py` | `test_synthetic_collapse_sentinel` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_fully_inside` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_fully_outside` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_exact_lower_boundary` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_exact_upper_boundary` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_infinite_bounds` | 通过 (PASSED) | 完成且可验证 |
| `test_settlement_hit_probability.py` | `test_hit_probability_partition_unity` | 通过 (PASSED) | 完成且可验证 |
| `test_resampling.py` | `test_generate_30day_blocks` | 通过 (PASSED) | 完成且可验证 |
| `test_resampling.py` | `test_cv_split_zero_leakage_and_reproducibility` | 通过 (PASSED) | 完成且可验证 |
| `test_resampling.py` | `test_get_or_create_cv_manifest_persistence` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_modes_and_gates.py` | `test_blind_mode_airgap_guardrail` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_modes_and_gates.py` | `test_metadata_header_persistence` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_modes_and_gates.py` | `test_cv_pipeline_dispersion_columns` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_evaluate_station_cdf_monotonicity` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_expand_prediction_records_properties` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_compute_binomial_ci_half_width_wilson` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_build_global_reliability_table` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_build_global_reliability_table_empty_strata` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_build_stratified_warning_table` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_compute_brier_skill_scores` | 通过 (PASSED) | 完成且可验证 |
| `test_reliability_check.py` | `test_run_reliability_pipeline` | 通过 (PASSED) | 完成且可验证 |

*汇报中曾提及但当前不存在的测试检查*:
- 经全量搜索与历史提交比对：此前报告中声称通过的测试函数，**全部真实存在且当前均处于 PASSED 状态**，不存在“汇报中声称存在但实则不存在或被删除”的幽灵测试。

---

## 第 5 节：已产生工件清单

| 工件路径 | 生成/更新时间 | 内容概述 | 自评标注 | 标注理由 |
| :--- | :--- | :--- | :---: | :--- |
| `evidence/cv_split_blocks_20rounds.json` | 2026-09-24T00:07 | 20 轮 × 30 天块划分明细清单 | **自认为可信** | 种子固定（20260923），程序生成，经自动化测试验证每轮验证集与训练集交集为 0。 |
| `evidence/reliability_check_main_global.csv` | 2026-09-27T23:22 | 20 概率段全局合并可靠性表 | **自认为可信（仅限工具自检）** | 产自 20 轮真实块交叉验证，如实暴露了旧模型 43.8% 超带缺陷；但输入数据仅为旧代 18h TMAX，不可作为未来生产模型的验收依据。 |
| `evidence/reliability_check_stratified_station_season.csv` | 2026-09-27T23:22 | 3 站 × 4 季分层警告表 | **自认为可信（仅限工具自检）** | 剔除了定向高亮，所有格子统一输出；同上，输入为旧代数据。 |
| `evidence/reliability_check_brier_skill.csv` | 2026-09-27T23:22 | 全局/分站/分季 BSS 汇总表 | **自认为可信（仅限工具自检）** | LOYO 气候基线算法正确；同上，输入为旧代数据。 |
| `evidence/p5_tool_audit_report.md` | 2026-09-23T23:50 | 14 题自查问卷答卷 | **自认为可信** | 客观记录了工具改造前的缺陷、漏洞与未实现项。 |
| `evidence/p5_overhaul_audit_deliverable.md` | 2026-09-24T00:08 | R1–R7 改造交付说明 | **自认为可信** | 真实记录了重构过程与合成测试通过证据。 |
| `evidence/p5_reliability_tool_overhaul_and_audit_report.md` | 2026-09-24T00:21 | P5 重构执行审计总报告 | **自认为可信** | 记录了 20 轮 CV 实跑指标与全库校验码。 |
| `specs/spec-reliability-001-strata-verification.md` | 2026-09-23T21:30 | 任务规格书初稿 | **无法判断** | 该文档为早前未吸纳 14 题整改令的旧版预注册草案，部分口径与后续 R1~R7 改造令存在差异，等待主控方出具统一修复规格替代。 |

---

## 第 6 节：专业意见（仅供主控参考，不必然采纳）

### 6.1 建议的恢复顺序及理由
1. **第一步：明确统计规格（分箱/FDR/功效）**
   - *理由*: 当前工具输出的 43.8% 超带率表明，对于 20 个等宽概率段，某些尾部或稀疏段的样本量虽然不为零但功效不足；若主控引入等频分箱（Quantile Binning）或 Benjamini-Hochberg FDR 校正，底层的置信区间和超带判定公式必须先在纸面上冻结，避免反复返工。
2. **第二步：补全全维度输入适配器（全 10 站、双温标、全 lead time）**
   - *理由*: 当前脚本硬编码读取 `2000_2018_training_arrays.parquet`（仅 3 站 18h TMAX），导致测试 Min 或其他站必然触发 `KeyError`。必须升级数据源接口，接入 GHCN-Daily 与多时效预报底账。
3. **第三步：对接 P4 最新 5 初猜重训协议**
   - *理由*: CV 引擎的 `refit_parameters_on_subset` 需直接调用 P4 重拟接口（多起点全局优化 + 全域积分似然），确保验证折预测与生产拟合逻辑 100% 镜像一致。

### 6.2 需要主控方提供的信息或决策（规格不明处、口径待拍板处）
1. **分箱口径选择**: 维持当前 20 等宽分箱（$[0, 0.05), \dots$）+ `WARNING_LOW_N` 标注，还是改用自适应等频分箱（每箱 $N \ge 100$）？
2. **多重检验校正标准**: 超带率是否需要施加 FDR（如 $q < 0.05$）校正？抑或仅作描述性诊断、不设硬性门禁？
3. **气候基线时间粒度**: 当前采用“站 × 月 × 留一年（LOYO）”经验分布，是否需要切换为平滑气候态（日历日 $\pm 15$ 天滑动窗口）？
4. **全维度数据源规范**: 10 站 × 2 变量 × 10 lead time 的预报与真值底账应从何处标准化加载？

### 6.3 恢复后第一件事
等待主控方出具包含上述 4 项决断的**《P5 统一最终修复规格书》**，逐条对齐后，先编写全维度数据适配与 FDR 统计检验的自动化测试用例，再行开工编写业务代码。
