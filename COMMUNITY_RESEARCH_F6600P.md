# Community Research: ZTE ZXHN F6600P & `ZX279128S` (English / Chinese / Regional Sources)

> Research compiled on 2026-11-21 starting from `douniwan5788/zte_modem_tools#20` and cross-referencing GitHub, Chinese forums (恩山 `right.com.cn`, 看雪 `kanxue.com`, `chinadsl.net`), and regional ISP threads (Malaysia TM Unifi `lowyat.net`, Europe `bandaancha.eu` / `elektroda.com`).

---

## 1. `douniwan5788/zte_modem_tools` Issue #20

- **Source:** https://github.com/douniwan5788/zte_modem_tools/issues/20
- **Title:** `[Feature] Enabling Telnet on ZTE firmware with post-October 2024 builds`
- **Affected Firmware Examples:** Post-October 2024 ZTE builds including `F670L V9.0.11P1N52`, `F6600P V9.0.10P25N1`, and 2025 builds (such as our `F6600P UNI V9.1.10P2N7`, built `2025-09-04`).

### Technical Summary of What Changed in Late-2024+ ZTE Firmware
1. **Factory-Mode Handshake Change (`newrand` → `re_rand`):**
   - Legacy `zte_factroymode.py` scripts relied on Step 2 of ZTE's factory-mode HTTP endpoint returning `newrand=%d`.
   - Post-October 2024 `httpd` builds replaced this with a composite parameter: `re_rand=%d&%d&...` containing three `&`-delimited parts:
     1. A random index (`0..59`, analogous to the old `newrand`)
     2. A random integer (`0..8388607`)
     3. An encoded representation of the device's MAC address
2. **Dynamic AES Key Pool:**
   - Newer `httpd` builds also replaced the static key table with a dynamically generated AES key pool.
   - Community forks/tools discussed in the thread (e.g. `zteonu3` and updated Python scripts) document the updated `re_rand` parsing and key-pool logic, sometimes requiring specific host NIC/MAC setups.
3. **Additional Protections on Recent Builds:**
   - Newer ZTE builds also add checks such as `Anti_Infringement_judge` and certificate/tag validation that can trigger automatic reboots on mismatched parameters.

### Relevance to `F6600P UNI V9.1.10P2N7`
- Stock firmware **already allows Telnet/SSH** via the standard Stock Web UI (`tmadmin` / `Adm@XXXX`, though the toggle must be cycled off→save→on→save after each reboot).
- However, the Telnet shell obtained via `tmadmin` is **command-restricted** (`dd`, `tftp`, `fw_flashing` return `/bin/sh: Access Denied`).
- Community discussions (e.g., SuperUser / GitHub threads on ZTE ONTs) note that ZTE's BusyBox shell restrictions are enforced via permission lists such as `/etc/tdsec/Authority.txt` (`r_permit_list` / `ops_permit_list`) and gated by the kernel/runtime factory-mode flag (`/proc/zteinfo/factory/factorymode`).
- **Important note:** Using exploit/bypass scripts to circumvent ZTE's factory-mode authentication or permission checks is out of scope for sanctioned/documented workflows; this section is documented strictly for architectural reference.

---

## 2. Chinese Community Findings (恩山 `right.com.cn`, 看雪 `kanxue.com`, `chinadsl.net`)

### A. `ZX279128S` / `ZX279127S` U-Boot & `downver`
- Chinese forum threads on `ZX279128S` / `ZX279127S` devices (e.g., F657GV9, E2603, F6600P, GM630, E1600) confirm:
  - `downver` ("download version") is ZTE's custom U-Boot (`cspboot`) TFTP upgrade command, using `fullfile=upgrade.bin`, `ipaddr=192.168.1.1`, `serverip=192.168.1.100`.
  - U-Boot strictly validates ZTE's proprietary header magic (`fwmagic`), CRC32 (`vmlinuz crc error`), and JFFS2 container layout; mismatched images trigger `no version available, pls downver!` or a reboot loop.
  - On newer locked builds where stage-2 U-Boot serial input/output is stripped or TFTP recovery requires vendor authentication, Chinese enthusiasts consistently fall back to **offline SPI-NAND programmer flashing** (e.g., RT809F / RT809R / CH341A-style SPI-NAND programmers) to back up or write full NAND dumps directly.

### B. `supgrade.html` & Stock Web Upgrade
- Some ZTE `ZX279128S` router firmwares expose a local upgrade page (`/supgrade.html`) in the stock Boa/uhttpd web server.
- However, on ISP-customized GPON ONTs like F6600P `V9.1.10P2N7`, stock web upgrades enforce signature verification (`/var/tmp/sign-cfg`), unlike un-signed router variants.

---

## 3. OpenWrt & Mainline Linux Projects on `ZX279128S`

Two notable public GitHub repositories target the exact same **Sanechips `ZX279128S`** SoC (dual-core ARM Cortex-A9, 256 MiB DDR3, 128 MiB SPI-NAND):

1. **`Zlion-Y/zte-e2631-openwrt`** (`https://github.com/Zlion-Y/zte-e2631-openwrt`)
   - OpenWrt port for the **ZTE ZXHN E2631** (`ZX279128S`).
   - Includes board overlays, host tooling, vendor-format image packaging, and A/B dual-slot rollback management.
   - Flashes via `supgrade.html` on the E2631 (where stock web upgrade does not enforce the same ISP GPON signature lock as F6600P).
2. **`Zlion-Y/e2631-mainline-zx279128s`** (`https://github.com/Zlion-Y/e2631-mainline-zx279128s`)
   - Mainline Linux kernel support files (board DTS, defconfig, UART support) for `ZX279128S`.

*(Note: Official OpenWrt does not currently have upstream support for the F6600P GPON ONT; our port in `port/` already targets `sanechips` Linux `6.18.55` with a byte-exact `0x168` slot-header packer.)*

---

## 4. Regional / ISP Context (Malaysia TM Unifi & International)

- **TM Unifi (Malaysia, `lowyat.net`):**
  - Default Web UI admin account on TM-issued F6600P units is `tmadmin` / `Adm@XXXX` (last 4 hex digits of MAC).
  - Even `tmadmin` has locked-down menus/commands on recent firmware; most end users either request Bridge Mode from TM or place an external OpenWrt router behind it.
- **European / LATAM ISPs (Vodafone, Lowi, Orange, Claro — `bandaancha.eu`, `elektroda.com`, `adrenaline.com.br`):**
  - Users report the same `/bin/sh: Access Denied` restricted shell behavior and late-2024+ `httpd` security updates across regional F6600P builds.

---

## 5. Takeaways for F6600P OpenWrt Bring-Up

| Approach | Community Status on Post-2024 F6600P (`V9.1.10P2N7`) | Practical Takeaway |
| :--- | :--- | :--- |
| Stock Web UI (`httpd` / `supgrade.html`) | Signature-checked (`/var/tmp/sign-cfg`) on ISP ONT builds | Cannot accept unsigned OpenWrt images |
| Stock Telnet (`tmadmin`) | Restricted BusyBox (`Authority.txt` whitelist) | Read-only diagnostics/backup only |
| `zte_modem_tools` / `re_rand` factory-mode scripts | Targets post-Oct 2024 `httpd` factory-mode auth to unlock full Telnet/factory mode | Relies on circumventing ZTE's authentication/ACL (not a sanctioned path) |
| U-Boot Reset-Button TFTP (`downver`) | Requires ZTE's custom `user`/`pass` TFTP OACK auth; stage-2 UART is stubbed | Blocked without vendor TFTP server auth |
| **External SPI-NAND Programmer** | Standard Chinese/community method for locked `ZX279128S` boards | **Cleanest unblocked path:** Secure Boot is OFF; flashing `squashfs-factory.bin` (`mkfs.jffs2 -s 4096`) to `kernel1` (`0x01a00000`) leaves Stock untouched in `kernel2` (`0x03a00000`) |
