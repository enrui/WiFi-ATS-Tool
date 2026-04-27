# WiFi Router Automated Test Framework

自動化 WiFi router 測試框架，支援 Serial + SSH 雙通道控制、Banana Pi BPI-R4 作為 WiFi 7 STA client，以及 Claude AI 做 log 分析。

> 作者：EJ Chang (張恩瑞)
> 產出版本：Phase 1 Bootstrap Kit
> Test PC 支援：**Ubuntu/Debian Linux**

---

## 這份專案是什麼？

一個**可以直接跑起來的**自動化測試骨架 —— 不是空殼。你拿到設備、按照 `SETUP.md` 做 15–30 分鐘的實體接線，剩下的軟體環境、測試案例、log 分析都由腳本自動處理。

## 專案結構

```
wifi_autotest/
├── README.md                    ← 你在讀的這個
├── SETUP.md                     ← 實體接線與前置步驟手冊
├── config.yaml.example          ← 設定檔範本（複製成 config.yaml 使用）
├── pytest.ini                   ← pytest 設定
├── .gitignore
│
├── bootstrap_testpc.sh          ← Test PC 一鍵安裝（Ubuntu/Debian）
├── bootstrap_bpi.sh             ← BPI-R4 一鍵配置
├── run_all.sh                   ← End-to-end pipeline（最常用）
├── stability_test.py            ← 長時間穩定度 soak test（連線 + 流量 + DUT 監控）
├── run_stability.sh             ← stability test 啟動器
├── collect_logs.py              ← 從設備抓 log
├── analyze_logs.py              ← 呼叫 Claude 分析 log
├── generate_report.py           ← 從 run dir 產生單頁 HTML 摘要報告
├── conftest.py                  ← pytest 共用 fixture
│
├── lib/
│   ├── devices.py               ← SSH / Serial 連線類別
│   └── logtools.py              ← Log redact + filter
│
├── tests/
│   ├── test_smoke.py            ← 連通性 smoke（必跑）
│   ├── test_association.py      ← WiFi 關聯 + DHCP
│   ├── test_throughput.py       ← iperf3 TCP/UDP 效能
│   ├── test_legacy_compat.py    ← 舊設備模式相容性（b/g/n/ac）
│   └── test_z_channel_sweep.py  ← 全頻道掃描效能一致性（最後執行，避免 MT7996 driver 狀態污染）
│
├── prompts/
│   └── wifi_triage.md           ← Claude 分析用 prompt
│
├── scripts/
│   ├── bpi_connect.sh           ← BPI 上的 WiFi 連線輔助
│   └── bpi_iperf_server.sh      ← BPI 上的 iperf3 server
│
└── runs/                        ← 每次測試結果（自動產生）
    ├── YYYYMMDD-HHMMSS/         ← run_all.sh 產生
    │   ├── pytest_report.html
    │   ├── pytest_stdout.log
    │   ├── dut_serial.log
    │   ├── dut_dmesg.log
    │   ├── bpi_*.log
    │   ├── iperf_*.json
    │   ├── claude_report.json   ← AI 分析結果
    │   └── claude_report.md
    └── stability-YYYYMMDD-HHMMSS/  ← run_stability.sh 產生
        ├── stability.log            ← 每次檢查的詳細 log
        ├── stability_data.json      ← 結構化時序資料（可進 DB）
        └── stability_report.md      ← 人類可讀的最終報告
```

## Quickstart（給工程師）

### 1. 實體接線（參照 `SETUP.md`）

- 接 Serial（USB-Serial adapter → DUT UART）
- 接網路（Test PC、DUT、BPI 都接到 mgmt switch）
- 設固定 IP：Test PC `192.168.99.10`，DUT `192.168.99.1`，BPI `192.168.99.100`
  - netplan 或 NetworkManager 設定靜態 IP
- `ping` 三台都通、SSH 都進得去

### 2. 設定

```bash
cp config.yaml.example config.yaml
nano config.yaml     # 填入 IP、帳號密碼、SSID、PSK...
export ANTHROPIC_API_KEY="sk-ant-..."   # 給 Claude 分析用
```

### 3. Bootstrap

```bash
bash bootstrap_testpc.sh      # 安裝 Python、pytest、iperf3、Claude Code CLI（需 sudo）
source .venv/bin/activate
bash bootstrap_bpi.sh         # 透過 SSH 設定 BPI-R4
```

### 4. 跑第一次測試

```bash
# 只跑 smoke test（連通性驗證，不需要 RF）
bash run_all.sh

# 包含 RF 測試（association + throughput）
bash run_all.sh rf

# 跑 RF 但不呼叫 Claude（省 API 成本）
bash run_all.sh rf --skip-ai
```

結果會進 `runs/<timestamp>/`，包含：
- `pytest_report.html` —— 開瀏覽器看測試結果
- `claude_report.md` —— AI 的根因分析
- 所有原始 log（備查）

---

## 穩定度測試（Stability Soak Test）

長時間（預設 **2 小時**）連續監控 WiFi 連線品質與 DUT 健康狀態。適合在功能測試全通過後、出貨前或固件更新後跑。

### 執行方式

```bash
# 預設：5G、2小時、每 60 秒檢查一次
bash run_stability.sh

# 指定頻段與時長
bash run_stability.sh --band 2G
bash run_stability.sh --band 5G --duration 3600   # 1 小時
bash run_stability.sh --band 6G --duration 14400  # 4 小時

# 加快 debug 節奏（縮短 interval）
bash run_stability.sh --duration 600 --interval 30
```

### 每個 interval 做什麼

1. **WiFi 連線確認**：BPI ping DUT（3 次），失敗則記錄 drop
2. **iperf3 雙向流量**：25 秒 TCP DL + 25 秒 TCP UL，記錄吞吐量
3. **DUT 健康監控**：
   - `uptime` — load average
   - `/proc/meminfo` — 可用記憶體
   - `top -bn1` — CPU 前幾名 process
   - `logread -l 50` — 最新系統 log
   - `dmesg | tail -20` — kernel ring buffer

### 異常偵測關鍵字

測試結束時自動掃描 DUT console log 是否出現：
`panic` · `kernel bug` · `oops` · `segfault` · `oom-kill` · `out of memory` · `watchdog` · `hung task` · `call trace` · `hard lockup` · `soft lockup` · `rcu stall`

### 輸出結果

結果存到 `runs/stability-<timestamp>/`：

| 檔案 | 說明 |
|------|------|
| `stability.log` | 每次 interval 的詳細執行 log |
| `stability_data.json` | 結構化時序資料（throughput、loadavg、drops per check） |
| `stability_report.md` | 人類可讀的最終摘要報告 |

### 判定標準

| 狀態 | 條件 |
|------|------|
| **PASS** | 零 drop、零 iperf 失敗、零異常關鍵字 |
| **FAIL** | 任一 WiFi drop、iperf 失敗、或 DUT log 出現異常關鍵字 |

> 本次 testbed 驗證結果（5G / BPI-R4 MT7996 + QCA WiFi 7 DUT）：
> 2 小時 121 次檢查，TCP DL/UL 平均皆 **~941 Mbps**，零 drop，零異常。

---

## Test Coverage

> **維護規則**：每次新增或移除 test case，**必須同步更新這張表**。

### Smoke Tests — `tests/test_smoke.py`
不需要 RF，驗證三節點連通性。執行：`bash run_all.sh`

| Test | 說明 |
|------|------|
| `test_dut_ssh_alive` | SSH 連 DUT，執行 `uptime` 確認回應 |
| `test_bpi_ssh_alive` | SSH 連 BPI-R4，執行 `uptime` 確認回應 |
| `test_dut_serial_alive` | Serial console 讀得到 DUT prompt |
| `test_dut_ping_from_bpi` | BPI-R4 能 ping 到 DUT（Ethernet 路徑） |

### RF Tests — `tests/test_association.py`
需要 WiFi 連線。執行：`bash run_all.sh rf`

| Test | 說明 |
|------|------|
| `test_bpi_associates_to_dut[2G]` | BPI 連 2.4G SSID，取得 IP，ping DUT over RF |
| `test_bpi_associates_to_dut[5G]` | BPI 連 5G SSID，取得 IP，ping DUT over RF |
| `test_bpi_associates_to_dut[6G]` | BPI 連 6G SSID（WPA3/SAE），取得 IP，ping DUT over RF |
| `test_deassociation_cleanup` | 確認所有 WiFi 介面離線並還原至 br-lan |

### RF Tests — `tests/test_throughput.py`
需要 WiFi 連線 + DUT 上的 iperf3 server。執行：`bash run_all.sh rf`

| Test | 方向 | 協定 | 最低門檻 |
|------|------|------|---------|
| `TestThroughput2G::test_tcp_downlink` | DL | TCP | 30 Mbps |
| `TestThroughput2G::test_tcp_uplink`   | UL | TCP | 30 Mbps |
| `TestThroughput2G::test_udp_downlink` | DL | UDP | 30 Mbps |
| `TestThroughput5G::test_tcp_downlink` | DL | TCP | 120 Mbps |
| `TestThroughput5G::test_tcp_uplink`   | UL | TCP | 120 Mbps |
| `TestThroughput5G::test_udp_downlink` | DL | UDP | 100 Mbps |
| `TestThroughput6G::test_tcp_downlink` | DL | TCP | 300 Mbps |
| `TestThroughput6G::test_tcp_uplink`   | UL | TCP | 300 Mbps |
| `TestThroughput6G::test_udp_downlink` | DL | UDP | 200 Mbps |

### RF Tests — `tests/test_legacy_compat.py`
模擬舊款設備（b/g/n/ac）連上 WiFi 7 AP，只驗證能連線。執行：`bash run_all.sh rf`

| Test | 模擬模式 | 頻段 |
|------|---------|------|
| `TestLegacyCompat2G::test_80211bg` | 802.11b/g（disable HT） | 2.4G |
| `TestLegacyCompat2G::test_80211n`  | 802.11n（disable VHT/HE） | 2.4G |
| `TestLegacyCompat2G::test_80211ax` | 802.11ax（預設） | 2.4G |
| `TestLegacyCompat5G::test_80211an` | 802.11a/n（disable VHT/HE） | 5G |
| `TestLegacyCompat5G::test_80211ac` | 802.11ac（disable HE） | 5G |
| `TestLegacyCompat5G::test_80211ax` | 802.11ax（預設） | 5G |
| `TestLegacyCompat6G::test_80211ax` | 802.11ax（6G 唯一支援模式） | 6G |

### RF Tests — `tests/test_z_channel_sweep.py`
每個頻道改 DUT channel 設定、重連、跑 TCP DL 效能，確認各頻道表現一致。執行：`bash run_all.sh rf`
> DUT channel 會在測試過程中變更，結束後自動還原。
> 檔名刻意加 `z_` 前綴讓 pytest 最後才執行，避免 MT7996 driver 狀態損壞影響其他 6G 測試。詳見 [`Note.md`](Note.md) #5。

| Test | 頻段 | 頻道 | 最低門檻 |
|------|------|------|---------|
| `TestChannelSweep2G::test_ch{1,6,11}` | 2.4G | 1, 6, 11 (HT20) | 20 Mbps |
| `TestChannelSweep2G::test_consistency` | 2.4G | — | max/min < 2× |
| `TestChannelSweep5G::test_ch{36,40,44,48}` | 5G | 36, 40, 44, 48 (EHT80, non-DFS) | 100 Mbps |
| `TestChannelSweep5G::test_consistency` | 5G | — | max/min < 2× |
| `TestChannelSweep6G::test_ch{1,5,9,13,17}` | 6G | 1, 5, 9, 13, 17 (EHT80) | 150 Mbps |
| `TestChannelSweep6G::test_consistency` | 6G | — | max/min < 2× |

**總計：39 test cases**（smoke 4 + association 4 + throughput 9 + legacy 7 + channel sweep 15）

門檻值基於此 testbed 實測（BPI-R4 MT7996 4addr/WDS 模式），不代表設備 PHY 上限。
修改門檻請直接改各測試檔的 `THROUGHPUT_MIN` / `SWEEP_CFG`。

---

## 設計原則

### 1. Log 先過濾，再送給 Claude

100 MB 的 kernel log 直接塞給 Claude 不划算。`lib/logtools.py` 做三件事：
- **Redact**：MAC、S/N、API key 替換成占位符（避免機敏資料外流）
- **Filter**：去除重複行、boot banner、random pool noise
- **Truncate**：保留頭 50K + 尾 450K（總計 500KB），最新事件通常最有料

### 2. 結構化 AI 輸出

`prompts/wifi_triage.md` 要求 Claude **只回 JSON**，schema 固定：
```json
{
  "status": "PASS|FAIL|INCONCLUSIVE",
  "root_cause": "...",
  "severity": "critical|high|medium|low|none",
  "confidence": "high|medium|low",
  "category": "boot|association|auth|dhcp|throughput|roaming|memory|kernel_crash|driver|firmware|unknown",
  "evidence": [...],
  "suggested_action": "...",
  "related_components": [...]
}
```

這讓分析結果可以進 DB 做趨勢追蹤，不會是一坨自由散文。

### 3. Serial 永遠在錄

`dut_serial` fixture 是 session-scoped，從 pytest 啟動到結束全程捕捉。
就算測試在中間 crash 或 timeout，serial log 還是完整的 —— 這是 debug kernel panic 唯一可靠的方式。

### 4. Fixture 分層

- **session**：設備連線（SSH/Serial）建一次用到底
- **module**：iperf3 server 起停
- **function**：每個測試的 banner + outcome 記錄

---

## 加新測試案例

1. 在 `tests/` 新增 `test_<topic>.py`
2. 用現成的 fixture：`dut_ssh`、`bpi_ssh`、`dut_serial`、`cfg`、`run_dir`
3. 打 `@pytest.mark.rf` 標記需要 RF link 的測試
4. `run_all.sh` 自動會納入

範例骨架：
```python
def test_my_new_case(dut_ssh, bpi_ssh, cfg):
    # Do something on DUT via SSH
    rc, out, _ = dut_ssh.run("iwinfo", check=True)
    assert "wlan0" in out

    # Do something on BPI
    bpi_ssh.run("ping -c 3 " + cfg.get("dut.host"), check=True)
```

---

## 調整 Claude 行為

改 `prompts/wifi_triage.md`。例如：
- 新增你們公司特有的錯誤碼字典
- 調整 severity 標準
- 加入產品線特定的已知 bug 清單

改 prompt 後不必改任何 Python 程式碼，下次 `run_all.sh` 就生效。

---

## 環境變數

| 變數 | 說明 | 必要性 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Claude API 金鑰 | AI 分析時必要 |
| `WIFI_AUTOTEST_CONFIG` | config.yaml 路徑覆寫 | 可選 |

---

## 已知限制與後續工作

這是 **Phase 1 (PoC / MVP)** 產出，以下是刻意留給 Phase 2+ 的：

- **沒有自動 firmware 燒錄** —— TFTP + bootloader 因產品而異，建議獨立寫
- **沒有 PDU 整合** —— `config.yaml.example` 有註解位置，依你家 PDU API 填
- **沒有 CI 整合** —— Jenkins/GitLab hook 是 Phase 3
- **沒有多 DUT 並行** —— 目前是單 cell 設計，Phase 4 才擴
- **Log 分析用雲端 Claude** —— 若 NDA 嚴格，需評估 on-prem 模型（Llama、Qwen）

---

## Troubleshooting

| 問題 | 處理 |
|------|------|
| `/dev/ttyUSB0` 不見 | `sudo dmesg \| tail`，可能是 driver 沒載入或線沒插好 |
| SSH 跑不動 | 確認 `config.yaml` 的 user/password 正確，手動 `ssh` 測 |
| pytest fixture 啟動失敗 | 八成是 `config.yaml` 沒填，或 ping 不通設備 |
| BPI 關聯不上 | 先手動 `ssh` 進去確認 `iw dev`、`brctl show`，或執行 `bpi_connect.sh <ssid> <psk>` debug |
| 6G 測試全部 ASSOCIATING 卡住 | BPI MT7996 driver 狀態損壞，重啟 BPI 即可。詳見 [`Note.md`](Note.md) #5 |
| 5G 掃描失敗 `Resource busy` | BPI 進入 DFS 靜默模式，`wifi down && wifi up` 或重啟。詳見 [`Note.md`](Note.md) #4 |

遇到更奇怪的硬體或驅動問題，參考 **[`Note.md`](Note.md)** — 記錄了這個 testbed 實際踩過的雷。

---

## License

Released for internal and educational use. Not for external distribution without permission.
