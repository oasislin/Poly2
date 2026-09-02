# Specification: NWS WRH 精度裁决与边界补测 (Round 5)

## Problem Statement
Round 4 验证了 NWS WRH 服务可用性，但暴露了根本性精度矛盾（R2）：v1.0 报告与 v0.9 报告对公制探针精度描述不一致。若公制为纯整数摄氏度透传，则之前的 $C \to F \to C$ 量化建模纯属脚本注入的“幻影噪声”。此外，探针 1 的留存深度结论存在过度声明，需补充记录数有效性验证及 >365 天边界探顶；报告需补齐限流压测、修正频次单位，并排查 IEM 抓取链路对 2026 年底停运的 MesoWest 的依赖。

## Solution
1. **R2 精度终审**：抽取 10 个代表时刻的公英制原始 JSON 进行逐字节比对。若整数透传确认，彻底删除 `Quantize()` 模拟算子，$\Delta_{res} = T_{NWS} - T_{IEM}$ 直接相减，废除量化噪声表并将 `sigma_quant` 标记为 `deprecated: phantom_model`；
2. **R1 留存补测**：统计回溯深度的返回记录数有效性，探测 400d / 730d 免费层边界；
3. **R3 限流压测**：执行 5 req/s 突发 60 秒压测，记录限流与恢复特征；
4. **R4/R5 修正与排查**：修正频次单位为“时次累计条数”，审计 IEM CN__ASOS 链路对 MesoWest 的依赖关系；
5. **综合交付**：发布《NWS WRH 数据可用性与精度裁决报告（v1.0-final）》。

## User Stories
1. As a data pipeline engineer, I want a definitive byte-level precision audit of metric vs english raw payloads so that phantom quantization noise models can be eliminated.
2. As a quant risk engineer, I want the quantization simulation step removed if NWS directly passes integer Celsius, so that artificial residuals do not distort downstream pricing.
3. As a researcher, I want empirical retention limits tested beyond 365 days with strict record count validation, so that storage and historical lookback bounds are accurately documented.
4. As a systems engineer, I want API rate limiting and burst behaviors stress-tested at 5 req/s, so that scraping retry parameters match upstream tolerances.
5. As a pipeline maintainer, I want the upstream dependency on MesoWest checked before its Dec 31 2026 shutdown, so that ingest continuity is guaranteed.

## Implementation Decisions
- **`PrecisionArbitrator`**: Byte-by-byte comparison of metric and english `air_temp_set_1` arrays, verifying exact numeric literals and producing `docs/reports/nws_wrh_precision_audit_verdict.md`.
- **`DeviationDecomposer` Refactoring**: If integer passthrough confirmed, eliminate `simulate_nws_quantization`, set $\Delta_{quant} = 0$, $\Delta_{res} = T_{NWS} - T_{IEM}$.
- **`RateLimitStressTester`**: Async/threaded burst runner sending 5 req/s for 60s, recording status codes and latency.
- **`RetentionBoundaryProber`**: Requests 400d and 730d depths and validates $N_{returned} \ge 0.8 \times N_{expected}$.
- **`IemUpstreamDependencyAuditor`**: Traces IEM Mesonet CN__ASOS backend data source.

## Testing Decisions
- Offline unit tests with mocked payloads for precision comparison and rate-limit parsing.
- Gated live network tests with `RUN_NETWORK_TESTS=1`.

## Out of Scope
- Downstream statistical modeling for pricing, sigma inflation, or Kelly sizing (strictly frozen).
