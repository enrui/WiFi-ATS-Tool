# Physical Setup Guide

> 這份文件是給工程師照著做的「第一哩路」手冊。
> 完成後，剩下的軟體自動化就能接手。

預計時間：**15–30 分鐘**（設備都在手邊的情況下）

---

## 1. Bill of Materials 清點

執行前確認以下設備都在：

| # | 項目 | 數量 | 備註 |
|---|------|------|------|
| 1 | DUT (WiFi Router) | 1 | 已 flash 目標 firmware |
| 2 | Test PC (Ubuntu 22.04 LTS) | 1 | 16 GB RAM 以上，可上網 |
| 3 | Banana Pi BPI-R4 + 電源 | 1 | 已燒錄 OpenWrt 或 Ubuntu image |
| 4 | USB-to-Serial adapter (FTDI / CP2102) | 1 | 建議 FTDI FT232，穩定度較佳 |
| 5 | Dupont 杜邦線（母-母） | 3 | 接 Serial 的 TX / RX / GND |
| 6 | Ethernet 網路線（CAT5e 或更好） | 3 | Test PC ↔ Switch, DUT ↔ Switch, BPI ↔ Switch |
| 7 | 5-port Gigabit Switch（或家用 router 閒置 port） | 1 | 做為 mgmt LAN |
| 8 | DUT 的 WAN 網路線（可選） | 1 | 若測試需要 Internet |

---

## 2. 網路拓撲

```
                  ┌──────────────────┐
                  │   Mgmt Switch    │
                  │  192.168.99.0/24 │
                  └────┬────┬────┬───┘
                       │    │    │
              ┌────────┘    │    └────────┐
              │             │             │
         ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
         │ Test PC │   │   DUT   │   │ BPI-R4  │
         │  .10    │   │   .1    │   │  .100   │
         └────┬────┘   └─────────┘   └─────────┘
              │              ╲           ╱
              │              ╲ RF WiFi  ╱
              │               ╲  Link  ╱
         USB-Serial            ╲──────╱
              │
              │ (TX/RX/GND)
              ▼
         DUT UART Pin Header
```

**關鍵點：**
- 所有設備用**固定 IP**在同一個 mgmt 網段，避免 DHCP 不穩
- 建議網段：`192.168.99.0/24`（避開家用常見的 192.168.0.x / 1.x）
- DUT 的 RF 由 BPI-R4 用 WiFi 連線（這條是被測試的鏈路）

---

## 3. 實體接線步驟

### 3.1 接 Serial Console

> ⚠️ **這是最容易出錯的一步，請仔細確認。**

在 DUT 上找到 UART pin header。通常是 4-pin 排針（有些產品需拆外殼才看得到）。

**接線對應：**

| USB-Serial adapter | DUT UART |
|--------------------|----------|
| GND                | GND      |
| TX                 | **RX**   |
| RX                 | **TX**   |
| VCC (3.3V)         | **不接**（DUT 自己供電） |

**常見錯誤：**
- TX/RX 要交叉接（adapter TX → DUT RX）
- 千萬不要把 VCC 接上去，會燒板子
- 確認 DUT UART 是 3.3V logic level（絕大多數是，但老舊產品可能是 1.8V，需要查 schematic）

**確認方法：**

**Linux (Ubuntu/Debian):**
```bash
sudo dmesg | tail
# 應該看到：
# [  xxx] usb 1-2: FTDI USB Serial Device converter now attached to ttyUSB0
```
記住裝置名（通常是 `/dev/ttyUSB0`），之後填進 config。

**macOS:**
```bash
ls /dev/tty.usb* /dev/tty.SLAB_* 2>/dev/null
# 你會看到類似：
#   /dev/tty.usbserial-FTABC123      (FTDI 晶片)
#   /dev/tty.SLAB_USBtoUART          (CP2102 晶片)
#   /dev/tty.wchusbserial1410        (CH340 晶片)
```
裝置名會帶 adapter 的序號後綴 —— 換條線就會變，所以記得每次更換後重新確認。

**Driver 安裝（macOS 限定）：**

| 晶片 | macOS 14+ | 處理方式 |
|------|----------|---------|
| FTDI FT232 | ✅ 內建 | 插上即可 |
| CP2102 / CP2104 | ❌ 需驅動 | [Silicon Labs VCP](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) |
| CH340 / CH341 | ❌ 需驅動 | [WCHSoftGroup ch34xser](https://github.com/WCHSoftGroup/ch34xser_macos) |

**強烈建議用 FTDI**，省去驅動安裝跟系統權限授權的麻煩。

### 3.2 接網路

1. Test PC Ethernet ↔ Switch
2. DUT LAN port (非 WAN) ↔ Switch
3. BPI-R4 LAN port ↔ Switch

### 3.3 接電源

按順序上電：
1. Switch → 2. DUT → 3. BPI-R4 → 4. Test PC

---

## 4. 設定固定 IP

### 4.1 Test PC

**Linux (Ubuntu 22.04+):**

編輯 netplan：
```bash
sudo nano /etc/netplan/01-testbed.yaml
```
貼入（把 `enp3s0` 換成你的介面名，用 `ip a` 查）：
```yaml
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: no
      addresses: [192.168.99.10/24]
```
套用：
```bash
sudo netplan apply
ping -c 3 192.168.99.1
```

**macOS:**

最簡單的方式是用我們提供的腳本：
```bash
bash scripts/macos_network_setup.sh
```
腳本會列出所有網路服務（Ethernet、USB-Ethernet 轉接器…），你選一個之後輸入 IP（預設 192.168.99.10）就完成。

或手動操作：
```bash
networksetup -listallnetworkservices       # 找到要用的服務名
sudo networksetup -setmanual "Ethernet" 192.168.99.10 255.255.255.0 0.0.0.0
ping -c 3 192.168.99.1
```

要還原回 DHCP：
```bash
bash scripts/macos_network_setup.sh --revert
# 或：sudo networksetup -setdhcp "Ethernet"
```

> **macOS 提醒**：如果 MacBook 是用 USB-Ethernet 轉接器接 mgmt LAN，網路服務名通常是「USB 10/100/1000 LAN」或 adapter 廠牌名（如「Belkin USB-C LAN」），不是「Ethernet」。

### 4.2 DUT

透過 Serial 或 Web UI 設定 LAN IP 為 `192.168.99.1/24`。
（每家 SDK 介面不同，照產品文件操作）

### 4.3 BPI-R4

首次登入（預設通常 `root` 無密碼或 `bananapi/bananapi`）：

```bash
ssh root@<bpi_initial_ip>

# OpenWrt:
uci set network.lan.ipaddr='192.168.99.100'
uci set network.lan.netmask='255.255.255.0'
uci commit network
/etc/init.d/network restart

# Ubuntu (netplan):
# 同 Test PC 的做法，IP 改為 192.168.99.100
```

---

## 5. 連通性驗證（Checklist）

在 Test PC 上逐一執行，全部通過才能進下一步：

```bash
# 1. Ping DUT
ping -c 3 192.168.99.1

# 2. Ping BPI-R4
ping -c 3 192.168.99.100

# 3. SSH 到 DUT（先確認你已經建立好登入憑證）
ssh admin@192.168.99.1 "uname -a"

# 4. SSH 到 BPI-R4
ssh root@192.168.99.100 "uname -a"

# 5. Serial console 可讀
# Linux:
sudo minicom -D /dev/ttyUSB0 -b 115200
# macOS:
sudo minicom -D /dev/tty.usbserial-XXXX -b 115200
# 或用 picocom（macOS 上比較順）:
picocom -b 115200 /dev/tty.usbserial-XXXX
# 按 Enter 應該看到 DUT 的 shell prompt
# minicom 離開：Ctrl+A 然後 X
# picocom 離開：Ctrl+A 然後 Ctrl+X
```

---

## 6. 硬體特殊注意事項

> ⚠️ 這些是這套 testbed 的**非標準設定**，跟一般教學不同，請務必閱讀。

### 6.1 SSH 認證方式：none-auth（無密碼）

本 testbed 的 DUT（OpenWrt/Dropbear）和 BPI-R4 都採用 **root 無密碼** 的 SSH none-auth 方式。

- **不要**在 `config.yaml` 填 `ssh_password` 或 `ssh_key_path`
- Framework 的 `lib/devices.py` 已處理好 paramiko none-auth，填了密碼反而會認證失敗

驗證方式：
```bash
ssh root@192.168.99.1    # DUT — 直接登入，不問密碼
ssh root@192.168.99.100  # BPI  — 直接登入，不問密碼
```

如果你的 DUT firmware 有設 root 密碼（非標準），才需要加 `ssh_password`。

### 6.2 BPI-R4 WiFi 介面名稱（MediaTek MT7996）

BPI-R4 使用 MediaTek MT7996 晶片，WiFi 介面**不是**一般的 `wlan0/wlan1/wlan2`，而是：

| 頻段 | 介面名稱 | 模式 |
|------|---------|------|
| 2.4 GHz | `apcli0`   | AP-client，4addr/WDS 強制開啟 |
| 5 GHz   | `apclii0`  | AP-client，4addr/WDS 強制開啟 |
| 6 GHz   | `apclix0`  | AP-client，4addr/WDS 強制開啟 |

4addr/WDS 模式代表這些介面無法用一般 STA 方式連線，需要 DUT AP 這側也開啟 WDS 支援（本 DUT 已設定）。

### 6.3 BPI-R4 的 br-lan bridge

BPI-R4 預設把所有介面（包含 `apcli0/apclii0/apclix0`）都橋接到 `br-lan`（IP: 192.168.99.100）。

RF 測試執行時，framework 會自動把要測試的 WiFi 介面從 bridge 拔出、讓它取得獨立 IP、跑完後還原。這個流程已內建在 `tests/test_association.py` 的 `_restore_all_wifi_ifaces()`，不需要手動操作。

---

## 7. 填寫 config.yaml 並執行

複製範例：
```bash
cp config/config.yaml.example config.yaml
```

填入你的環境值（參考下方）：

```yaml
dut:
  host: 192.168.99.1
  ssh_user: root
  # 無密碼 none-auth — 不要填 ssh_password 或 ssh_key_path
  serial_port: /dev/tty.usbserial-XXXX   # macOS，用 ls /dev/tty.usb* 查實際名稱
  # serial_port: /dev/ttyUSB0            # Linux
  serial_baud: 115200

  wifi:
    ssid_2g: "<DUT 2.4G SSID>"
    ssid_5g: "<DUT 5G SSID>"
    ssid_6g: "<DUT 6G SSID>"
    psk:     "<WiFi 密碼>"

bpi_sta:
  host: 192.168.99.100
  ssh_user: root
  # 無密碼 none-auth — 不要填 ssh_password 或 ssh_key_path
  wifi_iface_2g: apcli0    # MediaTek MT7996 固定名稱
  wifi_iface_5g: apclii0
  wifi_iface_6g: apclix0

controller:
  log_dir: ./runs
  report_dir: ./reports
  keep_last_n_runs: 20
```

然後安裝依賴並驗證環境：

```bash
bash bootstrap_testpc.sh          # 安裝 Python 套件、工具
bash bootstrap_bpi.sh             # BPI-R4 安裝 iperf3 等工具
bash run_all.sh                   # smoke tests（不需要 RF 連線）
```

確認 smoke tests 全綠後，跑完整 RF 測試（三個頻段 association + throughput）：

```bash
bash run_all.sh rf
```

看到 `pytest: PASS` 就完成。測試報告在 `runs/<timestamp>/pytest_report.html`。

---

## 8. 疑難排解快速表

| 症狀 | 可能原因 | 處理 |
|------|---------|------|
| `SSH Authentication failed` | 誤填了 `ssh_password` | 把 `ssh_password` 這行從 config.yaml 刪掉 |
| `/dev/ttyUSB0` 不存在（Linux） | USB-Serial driver 未載入 | `sudo modprobe ftdi_sio` 或換 adapter |
| `/dev/tty.usb*` 不存在（macOS） | 驅動未裝或被系統阻擋 | 系統設定 → 隱私權與安全性，允許該驅動 |
| Serial 有輸出但是亂碼 | Baud rate 不對 | 試 57600 / 38400 / 9600 |
| Ping 不通 DUT | IP 衝突或網段不同 | Linux: `ip a`；macOS: `ifconfig`，確認都在 99.x/24 |
| SSH 拒絕連線 | DUT 預設關閉 SSH | 先用 Serial 開 `/etc/init.d/sshd enable` |
| 6G association 失敗（stuck SCANNING） | wpa_supplicant 未啟用 SAE H2E | config 已內建 `sae_pwe=2`，確認 wpa_supplicant ≥ v2.10 |
| BPI WiFi 介面 `wlan0` 找不到 | MediaTek 介面名不同 | 用 `iw dev` 確認，正確名稱填入 config.yaml |
| macOS 接 USB-Ethernet 沒有 IP | DHCP 還沒給 IP，或服務名找錯 | `networksetup -listallnetworkservices` 確認 |

---

完成這份手冊 = 交接點。之後執行 `bash run_all.sh rf` 就是完整的自動化測試流程。
