#!/usr/bin/env bash
# diag_6g.sh — 6G 關聯失敗診斷腳本
# 執行方式: bash tools/diag_6g.sh

set -euo pipefail
cd "$(dirname "$0")/.."

DUT=192.168.99.1
BPI=192.168.99.100
OUT="runs/diag_6g_$(date +%Y%m%d-%H%M%S).log"

log() { echo "$*" | tee -a "$OUT"; }

log "======================================================"
log " 6G 診斷報告 — $(date '+%Y-%m-%d %H:%M:%S')"
log "======================================================"

# ---- DUT ----
log ""
log "====== [DUT] 無線介面狀態 ======"
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@$DUT \
  "iw dev" 2>&1 | tee -a "$OUT"

log ""
log "====== [DUT] 6G hostapd 狀態 ======"
ssh -o StrictHostKeyChecking=no root@$DUT \
  "for i in \$(iw dev | awk '/Interface/{print \$2}'); do
     echo \"--- \$i ---\";
     hostapd_cli -i \$i status 2>/dev/null | grep -E 'state|freq|channel|ssid|bss' || echo 'N/A';
   done" 2>&1 | tee -a "$OUT"

log ""
log "====== [DUT] 6G SSID beaconing ======"
ssh -o StrictHostKeyChecking=no root@$DUT \
  "iw dev | awk '/Interface/{iface=\$2} /type AP/{print iface}' | while read iface; do
     echo \"--- \$iface ---\";
     iw dev \$iface info 2>/dev/null;
   done" 2>&1 | tee -a "$OUT"

# ---- BPI ----
log ""
log "====== [BPI] 無線介面狀態 ======"
ssh -o StrictHostKeyChecking=no root@$BPI \
  "iw dev" 2>&1 | tee -a "$OUT"

log ""
log "====== [BPI] 掃描 6G SSID ======"
ssh -o StrictHostKeyChecking=no root@$BPI \
  "iw dev apclix0 scan 2>/dev/null | grep -A 15 'Gemtek_Wi-Fi7_1EA7DD_6' || echo 'SSID not found in scan'" 2>&1 | tee -a "$OUT"

log ""
log "====== [BPI] regulatory domain ======"
ssh -o StrictHostKeyChecking=no root@$BPI \
  "iw reg get" 2>&1 | tee -a "$OUT"

log ""
log "====== [DUT] regulatory domain ======"
ssh -o StrictHostKeyChecking=no root@$DUT \
  "iw reg get" 2>&1 | tee -a "$OUT"

log ""
log "======================================================"
log " 診斷完成 — 結果存於 $OUT"
log "======================================================"

echo ""
echo "Log 已存至: $OUT"
