# SESSION.md — Claude Code Handoff

> **這份文件是寫給 Claude Code（agent 模式）讀的**，目的是讓你接手這個專案時可以立刻進入狀況，不用再問一堆背景問題。讀完整份再開始動作。
>
> 如果有跟這份文件抵觸的指示來自 user，以 user 為準，但提醒一下抵觸點。

---

## 1. 專案是什麼

**WiFi Router 自動化測試框架**，目的是讓一個工程師（EJ）可以用 macOS 當 Test Controller，自動化執行對 WiFi router (DUT) 的 regression / smoke / performance 測試，並由 Claude Code（CLI）協助分析 log、產出根因報告。

設計目標是 **Phase 1 PoC**：
- 一個工程師、一台 DUT、一台 BPI-R4 STA、一台 macOS 控制
- 跑通 smoke + association + throughput 三類測試
- 產出 HTML 測試報告 + Claude AI 分析報告

**不是這個專案目標的**：
- 多 DUT 並行（Phase 4）
- CI/CD 整合（Phase 3）
- Firmware 自動燒錄（Phase 2，需配合產品 SDK）
- RF 認證級測試（需 shielded chamber）

---

## 2. 架構速覽

```
┌─────────┐  Serial+SSH  ┌────────────┐  LAN+SSH  ┌──────────┐
│   DUT   │◀────────────▶│ macOS Test │◀─────────▶│ BPI-R4   │
│ (Router)│              │ Controller │           │ (WiFi 7  │
└─────────┘              │  + Claude  │           │  STA)    │
     ▲                   └────────────┘           └────┬─────┘
     │                                                  │
     └──────────────── RF (WiFi OTA) ──────────────────┘
```

**三節點都接到同一個 mgmt switch**，固定 IP：
- DUT: `192.168.99.1`
- macOS Test PC: `192.168.99.10`
- BPI-R4: `192.168.99.100`

---

## 3. 專案結構與檔案職責

```
wifi_autotest/
├── README.md                ← 用戶 quickstart
├── conftest.py              ← pytest 共用 fixtures（session-scoped，必須在根目錄）
├── pytest.ini               ← pytest 設定 + markers（必須在根目錄）
│
├── bootstrap_testpc.sh      ← 自動偵測 macOS/Linux 安裝
├── bootstrap_bpi.sh         ← SSH 進 BPI 安裝工具
├── run_all.sh               ← End-to-end pipeline
├── run_stability.sh         ← 長時間穩定度 soak test 啟動器
│
├── docs/
│   ├── SETUP.md             ← 實體接線手冊
│   └── Note.md              ← 踩過的雷與注意事項
│
├── config/
│   └── config.yaml.example  ← 範本（入 git）
│   (config.yaml 由使用者自行複製填值，不入 git)
│
├── .claude/
│   └── SESSION.md           ← 你正在讀的這個（給 Claude Code）
│
├── lib/
│   ├── devices.py           ← SSHDevice, SerialConsole, Config 類別
│   └── logtools.py          ← Log redact + filter + truncate
│
├── tools/
│   ├── collect_logs.py      ← 從 DUT/BPI 抓 log
│   ├── analyze_logs.py      ← 測試失敗時 SSH 進 DUT/BPI 收集即時診斷資料
│   ├── generate_report.py   ← 從 run dir 產生單頁 HTML 摘要報告
│   └── stability_runner.py  ← 穩定度 soak test 主邏輯
│
├── tests/
│   ├── test_smoke.py           ← 連通性測試（必跑）
│   ├── test_association.py     ← WiFi 關聯（marker: rf）
│   ├── test_legacy_compat.py   ← 舊設備模式相容（b/g/n/ac）（marker: rf）
│   ├── test_throughput.py      ← iperf3 效能（marker: rf）
│   └── test_z_channel_sweep.py ← 全頻道效能掃描（最後跑，見 9.7）（marker: rf）
│
├── prompts/
│   └── wifi_triage.md       ← Claude 分析的 system prompt
│
├── scripts/
│   ├── macos_network_setup.sh  ← 互動式設 IP（macOS 專用）
│   ├── bpi_connect.sh          ← BPI 上跑的 wpa_supplicant 輔助
│   └── bpi_iperf_server.sh     ← BPI 上的 iperf3 server
│
└── runs/                    ← 每次執行結果（gitignore）
```

---

## 4. 關鍵設計決策（不要違反）

### 6.1 AI 分析架構（不呼叫外部 API）
測試失敗後的 AI 分析流程：
1. `analyze_logs.py` → SSH 進 DUT/BPI 執行診斷指令，寫 `live_diagnostics.json`
2. `run_all.sh` → 呼叫 `claude --print "..."` 請 Claude Code CLI 讀取 run dir 的檔案做分析
3. Claude Code 直接寫 `claude_report.md`
4. `generate_report.py` 把 `claude_report.md` 渲染進 `summary_report.html`

**不需要 ANTHROPIC_API_KEY**，分析用的是 Claude Code 已登入的 session。
**--skip-ai** 旗標可跳過步驟 2-3，只收集診斷資料。

### 6.2 Fixture 是 session-scoped
`conftest.py` 裡的 `dut_ssh`、`bpi_ssh`、`dut_serial` **故意設計成整個 pytest session 共用一個連線**。原因：
- SSH/Serial 反覆開關很慢
- Serial console 必須全程錄影才抓得到 kernel panic

如果你加新測試，**用現成 fixture**，不要自己 new 連線。

### 6.3 Claude Code 分析輸出格式
`claude --print` 產生的分析是 Markdown 自由格式，直接存成 `claude_report.md`。`generate_report.py` 有內建 Markdown-to-HTML 轉換器把它渲染進 `summary_report.html`。

`prompts/wifi_triage.md` 目前已不使用（原本是給 Anthropic API 用的 JSON schema prompt），未來可改成給 Claude Code 看的分析指引。

### 6.4 BPI-R4 的角色
**BPI-R4 是 STA client，不是 Test Controller。** 不要把測試邏輯寫到 BPI 上跑。BPI 上只該有：
- `wpa_supplicant`（連 DUT 的 WiFi）
- `iperf3`（產生流量）
- 兩個小 shell 腳本（`bpi_connect.sh`、`bpi_iperf_server.sh`）

所有判斷邏輯、assertion、log 分析都在 macOS Test PC 上做。

### 6.5 跨平台支援
腳本（特別是 `bootstrap_testpc.sh`）要保持 macOS + Ubuntu/Debian 雙支援。Phase 3 預期會搬到 Linux mini PC，所以不要寫死 macOS-only 的東西到 bootstrap 流程。

但 `scripts/macos_network_setup.sh` 是 macOS 專用沒關係，它本來就是。

---

## 5. 環境前提

當你接手時，**假設 EJ 已經做好以下**（如果沒有，先確認）：

1. ✅ macOS 已跑過 `bash bootstrap_testpc.sh`
2. ✅ `.venv` 已建立，套件已裝
3. ✅ `config.yaml` 已從 example 複製並填好
4. ✅ `claude` CLI 已安裝（`which claude` 有輸出）
5. ✅ 三台設備都接好線、能 ping 通、SSH 進得去
6. ✅ Serial 線插好，`/dev/tty.usbserial-XXXX` 看得到

如果上述任一條沒做，**先停下來請 EJ 確認**，不要硬跑下去產生一堆無意義的錯誤。

```bash
# 一鍵環境檢查
source .venv/bin/activate
python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print('DUT:', c['dut']['host']); print('BPI:', c['bpi_sta']['host'])"
ping -c 1 -t 2 $(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml'))['dut']['host'])")
ping -c 1 -t 2 $(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml'))['bpi_sta']['host'])")
ls $(python3 -c "import yaml; print(yaml.safe_load(open('config.yaml'))['dut']['serial_port'])")
which claude && echo "claude CLI: OK" || echo "claude CLI: NOT FOUND"
```

---

## 6. 常見任務的處理模式

### 8.0 跑測試的正確方式

| 場景 | 指令 | 說明 |
|------|------|------|
| **正式測試**（有完整紀錄） | `bash run_all.sh rf` | 產生 junit.xml、pytest_report.html、device logs、summary_report.html |
| Debug 單一 test | `.venv/bin/pytest tests/test_foo.py::test_bar -v -s` | 只有 iperf JSON，**沒有** junit.xml / device logs / summary report |
| Smoke only（不需 RF） | `bash run_all.sh` | 同上，完整紀錄 |

⚠️ **直接跑 pytest 不會產生完整 runs 紀錄**，僅適合開發時驗證語法/邏輯。正式回報測試結果一律用 `run_all.sh`。

### 8.1 EJ 說「幫我加個測 X 的 case」

1. 先看 `tests/test_smoke.py` 的 style，照樣寫
2. 用既有 fixture（`dut_ssh`、`bpi_ssh`、`cfg`、`run_dir`）
3. 需要 RF link 的測試打 `@pytest.mark.rf`
4. 需要 30s+ 的打 `@pytest.mark.slow`
5. 會 reboot/reflash DUT 的打 `@pytest.mark.destructive`
6. **先寫測試再跑**，不要先跑後寫
7. 加完後執行 `pytest tests/test_<新檔>.py -v` 驗證
8. ⚠️ **測試通過後必須更新 `README.md` 的 Test Coverage 表格**（新增一列），同時更新「總計：X test cases」的數字

### 8.2 EJ 說「這次測試失敗，幫我看看為什麼」

`run_all.sh` 失敗時已**自動**完成：
1. `analyze_logs.py` SSH 進 DUT/BPI 收集診斷 → `live_diagnostics.json`
2. `claude --print` 分析並寫 `claude_report.md`
3. `summary_report.html` 包含診斷資料 + AI 分析

若需要手動重新分析（e.g. 想補充更多 context 再問）：
1. 直接跟 Claude Code 說「幫我分析 `runs/<run>`」
2. 或手動重跑診斷：`python analyze_logs.py runs/<run>`
3. **不要直接把整個 log 貼進對話**，超大也沒幫助；引用具體行號或 timestamp

### 8.3 EJ 說「Claude 分析得不對」

1. 看 `runs/<run>/claude_report.md`（純文字，直接讀）
2. 若診斷資料不夠 → 手動 SSH 進 DUT 補充：`python analyze_logs.py runs/<run>`
3. 告訴 Claude Code 你認為哪裡分析錯了，讓它重新看一次
4. 若要調整 AI 的分析方向，修改 `run_all.sh` 裡的 `ANALYSIS_PROMPT` 文字

### 8.4 EJ 說「我要部署 framework 到新環境」

1. 確認 OS 是 macOS 或 Ubuntu/Debian（支援範圍）
2. `git clone`（或解壓 tar）後跑 `bootstrap_testpc.sh`
3. 設網路（macOS 用 `scripts/macos_network_setup.sh`）
4. 複製 `config.yaml.example` → `config.yaml`，填值
5. 跑 `bash run_all.sh`（smoke only）驗證

---

## 7. 環境特殊性（2026-04-25 實測紀錄）

這些是在真實硬體上踩過的坑，**下次 Claude Code 接手時不用再重新探索**。

### 9.1 SSH 認證
- **DUT 和 BPI 都是 no-password root** — Dropbear/SSH 接受 "none" auth
- `config.yaml` 不要設 `ssh_password` 或 `ssh_key_path`，讓 `devices.py` 走 `auth_none`
- `paramiko` 標準 API 不支援 none auth，需走低階 `Transport.auth_none()`，見 [lib/devices.py](lib/devices.py) 的 `connect()` else 分支
- None-auth Transport 必須設 `t.set_keepalive(30)`，否則 idle 20s 後 Dropbear 切斷，造成 throughput test EOFError

### 9.2 BPI-R4 WiFi 介面命名（MediaTek MT7996）
| Band | AP 介面 | AP-Client 介面（4addr） |
|------|---------|------------------------|
| 2.4G | `ra0` / `ra1` | `apcli0` |
| 5G | `rai0` / `rai1` | `apclii0` |
| 6G | `rax0` / `rax1` | `apclix0` |

- `config.yaml` 的 `bpi_sta.wifi_iface` 設 `apclii0`（5G 測試用）
- **不是 `wlan0`**（這是 ath9k / mac80211 平台的命名，MediaTek 不同）

### 9.3 BPI-R4 br-lan Bridge 問題
- BPI 所有介面（含 `apclii0`）都橋接在 `br-lan`（192.168.99.100/24）
- 在 `br-lan` 裡跑 `udhcpc -i apclii0` **不會成功**，DUT 的 DHCP OFFER 被 bridge 吸走
- **測試前必須 `brctl delif br-lan apclii0`**，測試後 `brctl addif br-lan apclii0` 還原
- `test_association.py` 已處理此流程，不需手動

### 9.4 `apclii0` 的 4addr (WDS) 模式
- MediaTek driver 強制 `apclii0` 開啟 `4addr: on`，無法用 `iw set 4addr off` 關掉
- DUT 的 5G SSID 已設 `wds='1'`，可以接受 4addr 客戶端，**不是問題**
- 若未來換 DUT，記得確認 DUT 端有開 WDS

### 9.5 Busybox Ping 輸出格式
- 標準 Linux ping：`5 packets transmitted, 5 received`
- Busybox ping（BPI-R4）：`5 packets transmitted, 5 packets received`
- Regex 必須用 `r"(\d+)\s+(?:packets\s+)?received"` 才能兩種都 match
- `test_association.py` 已修正，**不要改回 `(\d+) received`**

### 9.6 BPI-R4 5G DFS Silence Mode（重要）

**症狀**：5G 測試出現 `CTRL-EVENT-SCAN-FAILED ret=-16 (Resource busy)`，wpa_supplicant 無法掃描，association 在 30s 內失敗。

**根因**：DUT 若使用 **DFS 頻道**（ch52–ch144，5G UNII-2/UNII-3）：
1. BPI 連上後再斷線，BPI 的 5G phy（`rai0`，與 `apclii0` 共 phy1）進入 DFS 靜默監測模式
2. 整個 phy1 的 scan 被 lock，dmesg 顯示 `rai0: still in silence mode, can not trigger scan`
3. 唯一解除方式：等待逾時（60–120 秒）或重啟 BPI 的 WiFi 驅動

**解法**（由 EJ 在 DUT 上設定，不在程式碼處理）：
- **DUT 5G 必須使用非 DFS 頻道**：channel 36/40/44/48（UNII-1，80 MHz 可完全非 DFS）
- 目前 testbed 設定：**ch36, EHT80**（記錄在 `config.yaml` 的 `channel_5g`）
- **80 MHz（非 160 MHz）的理由**：ch36 + 160 MHz 後半段會進入 DFS 頻帶，驅動自動縮回 20 MHz

**測試前確認**：若懷疑 BPI 進入 silence mode，在 BPI 上執行 `dmesg | grep silence` 確認，然後重啟 WiFi 驅動：`wifi down && wifi up`（需 ~10s）或 reboot BPI。

### 9.7 MT7996 SAE ExternalAuth 狀態機 Bug（6G channel sweep 後失效）

**症狀**：跑完 `TestChannelSweep6G`（ch1/5/9/13/17 各連一次 + 斷線）後，所有後續 6G 測試（`TestLegacyCompat6G`、`TestThroughput6G`）全部失敗：
```
wpa_state=ASSOCIATING  ← 永遠卡在這裡
[CNTL_IDLE][CNTL_MLME_AUTH_CONF] ERR  ← dmesg 顯示
```
tcpdump 在 DUT 端捕捉到 **零個** BPI 的 auth frame —— BPI 雖顯示在正確頻道（ch33/EHT320），實際上沒有發出任何 SAE Commit。

**根因**：MT7996 driver（7990）的 CNTL state machine 在多次 6G ExternalAuth 連/斷後進入損壞狀態。`ExternalAuthRequest` 發給 wpa_supplicant 後 **7ms** 就收到 `AUTH_CONF` 失敗，遠小於任何 SAE round-trip 時間，代表 wpa_supplicant 根本沒機會送出 auth frame。

**無效的嘗試**（不要浪費時間再試）：
- `killall wpa_supplicant && wifi down && wifi up` → 無效
- DUT `wifi restart` → 無效
- 換 EHT80 / 換頻道（ch37） → 無效
- `rmmod mt7996` → 失敗（built-in 或 dependency lock）
- 新增 managed interface on phy2 → 失敗（driver 不允許）

**唯一有效解法**：重啟 BPI（`reboot`）完整清除 driver 狀態。

**已實施的架構解法**：將 channel sweep 測試檔重命名為 `test_z_channel_sweep.py`，使其在所有其他 RF 測試**之後**執行（pytest 按字母順序收集）。這樣 association / legacy_compat / throughput 都在乾淨的 driver 狀態下跑，channel sweep 的 driver 污染只影響它自己之後（沒有後續測試了）。

**⚠️ 重要**：**不要把 `test_z_channel_sweep.py` 改回 `test_channel_sweep.py`**，也不要加任何字母序比 `t`（throughput）更早的名字。

### 9.8 BPI wpa_supplicant 不支援 `disable_he=1`

**版本**：BPI-R4 上的 wpa_supplicant v2.11-devel（MediaTek 自行 patch）

**症狀**：`_write_wpa_conf_legacy()` 如果在 network block 裡加 `disable_he=1`，wpa_supplicant 直接 log：
```
Line N: unknown network field 'disable_he'
```
並跳過該 network block，永遠不嘗試連線。

**解法**：模擬「沒有 HE/AX 能力的舊設備」不靠 `disable_he`，改用安全性降級：
```python
# 用 WPA2-PSK + ieee80211w=0 模擬舊設備（沒有 MFP，沒有 SAE）
key_mgmt=WPA-PSK
proto=RSN WPA
ieee80211w=0
```
這個方法在 2.4G (b/g/n) 和 5G (a/n/ac) 上有效。6G 因為強制 WPA3/SAE，根本無法模擬「舊設備」，故 `TestLegacyCompat6G` 只有 `test_80211ax` 一個 case。

**已實施**：`LegacyMode` dataclass 使用 `wpa2_only` flag，**沒有** `disable_he` field。不要加。

### 9.9 DUT 介面命名（QCA/Qualcomm WiFi 7，MLO 架構）

這台 DUT 是 **MLO（Multi-Link Operation）** 架構，介面命名跟一般 OpenWrt 不同：

| 用途 | 介面 | Band | 說明 |
|------|------|------|------|
| raw PHY 基底介面 | `wifi0` | 2.4G | UCI 用，不直接收封包 |
| raw PHY 基底介面 | `wifi1` | 5G | UCI 用 |
| raw PHY 基底介面 | `wifi2` | 6G | UCI 用，tcpdump 在這裡抓 |
| MLO 主 SSID | `mld0` / `mld2` / `mld4` | 2G/5G/6G | 真正收發封包 |
| MLO 回程 SSID | `mld1` / `mld3` / `mld5` | 2G/5G/6G | backhaul 用 |

- UCI 改頻道：`uci set wireless.wifi2.channel=37`（用 `wifi0/1/2`）
- 看連線狀態：`iw dev mld4 station dump`（用 `mld4`）
- 抓封包：`tcpdump -i wifi2`（用 raw phy 介面，才能看到所有管理幀）
- `iw dev wlan2` → **No such device** — 這台 DUT 沒有 wlan 介面
- `hostapd_cli` socket 路徑：`/var/run/hostapd-wifi2`（目錄），裡面有 `mld4` / `mld5`

### 9.10 6G channel sweep 後 BPI 掃描快取污染

**背景**：DUT 6G 在 `channel=auto` 時 ACS 可能選到**非 PSC 頻道**（例如 ch33/6115 MHz）。PSC（Preferred Scanning Channels）是 ch5, 21, 37, 53...，ch33 **不是** PSC。

**問題**：channel sweep 在 ch1/5/9/13/17（EHT80）各連一次後，BPI 的 kernel cfg80211 掃描快取裡對同一 BSSID 存了 17 個不同頻率的紀錄（EHT320 的 320 MHz 帶寬讓同一 BSSID 在多個子頻道都可見）。快取裡的 `last_seen` 全部顯示「幾秒前」，wpa_supplicant 無法區分哪個才是真正的 primary channel，MT7996 driver 就從損壞的狀態嘗試 ExternalAuth。

**這個問題在乾淨開機後不存在**（只有 channel sweep 後才發生），且已被 section 9.7 的架構解法（channel sweep 最後跑）覆蓋。如果未來需要在 sweep 後繼續跑其他 6G 測試，唯一可靠的做法是：**重啟 BPI**。

### 9.11 AI 分析不需要 ANTHROPIC_API_KEY
- `run_all.sh` 呼叫的是 `claude --print`（Claude Code CLI），用的是 EJ 已登入的 Claude Code session
- **不需要也不應該用 ANTHROPIC_API_KEY**，那是舊架構的遺留物
- 若 `claude` CLI 不存在（`which claude` 無輸出），安裝方式：`npm install -g @anthropic-ai/claude-code`

---

## 7b. 已知限制 / 已被跳過的東西

這些**刻意**沒做，不是 bug：

| 缺項 | 為什麼 | 何時做 |
|------|--------|--------|
| Firmware 自動燒錄 | 每家 SDK 不同，TFTP/UART 流程因產品而異 | Phase 2，配合具體產品做 |
| PDU 遠端電源控制 | 還沒選 PDU 廠牌 | Phase 3 |
| Multi-DUT 並行 | 框架是單 cell 設計 | Phase 4，需要重構 fixture |
| CI/CD hook | 還沒選 Jenkins / GitLab CI | Phase 3 |
| On-prem LLM | API 成本可接受，且 Claude 品質高 | 有隱私需求時才考慮 |
| RF 隔離環境測試 | 沒有 shielded chamber | 看預算 |
| 中文報告輸出 | Claude 預設英文，prompt 沒指定 | 若 EJ 要再加 |

---

## 8. Claude Code 行為守則

### 10.1 動手前先看
- 改 Python 前 `view` 該檔
- 改測試前 `view conftest.py` 確認 fixture
- 改 prompt 前 `view prompts/wifi_triage.md`

### 10.2 不要自作主張的事
- ❌ 拿掉 redact 邏輯（log 可能含機敏資料）
- ❌ 把測試邏輯搬到 BPI（架構違反）
- ❌ 在 commit message 寫客戶名
- ❌ 沒問就 reboot DUT（destructive）
- ❌ 把真實 log 內容貼到報告或 commit
- ❌ **測試過程中修改 DUT 設定**（channel、bandwidth、security 等）— 會改變被測條件，失去測試意義。發現設定問題時告知 EJ，由 EJ 決定是否修改。例外：明確被授權進行 debug 調整時才可執行。

### 10.3 一定要做的事
- ✅ 改完跑語法檢查（`python3 -m py_compile <file>`、`bash -n <script>`）
- ✅ 加新測試後實際執行驗證
- ✅ **加新 / 移除測試後更新 `README.md` 的 Test Coverage 表格**
- ✅ 改 config schema 同時更新 `config.yaml.example`
- ✅ 機敏動作前確認（reboot、flash、刪檔）
- ✅ **測試有 FAIL 時**：`run_all.sh` 會自動呼叫 `claude --print` 分析；若要補充手動分析，直接讀 `live_diagnostics.json` + `pytest_stdout.log`，不要呼叫外部 API

### 10.4 模糊時的決策
不確定就問使用者，特別是：
- 動到 prompt 內容（影響所有未來分析）
- 改 fixture scope（影響所有測試）
- 加新 dependency（影響 bootstrap）

---

## 9. 常用指令速查

```bash
# 啟動環境
source .venv/bin/activate

# 跑 smoke
bash run_all.sh

# 跑 RF 測試（含 association + throughput）
bash run_all.sh rf

# 跑 RF 但不呼叫 Claude Code 分析（只收集診斷資料）
bash run_all.sh rf --skip-ai

# 單獨跑某個測試
pytest tests/test_smoke.py::TestConnectivity::test_dut_ssh_alive -v

# 手動補收診斷資料（不呼叫 Claude）
python analyze_logs.py runs/latest

# 手動抓 log（不跑測試）
python collect_logs.py --run runs/manual-$(date +%H%M)

# 進 DUT serial console 互動
picocom -b 115200 /dev/tty.usbserial-XXXX
# 離開：Ctrl+A 然後 Ctrl+X
```

---

## 10. 給 Claude Code 的開場白範本

當 EJ 第一次叫你進來時，建議的回應方式：

> 我看過 `SESSION.md` 了，了解這是 Phase 1 PoC、macOS 環境、WiFi router 自動化測試框架。
>
> 目前看下來專案是 **<檢查 git status / runs/ 後的具體狀態>**。
>
> 你想做什麼？常見的有：
> 1. 新增測試案例
> 2. 看某次 run 失敗原因
> 3. 調整 Claude 分析的 prompt
> 4. 加 framework 功能（如新 fixture、log 處理）
> 5. 部署到新環境
>
> 或是其他任務也可以說。

不要直接動手 — 先問清楚再動。

---

## 11. 緊急脫困

如果遇到完全卡住的狀況：

| 情境 | 處理 |
|------|------|
| 設備全部 ping 不通 | 檢查網路線 + IP 設定，跑 `bash scripts/macos_network_setup.sh` 重設 |
| Serial 一直亂碼 | baud 試 57600/38400/9600；換條 USB-Serial 線（先試 FTDI） |
| BPI 沒有 wlan0 | `iw dev` 看實際介面名，改 `config.yaml` 的 `bpi_sta.wifi_iface` |
| pytest 一啟動就 exit | 多半是 `config.yaml` 沒填或設備連不上，看 fixture 錯誤訊息 |
| `claude` CLI 找不到 | `which claude`；若無，執行 `npm install -g @anthropic-ai/claude-code` |
| Claude Code 分析沒產生 `claude_report.md` | 手動跑：`claude --print "分析 runs/<run> 的失敗..."` 並確認 `claude` CLI 已登入 |
| 一切都壞了 | `git stash && git checkout main`，從乾淨狀態重來 |

---

## 12. 文件與外部參考

| 主題 | 來源 |
|------|------|
| 架構規劃簡報 | `WiFi_Router_AutoTest_Architecture.pptx`（不在此 repo） |
| Anthropic API | https://docs.claude.com |
| Claude Code | https://docs.claude.com/en/docs/claude-code |
| BPI-R4 wiki | https://wiki.banana-pi.org/Banana_Pi_BPI-R4 |
| pytest fixtures | https://docs.pytest.org/en/stable/explanation/fixtures.html |
| OpenWrt UCI | https://openwrt.org/docs/guide-user/base-system/uci |

---

## 結尾

這份文件會隨專案演進而過時。如果你發現現況跟這份描述對不上：

1. **先信現況，不要硬套這份文件**
2. 跟 EJ 確認哪邊正確
3. 修正這份文件（你可以直接改）

文件版本：Phase 1 PoC 完成，2026-04-26（35 RF + 4 smoke tests 全綠，含 legacy compat + channel sweep）
下次大幅更新時機：Phase 2 啟動（加入 firmware 燒錄）

### 版本歷程
- 2026-04-25：Phase 1 初版，smoke + association + throughput 全綠（13 RF tests）
- 2026-04-26：新增 legacy compat（7 tests）、channel sweep（15 tests）；修正 MT7996 SAE ExternalAuth bug（section 9.7）；記錄 disable_he 不支援（section 9.8）；補充 DUT MLO 介面命名（section 9.9）
