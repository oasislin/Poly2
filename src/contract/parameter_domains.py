"""
Physical Parameter Domains Specification and Governance (Ticket 26 / ADR-0019 Appendix A).
Defines Tier 1 Mathematical Domains (pure statistical/math definitions, executable, fail-closed)
and Tier 2 Effective Domains (parameter tuning schema, F-2 locked, zero hardcoded values).

Decouples numeric definitions completely from downstream pricing, bankroll, and risk algorithms.
"""

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

TIER1_MATH_DOMAIN: str = "TIER1_MATH_DOMAIN"
TIER2_EFFECTIVE_DOMAIN: str = "TIER2_EFFECTIVE_DOMAIN"
IDENTITY_FIELDS: Tuple[str, ...] = ("station", "lead_hours", "variable")
CROSS_FIELD_INVARIANTS: Tuple[str, ...] = ("fstd_lo < fstd_hi",)


@dataclass(frozen=True)
class ParameterDomain:
    """Specification of a physical parameter's mathematical and effective domain."""

    field_name: str
    dtype: str  # "float" | "bool"
    unit: str  # "ratio" | "probability" | "probability_sq" | "count" | "statistic" | "boolean"
    tier1_lower: Optional[float]
    tier1_upper: Optional[float]
    lower_inclusive: bool
    upper_inclusive: bool
    definition_source: str  # Mathematical/statistical rationale and code reference
    consume_status: str  # ADR-0019 §三 controlled vocabulary: 必须消费 / 间接消费 / 不消费
    downstream_anchor: str  # Downstream algorithm consumption point
    lock_state: str  # Lock status string
    degenerate_note: str  # Semantics at degenerate boundaries
    tier2_lower: Optional[float] = None  # F-2 LOCKED
    tier2_upper: Optional[float] = None  # F-2 LOCKED
    tier2_tuning_ticket: str = "Phase 2 Task 08 - Ticket 23 (#156)"


class ParameterDomainError(ValueError):
    """Base exception for parameter domain errors, inheriting from ValueError."""


class ParameterDomainViolation(ParameterDomainError):
    """Raised when a parameter value violates its defined domain, type, or is unknown."""


class CrossFieldInvariantViolation(ParameterDomainError):
    """Raised when cross-field invariants (e.g. CF-1) are violated."""


class F2LockNotReleasedError(ParameterDomainError):
    """Raised when attempting to access a locked Tier 2 effective domain."""


_DOMAINS_MAP: Dict[str, ParameterDomain] = {
    "s_oos": ParameterDomain(
        field_name="s_oos",
        dtype="float",
        unit="ratio",
        tier1_lower=0.0,
        tier1_upper=None,
        lower_inclusive=True,
        upper_inclusive=False,
        definition_source="Var(resid) / mean(sig_eff²) ：分子为方差 ≥ 0，分母为尺度平方均值 > 0，故比值 ≥ 0（parameter_contract.py 字段注释；ADR-0019 §三）",
        consume_status="必须消费",
        downstream_anchor="Q1 软折减 ψ(s_oos) 计算；σ_adj 外展修正 (Ticket 07 / Ticket 11 / Ticket 12)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="s_oos=0 表示残差方差为零（确定性预报/零离散度）",
    ),
    "fstd_lo": ParameterDomain(
        field_name="fstd_lo",
        dtype="float",
        unit="ratio",
        tier1_lower=0.0,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="F.ppf(0.025, neff, n-1) 为正分位数比值（scripts/audit_v2/reliability_v2.py:152）",
        consume_status="必须消费",
        downstream_anchor="构造硬准入阻断极值熔断门槛 s_max^hard (reliability_v2.py:152)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="F 分布 2.5% 分位数比值，严格正",
    ),
    "fstd_hi": ParameterDomain(
        field_name="fstd_hi",
        dtype="float",
        unit="ratio",
        tier1_lower=0.0,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="F.ppf(0.975, neff, n-1) （reliability_v2.py:153）",
        consume_status="必须消费",
        downstream_anchor="构造硬准入阻断极值熔断门槛 s_max^hard (reliability_v2.py:153)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="F 分布 97.5% 分位数比值，严格正",
    ),
    "fstd_in": ParameterDomain(
        field_name="fstd_in",
        dtype="bool",
        unit="boolean",
        tier1_lower=None,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="布尔类型域，由 _parse_strict_bool 强制",
        consume_status="必须消费",
        downstream_anchor="上游 F-test 门禁判定结果 (reliability_v2.py:154)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="指示 s_oos 是否落在 [fstd_lo, fstd_hi] 内",
    ),
    "ece_2f": ParameterDomain(
        field_name="ece_2f",
        dtype="float",
        unit="probability",
        tier1_lower=0.0,
        tier1_upper=1.0,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="期望校准误差 Σ_b w_b·|p̂_b − p_b| ：单项绝对差 ≤ 1，凸组合仍 ≤ 1",
        consume_status="必须消费",
        downstream_anchor="Q1 连续可信度得分 S_conf 的 x_ece 核心输入 (Ticket 10)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="ece_2f=0 表示经验频率与预测概率完全对齐",
    ),
    "v1_coverage_90": ParameterDomain(
        field_name="v1_coverage_90",
        dtype="float",
        unit="probability",
        tier1_lower=0.0,
        tier1_upper=1.0,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="经验覆盖率 = 命中数 / 样本数，比例量",
        consume_status="必须消费",
        downstream_anchor="Q1 连续可信度得分 S_conf 的 x_cov 核心输入 (Ticket 10)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="经验覆盖率（标称分位点理论目标值）",
    ),
    "v1_coverage_90_pass": ParameterDomain(
        field_name="v1_coverage_90_pass",
        dtype="bool",
        unit="boolean",
        tier1_lower=None,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="布尔类型域； 上游 G5 门禁布尔，契约层只搬运不自算 （见 §6）",
        consume_status="必须消费",
        downstream_anchor="G5 门禁合格性核验，若为 False 触发人工复审",
        lock_state="22 格静态表 / 当前全 True",
        degenerate_note="门禁通过状态，契约层只搬运不自算",
    ),
    "pit_mean": ParameterDomain(
        field_name="pit_mean",
        dtype="float",
        unit="probability",
        tier1_lower=0.0,
        tier1_upper=1.0,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="PIT 经概率积分变换取值于 [0,1]，其算术均值必落在同一凸包",
        consume_status="必须消费",
        downstream_anchor="检查系统偏置，作为偏置漂移报警门禁",
        lock_state="22 格静态表 / 参考容差",
        degenerate_note="理想均匀分布时理论期望为 0.5",
    ),
    "pit_var": ParameterDomain(
        field_name="pit_var",
        dtype="float",
        unit="probability_sq",
        tier1_lower=0.0,
        tier1_upper=0.25,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="Popoviciu 不等式 ：有界支撑 [a,b] 的方差 ≤ (b−a)²/4 ；a=0, b=1 → 上界 0.25",
        consume_status="必须消费",
        downstream_anchor="Q1 连续可信度得分 S_conf 的 x_pit 核心输入 (Ticket 10)",
        lock_state="22 格静态表 / [F-2 LOCKED]",
        degenerate_note="理想均匀分布时理论方差为 1/12 ≈ 0.08333",
    ),
    "reject_uniform": ParameterDomain(
        field_name="reject_uniform",
        dtype="bool",
        unit="boolean",
        tier1_lower=None,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="布尔类型域；上游 CvM 裁决，契约层只搬运",
        consume_status="必须消费",
        downstream_anchor="硬准入安全门禁（若为 True 则直接阻断该格交易）",
        lock_state="22 格静态表 / 当前全 False",
        degenerate_note="CvM 均匀性假设检验拒绝标志",
    ),
    "neff": ParameterDomain(
        field_name="neff",
        dtype="float",
        unit="count",
        tier1_lower=0.0,
        tier1_upper=None,
        lower_inclusive=False,
        upper_inclusive=False,
        definition_source="n·(1−ρ1)/(1+ρ1) ，n > 0 、ρ1 ∈ [0, 0.99] → 严格正（reliability_v2.py:141-145）",
        consume_status="间接消费",
        downstream_anchor="记录抽样有效自由度，计入交易决策审计日志",
        lock_state="22 格静态表 / 只读记录",
        degenerate_note="有效样本量，严格正",
    ),
    "cvm_stat": ParameterDomain(
        field_name="cvm_stat",
        dtype="float",
        unit="statistic",
        tier1_lower=0.0,
        tier1_upper=None,
        lower_inclusive=True,
        upper_inclusive=False,
        definition_source="Cramér–von Mises 统计量为非负平方型泛函",
        consume_status="间接消费",
        downstream_anchor="PIT 形态辅助验证，作为极端异常报警标志",
        lock_state="22 格静态表 / 只读报警",
        degenerate_note="CvM 拟合优度统计量，非负",
    ),
    "cvm_p": ParameterDomain(
        field_name="cvm_p",
        dtype="float",
        unit="probability",
        tier1_lower=0.0,
        tier1_upper=1.0,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="p 值为概率量",
        consume_status="间接消费",
        downstream_anchor="PIT 形态辅助验证，作为极端异常报警标志",
        lock_state="22 格静态表 / 只读报警",
        degenerate_note="CvM 检验 p 值，概率度量",
    ),
    "ece_range": ParameterDomain(
        field_name="ece_range",
        dtype="float",
        unit="probability",
        tier1_lower=0.0,
        tier1_upper=1.0,
        lower_inclusive=True,
        upper_inclusive=True,
        definition_source="全域可靠性 ECE 口径（ADR-0019 §三「全域可靠性」），同 #5 推导",
        consume_status="间接消费",
        downstream_anchor="全域可靠性辅助交叉验证，计入策略决策日志",
        lock_state="22 格静态表 / 只读记录",
        degenerate_note="全域校准误差",
    ),
}

PARAMETER_DOMAINS: Mapping[str, ParameterDomain] = MappingProxyType(_DOMAINS_MAP)


def get_domain(field_name: str) -> ParameterDomain:
    """Retrieve parameter domain specification for given field name."""
    if field_name not in PARAMETER_DOMAINS:
        raise ParameterDomainViolation(f"Unknown parameter field: '{field_name}'")
    return PARAMETER_DOMAINS[field_name]


def _check_tier1_bounds(domain: ParameterDomain, val: float) -> None:
    """Check numeric lower and upper Tier 1 bounds."""
    if domain.tier1_lower is not None:
        if domain.lower_inclusive and val < domain.tier1_lower:
            raise ParameterDomainViolation(
                f"Field '{domain.field_name}' value {val} < lower bound {domain.tier1_lower}"
            )
        if not domain.lower_inclusive and val <= domain.tier1_lower:
            raise ParameterDomainViolation(
                f"Field '{domain.field_name}' value {val} <= strict lower bound {domain.tier1_lower}"
            )
    if domain.tier1_upper is not None:
        if domain.upper_inclusive and val > domain.tier1_upper:
            raise ParameterDomainViolation(
                f"Field '{domain.field_name}' value {val} > upper bound {domain.tier1_upper}"
            )
        if not domain.upper_inclusive and val >= domain.tier1_upper:
            raise ParameterDomainViolation(
                f"Field '{domain.field_name}' value {val} >= strict upper bound {domain.tier1_upper}"
            )


def validate_parameter(field_name: str, value: Any) -> bool:
    """Validate a single parameter against its Tier 1 domain."""
    domain = get_domain(field_name)
    if domain.dtype == "bool":
        if not isinstance(value, bool):
            raise ParameterDomainViolation(
                f"Field '{field_name}' expected bool, got {type(value).__name__} ({value!r})"
            )
        return True

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParameterDomainViolation(
            f"Field '{field_name}' expected finite float, got {type(value).__name__} ({value!r})"
        )
    if math.isnan(value) or math.isinf(value):
        raise ParameterDomainViolation(
            f"Field '{field_name}' must be finite, got {value}"
        )

    _check_tier1_bounds(domain, float(value))
    return True


def validate_cell_parameters(record: Any) -> bool:
    """
    Validate all 14 controlled parameters in a cell record plus CF-1 cross-field invariant.
    Accepts CellCalibrationRecord or dict representation.
    """
    is_dict = isinstance(record, dict)
    for field_name in PARAMETER_DOMAINS:
        if is_dict:
            if field_name not in record:
                raise ParameterDomainViolation(
                    f"Missing required parameter field: '{field_name}'"
                )
            val = record[field_name]
        else:
            if not hasattr(record, field_name):
                raise ParameterDomainViolation(
                    f"Missing required parameter field: '{field_name}'"
                )
            val = getattr(record, field_name)
        validate_parameter(field_name, val)

    fstd_lo = record["fstd_lo"] if is_dict else getattr(record, "fstd_lo")
    fstd_hi = record["fstd_hi"] if is_dict else getattr(record, "fstd_hi")
    if not (fstd_lo < fstd_hi):
        raise CrossFieldInvariantViolation(
            f"CF-1 violation: fstd_lo ({fstd_lo}) must be strictly less than fstd_hi ({fstd_hi})"
        )
    return True


def require_effective_domain(field_name: str) -> ParameterDomain:
    """
    Retrieve Tier 2 effective domain. Fails closed with F2LockNotReleasedError
    if the F-2 lock has not been officially released.
    """
    domain = get_domain(field_name)
    if "LOCKED" in domain.lock_state or (
        domain.tier2_lower is None and domain.tier2_upper is None
    ):
        raise F2LockNotReleasedError(
            f"Field '{field_name}' effective domain is locked ({domain.lock_state}). "
            f"Unlock ticket: {domain.tier2_tuning_ticket}"
        )
    return domain


def describe_domains() -> List[Dict[str, Any]]:
    """Serialize all 14 parameter domains for audit and ADR reconciliation."""
    records: List[Dict[str, Any]] = []
    for field_name, d in PARAMETER_DOMAINS.items():
        records.append(
            {
                "field_name": d.field_name,
                "dtype": d.dtype,
                "unit": d.unit,
                "tier1_lower": d.tier1_lower,
                "tier1_upper": d.tier1_upper,
                "lower_inclusive": d.lower_inclusive,
                "upper_inclusive": d.upper_inclusive,
                "definition_source": d.definition_source,
                "consume_status": d.consume_status,
                "downstream_anchor": d.downstream_anchor,
                "lock_state": d.lock_state,
                "degenerate_note": d.degenerate_note,
                "tier2_lower": d.tier2_lower,
                "tier2_upper": d.tier2_upper,
                "tier2_tuning_ticket": d.tier2_tuning_ticket,
            }
        )
    return records
