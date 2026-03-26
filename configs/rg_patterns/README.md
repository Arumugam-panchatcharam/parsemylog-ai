# Ripgrep pattern packs (rg → Drain3)

Each YAML file defines one **domain**: file name globs and regexes OR-chained into a single `rg -e` invocation. Only **matching lines** (not `-C` context) are passed to Drain3.

## Design rules

1. **Avoid bare numeric tokens in `\b…\b` alternations**  
   Example: `\b1905\b` matched the **glitch counter column** `1905` in Broadcom `chanspec` stats rows and sent whole numeric lines to Drain3. Prefer `ieee1905`, or tie `1905` to text context (e.g. `\b1905\s+(fail|error|timeout)\b`).

2. **Avoid very short English tokens** that appear as standalone numbers or codes in vendor tables (e.g. `100`, `bad` only if it can appear as a numeric-adjacent token in those files). When in doubt, require a keyword before/after (`cpu\s+100` vs `\b100\b`).

3. **Per-domain file globs** limit where patterns apply; the same line is not scanned by every domain unless the filename matches multiple packs.

4. **Duplicates** in the OR-chain are harmless but add compile size; trim repeated sub-patterns when editing.

## Files

| File            | Domain       | Notes |
|-----------------|-------------|--------|
| `wifi.yaml`     | `wireless`  | WiFi / hostapd / HAL style logs |
| `mesh.yaml`     | `mesh`      | Includes `*wifi_vendor_apps*`; mesh / 1905 wording |
| `platform.yaml` | `platform`  | Kernel, boot, self-heal, wide `*kernel*` glob |
| `core_router.yaml` | `core_router` | WAN / CCSP / PPP / GPON |
| `cellular.yaml` | `cellular`  | Modem / SIM |
| `telemetry.yaml`| `telemetry` | WebPA / Parodus / xconf |
| `common.yaml`   | `common`    | Shared syslog-style |
| `voice.yaml`    | `voice`     | VoIP (broad keyword line is intentional for coverage) |

After changing any pack, **re-index** affected CPEs (remove `*_rg.parquet` or re-upload) so ripgrep output is regenerated.
