# 美股历史数据采集项目

这是一个可复制、无需数据库服务的本地数据项目。它使用 `yfinance` 下载 Yahoo Finance 的日线和 5 分钟 K 线，以 SQLite 作为唯一真实数据源，并可随时导出 CSV。

初始 symbols：`^NDX`、`^GSPC`、`SPY`、`QQQ`、`VOO`、`VTI`。

## 功能

- 新加入的 symbol：下载 `period=max` 的全部日线历史，以及 Yahoo 当前可提供的最近 59 天 5 分钟数据。
- 已有 symbol：日线回看 10 天、5 分钟线回看 3 天，使用主键 UPSERT，既去重又能接收 Yahoo 的近期修订。
- 保存 `Open`、`High`、`Low`、`Close`、`Adj Close`、`Volume`、`Dividends`、`Stock Splits` 和 `Capital Gains`。
- 显式处理 yfinance 的 `(字段, symbol)` 或 `(symbol, 字段)` 多层列索引。
- 一次更新，或常驻进程每 30 分钟更新。
- 按全部/指定 symbol 导出日线和 5 分钟 CSV。
- 用 SQLite 在线备份 API 生成可安全复制的数据库快照。

> Yahoo Finance 数据适合个人研究。请自行遵守 Yahoo 的使用条款；它不是交易所级行情，也不应直接用于实盘下单决策。

## 1. 安装

需要 Python 3.11 或更高版本。

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### Windows（PowerShell）

在项目目录中打开 PowerShell，然后运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

如果 PowerShell 因执行策略拒绝激活脚本，先在**当前 PowerShell 窗口**执行以下命令，再重新运行激活命令：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

如果没有安装 Python Launcher（`py`），将第一条命令改为：

```powershell
python -m venv .venv
```

这里使用了 `yfinance[repair]`，会同时安装日线价格修复所需的 SciPy。项目对长历史日线启用 `repair=True`；如果曾安装过旧版本的本项目，请再次运行上面的安装命令来补齐依赖。5 分钟数据不启用价格重建，因为 yfinance 可能为较早的 5 分钟 K 线继续请求已经超过 Yahoo 保留期的 1/2 分钟数据，并打印误导性的内部失败；这不影响项目保存原始 5 分钟 OHLC 和公司行动。

初始化数据库（其他命令也会自动初始化）：

```bash
stock-data init
```

默认数据库位置为 `data/market_data.sqlite`。

## 2. 下载数据

运行一次：

```bash
stock-data update
```

立即运行一次，之后每 30 分钟运行：

```bash
stock-data run
```

按 `Ctrl+C` 会在当前网络请求完成后安全停止。查看进度和行数：

```bash
stock-data status
```

首次运行需要为 6 个 symbols 回填数据，耗时会明显长于后续增量更新。单个 symbol 或单个周期失败不会阻止其他任务；错误会记录在 `download_state` 并显示在 `status` 中。命令只要有任何下载失败就返回非零退出码。

### 后台常驻

开发和手动运行可直接使用 `stock-data run`。需要登录后自动运行时，建议由操作系统的 `launchd`（macOS）或 `systemd`（Linux）管理进程，而不是使用 `nohup`；进程异常退出后可自动重启。

更新时间可通过环境变量调整：

```bash
export STOCK_UPDATE_MINUTES=30
export STOCK_REQUEST_PAUSE_SECONDS=1
stock-data run
```

Windows PowerShell：

```powershell
$env:STOCK_UPDATE_MINUTES = "30"
$env:STOCK_REQUEST_PAUSE_SECONDS = "1"
stock-data run
```

上述 Windows 环境变量仅对当前 PowerShell 窗口有效；关闭窗口后需要重新设置。

默认只保存正常交易时段。若确实需要 Yahoo 提供的盘前/盘后数据：

```bash
export STOCK_PREPOST=1
stock-data run
```

Windows PowerShell：

```powershell
$env:STOCK_PREPOST = "1"
stock-data run
```

## 3. 管理 symbols

```bash
stock-data symbols list
stock-data symbols add AAPL MSFT NVDA
stock-data symbols disable VOO
stock-data symbols enable VOO
```

`symbols add` 只登记或重新启用 symbol。下一次 `update`/`run` 发现该 symbol 没有日线记录时，会自动使用 `period=max` 下载全部日线，不会错误地只下载最近几天。

shell 会把 `^` 当普通字符，但为了跨 shell 稳妥，可写成：

```bash
stock-data symbols add '^DJI'
```

## 4. 导出 CSV

导出全部数据（生成日线和 5 分钟两个带时间戳的文件）：

```bash
stock-data export
```

只导出日线：

```bash
stock-data export --interval 1d --output-dir /tmp/stock-export
```

只导出 SPY 和 QQQ 的 5 分钟数据：

```bash
stock-data export --interval 5m --symbol SPY --symbol QQQ
```

CSV 使用 UTF-8 BOM，Excel 可直接识别。`timestamp_utc` 在数据库中是 Unix 秒，在 CSV 中转换为带 `+00:00` 的 ISO 8601 UTC 时间；日线还带有不受时区影响的 `trading_date`。

## 5. 搬迁与备份

项目没有绝对路径依赖。停止采集进程后，可直接复制整个目录并继续运行。也可把数据放到外接磁盘：

```bash
export STOCK_DATA_DIR="/Volumes/ExternalSSD/stock-data"
stock-data update
```

运行期间 SQLite 使用 WAL。不要在进程写入时仅复制主 `.sqlite` 文件，因为尚未 checkpoint 的数据可能位于 `-wal` 文件。使用内置备份命令可获得一致快照：

```bash
stock-data backup backups/market_data_$(date +%Y%m%d).sqlite
```

把该备份复制到其他位置后，将其命名为 `market_data.sqlite` 并放入目标数据目录即可继续更新。

## 6. 数据结构

数据库主要有四张表：

| 表 | 用途 | 唯一键 |
|---|---|---|
| `symbols` | symbol 清单与启用状态 | `symbol` |
| `daily_prices` | 日线、复权收盘和公司行动 | `(symbol, trading_date)` |
| `intraday_5m_prices` | 5 分钟数据 | `(symbol, timestamp_utc)` |
| `download_state` | 成功时间、错误和接收行数 | `(symbol, interval)` |

日线使用 `trading_date` 作为业务主键，因为日 K 线代表交易日而不是某个精确时刻；同时保留 `timestamp_utc` 便于与其他数据联接。5 分钟数据以 UTC Unix 时间为主键，能正确跨越美国夏令时。

`auto_adjust=False` 很重要：这会保留原始 OHLC，并单独保存 `Adj Close`。`actions=True` 用于要求 yfinance 返回分红和拆股；某些基金还可能返回 `Capital Gains`。某个数据源未返回的 action 列会补为 `0`，未返回的普通行情列会保存为 `NULL`，不会用 0 伪造价格。

## 7. 5 分钟数据限制

yfinance 官方文档说明盘中数据不能超出最近 60 天。因此本项目首次请求 59 天，避免因时间边界产生整段失败；之后只要持续运行，旧的 5 分钟记录会永久保留在 SQLite 中。若停机超过 60 天，中间更早的缺口无法再从 Yahoo 补回，项目会从当前仍可取得的最早日期继续采集。

Yahoo 偶尔可能限流、返回空数据或修订最新 K 线。本项目通过请求间隔、重叠下载、UPSERT 和错误状态记录降低影响，但不会把“空返回”解释为应删除旧数据。

如果看到 `ModuleNotFoundError: No module named 'scipy'`，说明当前虚拟环境是在项目补充价格修复依赖之前创建的。进入项目并执行：

```bash
source .venv/bin/activate
python -m pip install -e .
stock-data update
```

## 8. 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖两种常见 MultiIndex 排列、字段补全、时间窗口限制和 SQLite UPSERT。测试不访问网络。

## 9. 直接用 Python 运行

如果没有安装 console script，也可在项目根目录运行：

```bash
python -m stock_data init
python -m stock_data update
python -m stock_data export --interval all
```

## 10. 相关文档

- [yfinance download 参数](https://ranaroussi.github.io/yfinance/reference/yfinance.functions.html)：interval、actions、auto_adjust、60 天盘中限制和 multi_level_index。
- [yfinance Multi-Level Column Index](https://ranaroussi.github.io/yfinance/advanced/multi_level_columns.html)：多层列索引说明。
- [SQLite Online Backup API](https://www.sqlite.org/backup.html)：运行期间创建一致数据库快照的原理。
