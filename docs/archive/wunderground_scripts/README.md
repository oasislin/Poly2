# Wunderground 历史爬虫脚本归档说明

**归档日期**：2026-10-13  
**执行工单**：REMEDIATION_PLAN R-18  
**归档性质**：**非生产代码存档，禁止在生产构建或主流程中 import**。  
**说明与处置依据**：
依据 ADR-0007 与 ADR-0012，Wunderground 已彻底解除作为结算源或训练真值源的职责，生产数据管道已全面迁移至 IEM METAR 原报与 NWS WRH 官方时序表。
本目录下的抓取脚本（`wunderground_scraper.py` 等）从 `src/data_acquisition/` 移出至本存档区，标记保留以备未来作为非官方备选数据对比或参考复用，严禁删除。
