# 🌐 NOAA GEFS 批量数据采集与实时监控操作指南 (Data Ingestion & Operations Guide)

> **版本**: v5.9.2 (已对齐 v5.9.2 规格)  
> **更新日期**: 2026-09-02  
> **适用模块**: `src/data_acquisition/`, `scripts/download_gefs_batch.py`, `scripts/dashboard.py`

---

## 1. 系统架构与物理协议 (Protocol & Architecture)

本项目数据采集管道负责从 NOAA AWS S3 开放数据存储库中拉取 2000~2019 年（20 年代际）高精度 GEFSv12 重预报（Reforecast）气象数据，供物理特征库构建与 EMOS 概率模型训练。

### 1.1 核心物理协议约束

| 协议维度 | 物理规范 | 技术依据 |
| :--- | :--- | :--- |
| **起报时次** | 仅存在 **`00Z`** 单一时次 | NOAA AWS 存储规范（06/12/18Z 不存在） |
| **集合成员** | 严格 **5 成员**（`c00` 控制预报 + `p01`~`p04` 扰动成员） | **ADR 0004**（历史重预报仅归档 5 成员） |
| **目标变量** | `tmax_2m`（2米最高温）与 `tmin_2m`（2米最低温） | 离散存储于独立 GRIB2 消息中 |
| **空间分辨率** | **0.25°**（41×41 格点切片） | 上海（25~35°N, 115~125°E）、丹佛（35~45°N, -110~-100°E） |
| **单日切片数** | $5 \text{ 成员} \times 2 \text{ 变量} = \mathbf{10} \text{ 个切片文件}$ | 5 成员并发拉取，每个成员依次拉取 tmax 与 tmin |

---

## 2. 数据流转与目录层级 (Data Flow & Directory Structure)

```
[NOAA AWS S3] ──► (HTTP Range 8KB 流式读入) ──► [GEFSFetcher 抓取引擎]
                                                         │
                                                         ▼
[临时分块缓存] ◄── data/raw/gefs/gefs_reforecast/{init_day}/
       │
       ▼ (10 切片齐备 + 空间裁剪)
[单日净数据集] ◄── data/raw/gefs/cropped/{year}/{station}/{init_day}.nc
       │            └── {init_day}.nc.md5 (双重原子校验锁)
       ▼ (全年 365/366 天全齐)
[正式处理库]   ◄── data/processed/gefs/{year}/{station}/
       │
       ▼ (自动空间释放)
[临时缓存清理] ──► 物理删除临时 .grib2 切片，保持磁盘占用恒定受控
```

### 目录路径对照表

| 目录路径 | 格式与命名 | 作用与生命周期 |
| :--- | :--- | :--- |
| `data/raw/gefs/gefs_reforecast/{init_day}/` | `subset_...__{var}_{init_day}00_{mem}.grib2` | 临时分块切片（单日拉齐并裁剪后自动释放） |
| `data/raw/gefs/cropped/{year}/{station}/` | `{init_day}.nc` + `{init_day}.nc.md5` | 单日裁剪后的 41×41 NetCDF 净数据集 |
| `data/processed/gefs/{year}/{station}/` | `{init_day}.nc` | 全年归档数据集，作为特征工程输入 |
| `data/state/gefs_download_state.json` | JSON 状态机 | 年份级别下载进度状态跟踪 |

---

## 3. 批量下载命令行操作 (CLI Operations)

主入口脚本为 `scripts/download_gefs_batch.py`。

### 3.1 推荐执行命令

```bash
# 1. 生产全量运行（以 2000~2009 年代际为例）
python -u scripts/download_gefs_batch.py \
  --start-year 2000 \
  --end-year 2009 \
  --auto-continue \
  --log-file logs/download_2000_2009.log
```

### 3.2 CLI 参数详解

| 参数名 | 类型 | 默认值 | 作用说明 |
| :--- | :--- | :--- | :--- |
| `--start-year` | `int` | `2000` | 批量下载起始年份（含） |
| `--end-year` | `int` | `2019` | 批量下载结束年份（含） |
| `--auto-continue` | `flag` | `False` | 单年代际下载完成后全自动裁剪入库，无需终端回车确认 |
| `--log-file` | `str` | `None` | 将心跳脉冲与详细日志写入指定文件（大盘将自动挂载解析） |
| `--use-proxy` | `flag` | 配置文件值 | 强制启用本地 HTTP/HTTPS 代理访问 |
| `--no-proxy` | `flag` | 配置文件值 | 强制禁用代理，采用纯直连 AWS S3（推荐，793ms 高吞吐） |

---

## 4. 实时监控大盘 (Web Monitoring Dashboard)

大盘由 `scripts/dashboard.py` 提供，采用轻量级原生 HTTP 服务，无任何重型前端构建依赖，具备请求驱动特性（无浏览器访问时 0 CPU 消耗）。

### 4.1 启动大盘服务

```bash
# 启动大盘（默认监听 8080 端口）
python scripts/dashboard.py --port 8080
```

打开浏览器访问：**`http://localhost:8080`**

### 4.2 大盘核心监控视图

1. **活跃下载工作窗口（5 槽位实时流速）**：
   - 展示当前活跃下载进程（PID 与对应日志）；
   - 呈现 `c00`, `p01`, `p02`, `p03`, `p04` 的 5 槽位单切片进度条；
   - 动态标注当前正在传输的变量（`[tmax]` / `[tmin]`）；
   - 展示过去 30 秒周期的真实物理平均网速（$\Delta\text{Bytes} / 30\text{s}$）。
2. **20 年代际全景热力大盘（2000 ~ 2019）**：
   - 20 个年份网格卡片，实时展示上海（ZSPD）与丹佛（KDEN）两站点的已完成天数与百分比；
   - 自动识别闰年（366天）与 2000 年起报截断（365天），单年完成即亮起翡翠绿灯。
3. **最近数据落盘流水**：
   - 实时列出最新裁剪落盘的 `.nc` 文件、文件体积与落盘时效。
4. **NOAA S3 实时链路诊断**：
   - 每隔 2 秒自动探测 AWS S3 连通性、HTTP 响应状态与 RTT 延迟。

---

## 5. 防御性设计与容灾恢复 (Fault Tolerance & Safety)

### 5.1 随时中断（`Ctrl + C`）安全保证
- 单日数据写入采用 **`.nc` + `.md5` 双重原子锁**；
- 若下载中途强行中断，未完成的单日不会生成 `.md5`；
- 下次启动时，下载器自动秒级跳过已验证合格的历史天数，并对中断的单日自动完全重新拉取，**绝对不会落入残缺数据**。

### 5.2 测速算法与真实流速保证
- 摒弃瞬时脉冲峰值与生命周期摊薄估算，严格采用 **30 秒周期净增量模型**：
  $$\text{网速} = \frac{\text{本周期已下载字节} - \text{上周期已下载字节 (KB)}}{30\text{ 秒}}$$
- 切片下完后速度即刻归零（`0 KB/s`），进入下一变量时自动重置计时器。
