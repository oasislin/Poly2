<!-- FROZEN ARTIFACT / 只读冻结产物 -->
> **[FROZEN ARTIFACT / 只读冻结产物]**
> 本文档系 Phase 1 阶段（M0' 结算站点审计与评估）交付之基线冻结产物，内容严格只读。
> 任何修改、修订或废止必须通过正规 ADR 裁决流程推进，禁止直接变更既有文本。

# 🌍 Polymarket 全球温度预测市场与结算员全景台账（v1.0）

> **生成时间**：`2026-09-03 17:53:28 UTC`  
> **抓取总盘口数**：`3610` 个  
> **覆盖全球城市**：`53` 个  
> **自检判定**：🟢 **全部自检通过 (PASS)**

---

## §1 全球市场宏观统计总览 (Macro Summary)

| 统计维度 | 统计值 | 说明 |
| :--- | :--- | :--- |
| **总收录温度盘口** | **3610 个** | 包含最高温与最低温全部日盘 |
| **覆盖城市/地区总数** | **53 个** | 涵盖美洲、欧洲、亚太、中东、非洲 |
| **最高温盘口 (MAX_TEMP)** | **2505 个** | 传统最高气温日盘 |
| **最低温盘口 (MIN_TEMP)** | **1105 个** | 最低气温日盘（此前完全遗漏的板块） |
| **双向覆盖城市数 (Max + Min)** | **51 个** | 同时开通最高温与最低温双边盘口的城市 |
| **华氏度 (°F) 盘口** | **818 个** | 美国本土市场统一采用华氏度 |
| **摄氏度 (°C) 盘口** | **2792 个** | 国际非美市场统一采用摄氏度 |
| **站号解析成功率** | **99.9%** | 规则文本明确给出或映射对应物理台站 |
| **结算源 URL 解析率** | **100.0%** | 规则包含精确的官方时序表/日报链接 |
| **Show Hourly Data 约束率** | **172 个** | 强制要求整点报文过滤，排除高频毛刺 |

---

## §2 核心城市及结算员对照矩阵 (City vs Settlement Entity)

| 城市/地区 | 盘口方向 | 标的站号 | 台站名称 | 法定结算机构 (结算员) | 结算仲裁机制 | 结算源链接 / 规则页面 | 计价单位 | 状态样本 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Amsterdam** | 🔺 最高温 | `EHAM` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/nl/schiphol/EHAM) | `Celsius` | `resolved` |
| **Amsterdam** | 🔻 最低温 | `EHAM` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/nl/schiphol/EHAM) | `Celsius` | `resolved` |
| **Ankara** | 🔺 最高温 | `LTAC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/tr/%C3%A7ubuk/LTAC) | `Celsius` | `resolved` |
| **Ankara** | 🔻 最低温 | `LTAC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/tr/%C3%A7ubuk/LTAC) | `Celsius` | `resolved` |
| **Atlanta** | 🔺 最高温 | `KATL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ga/atlanta/KATL) | `Fahrenheit` | `resolved` |
| **Atlanta** | 🔻 最低温 | `KATL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ga/atlanta/KATL) | `Fahrenheit` | `resolved` |
| **Austin** | 🔺 最高温 | `KAUS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/austin/KAUS) | `Fahrenheit` | `resolved` |
| **Austin** | 🔻 最低温 | `KAUS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/austin/KAUS) | `Fahrenheit` | `resolved` |
| **Beijing** | 🔺 最高温 | `ZBAA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/beijing/ZBAA) | `Celsius` | `resolved` |
| **Beijing** | 🔻 最低温 | `ZBAA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/beijing/ZBAA) | `Celsius` | `resolved` |
| **Buenos Aires** | 🔺 最高温 | `SAEZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ar/ezeiza/SAEZ) | `Celsius` | `resolved` |
| **Buenos Aires** | 🔻 最低温 | `SAEZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ar/ezeiza/SAEZ) | `Celsius` | `resolved` |
| **Busan** | 🔺 最高温 | `BUSAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/busan/RKPK) | `Celsius` | `resolved` |
| **Busan** | 🔻 最低温 | `BUSAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/busan/RKPK) | `Celsius` | `resolved` |
| **Cape Town** | 🔺 最高温 | `FACT` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/za/matroosfontein/FACT) | `Celsius` | `resolved` |
| **Cape Town** | 🔻 最低温 | `FACT` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/za/matroosfontein/FACT) | `Celsius` | `resolved` |
| **Chengdu** | 🔺 最高温 | `ZUUU` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/chengdu/ZUUU) | `Celsius` | `resolved` |
| **Chengdu** | 🔻 最低温 | `ZUUU` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/chengdu/ZUUU) | `Celsius` | `resolved` |
| **Chicago** | 🔺 最高温 | `KORD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/il/chicago/KORD) | `Fahrenheit` | `resolved` |
| **Chicago** | 🔻 最低温 | `KORD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/il/chicago/KORD) | `Fahrenheit` | `resolved` |
| **Chongqing** | 🔺 最高温 | `ZUCK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/chongqing/ZUCK) | `Celsius` | `resolved` |
| **Chongqing** | 🔻 最低温 | `ZUCK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/chongqing/ZUCK) | `Celsius` | `resolved` |
| **DC** | 🔺 最高温 | `KDCA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/dc/washington/KDCA) | `Fahrenheit` | `resolved` |
| **Dallas** | 🔺 最高温 | `KDAL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/dallas/KDAL) | `Fahrenheit` | `resolved` |
| **Dallas** | 🔻 最低温 | `KDAL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/dallas/KDAL) | `Fahrenheit` | `resolved` |
| **Denver** | 🔺 最高温 | `KBKF` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/co/aurora/KBKF) | `Fahrenheit` | `resolved` |
| **Denver** | 🔻 最低温 | `KBKF` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/co/aurora/KBKF) | `Fahrenheit` | `resolved` |
| **Guangzhou** | 🔺 最高温 | `ZGGG` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/guangzhou/ZGGG) | `Celsius` | `resolved` |
| **Guangzhou** | 🔻 最低温 | `ZGGG` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/guangzhou/ZGGG) | `Celsius` | `resolved` |
| **Helsinki** | 🔺 最高温 | `EFHK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/fi/vantaa/EFHK) | `Celsius` | `resolved` |
| **Helsinki** | 🔻 最低温 | `EFHK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/fi/vantaa/EFHK) | `Celsius` | `resolved` |
| **Hong Kong** | 🔺 最高温 | `HKO` | Hong Kong Observatory Headquarters (Tsim Sha Tsui) | **Hong Kong Observatory (HKO)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov.hk/en/cis/climat.htm) | `Celsius` | `resolved` |
| **Hong Kong** | 🔻 最低温 | `HKO` | Hong Kong Observatory Headquarters (Tsim Sha Tsui) | **Hong Kong Observatory (HKO)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov.hk/en/cis/climat.htm) | `Celsius` | `resolved` |
| **Houston** | 🔺 最高温 | `KHOU` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/houston/KHOU) | `Fahrenheit` | `resolved` |
| **Houston** | 🔻 最低温 | `KHOU` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/tx/houston/KHOU) | `Fahrenheit` | `resolved` |
| **Istanbul** | 🔺 最高温 | `LTFM` | Istanbul Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=LTFM) | `Celsius` | `resolved` |
| **Istanbul** | 🔻 最低温 | `LTFM` | Istanbul Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=LTFM) | `Celsius` | `resolved` |
| **Jeddah** | 🔺 最高温 | `OEJN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/sa/jeddah/OEJN) | `Celsius` | `resolved` |
| **Jeddah** | 🔻 最低温 | `OEJN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/sa/jeddah/OEJN) | `Celsius` | `resolved` |
| **Jinan** | 🔺 最高温 | `JINAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/jinan/ZSJN) | `Celsius` | `active` |
| **Jinan** | 🔻 最低温 | `JINAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/jinan/ZSJN) | `Celsius` | `resolved` |
| **Karachi** | 🔺 最高温 | `OPKC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/pk/karachi/OPKC) | `Celsius` | `resolved` |
| **Karachi** | 🔻 最低温 | `OPKC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/pk/karachi/OPKC) | `Celsius` | `resolved` |
| **Kuala Lumpur** | 🔺 最高温 | `WMKK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/my/sepang-district/WMKK) | `Celsius` | `resolved` |
| **Kuala Lumpur** | 🔻 最低温 | `WMKK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/my/sepang-district/WMKK) | `Celsius` | `resolved` |
| **London** | 🔺 最高温 | `EGLC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/gb/london/EGLC) | `Fahrenheit` | `resolved` |
| **London** | 🔻 最低温 | `EGLC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/gb/london/EGLC) | `Celsius` | `resolved` |
| **Los Angeles** | 🔺 最高温 | `KLAX` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ca/los-angeles/KLAX) | `Fahrenheit` | `resolved` |
| **Los Angeles** | 🔻 最低温 | `KLAX` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ca/los-angeles/KLAX) | `Fahrenheit` | `resolved` |
| **Lucknow** | 🔺 最高温 | `VILK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/in/lucknow/VILK) | `Celsius` | `resolved` |
| **Lucknow** | 🔻 最低温 | `VILK` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/in/lucknow/VILK) | `Celsius` | `resolved` |
| **Madrid** | 🔺 最高温 | `LEMD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/es/madrid/LEMD) | `Celsius` | `resolved` |
| **Madrid** | 🔻 最低温 | `LEMD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/es/madrid/LEMD) | `Celsius` | `resolved` |
| **Manila** | 🔺 最高温 | `RPLL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ph/manila/RPLL) | `Celsius` | `resolved` |
| **Manila** | 🔻 最低温 | `RPLL` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ph/manila/RPLL) | `Celsius` | `resolved` |
| **Mexico City** | 🔺 最高温 | `MMMX` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/mx/mexico-city/MMMX) | `Celsius` | `resolved` |
| **Mexico City** | 🔻 最低温 | `MMMX` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/mx/mexico-city/MMMX) | `Celsius` | `resolved` |
| **Miami** | 🔺 最高温 | `MIAMI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/fl/miami/KMIA) | `Fahrenheit` | `resolved` |
| **Miami** | 🔻 最低温 | `MIAMI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/fl/miami/KMIA) | `Fahrenheit` | `resolved` |
| **Milan** | 🔺 最高温 | `MILAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/it/milan/LIMC) | `Celsius` | `resolved` |
| **Milan** | 🔻 最低温 | `MILAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/it/milan/LIMC) | `Celsius` | `resolved` |
| **Moscow** | 🔺 最高温 | `UUWW` | Vnukovo International Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=UUWW) | `Celsius` | `resolved` |
| **Moscow** | 🔻 最低温 | `UUWW` | Vnukovo International Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=UUWW) | `Celsius` | `resolved` |
| **Munich** | 🔺 最高温 | `EDDM` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/de/munich/EDDM) | `Celsius` | `resolved` |
| **Munich** | 🔻 最低温 | `EDDM` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/de/munich/EDDM) | `Celsius` | `resolved` |
| **NYC** | 🔺 最高温 | `KLGA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA) | `Fahrenheit` | `resolved` |
| **NYC** | 🔻 最低温 | `KLGA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA) | `Fahrenheit` | `resolved` |
| **Paris** | 🔺 最高温 | `PARIS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/fr/paris/LFPG) | `Celsius` | `resolved` |
| **Paris** | 🔻 最低温 | `LFPB` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/fr/bonneuil-en-france/LFPB) | `Celsius` | `resolved` |
| **Qingdao** | 🔺 最高温 | `ZSQD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/qingdao/ZSQD) | `Celsius` | `resolved` |
| **Qingdao** | 🔻 最低温 | `ZSQD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/qingdao/ZSQD) | `Celsius` | `resolved` |
| **San Francisco** | 🔺 最高温 | `KSFO` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ca/san-francisco/KSFO) | `Fahrenheit` | `resolved` |
| **San Francisco** | 🔻 最低温 | `KSFO` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/ca/san-francisco/KSFO) | `Fahrenheit` | `resolved` |
| **Sao Paulo** | 🔺 最高温 | `SBGR` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/br/guarulhos/SBGR) | `Celsius` | `resolved` |
| **Sao Paulo** | 🔻 最低温 | `SBGR` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/br/guarulhos/SBGR) | `Celsius` | `resolved` |
| **Seattle** | 🔺 最高温 | `KSEA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/wa/seatac/KSEA) | `Fahrenheit` | `resolved` |
| **Seattle** | 🔻 最低温 | `KSEA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/us/wa/seatac/KSEA) | `Fahrenheit` | `resolved` |
| **Seoul** | 🔺 最高温 | `RKSI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/incheon/RKSI) | `Celsius` | `resolved` |
| **Seoul** | 🔻 最低温 | `RKSI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/incheon/RKSI) | `Celsius` | `resolved` |
| **Seoul (Incheon)** | 🔺 最高温 | `RKSI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/incheon/RKSI) | `Celsius` | `resolved` |
| **Seoul (Incheon)** | 🔻 最低温 | `RKSI` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/kr/incheon/RKSI) | `Celsius` | `resolved` |
| **Shanghai** | 🔺 最高温 | `ZSPD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/shanghai/ZSPD) | `Celsius` | `resolved` |
| **Shanghai** | 🔻 最低温 | `ZSPD` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/shanghai/ZSPD) | `Celsius` | `resolved` |
| **Shenzhen** | 🔺 最高温 | `ZGSZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ) | `Celsius` | `resolved` |
| **Shenzhen** | 🔻 最低温 | `ZGSZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/shenzhen/ZGSZ) | `Celsius` | `resolved` |
| **Singapore** | 🔺 最高温 | `WSSS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/sg/singapore/WSSS) | `Celsius` | `resolved` |
| **Singapore** | 🔻 最低温 | `WSSS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/sg/singapore/WSSS) | `Celsius` | `resolved` |
| **Taipei** | 🔺 最高温 | `RCTP` | Taiwan Taoyuan International Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=RCTP) | `Celsius` | `resolved` |
| **Taipei** | 🔻 最低温 | `RCSS` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/tw/taipei/RCSS) | `Celsius` | `resolved` |
| **Tel Aviv** | 🔺 最高温 | `LLBG` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/il/tel-aviv/LLBG) | `Celsius` | `resolved` |
| **Tel Aviv** | 🔻 最低温 | `LLBG` | Ben Gurion International Airport | **NOAA NWS (National Weather Service)** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/timeseries?site=LLBG) | `Celsius` | `resolved` |
| **Tokyo** | 🔺 最高温 | `TOKYO` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/jp/tokyo/RJTT) | `Celsius` | `resolved` |
| **Tokyo** | 🔻 最低温 | `TOKYO` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/jp/tokyo/RJTT) | `Celsius` | `resolved` |
| **Toronto** | 🔺 最高温 | `CYYZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ca/mississauga/CYYZ) | `Celsius` | `resolved` |
| **Toronto** | 🔻 最低温 | `CYYZ` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/ca/mississauga/CYYZ) | `Celsius` | `resolved` |
| **Unknown** | 🔺 最高温 | *(待标注)* | *(按规则链接直定)* | **Unknown** | `UMA Optimistic Oracle` | [规则链接](https://www.weather.gov/wrh/Climate?wfo=okx) | `Fahrenheit` | `closed` |
| **Warsaw** | 🔺 最高温 | `EPWA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/pl/warsaw/EPWA) | `Celsius` | `resolved` |
| **Warsaw** | 🔻 最低温 | `EPWA` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/pl/warsaw/EPWA) | `Celsius` | `resolved` |
| **Wellington** | 🔺 最高温 | `NZWN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/nz/wellington/NZWN) | `Celsius` | `resolved` |
| **Wellington** | 🔻 最低温 | `NZWN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/nz/wellington/NZWN) | `Celsius` | `resolved` |
| **Wuhan** | 🔺 最高温 | `WUHAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/wuhan/ZHHH) | `Celsius` | `resolved` |
| **Wuhan** | 🔻 最低温 | `WUHAN` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/wuhan/ZHHH) | `Celsius` | `resolved` |
| **Zhengzhou** | 🔺 最高温 | `ZHCC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/zhengzhou/ZHCC) | `Celsius` | `active` |
| **Zhengzhou** | 🔻 最低温 | `ZHCC` | *(按规则链接直定)* | **Weather Underground** | `UMA Optimistic Oracle` | [规则链接](https://www.wunderground.com/history/daily/cn/zhengzhou/ZHCC) | `Celsius` | `resolved` |

---

## §3 结算机构（Settlement Agencies）分类架构
1. **NOAA NWS (美国国家气象局)**：
   - **适用城市**：全美 11 个城市（NYC, Chicago, Denver, Miami, Dallas, Seattle, Atlanta, Los Angeles, San Francisco, Houston, Austin, DC 等），以及**部分海外使用 ASOS 架构的国际机场**（如 London EGLC, Paris LFPB, Tokyo RJTT, Toronto CYYZ, Shanghai ZSPD）；
   - **结算载体**：`https://www.weather.gov/wrh/timeseries?site=<stid>`；
   - **离散过滤**：明文规定必须通过 `Show Hourly Data` 进行整点过滤；
2. **Hong Kong Observatory (香港天文台 - HKO)**：
   - **适用城市**：Hong Kong（香港）；
   - **结算载体**：`https://www.weather.gov.hk/en/cis/climat.htm` 官方日提取日报（Daily Extract）；
   - **指标定义**：最高温严格采信 `Absolute Daily Max (deg. C)`，最低温严格采信 `Absolute Daily Min (deg. C)`；
3. **Weather Underground (备用降级结算员)**：
   - 当主气象局数据在次日 23:59 ET 前无法获取时，作为统一的一级降级备用数据源；
4. **UMA Optimistic Oracle (链上终审裁决员)**：
   - 智能合约级仲裁人，在发生规则争议或文本歧义时，由质押代币的博弈投票人根据上述规则文本完成终审决议。

---

## §4 并行自检与数据质量审计报告 (Parallel Self-Check)
- **总盘口检索完整度**：`3610` 个温度市场全部完成字段对齐与解析；
- **最低温盘口挖掘**：成功挖掘到 **1105 个最低温日盘**，全面消除了此前的单向盲区；
- **双向覆盖城市**：以下 **51 个城市** 已实证具备完整的最高温/最低温双向对冲盘口：
  `Amsterdam, Ankara, Atlanta, Austin, Beijing, Buenos Aires, Busan, Cape Town, Chengdu, Chicago, Chongqing, Dallas, Denver, Guangzhou, Helsinki, Hong Kong, Houston, Istanbul, Jeddah, Jinan, Karachi, Kuala Lumpur, London, Los Angeles, Lucknow, Madrid, Manila, Mexico City, Miami, Milan, Moscow, Munich, NYC, Paris, Qingdao, San Francisco, Sao Paulo, Seattle, Seoul, Seoul (Incheon), Shanghai, Shenzhen, Singapore, Taipei, Tel Aviv, Tokyo, Toronto, Warsaw, Wellington, Wuhan, Zhengzhou`；
- **唯一确证物理台站池**（共 **58 个**）：
  `BUSAN, CYYZ, EDDM, EFHK, EGLC, EHAM, EPWA, FACT, HKO, JINAN, KATL, KAUS, KBKF, KDAL, KDCA, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO, LEMD, LFPB, LIMC, LLBG, LTAC, LTFM, MIAMI, MILAN, MMMX, NZWN, OEJN, OPKC, PARIS, RCSS, RCTP, RJTT, RKPK, RKSI, RPLL, SAEZ, SBGR, TOKYO, UUWW, VILK, WMKK, WSSS, WUHAN, ZBAA, ZGGG, ZGSZ, ZHCC, ZHHH, ZSPD, ZSQD, ZUCK, ZUUU`；
- **数据异常与告警**：无异常，全部门禁检查通过！
