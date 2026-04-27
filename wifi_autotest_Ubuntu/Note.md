# Testbed Notes — 踩過的雷與注意事項

> 給人類看的。記錄實際在這套 testbed 上跑測試時遇到的問題，省得下一個人重踩。

---

## 1. BPI-R4 WiFi 介面名稱不是 `wlan0`

MediaTek MT7996 的介面命名跟 ath9k / mac80211 完全不同：

| Band | AP 介面 | STA（AP-Client）介面 |
|------|---------|----------------------|
| 2.4G | `ra0` / `ra1` | `apcli0` |
| 5G   | `rai0` / `rai1` | `apclii0` |
| 6G   | `rax0` / `rax1` | `apclix0` |

`config.yaml` 裡要填對，不然 wpa_supplicant 起不來。確認方式：`iw dev`。

---

## 2. BPI 所有介面都橋接在 `br-lan`，DHCP 前要先拆橋

BPI 的 `apcli0`、`apclii0`、`apclix0` 預設都在 `br-lan` 裡。
如果直接在這些介面上跑 `udhcpc`，DHCP offer 會被 bridge 吸走拿不到 IP。

**測試前**必須先拆橋：
```bash
brctl delif br-lan apclii0
ip addr flush dev apclii0
```
**測試後**要還原，否則 BPI 的管理網路會有問題：
```bash
brctl addif br-lan apclii0
```
`test_association.py` 裡的 `_restore_all_wifi_ifaces()` 已自動處理，但手動 debug 時要記得。

---

## 3. BPI wpa_supplicant 不支援 `disable_he=1`

BPI-R4 上的 wpa_supplicant 是 MediaTek patch 過的 v2.11-devel，**不認識 `disable_he`**：
```
Line N: unknown network field 'disable_he'
```
這個 network block 會被跳過，連線永遠不會嘗試。

想模擬「沒有 Wi-Fi 6/HE 能力的舊設備」，改用安全性降級的方式：
```
key_mgmt=WPA-PSK
proto=RSN WPA
ieee80211w=0
```
這樣 AP 端就不會要求 HE 相關的安全功能。注意 **6G 強制 WPA3/SAE**，沒辦法模擬舊設備，6G 只能測 802.11ax。

---

## 4. 5G 避開 DFS 頻道，否則 BPI 會進入靜默模式

DUT 5G 若使用 DFS 頻道（ch52–ch144），BPI 斷線後會進入 DFS 靜默監測模式，整個 phy1 的 scan 被 lock：
```
rai0: still in silence mode, can not trigger scan
```
這個狀態靠 `wifi down && wifi up` 或等 60–120 秒才能解除。

**解法**：DUT 5G 設定用 **UNII-1 非 DFS 頻道**（ch36/40/44/48），建議 ch36 + EHT80。
注意：ch36 + EHT160 的後半段會碰到 DFS，driver 會自動縮回 20 MHz，所以用 EHT80 就好。

---

## 5. 6G Channel Sweep 後 BPI 無法再連 6G（MT7996 driver bug）

**現象**：跑完 6G 頻道掃描（apclix0 分別連到 ch1/5/9/13/17 各一次後斷線），之後所有 6G 測試都卡在：
```
wpa_state=ASSOCIATING  ← 永遠不動
```
DUT 端 tcpdump 看不到 BPI 的任何 auth frame，代表 BPI 雖然顯示在正確頻道，實際上什麼都沒發出去。

**根因**：MT7996 driver 的 SAE ExternalAuth 狀態機在多次連/斷後損壞，`ExternalAuthRequest` 送出後 7ms 內就收到失敗回應（比任何 SAE round-trip 都快），SAE Commit frame 根本沒有被送出。

**無效的嘗試**（不要浪費時間）：
- `killall wpa_supplicant && wifi down && wifi up`
- DUT `wifi restart`
- 換頻道（ch37）或換頻寬（EHT80 → EHT80）
- `rmmod mt7996`（built-in，無法卸載）

**唯一解法**：重啟 BPI。

**已採用的預防方案**：把 channel sweep 的測試檔命名為 `test_z_channel_sweep.py`，讓它在所有其他測試跑完後才執行。這樣 driver 狀態損壞時已經沒有後續測試了，整個 session 的結果不受影響。

> ⚠️ 不要把 `test_z_channel_sweep.py` 改回 `test_channel_sweep.py`，否則 `TestLegacyCompat6G` 和 `TestThroughput6G` 都會失敗。

---

## 6. DUT（QCA/Qualcomm WiFi 7）的介面命名跟一般 OpenWrt 不同

這台 DUT 是 MLO 架構，沒有 `wlan0`/`wlan1`/`wlan2`：

| 用途 | 介面 |
|------|------|
| UCI 設定（改頻道、htmode） | `wifi0`（2.4G）、`wifi1`（5G）、`wifi2`（6G） |
| 看 station 連線狀態 | `mld0`（2.4G）、`mld2`（5G）、`mld4`（6G）|
| tcpdump 抓管理幀 | `wifi0` / `wifi1` / `wifi2`（raw phy 介面）|

```bash
# 改 6G 頻道
uci set wireless.wifi2.channel=37
uci set wireless.wifi2.htmode=EHT80
uci commit wireless && wifi

# 看有沒有 STA 連上 6G
iw dev mld4 station dump

# 抓 6G 的 auth frame
tcpdump -i wifi2 -e -n 'wlan type mgt subtype auth'
```

---

## 7. 6G ACS 可能選到非 PSC 頻道，BPI 掃不到

DUT 6G 設 `channel=auto` 時，ACS（自動選頻）可能選到非 PSC 頻道（例如 ch33/6115 MHz）。
BPI 的 6G 掃描預設只掃 PSC 頻道（ch5, 21, 37, 53...），非 PSC 頻道可能找不到 AP。

**症狀**：BPI 的 `iw dev apclix0 scan` 找不到（或很慢找到）6G SSID，wpa_supplicant 久久才嘗試連線。

**解法選項**：
- 在 DUT 上設 `acs_6g_only_psc=1`，讓 ACS 只從 PSC 頻道裡選
- 或直接固定 6G 到一個 PSC 頻道（如 ch37）

---

## 8. Busybox ping 輸出格式跟標準 Linux 不同

BPI-R4 用的是 Busybox ping，輸出是：
```
5 packets transmitted, 5 packets received, 0% packet loss
```
標準 Linux ping 是：
```
5 packets transmitted, 5 received, 0% packet loss
```
多了一個 `packets`。解析 ping 結果的 regex 要寫成：
```python
r"(\d+)\s+(?:packets\s+)?received"
```
才能兼容兩種格式，不要寫 `(\d+) received`。

---

## 9. 吞吐量門檻值基於這個 testbed 的實測值

`test_throughput.py` 裡的 `THROUGHPUT_MIN` 是根據這個具體 testbed（BPI-R4 MT7996 + DUT 實際環境）調出來的，**不代表設備的 PHY 上限**：

| Band | TCP DL | TCP UL | UDP DL |
|------|--------|--------|--------|
| 2.4G | 30 Mbps | 30 Mbps | 30 Mbps |
| 5G (EHT80, ch36) | 120 Mbps | 120 Mbps | 100 Mbps |
| 6G (EHT320, auto) | 300 Mbps | 300 Mbps | 200 Mbps |

換不同 testbed 環境後需要重新校準，直接改 `test_throughput.py` 裡的 `THROUGHPUT_MIN` dict。

---

*最後更新：2026-04-26*
