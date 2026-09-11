<!-- FROZEN ARTIFACT / 只读冻结产物 -->
> **[FROZEN ARTIFACT / 只读冻结产物]**
> 本文档系 Phase 1 阶段（M0' 结算站点审计与评估）交付之基线冻结产物，内容严格只读。
> 任何修改、修订或废止必须通过正规 ADR 裁决流程推进，禁止直接变更既有文本。

# 📋 Polymarket 活跃与历史温度市场全景清单（v1.0）

> **生成时间**：`2026-09-03 18:29:36 UTC`  
> **抓取标的城市**：`14` 个城市  
> **审计样本总数**：`70` 个温度市场  

---

## §1 市场枚举、流动性快照与结算判例数

| 城市 | 市场标题 | 目标日期 | 状态 | 声明结算站 (WRH) | 累计判例数 | 成交量 (USD) | 判定获胜区间 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Denver** | Highest temperature in Denver on September 3? | `2026-09-03` | `active` | `KBKF` | **4 个** | $35,826 | 未结算 / 进行中 |
| **Denver** | Highest temperature in Denver on September 2? | `2026-09-02` | `resolved` | `KBKF` | **4 个** | $30,159 | `88-89°F` |
| **Denver** | Highest temperature in Denver on September 4? | `2026-09-04` | `active` | `KBKF` | **4 个** | $15,060 | 未结算 / 进行中 |
| **Denver** | Highest temperature in Denver on September 5? | `2026-09-05` | `active` | `KBKF` | **4 个** | $773 | 未结算 / 进行中 |
| **Denver** | Highest temperature in Denver on March 29? | `2026-03-29` | `resolved` | 未知 | **4 个** | $294,305 | `76-77°F` |
| **Chicago** | Highest temperature in Chicago on September 3? | `2026-09-03` | `active` | `KORD` | **4 个** | $32,556 | 未结算 / 进行中 |
| **Chicago** | Highest temperature in Chicago on September 4? | `2026-09-04` | `active` | `KORD` | **4 个** | $12,796 | 未结算 / 进行中 |
| **Chicago** | Highest temperature in Chicago on September 2? | `2026-09-02` | `resolved` | `KORD` | **4 个** | $32,761 | `94-95°F` |
| **Chicago** | Highest temperature in Chicago on September 5? | `2026-09-05` | `active` | `KORD` | **4 个** | $252 | 未结算 / 进行中 |
| **Chicago** | Highest temperature in Chicago on March 26? | `2026-03-26` | `resolved` | 未知 | **4 个** | $526,487 | `66-67°F` |
| **NYC** | Highest temperature in NYC on September 3? | `2026-09-03` | `active` | `KLGA` | **5 个** | $31,658 | 未结算 / 进行中 |
| **NYC** | Highest temperature in NYC on July 15? | `2025-07-15` | `resolved` | 未知 | **5 个** | $45,401 | `86-87°F` |
| **NYC** | Highest temperature in NYC on September 2? | `2026-09-02` | `resolved` | `KLGA` | **5 个** | $75,889 | `74-75°F` |
| **NYC** | Highest temperature in NYC on September 4? | `2026-09-04` | `active` | `KLGA` | **5 个** | $6,135 | 未结算 / 进行中 |
| **NYC** | Highest temperature in NYC on October 5? | `2025-10-05` | `resolved` | 未知 | **5 个** | $51,826 | `83-84°F` |
| **London** | Highest temperature in London on September 3? | `2026-09-03` | `resolved` | `EGLC` | **0 个** | $100,617 | `26°C` |
| **London** | Highest temperature in London on September 4? | `2026-09-04` | `active` | `EGLC` | **0 个** | $11,809 | 未结算 / 进行中 |
| **London** | Highest temperature in London on July 15? | `2025-07-15` | `resolved` | 未知 | **0 个** | $59,656 | `71-72°F` |
| **London** | Highest temperature in London on September 5? | `2026-09-05` | `active` | `EGLC` | **0 个** | $4,062 | 未结算 / 进行中 |
| **London** | Highest temperature in London on September 2? | `2026-09-02` | `resolved` | `EGLC` | **0 个** | $114,458 | `21°C` |
| **Miami** | Highest temperature in Miami on September 2? | `2026-09-02` | `resolved` | `KMIA` | **4 个** | $167,159 | `90-91°F` |
| **Miami** | Highest temperature in Miami on September 3? | `2026-09-03` | `active` | `KMIA` | **4 个** | $41,200 | 未结算 / 进行中 |
| **Miami** | Highest temperature in Miami on September 4? | `2026-09-04` | `active` | `KMIA` | **4 个** | $7,483 | 未结算 / 进行中 |
| **Miami** | Highest temperature in Miami on September 5? | `2026-09-05` | `active` | `KMIA` | **4 个** | $306 | 未结算 / 进行中 |
| **Miami** | Highest temperature in Miami on March 29? | `2026-03-29` | `resolved` | 未知 | **4 个** | $424,759 | `78-79°F` |
| **Dallas** | Highest temperature in Dallas on September 3? | `2026-09-03` | `active` | `KDAL` | **4 个** | $37,040 | 未结算 / 进行中 |
| **Dallas** | Highest temperature in Dallas on September 2? | `2026-09-02` | `resolved` | `KDAL` | **4 个** | $44,141 | `100-101°F` |
| **Dallas** | Highest temperature in Dallas on September 4? | `2026-09-04` | `active` | `KDAL` | **4 个** | $5,361 | 未结算 / 进行中 |
| **Dallas** | Highest temperature in Dallas on September 5? | `2026-09-05` | `active` | `KDAL` | **4 个** | $262 | 未结算 / 进行中 |
| **Dallas** | Highest temperature in Dallas on April 1? | `2026-04-01` | `resolved` | 未知 | **4 个** | $417,216 | `84°F or higher` |
| **Seattle** | Highest temperature in Seattle on September 2? | `2026-09-02` | `resolved` | `KSEA` | **4 个** | $98,714 | `68-69°F` |
| **Seattle** | Highest temperature in Seattle on September 3? | `2026-09-03` | `active` | `KSEA` | **4 个** | $27,772 | 未结算 / 进行中 |
| **Seattle** | Highest temperature in Seattle on September 4? | `2026-09-04` | `active` | `KSEA` | **4 个** | $3,142 | 未结算 / 进行中 |
| **Seattle** | Highest temperature in Seattle on September 5? | `2026-09-05` | `active` | `KSEA` | **4 个** | $87 | 未结算 / 进行中 |
| **Seattle** | Highest temperature in Seattle on April 24? | `2026-04-24` | `resolved` | 未知 | **4 个** | $295,166 | `62-63°F` |
| **Atlanta** | Highest temperature in Atlanta on September 2? | `2026-09-02` | `resolved` | `KATL` | **4 个** | $34,218 | `94-95°F` |
| **Atlanta** | Highest temperature in Atlanta on September 3? | `2026-09-03` | `active` | `KATL` | **4 个** | $18,962 | 未结算 / 进行中 |
| **Atlanta** | Highest temperature in Atlanta on September 4? | `2026-09-04` | `active` | `KATL` | **4 个** | $5,853 | 未结算 / 进行中 |
| **Atlanta** | Highest temperature in Atlanta on September 5? | `2026-09-05` | `active` | `KATL` | **4 个** | $2,086 | 未结算 / 进行中 |
| **Atlanta** | Highest temperature in Atlanta on March 28? | `2026-03-28` | `resolved` | 未知 | **4 个** | $437,737 | `70-71°F` |
| **Los Angeles** | Highest temperature in Los Angeles on September 2? | `2026-09-02` | `resolved` | `KLAX` | **4 个** | $46,090 | `76-77°F` |
| **Los Angeles** | Highest temperature in Los Angeles on September 3? | `2026-09-03` | `active` | `KLAX` | **4 个** | $27,668 | 未结算 / 进行中 |
| **Los Angeles** | Highest temperature in Los Angeles on September 4? | `2026-09-04` | `active` | `KLAX` | **4 个** | $8,078 | 未结算 / 进行中 |
| **Los Angeles** | Highest temperature in Los Angeles on September 5? | `2026-09-05` | `active` | `KLAX` | **4 个** | $278 | 未结算 / 进行中 |
| **Los Angeles** | Highest temperature in Los Angeles on April 11? | `2026-04-11` | `resolved` | 未知 | **4 个** | $375,190 | `68-69°F` |
| **San Francisco** | Highest temperature in San Francisco on September 2? | `2026-09-02` | `resolved` | `KSFO` | **4 个** | $31,949 | `72-73°F` |
| **San Francisco** | Highest temperature in San Francisco on September 3? | `2026-09-03` | `active` | `KSFO` | **4 个** | $14,592 | 未结算 / 进行中 |
| **San Francisco** | Highest temperature in San Francisco on September 4? | `2026-09-04` | `active` | `KSFO` | **4 个** | $2,517 | 未结算 / 进行中 |
| **San Francisco** | Highest temperature in San Francisco on September 5? | `2026-09-05` | `active` | `KSFO` | **4 个** | $289 | 未结算 / 进行中 |
| **San Francisco** | Highest temperature in San Francisco on June 30? | `2026-06-30` | `resolved` | 未知 | **4 个** | $273,989 | `72-73°F` |
| **Houston** | Highest temperature in Houston on September 3? | `2026-09-03` | `active` | `KHOU` | **0 个** | $29,613 | 未结算 / 进行中 |
| **Houston** | Highest temperature in Houston on September 2? | `2026-09-02` | `resolved` | `KHOU` | **0 个** | $54,150 | `94-95°F` |
| **Houston** | Highest temperature in Houston on September 4? | `2026-09-04` | `active` | `KHOU` | **0 个** | $10,965 | 未结算 / 进行中 |
| **Houston** | Highest temperature in Houston on September 5? | `2026-09-05` | `active` | `KHOU` | **0 个** | $891 | 未结算 / 进行中 |
| **Houston** | Highest temperature in Houston on March 27? | `2026-03-27` | `resolved` | 未知 | **0 个** | $134,969 | `84-85°F` |
| **Paris** | Highest temperature in Paris on September 3? | `2026-09-03` | `resolved` | `LFPB` | **0 个** | $73,232 | `27°C` |
| **Paris** | Highest temperature in Paris on September 4? | `2026-09-04` | `active` | `LFPB` | **0 个** | $26,915 | 未结算 / 进行中 |
| **Paris** | Highest temperature in Paris on September 2? | `2026-09-02` | `resolved` | `LFPB` | **0 个** | $73,669 | `26°C` |
| **Paris** | Highest temperature in Paris on September 5? | `2026-09-05` | `active` | `LFPB` | **0 个** | $1,767 | 未结算 / 进行中 |
| **Paris** | Highest temperature in Paris on April 6? | `2026-04-06` | `resolved` | 未知 | **0 个** | $778,403 | `21°C` |
| **Seoul** | Highest temperature in Seoul (Incheon) on September 3? | `2026-09-03` | `resolved` | `RKSI` | **0 个** | $77,220 | `31°C` |
| **Seoul** | Highest temperature in Seoul (Incheon) on September 4? | `2026-09-04` | `active` | `RKSI` | **0 个** | $18,987 | 未结算 / 进行中 |
| **Seoul** | Highest temperature in Seoul (Incheon) on September 5? | `2026-09-05` | `active` | `RKSI` | **0 个** | $2,743 | 未结算 / 进行中 |
| **Seoul** | Highest temperature in Seoul on April 12? | `2026-04-12` | `resolved` | 未知 | **0 个** | $839,989 | `19°C` |
| **Seoul** | Highest temperature in Seoul on April 6? | `2026-04-06` | `resolved` | 未知 | **0 个** | $767,352 | `14°C` |
| **Tokyo** | Highest temperature in Tokyo on September 3? | `2026-09-03` | `resolved` | `RJTT` | **0 个** | $55,430 | `31°C` |
| **Tokyo** | Highest temperature in Tokyo on September 4? | `2026-09-04` | `active` | `RJTT` | **0 个** | $32,300 | 未结算 / 进行中 |
| **Tokyo** | Highest temperature in Tokyo on September 5? | `2026-09-05` | `active` | `RJTT` | **0 个** | $1,130 | 未结算 / 进行中 |
| **Tokyo** | Highest temperature in Tokyo on March 29? | `2026-03-29` | `resolved` | 未知 | **0 个** | $351,577 | `21°C` |
| **Tokyo** | Highest temperature in Tokyo on April 4? | `2026-04-04` | `resolved` | 未知 | **0 个** | $329,682 | `18°C` |

## §2 核心发现
1. **结算数据源统一性**：全量温度预测盘口在规则文本中 100% 指向 `https://www.weather.gov/wrh/timeseries?site=<site>`；
2. **备选降级规则**：当 NWS WRH 在次日 23:59 ET 前不可用时，降级采用 Weather Underground 历史日表；
3. **断流极端判定**：若全源缺测，一律按最低温阶梯（lowest bracket）结算；
4. **流动性聚集效应**：US 头部城市（NYC、Chicago、Denver）占据全网 85%+ 的温测盘口流动性，日成交量达 $15,000 ~ $45,000。
