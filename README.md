# WiFi Router Automated Test Framework

A ready-to-run automated testing framework for WiFi 7 routers, using a Banana Pi BPI-R4 (MT7996) as the WiFi STA client and Claude AI for log analysis and failure triage.

## What it does

- Runs functional regression tests over SSH + Serial (smoke, association, throughput, legacy compatibility, channel sweep)
- Performs a long-running stability soak test (2+ hours) with continuous traffic and DUT health monitoring
- On test failure, automatically collects live diagnostics from DUT and BPI, then invokes Claude Code CLI to generate a root-cause analysis report

## Repository layout

| Folder | Description |
|--------|-------------|
| `wifi_autotest_Mac/` | Test PC on **macOS** (Bootstrap uses Homebrew) |
| `wifi_autotest_Ubuntu/` | Test PC on **Ubuntu/Debian Linux** (Bootstrap uses apt) |

Both variants share the same test suite, libraries, and tools — only the bootstrap script differs by platform.

## Quickstart

```bash
cd wifi_autotest_Mac        # or wifi_autotest_Ubuntu
cp config/config.yaml.example config.yaml
nano config.yaml            # fill in DUT IP, SSID, PSK, BPI IP
bash bootstrap_testpc.sh
source .venv/bin/activate
bash run_all.sh rf
```

See the platform-specific `README.md` inside each folder for full setup instructions.

## Hardware testbed

```
┌─────────┐  Serial+SSH  ┌────────────┐  LAN+SSH  ┌──────────────┐
│   DUT   │◀────────────▶│  Test PC   │◀─────────▶│  BPI-R4      │
│ (Router)│              │ Controller │           │ (WiFi 7 STA) │
└─────────┘              └────────────┘           └──────┬───────┘
     ▲                                                    │
     └───────────────── RF (WiFi OTA) ───────────────────┘
```

- DUT: WiFi 7 router under test (QCA/Qualcomm, OpenWrt)
- BPI-R4: Banana Pi with MediaTek MT7996 — acts as WiFi STA and iperf3 traffic source
- Test PC: macOS or Ubuntu, runs pytest + Claude Code CLI

## Author

EJ Chang (張恩瑞)
