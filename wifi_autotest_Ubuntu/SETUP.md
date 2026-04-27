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
插上 USB 後在 Test PC 執行：
```bash
sudo dmesg | tail
# 應該看到：
# [  xxx] usb 1-2: FTDI USB Serial Device converter now attached to ttyUSB0
```

記住裝置名（通常是 `/dev/ttyUSB0`，之後要填進 config）。

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

編輯 netplan（Ubuntu 22.04）：

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
ping -c 3 192.168.99.1  # 應該能通（DUT）
```

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
sudo minicom -D /dev/ttyUSB0 -b 115200
# 按 Enter 應該看到 DUT 的 shell prompt
# Ctrl+A 然後 X 離開
```

---

## 6. 交接給自動化流程

以上都通過後，填好 `config.yaml`：

```yaml
dut:
  host: 192.168.99.1
  ssh_user: admin
  ssh_password: <your_password>   # 或用 ssh_key_path
  serial_port: /dev/ttyUSB0
  serial_baud: 115200

bpi_sta:
  host: 192.168.99.100
  ssh_user: root
  ssh_key_path: ~/.ssh/id_rsa

controller:
  log_dir: ./runs
```

然後執行：

```bash
bash bootstrap_testpc.sh     # Test PC 安裝所有軟體
bash bootstrap_bpi.sh        # BPI-R4 安裝所需工具
pytest tests/test_smoke.py   # 第一次跑測試驗證整條鏈路
```

如果看到 `PASSED`，恭喜，framework 就緒。之後所有開發都可以在這個環境上跑。

---

## 7. 疑難排解快速表

| 症狀 | 可能原因 | 處理 |
|------|---------|------|
| `/dev/ttyUSB0` 不存在 | USB-Serial driver 未載入 | `sudo modprobe ftdi_sio` 或換 adapter |
| Serial 有輸出但是亂碼 | Baud rate 不對 | 試 57600 / 38400 / 9600 |
| Ping 不通 DUT | IP 衝突或網段不同 | `ip a` 確認兩邊都在 99.x/24 |
| SSH 拒絕連線 | DUT 預設關閉 SSH | 先用 Serial 開 `/etc/init.d/sshd enable` |
| BPI 找不到 WiFi 介面 | mt76 driver 未編入 | `dmesg \| grep mt76`，可能要換 kernel |

---

完成這份手冊 = 交接點。接下來交給 `bootstrap_*.sh` 和 pytest framework。
