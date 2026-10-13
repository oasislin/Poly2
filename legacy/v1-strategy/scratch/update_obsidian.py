import subprocess
import os

vault_name = "My Vault"

def append_via_obsidian_cli(file_path, content):
    print(f"Appending content to: {file_path}")
    # 构造 obsidian cli 命令并通过 subprocess 运行，防止 shell 转义引发的解析问题
    cmd = [
        "obsidian",
        f"vault={vault_name}",
        "append",
        f"path={file_path}",
        f"content={content}"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Successfully updated: {file_path}")
    else:
        print(f"Failed to update {file_path}: {result.stderr}")

# 1. 投注算法.md 追加内容
betting_algorithm_path = "项目/Polymarket 天气套利自动化交易系统/投注算法.md"
betting_algorithm_content = """

### 10.4 回测数据归档与算法版本打标 (Backtest Archive Spec)
为了支持未来高保真的策略回测与算法迭代，系统定义了 `backtest_archive` 数据契约。该契约采用客观物理数据与主观计算结果分离的设计，并在元数据中强制注入算法版本与超参数标签：
- **客观物理数据 (`raw_data`)**：归档 15 分钟级的实时订单簿深度（`clob_books`）以及原始天气预报 JSON 响应（`raw_forecast`）。物理数据长期有效，可被任何未来版本的算法重复载入进行回放。
- **算法估算结果 (`calculated_results`)**：记录基于当前版本算法推导出的胜率分布，便于与未来新算法进行横向期望对比。
- **算法标签 (`algorithm_metadata`)**：强制标记算法名字（`algorithm_name`）、版本号（`algorithm_version`）和当时的运行超参数，确保当算法迭代升级后，旧数据能够根据此版本标签平顺替换或通过匹配逻辑做平滑过渡。"""

# 2. Backtest Loader 实施方案.md 追加内容
backtest_loader_path = "项目/Polymarket 天气套利自动化交易系统/Polymarket 天气套利历史数据加载器 (Backtest Loader) 实施方案.md"
backtest_loader_content = """

### 3. 数据归档与算法版本标签定义
在未来的高频数据回测中，我们将直接以 15 分钟为周期将原始数据保存为 `backtest_archive` 格式。为了方便未来迭代算法后能平顺地替换或读取旧数据，我们在归档中集成了**算法版本打标（Algorithm Version Tag）**机制：
1. **元数据标签**：每个归档数据行包含一个 `algorithm_metadata` 字典，里面必须包含 `algorithm_name` 和 `algorithm_version` 字段（例如 `v3.1`）。
2. **数据隔离结构**：
   - 将不变的物理数据（当时的 `clob_books` 订单簿深度与 Open-Meteo 天气预报 `raw_forecast` 原始 JSON 串）保存在 `raw_data` 中，支持被未来任意版本的新算法反复重加载运行。
   - 将当前算法生成的概率放在 `calculated_results` 中。在未来更新算法重新回测时，回测引擎可根据 `algorithm_version` 标志来决定是使用当前行中计算好的旧胜率，还是调用新版本算法基于 `raw_data` 重新估算胜率，实现了极佳的版本兼容与平顺替换能力。"""

# 3. 架构设计与工程规范文档.md 追加内容
architecture_path = "项目/Polymarket 天气套利自动化交易系统/Polymarket 天气套利自动化交易系统 — 架构设计与工程规范文档.md"
architecture_content = """

### 2.4 回测数据归档契约 (backtest_archive)
为了支持未来进行连续 15 分钟高保真回测，系统定义了归档数据契约规范。该契约要求每次持久化归档时，必须携带算法版本标签，以便在未来算法升级时能够平顺替换和过渡：
- **契约核心键**：
  - `protocol_version`: 协议版本
  - `algorithm_metadata`: 包含 `algorithm_name`、`algorithm_version` 及超参数的算法定义。
  - `raw_data`: 包含 `clob_books` 订单簿与 `raw_forecast` 原始预报响应的物理信息。
  - `calculated_results`: 包含历史估算胜率的记录。
- **配置校验**：该契约在代码中被硬校验保护，确保回测归档数据符合强类型 JSON Schema 约束。"""

# 依次更新三个文档
append_via_obsidian_cli(betting_algorithm_path, betting_algorithm_content)
append_via_obsidian_cli(backtest_loader_path, backtest_loader_content)
append_via_obsidian_cli(architecture_path, architecture_content)
