import subprocess

vault_name = "My Vault"

files = [
    "项目/Polymarket 天气套利自动化交易系统/投注算法.md",
    "项目/Polymarket 天气套利自动化交易系统/Polymarket 天气套利历史数据加载器 (Backtest Loader) 实施方案.md",
    "项目/Polymarket 天气套利自动化交易系统/Polymarket 天气套利自动化交易系统 — 架构设计与工程规范文档.md"
]

for f in files:
    print(f"--- File: {f} ---")
    cmd = ["obsidian", f"vault={vault_name}", "read", f"path={f}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # 仅打印前 15 行以查看 Frontmatter
        lines = result.stdout.split("\n")
        print("\n".join(lines[:15]))
    else:
        print("Failed to read")
