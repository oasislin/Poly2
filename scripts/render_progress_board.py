#!/usr/bin/env python3
"""Zero-dependency offline progress board generator & validator.

Parses `docs/audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md` directly as the single
authoritative source of truth and produces a deterministic, self-contained
read-only HTML control board (`docs/audit/progress_board.html`).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

ALLOWED_MODULE_STATES = frozenset({"已就绪", "待实现", "待修复", "待改造"})
ALLOWED_TASK_STATES = frozenset(
    {"DONE", "DESIGNING", "PENDING_APPROVAL", "READY", "BLOCKED", "PLANNED"}
)
EXPECTED_MODULE_IDS = tuple(f"M{i}" for i in range(1, 11))
ALGORITHM_PROTECTED_IDS = frozenset({"S3-01", "S3-02", "S3-04", "S3-05"})
SLICE_ORDER = ("切片 1", "切片 2", "切片 3", "切片 4")

_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()\\]|\\.)*(?:\([^()]*\)[^()]*)*)\)")
_TASK_ID_RE = re.compile(r"\bS\d+-\d{2}\b")
_MODULE_ID_RE = re.compile(r"\bM(?:10|[1-9])\b")


class LedgerValidationError(ValueError):
    """Raised when the task ledger breaks schema, anchor, DAG, or guardrail rules."""


def _strip_md(text: str) -> str:
    cleaned = _LINK_RE.sub(r"\1", text.strip())
    cleaned = cleaned.replace("`", "").replace("**", "")
    return cleaned.strip()


def _extract_links(text: str) -> List[Dict[str, str]]:
    return [
        {"label": _strip_md(m.group(1)), "href": m.group(2).strip()}
        for m in _LINK_RE.finditer(text)
    ]


def _split_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def parse_markdown_tables(lines: Sequence[str]) -> List[List[Dict[str, str]]]:
    """Extract all GFM pipe tables inside a section slice."""
    tables: List[List[Dict[str, str]]] = []
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx].strip()
        if line.startswith("|") and idx + 1 < total:
            sep = lines[idx + 1].strip()
            if sep.startswith("|") and set(sep.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
                headers = [_strip_md(h) for h in _split_row(lines[idx])]
                idx += 2
                rows: List[Dict[str, str]] = []
                while idx < total and lines[idx].strip().startswith("|"):
                    cells = _split_row(lines[idx])
                    if len(cells) == len(headers):
                        rows.append(dict(zip(headers, cells)))
                    idx += 1
                tables.append(rows)
                continue
        idx += 1
    return tables


def _split_major_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"_preamble": []}
    current = "_preamble"
    for raw_line in text.splitlines():
        if raw_line.startswith("## §"):
            key = raw_line[3:].strip().split()[0]
            current = key
            sections[current] = []
        else:
            sections[current].append(raw_line)
    return sections


def _validate_dag_acyclic(tasks_by_id: Dict[str, Dict[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(tid: str) -> None:
        if tid in visited:
            return
        if tid in visiting:
            raise LedgerValidationError(f"Cycle detected in task dependencies at {tid}")
        visiting.add(tid)
        for dep in tasks_by_id[tid]["depends_on"]:
            if dep not in tasks_by_id:
                raise LedgerValidationError(
                    f"Task {tid} references unknown dependency '{dep}'"
                )
            dfs(dep)
        visiting.remove(tid)
        visited.add(tid)

    for task_id in tasks_by_id:
        dfs(task_id)


def load_task_ledger(
    ledger_path: Path, *, allow_arch_supplied: bool = False
) -> Dict[str, Any]:
    """Parse and validate `P8-PROJECT-TASKS_全量任务分解台账_v1.0.md`."""
    if not ledger_path.exists():
        raise LedgerValidationError(f"Ledger file not found: {ledger_path}")

    raw_bytes = ledger_path.read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    raw_text = raw_bytes.decode("utf-8")
    sections = _split_major_sections(raw_text)

    if "§1" not in sections or "§2" not in sections:
        raise LedgerValidationError("Ledger missing required '## §1' or '## §2' section")

    steps_match = re.search(r"离实钱步数.*?`(\d+)`", raw_text)
    steps_to_live = int(steps_match.group(1)) if steps_match else None

    # Parse §1 Modules
    mod_tables = parse_markdown_tables(sections["§1"])
    if not mod_tables:
        raise LedgerValidationError("No module summary table found in §1")
    modules: List[Dict[str, Any]] = []
    seen_mods: set[str] = set()
    for row in mod_tables[0]:
        mid = _strip_md(row["模块编号"])
        mstate = _strip_md(row["模块状态"])
        if mid not in EXPECTED_MODULE_IDS:
            raise LedgerValidationError(f"Unexpected module ID '{mid}' in §1")
        if mid in seen_mods:
            raise LedgerValidationError(f"Duplicate module ID '{mid}' in §1")
        if mstate not in ALLOWED_MODULE_STATES:
            raise LedgerValidationError(
                f"Module {mid} has invalid status '{mstate}' (allowed: {sorted(ALLOWED_MODULE_STATES)})"
            )
        seen_mods.add(mid)
        modules.append(
            {
                "id": mid,
                "name": _strip_md(row["模块名称"]),
                "status": mstate,
                "pending_tasks": [
                    t.strip() for t in _strip_md(row["主责待推进单"]).split(",") if t.strip()
                ],
                "summary": _strip_md(row["当前态势与阻塞摘要"]),
                "anchor_label": _strip_md(row["法定文档锚点"]),
                "anchor_links": _extract_links(row["法定文档锚点"]),
            }
        )
    if tuple(seen_mods_sorted := tuple(sorted(seen_mods, key=lambda x: int(x[1:])))) != EXPECTED_MODULE_IDS:
        raise LedgerValidationError(
            f"§1 must contain exact modules M1–M10, got {seen_mods_sorted}"
        )

    # Parse §2 Tasks
    task_tables = parse_markdown_tables(sections["§2"])
    if not task_tables:
        raise LedgerValidationError("No slice task tables found in §2")

    required_cols = {"单号", "切片", "模块归属", "任务名称", "法定文档锚点", "前置依赖", "验收标准", "当前状态"}
    tasks: List[Dict[str, Any]] = []
    tasks_by_id: Dict[str, Dict[str, Any]] = {}

    for table in task_tables:
        if not table:
            continue
        missing_cols = required_cols - set(table[0].keys())
        if missing_cols:
            raise LedgerValidationError(f"Task table missing columns: {sorted(missing_cols)}")

        for row in table:
            tid = _strip_md(row["单号"])
            if not _TASK_ID_RE.fullmatch(tid):
                raise LedgerValidationError(f"Invalid task ID format: '{tid}'")
            if tid in tasks_by_id:
                raise LedgerValidationError(f"Duplicate task ID: '{tid}'")

            slice_name = _strip_md(row["切片"])
            if slice_name not in SLICE_ORDER:
                raise LedgerValidationError(f"Task {tid} has unknown slice '{slice_name}'")

            status = _strip_md(row["当前状态"])
            if status not in ALLOWED_TASK_STATES:
                raise LedgerValidationError(
                    f"Task {tid} has invalid status '{status}' (allowed: {sorted(ALLOWED_TASK_STATES)})"
                )

            mod_raw = _strip_md(row["模块归属"])
            mod_ids = _MODULE_ID_RE.findall(mod_raw)
            if not mod_ids:
                raise LedgerValidationError(f"Task {tid} missing valid module ID in '{mod_raw}'")

            anchor_raw = row["法定文档锚点"]
            anchor_text = _strip_md(anchor_raw)
            deps_text = _strip_md(row["前置依赖"])
            acceptance = _strip_md(row["验收标准"])
            title = _strip_md(row["任务名称"])

            for field_name, val in (
                ("模块归属", mod_raw),
                ("法定文档锚点", anchor_text),
                ("前置依赖", deps_text),
                ("验收标准", acceptance),
            ):
                if not val:
                    raise LedgerValidationError(f"Task {tid} has empty required field '{field_name}'")

            if tid in ALGORITHM_PROTECTED_IDS and not allow_arch_supplied:
                if status == "BLOCKED":
                    if acceptance != "待架构侧供给":
                        raise LedgerValidationError(
                            f"Blocked algorithm task {tid} acceptance must remain '待架构侧供给', got '{acceptance}'"
                        )
                    if "阻塞于架构侧" not in deps_text:
                        raise LedgerValidationError(
                            f"Blocked algorithm task {tid} dependencies must include '阻塞于架构侧'"
                        )
                elif status == "DESIGNING":
                    if acceptance == "待架构侧供给":
                        raise LedgerValidationError(
                            f"Designing algorithm task {tid} must carry supplied acceptance criteria"
                        )

            depends_on = []
            for dep in _TASK_ID_RE.findall(deps_text):
                if dep != tid and dep not in depends_on:
                    depends_on.append(dep)

            item = {
                "id": tid,
                "slice": slice_name,
                "modules": mod_ids,
                "module_label": mod_raw,
                "title": title,
                "anchor_label": anchor_text,
                "anchor_links": _extract_links(anchor_raw),
                "depends_on": depends_on,
                "dependencies_label": deps_text,
                "dependents": [],
                "acceptance": acceptance,
                "status": status,
                "is_algo_protected": tid in ALGORITHM_PROTECTED_IDS,
                "is_arch_pending": acceptance == "待架构侧供给",
                "is_blocked_by_arch": "阻塞于架构侧" in deps_text,
            }
            tasks.append(item)
            tasks_by_id[tid] = item

    _validate_dag_acyclic(tasks_by_id)
    for task in tasks:
        for dep in task["depends_on"]:
            tasks_by_id[dep]["dependents"].append(task["id"])

    # Parse optional §3 Station snapshot table
    stations: List[Dict[str, str]] = []
    if "§3" in sections:
        st_tables = parse_markdown_tables(sections["§3"])
        if st_tables:
            for row in st_tables[0]:
                stations.append({k: _strip_md(v) for k, v in row.items()})

    # Parse optional §4 Mainline review log table (append-only, blank placeholder allowed)
    mainline_reviews: List[Dict[str, str]] = []
    if "§4" in sections:
        rv_tables = parse_markdown_tables(sections["§4"])
        if rv_tables:
            required_rv_cols = {"日期", "当轮优先级排序", "依据"}
            if rv_tables[0] and not required_rv_cols.issubset(rv_tables[0][0].keys()):
                raise LedgerValidationError(
                    f"§4 mainline review table missing columns: {sorted(required_rv_cols - set(rv_tables[0][0].keys()))}"
                )
            for row in rv_tables[0]:
                mainline_reviews.append(
                    {
                        "date": _strip_md(row.get("日期", "")),
                        "priority": _strip_md(row.get("当轮优先级排序", "")),
                        "rationale": _strip_md(row.get("依据", "")),
                    }
                )

    return {
        "ledger_file": ledger_path.name,
        "source_sha256": source_sha256,
        "steps_to_live": steps_to_live,
        "slices": list(SLICE_ORDER),
        "modules": modules,
        "tasks": tasks,
        "stations": stations,
        "mainline_reviews": mainline_reviews,
    }


def render_html(data: Dict[str, Any]) -> str:
    """Render deterministic offline single-file HTML board from parsed ledger data."""
    payload_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    short_sha = html.escape(data["source_sha256"][:12])
    steps = data["steps_to_live"] if data["steps_to_live"] is not None else "—"
    total_tasks = len(data["tasks"])
    done_tasks = sum(1 for t in data["tasks"] if t["status"] == "DONE")
    pct = round((done_tasks / total_tasks) * 100) if total_tasks else 0

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Poly Way2 · 全量工程进度管控看板（只读）</title>
<style>
  :root {{
    --bg: #0f172a;
    --panel: #1e293b;
    --panel-alt: #162032;
    --border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --green: #10b981;
    --green-bg: rgba(16, 185, 129, 0.14);
    --amber: #f59e0b;
    --amber-bg: rgba(245, 158, 11, 0.16);
    --red: #ef4444;
    --red-bg: rgba(239, 68, 68, 0.16);
    --blue: #38bdf8;
    --blue-bg: rgba(56, 189, 248, 0.14);
    --purple: #a78bfa;
    --purple-bg: rgba(167, 139, 250, 0.16);
    --slate: #64748b;
    --slate-bg: rgba(100, 116, 139, 0.16);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.45;
  }}
  .wrap {{ max-width: 1440px; margin: 0 auto; padding: 20px; }}
  header {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 22px;
    margin-bottom: 16px;
  }}
  .head-top {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }}
  h1 {{ margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0.2px; }}
  .readonly-pill {{
    display: inline-block; font-size: 12px; padding: 3px 10px; border-radius: 999px;
    background: var(--blue-bg); color: var(--blue); border: 1px solid rgba(56,189,248,0.35);
    margin-left: 8px; vertical-align: middle;
  }}
  .meta-line {{ font-size: 12px; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin-top: 14px; }}
  .kpi {{ background: var(--panel-alt); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; }}
  .kpi-label {{ font-size: 12px; color: var(--muted); }}
  .kpi-val {{ font-size: 20px; font-weight: 700; margin-top: 2px; }}
  .progress-bar {{ height: 6px; background: #0b1220; border-radius: 99px; overflow: hidden; margin-top: 6px; }}
  .progress-fill {{ height: 100%; background: linear-gradient(90deg, var(--green), var(--blue)); }}

  .controls {{
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between;
    margin-bottom: 16px;
  }}
  .tabs {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .tab-btn {{
    background: var(--panel); color: var(--muted); border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600;
  }}
  .tab-btn.active {{ background: var(--blue-bg); color: var(--blue); border-color: var(--blue); }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  input[type="search"], select {{
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 12px; font-size: 13px;
  }}

  .badge {{
    display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
    border-radius: 999px; border: 1px solid transparent; white-space: nowrap;
  }}
  .st-DONE, .ms-已就绪 {{ background: var(--green-bg); color: var(--green); border-color: rgba(16,185,129,0.35); }}
  .st-DESIGNING {{ background: var(--purple-bg); color: var(--purple); border-color: rgba(167,139,250,0.45); }}
  .st-PENDING_APPROVAL {{ background: var(--amber-bg); color: var(--amber); border-color: rgba(245,158,11,0.45); }}
  .st-READY, .ms-待实现 {{ background: var(--blue-bg); color: var(--blue); border-color: rgba(56,189,248,0.35); }}
  .st-BLOCKED, .ms-待修复 {{ background: var(--red-bg); color: var(--red); border-color: rgba(239,68,68,0.38); }}
  .st-PLANNED {{ background: var(--slate-bg); color: #cbd5e1; border-color: rgba(148,163,184,0.3); }}
  .ms-待改造 {{ background: var(--purple-bg); color: var(--purple); border-color: rgba(167,139,250,0.4); }}
  .tag-arch {{ background: var(--purple-bg); color: var(--purple); border-color: rgba(167,139,250,0.45); }}
  .tag-mod {{ background: #0b1220; color: #cbd5e1; border-color: var(--border); }}

  /* View A: Module Grid */
  .mod-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }}
  .mod-card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px; cursor: pointer; transition: border-color 0.15s ease;
  }}
  .mod-card:hover, .mod-card.selected {{ border-color: var(--blue); }}
  .mod-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
  .mod-id {{ font-weight: 700; font-size: 15px; }}
  .mod-summary {{ font-size: 12px; color: var(--muted); margin: 6px 0 8px; }}

  /* View B: Slice Swimlanes */
  .legend {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }}
  .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: middle; }}
  .lanes {{ display: grid; grid-template-columns: repeat(4, minmax(250px, 1fr)); gap: 12px; overflow-x: auto; }}
  .lane {{ background: var(--panel-alt); border: 1px solid var(--border); border-radius: 10px; padding: 12px; min-height: 360px; }}
  .lane-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); font-weight: 700; font-size: 14px; }}
  .task-card {{
    background: var(--panel); border: 2px solid var(--border); border-radius: 9px;
    padding: 10px 11px; margin-bottom: 9px; cursor: pointer; transition: all 0.12s ease;
  }}
  .task-card:hover {{ border-color: #64748b; }}
  .task-card.hl-selected {{ border-color: #ffffff; box-shadow: 0 0 0 2px rgba(255,255,255,0.2); }}
  .task-card.hl-upstream {{ border-color: var(--amber); background: rgba(245,158,11,0.08); }}
  .task-card.hl-downstream {{ border-color: var(--blue); background: rgba(56,189,248,0.08); }}
  .task-card.hl-dim {{ opacity: 0.36; }}
  .task-top {{ display: flex; justify-content: space-between; align-items: center; gap: 6px; margin-bottom: 5px; }}
  .task-id {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 700; font-size: 12px; }}
  .task-title {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .task-tags {{ display: flex; flex-wrap: wrap; gap: 4px; }}

  /* Detail Drawer */
  .detail-box {{
    margin-top: 16px; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px;
  }}
  .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 10px; }}
  .detail-item {{ background: var(--panel-alt); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 13px; }}
  .detail-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; margin-bottom: 4px; }}

  /* View C: Action Queue */
  .action-section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; }}
  .action-section h2 {{ margin: 0 0 10px; font-size: 15px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }}
  th {{ color: var(--muted); font-weight: 600; font-size: 12px; background: var(--panel-alt); }}
  a {{ color: var(--blue); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .hidden {{ display: none !important; }}
  @media (max-width: 1050px) {{ .lanes {{ grid-template-columns: repeat(2, minmax(240px, 1fr)); }} }}
  @media (max-width: 640px) {{ .lanes {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="head-top">
      <div>
        <h1>Poly Way2 · 全量工程进度管控看板<span class="readonly-pill">OFFLINE · READ-ONLY · ZERO MANUAL STATE</span></h1>
      </div>
      <div class="meta-line">唯一事实源: P8-PROJECT-TASKS v1.0 ｜ 源校验 SHA256: {short_sha}</div>
    </div>
    <div class="kpi-row" id="kpi-row">
      <div class="kpi"><div class="kpi-label">离实钱步数</div><div class="kpi-val">{steps} 步</div></div>
      <div class="kpi">
        <div class="kpi-label">全量任务闭环率</div>
        <div class="kpi-val">{done_tasks} / {total_tasks} ({pct}%)</div>
        <div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>
      </div>
    </div>
  </header>

  <div class="controls">
    <div class="tabs">
      <button class="tab-btn active" data-view="modules">按模块十宫格 (M1–M10)</button>
      <button class="tab-btn" data-view="slices">按切片泳道 × 依赖高亮 (切片 1–4)</button>
      <button class="tab-btn" data-view="actions">阻塞 / 设计中 / 待批清单</button>
    </div>
    <div class="filters">
      <input id="search-input" type="search" placeholder="搜索单号 / 模块 / 关键词..." />
      <select id="status-filter">
        <option value="ALL">全部状态</option>
        <option value="DESIGNING">DESIGNING (设计中)</option>
        <option value="PENDING_APPROVAL">PENDING_APPROVAL (待用户批准)</option>
        <option value="READY">READY (就绪可开)</option>
        <option value="BLOCKED">BLOCKED (受阻)</option>
        <option value="PLANNED">PLANNED (排期中)</option>
        <option value="DONE">DONE (已完成)</option>
      </select>
      <button class="tab-btn" id="clear-hl-btn">清除高亮/过滤</button>
    </div>
  </div>

  <section id="view-modules"></section>
  <section id="view-slices" class="hidden"></section>
  <section id="view-actions" class="hidden"></section>
  <div id="detail-drawer" class="detail-box hidden"></div>
  <section id="mainline-review-section" class="action-section" style="margin-top:16px"></section>
</div>

<script id="board-data" type="application/json">{payload_json}</script>
<script>
(function() {{
  const DATA = JSON.parse(document.getElementById("board-data").textContent);
  const STATUS_TEXT = {{
    DONE: "DONE · 已完成",
    DESIGNING: "DESIGNING · 设计中",
    PENDING_APPROVAL: "PENDING_APPROVAL · 待用户批准",
    READY: "READY · 就绪可开",
    BLOCKED: "BLOCKED · 受阻",
    PLANNED: "PLANNED · 排期中"
  }};

  const taskMap = Object.fromEntries(DATA.tasks.map(t => [t.id, t]));
  let currentView = "modules";
  let selectedTaskId = null;
  let selectedModuleId = null;
  let queryText = "";
  let statusFilter = "ALL";

  function esc(str) {{
    return String(str ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
  }}

  function matchesFilter(task) {{
    if (statusFilter !== "ALL" && task.status !== statusFilter) return false;
    if (selectedModuleId && !task.modules.includes(selectedModuleId)) return false;
    if (queryText) {{
      const hay = (task.id + " " + task.title + " " + task.module_label + " " + task.dependencies_label + " " + task.acceptance).toLowerCase();
      if (!hay.includes(queryText)) return false;
    }}
    return true;
  }}

  function collectTransitive(startId, field) {{
    const result = new Set();
    const stack = [...(taskMap[startId]?.[field] || [])];
    while (stack.length) {{
      const cur = stack.pop();
      if (!result.has(cur) && taskMap[cur]) {{
        result.add(cur);
        for (const nxt of (taskMap[cur][field] || [])) stack.push(nxt);
      }}
    }}
    return result;
  }}

  function renderKpis() {{
    const kpiRow = document.getElementById("kpi-row");
    const pending = DATA.tasks.filter(t => t.status === "PENDING_APPROVAL").length;
    const designing = DATA.tasks.filter(t => t.status === "DESIGNING").length;
    const blocked = DATA.tasks.filter(t => t.status === "BLOCKED").length;
    const ready = DATA.tasks.filter(t => t.status === "READY").length;
    const sliceHtml = DATA.slices.map(s => {{
      const list = DATA.tasks.filter(t => t.slice === s);
      const done = list.filter(t => t.status === "DONE").length;
      return `${{s}} ${{done}}/${{list.length}}`;
    }}).join(" · ");

    kpiRow.innerHTML = kpiRow.children[0].outerHTML + kpiRow.children[1].outerHTML + `
      <div class="kpi"><div class="kpi-label">待用户批准节点</div><div class="kpi-val" style="color:var(--amber)">${{pending}} 项</div></div>
      <div class="kpi"><div class="kpi-label">算法四单（设计中 / 待审核）</div><div class="kpi-val" style="color:var(--purple)">${{designing}} 项</div></div>
      <div class="kpi"><div class="kpi-label">BLOCKED / READY</div><div class="kpi-val">${{blocked}} / ${{ready}}</div></div>
      <div class="kpi"><div class="kpi-label">四切片完成分布</div><div class="kpi-val" style="font-size:13px;margin-top:6px">${{esc(sliceHtml)}}</div></div>
    `;
  }}

  function renderTaskDetail(taskId) {{
    const drawer = document.getElementById("detail-drawer");
    if (!taskId || !taskMap[taskId]) {{
      drawer.classList.add("hidden");
      drawer.innerHTML = "";
      return;
    }}
    const t = taskMap[taskId];
    const upstream = Array.from(collectTransitive(taskId, "depends_on"));
    const downstream = Array.from(collectTransitive(taskId, "dependents"));
    const linksHtml = (t.anchor_links || []).map(l => `<a href="${{esc(l.href)}}">${{esc(l.label)}}</a>`).join(" · ") || esc(t.anchor_label);

    drawer.classList.remove("hidden");
    drawer.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <div>
          <span class="task-id" style="font-size:15px">${{esc(t.id)}}</span>
          <span class="badge st-${{esc(t.status)}}">${{esc(STATUS_TEXT[t.status] || t.status)}}</span>
          ${{t.is_arch_pending ? '<span class="badge tag-arch">待架构侧供给</span>' : ''}}
          <strong style="margin-left:8px;font-size:15px">${{esc(t.title)}}</strong>
        </div>
        <span style="font-size:12px;color:var(--muted)">${{esc(t.slice)}} ｜ 模块: ${{esc(t.module_label)}}</span>
      </div>
      <div class="detail-grid">
        <div class="detail-item"><div class="detail-label">法定文档锚点</div><div>${{linksHtml}}</div></div>
        <div class="detail-item"><div class="detail-label">前置依赖（直接 + 阻塞标签）</div><div>${{esc(t.dependencies_label)}}</div><div style="font-size:11px;color:var(--amber);margin-top:4px">上游传递链路: ${{upstream.length ? upstream.join(" → ") : "无"}}</div></div>
        <div class="detail-item"><div class="detail-label">下游受影响单号</div><div>${{downstream.length ? downstream.join(", ") : "无后继依赖单"}}</div></div>
        <div class="detail-item"><div class="detail-label">验收标准</div><div style="color:${{t.is_arch_pending ? 'var(--purple)' : 'var(--text)'}};font-weight:${{t.is_arch_pending ? '700' : '400'}}">${{esc(t.acceptance)}}</div></div>
      </div>
    `;
  }}

  function renderModules() {{
    const el = document.getElementById("view-modules");
    const cards = DATA.modules.map(m => {{
      const related = DATA.tasks.filter(t => t.modules.includes(m.id));
      const done = related.filter(t => t.status === "DONE").length;
      const pct = related.length ? Math.round((done / related.length) * 100) : 0;
      const selCls = selectedModuleId === m.id ? "selected" : "";
      const taskPills = related.filter(matchesFilter).map(t =>
        `<span class="badge st-${{esc(t.status)}}" data-task="${{esc(t.id)}}" style="cursor:pointer" title="${{esc(t.title)}}">${{esc(t.id)}}</span>`
      ).join(" ");
      return `
        <div class="mod-card ${{selCls}}" data-mod="${{esc(m.id)}}">
          <div class="mod-head">
            <span class="mod-id">${{esc(m.id)}} · ${{esc(m.name)}}</span>
            <span class="badge ms-${{esc(m.status)}}">${{esc(m.status)}}</span>
          </div>
          <div style="font-size:12px;color:var(--muted)">关联任务闭环: ${{done}} / ${{related.length}} (${{pct}}%)</div>
          <div class="progress-bar"><div class="progress-fill" style="width:${{pct}}%"></div></div>
          <div class="mod-summary">${{esc(m.summary)}}</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px">${{taskPills || '<span style="font-size:11px;color:var(--muted)">当前过滤条件下无匹配单</span>'}}</div>
        </div>
      `;
    }}).join("");
    el.innerHTML = `<div class="mod-grid">${{cards}}</div>`;
    el.querySelectorAll("[data-mod]").forEach(card => {{
      card.addEventListener("click", (e) => {{
        const taskBtn = e.target.closest("[data-task]");
        if (taskBtn) {{
          e.stopPropagation();
          selectedTaskId = taskBtn.dataset.task;
          renderTaskDetail(selectedTaskId);
          return;
        }}
        const mid = card.dataset.mod;
        selectedModuleId = selectedModuleId === mid ? null : mid;
        renderAll();
      }});
    }});
  }}

  function renderSlices() {{
    const el = document.getElementById("view-slices");
    const upSet = selectedTaskId ? collectTransitive(selectedTaskId, "depends_on") : new Set();
    const downSet = selectedTaskId ? collectTransitive(selectedTaskId, "dependents") : new Set();

    const lanesHtml = DATA.slices.map(slice => {{
      const list = DATA.tasks.filter(t => t.slice === slice && matchesFilter(t));
      const done = DATA.tasks.filter(t => t.slice === slice && t.status === "DONE").length;
      const total = DATA.tasks.filter(t => t.slice === slice).length;
      const cards = list.map(t => {{
        let hlCls = "";
        if (selectedTaskId) {{
          if (t.id === selectedTaskId) hlCls = "hl-selected";
          else if (upSet.has(t.id)) hlCls = "hl-upstream";
          else if (downSet.has(t.id)) hlCls = "hl-downstream";
          else hlCls = "hl-dim";
        }}
        return `
          <div class="task-card ${{hlCls}}" data-task="${{esc(t.id)}}">
            <div class="task-top">
              <span class="task-id">${{esc(t.id)}}</span>
              <span class="badge st-${{esc(t.status)}}">${{esc(t.status)}}</span>
            </div>
            <div class="task-title">${{esc(t.title)}}</div>
            <div class="task-tags">
              ${{t.modules.map(m => `<span class="badge tag-mod">${{esc(m)}}</span>`).join("")}}
              ${{t.is_arch_pending ? '<span class="badge tag-arch">待架构侧供给</span>' : ''}}
              ${{t.status === "PENDING_APPROVAL" ? '<span class="badge st-PENDING_APPROVAL">待用户批准</span>' : ''}}
            </div>
          </div>
        `;
      }}).join("") || '<div style="font-size:12px;color:var(--muted)">当前过滤条件下无任务</div>';

      return `
        <div class="lane">
          <div class="lane-head"><span>${{esc(slice)}}</span><span style="font-size:12px;color:var(--muted)">${{done}}/${{total}} DONE</span></div>
          ${{cards}}
        </div>
      `;
    }}).join("");

    el.innerHTML = `
      <div class="legend">
        <span>点击任意任务卡片追踪上下游阻塞链：</span>
        <span><span class="legend-dot" style="background:#ffffff"></span>当前选中</span>
        <span><span class="legend-dot" style="background:var(--amber)"></span>上游前置依赖</span>
        <span><span class="legend-dot" style="background:var(--blue)"></span>下游受阻任务</span>
      </div>
      <div class="lanes">${{lanesHtml}}</div>
    `;
    el.querySelectorAll("[data-task]").forEach(card => {{
      card.addEventListener("click", () => {{
        const tid = card.dataset.task;
        selectedTaskId = selectedTaskId === tid ? null : tid;
        renderSlices();
        renderTaskDetail(selectedTaskId);
      }});
    }});
  }}

  function renderTaskTable(list) {{
    if (!list.length) return '<div style="font-size:12px;color:var(--muted)">无匹配项</div>';
    return `<table><thead><tr><th>单号</th><th>切片</th><th>模块</th><th>任务名称</th><th>前置依赖 / 阻塞源</th><th>验收标准</th><th>状态</th></tr></thead><tbody>` +
      list.map(t => `<tr data-task="${{esc(t.id)}}" style="cursor:pointer">
        <td class="task-id">${{esc(t.id)}}</td>
        <td>${{esc(t.slice)}}</td>
        <td>${{esc(t.module_label)}}</td>
        <td>${{esc(t.title)}}</td>
        <td>${{esc(t.dependencies_label)}}</td>
        <td style="color:${{t.is_arch_pending ? 'var(--purple)' : 'var(--text)'}};font-weight:${{t.is_arch_pending ? '700' : '400'}}">${{esc(t.acceptance)}}</td>
        <td><span class="badge st-${{esc(t.status)}}">${{esc(t.status)}}</span></td>
      </tr>`).join("") + `</tbody></table>`;
  }}

  function renderActions() {{
    const el = document.getElementById("view-actions");
    const matched = DATA.tasks.filter(matchesFilter);
    const pendingList = matched.filter(t => t.status === "PENDING_APPROVAL");
    const archList = matched.filter(t => t.is_algo_protected || t.is_arch_pending || t.status === "DESIGNING");
    const readyBlockedList = matched.filter(t => (t.status === "READY" || t.status === "BLOCKED") && !t.is_algo_protected && !t.is_arch_pending);

    const stRows = (DATA.stations || []).map(r => `<tr>
      <td><strong>${{esc(r["站点"])}}</strong></td>
      <td>${{esc(r["城市"])}}</td>
      <td>${{esc(r["2026-11-19T03:15Z 流动性 (USD)"])}}</td>
      <td>${{esc(r["总成交量 (USD)"])}}</td>
      <td>${{esc(r["并发在盘天数"])}}</td>
      <td>${{esc(r["档 B（默认建议）"])}}</td>
      <td>${{esc(r["选站说明"])}}</td>
    </tr>`).join("");

    el.innerHTML = `
      <div class="action-section">
        <h2 style="color:var(--amber)">1. 待用户批准节点（PENDING_APPROVAL）</h2>
        ${{renderTaskTable(pendingList)}}
        ${{stRows ? `<div style="margin-top:12px"><div style="font-size:12px;color:var(--muted);margin-bottom:6px"><strong>S2-01 默认建议站表（档 B · 5 站）与 Active 10 流动性参照：</strong></div><table><thead><tr><th>站点</th><th>城市</th><th>流动性</th><th>成交量</th><th>并发天数</th><th>档 B 默认建议</th><th>说明</th></tr></thead><tbody>${{stRows}}</tbody></table></div>` : ""}}
      </div>
      <div class="action-section">
        <h2 style="color:var(--purple)">2. 算法改造四单（S3-01 / S3-02 / S3-04 / S3-05 · 设计中待审核）</h2>
        ${{renderTaskTable(archList)}}
      </div>
      <div class="action-section">
        <h2 style="color:var(--blue)">3. 工程就绪（READY）与其他受阻项（BLOCKED）</h2>
        ${{renderTaskTable(readyBlockedList)}}
      </div>
    `;
    el.querySelectorAll("[data-task]").forEach(row => {{
      row.addEventListener("click", () => {{
        selectedTaskId = row.dataset.task;
        renderTaskDetail(selectedTaskId);
      }});
    }});
  }}

  function renderMainlineReviews() {{
    const el = document.getElementById("mainline-review-section");
    const list = DATA.mainline_reviews || [];
    const rowsHtml = list.length
      ? list.map((r, idx) => {{
          const isBlank = !r.date && !r.priority && !r.rationale;
          if (isBlank) {{
            return `<tr><td colspan="3" style="color:var(--muted);font-style:italic">第 ${{idx + 1}} 行预留空行 · 待首次主线审视填写</td></tr>`;
          }}
          return `<tr>
            <td style="white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace">${{esc(r.date || "—")}}</td>
            <td>${{esc(r.priority || "—")}}</td>
            <td>${{esc(r.rationale || "—")}}</td>
          </tr>`;
        }}).join("")
      : '<tr><td colspan="3" style="color:var(--muted)">台账 §4 暂无主线审视记录</td></tr>';

    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
        <h2 style="margin:0;font-size:15px">主线审视记录（每计划点一行 · 增补式登记）</h2>
        <span style="font-size:12px;color:var(--muted)">来源: P8-PROJECT-TASKS §4（只追不改）</span>
      </div>
      <table>
        <thead><tr><th style="width:140px">日期</th><th style="width:38%">当轮优先级排序</th><th>依据</th></tr></thead>
        <tbody>${{rowsHtml}}</tbody>
      </table>
    `;
  }}

  function renderAll() {{
    renderKpis();
    document.getElementById("view-modules").classList.toggle("hidden", currentView !== "modules");
    document.getElementById("view-slices").classList.toggle("hidden", currentView !== "slices");
    document.getElementById("view-actions").classList.toggle("hidden", currentView !== "actions");
    if (currentView === "modules") renderModules();
    else if (currentView === "slices") renderSlices();
    else renderActions();
    renderTaskDetail(selectedTaskId);
    renderMainlineReviews();
  }}

  document.querySelectorAll(".tab-btn[data-view]").forEach(btn => {{
    btn.addEventListener("click", () => {{
      document.querySelectorAll(".tab-btn[data-view]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentView = btn.dataset.view;
      renderAll();
    }});
  }});
  document.getElementById("search-input").addEventListener("input", e => {{
    queryText = e.target.value.trim().toLowerCase();
    renderAll();
  }});
  document.getElementById("status-filter").addEventListener("change", e => {{
    statusFilter = e.target.value;
    renderAll();
  }});
  document.getElementById("clear-hl-btn").addEventListener("click", () => {{
    selectedTaskId = null;
    selectedModuleId = null;
    queryText = "";
    statusFilter = "ALL";
    document.getElementById("search-input").value = "";
    document.getElementById("status-filter").value = "ALL";
    renderAll();
  }});

  renderAll();
}})();
</script>
</body>
</html>
"""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or verify deterministic offline project progress board HTML."
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("docs/audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md"),
        help="Path to the authoritative task ledger markdown.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/audit/progress_board.html"),
        help="Output path for the single-file offline HTML board.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate ledger invariants and confirm --output matches freshly rendered HTML.",
    )
    parser.add_argument(
        "--allow-arch-supplied",
        action="store_true",
        help="Allow algorithm-4 tasks to hold supplied acceptance criteria instead of placeholder.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        data = load_task_ledger(
            args.ledger, allow_arch_supplied=args.allow_arch_supplied
        )
    except LedgerValidationError as exc:
        print(f"ERROR: ledger validation failed: {exc}", file=sys.stderr)
        return 1

    rendered = render_html(data)
    if args.check:
        if not args.output.exists():
            print(f"ERROR: board HTML does not exist: {args.output}", file=sys.stderr)
            return 1
        existing = args.output.read_text(encoding="utf-8")
        if existing != rendered:
            print(
                f"ERROR: {args.output} is out of sync with {args.ledger}. "
                f"Run `python3 scripts/render_progress_board.py` to regenerate.",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK: {len(data['modules'])} modules, {len(data['tasks'])} tasks validated; "
            f"{args.output} matches {args.ledger} (sha256={data['source_sha256'][:12]})."
        )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"Rendered {args.output} from {args.ledger} "
        f"({len(data['modules'])} modules, {len(data['tasks'])} tasks, sha256={data['source_sha256'][:12]})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
