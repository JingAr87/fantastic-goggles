# ZTE F6600P (ZX279128S + MT7916AN) — Stage 1 & Stage 2 Feasibility Report

**Date:** 2026-11-21  
**Device Under Test:** ZTE `ZXHN F6600P` (TM / Unifi Malaysia AX3000 GPON ONT)  
**Stock Firmware:** `ZXHN F6600P UNI V9.1.10P2N7` (Linux `4.1.25`, built `2025-09-04`)  
**Bootloader:** `U-Boot V9.1.10P10N9` (`20250904100727`, **Non-Secure U-Boot**)  
**Factory MACs (`/tagparam/paramtag`):** 6 sequential factory MACs (`+0x62`..`+0x6e`, `ZTEG` GPON serial)  
**Stage 2 Feasibility Verdict:** **GO — 100% Portable to OpenWrt `sanechips` (Linux 6.18.55)**

---

## 1. Secure Boot Verification (Stage 2 Gate — PASSED)

Disassembled `mtd1_uboot.bin` (stage-2 U-Boot loaded at `0x46000000` from file offset `0x20800`) using `arm-openwrt-linux-muslgnueabi-objdump`:

- **No RSA-2048 signature or public key in bootloader:** Both SPL (`0x00000`) and stage-2 U-Boot (`0x20000`) headers have all-zero signature/key fields (`0x00c0..0x02d3` / `0x200c0..0x202d3`), containing only a plain SHA-256 hash at `+0x2d4`.
- **`verify_image()` (`0x4602cea4`) is dead code:** Static call-graph scan across the entire stage-2 U-Boot binary confirmed **0 callers** of `0x4602cea4` and **0 external callers** of `is_secure_boot()` (`0x4602ce80`, which reads eFuse bit 0 at `0x9a10701c`).
- **Unsigned kernel image:** `/0uImage` is a standard legacy U-Boot `uImage` (`27 05 19 56`, load/entry `0x40008000`, `3,710,030` B = exact `filesize=389c4e` in U-Boot env, Data CRC32 `0xf0a26e3a` verified `OK`, zero trailing signature).
- **Bootloader flow:** U-Boot reads `BootImageNum` from `mtd2` (`others`), selects `kernel1` (`0x01a00000`, Slot 0) or `kernel2` (`0x03a00000`, Slot 1), validates header CRC32, loads `/0uImage` from the JFFS2 rootfs (`+0x20000` inside the slot) via `fsload 0x44000000 0uImage`, and executes:
  ```text
  bootcmd=setenv bootargs console=$(console) root=/dev/mtdblock9 ro rootfstype=jffs2  mem=$(memsize);bootm 0x44000000;
  ```

---

## 2. Verified Hardware Specifications

| Subsystem | F6600P Specification | OpenWrt `sanechips` Compatibility |
| :--- | :--- | :--- |
| **SoC** | ZTE / Sanechips `ZX279128S` (dual Cortex-A9 `0xc09`, ARMv7 soft-float, no VFP/NEON) | **Identical** (`sanechips` target, `CONFIG_SOFT_FLOAT=y`) |
| **RAM** | `256 MiB` DDR3 (`mem=256M`) | **Identical** to `DIR-X1860Z` / `DIR-X3060Z` |
| **SPI-NAND** | `128 MiB` (`0x08000000`, 2 KiB page, 128 KiB eraseblock) | Dual **32 MiB** slots (`kernel1` @ `0x01a00000`, `kernel2` @ `0x03a00000`) |
| **Wi-Fi 6** | MediaTek **`MT7916AN`** (`0x14c3:0x7906` + ext-HIF `0x14c3:0x790a`, **AX3000**) | `kmod-mt7915e` + `kmod-mt7916-firmware` (same chip as `DIR-X3060Z`); `/wlan/caldata` = `196,608` B, magic `16 79`, `0x190=0x12`, `0x194..0x197=01280000` |
| **Ethernet** | 4× integrated GbE PHYs (`gphy0..gphy3`, GIC IRQs `71..74`) | Same integrated GMAC + 4× GPHY block |
| **USB** | USB 2.0 (`dwc2_hsotg`, GIC IRQ 76) + **USB 3.0 (`xhci-hcd`, GIC IRQ 82)** | Bonus USB 3.0 port |
| **GPON** | Integrated PON MAC (`bob_GN25L95_gpon.bin`) | Intentionally unused on OpenWrt (Stock kept in alternate slot) |

---

## 3. Complete Stage 1 Backup Inventory (`backup_f6600p/`)

All partitions dumped cleanly with **zero bad pages** (`bad_pages=[]` via `/dev/mtdN`):

| Local File (`backup_f6600p/`) | Size (Bytes) | SHA-256 (prefix) | Contents |
| :--- | ---: | :--- | :--- |
| `mtd1_uboot.bin` | `2,097,152` | `89c46064b2c9d138` | SPL + Stage-2 U-Boot `V9.1.10P10N9` + U-Boot env (`0x180000`) |
| `mtd2_others.bin` | `4,194,304` | `c869a25a67726ecb` | Dual-slot selector (`BootImageNum=0x00000000`) |
| `mtd3_tagparam.bin` | `4,194,304` | `767d9cf35928ecab` | JFFS2 `/tagparam` (MACs, serial, GPON BOB cal) |
| `mtd4_wlan.bin` | `4,194,304` | `726558a529cc6a2c` | JFFS2 `/wlan` (`caldata` + `paramtag`) |
| `mtd5_usercfg.bin` | `8,388,608` | `05b2cf9f599f1499` | JFFS2 `/userconfig` |
| `mtd6_middleware.bin` | `4,194,304` | `cd3517473707d59c` | JFFS2 middleware |
| `mtd7_kernel1.bin` | `33,554,432` | `fc6e8d515a792e34` | Slot 0 header (`0x00000..0x1ffff`) + JFFS2 `rootfs` (`mtd9`, includes `/0uImage`) |
| `mtd8_kernel2.bin` | `33,554,432` | `f84027949cfcb314` | Slot 1 header + JFFS2 `rootfs` (backup stock slot) |
| `mtd10_plugin.bin` | `2,097,152` | `4bda3a28f4ffe603` | Plugin partition |
| `mtd11_pluginlog.bin` | `20,971,520` | `3256ee369d24ef50` | Pluginlog partition |
| `0uImage.bin` | `3,710,030` | `feee187df77099cf` | Active kernel `uImage` (CRC32 `0xf0a26e3a` OK, appended FDT at `0x9e0`) |
| `caldata.bin` | `196,608` | `910a1b29b614b10c` | Factory MT7916AN Wi-Fi EEPROM (`16 79`) |
| `paramtag.bin` | `368` | `169fd0b84d71db23` | Factory MACs & GPON serial |
| `bob_GN25L95_gpon.bin` | `1,028` | `694a0e063db7d52b` | GPON optical transceiver calibration |
| `telemetry.txt` | `1,606` | — | `/proc/version`, `/proc/cmdline`, `/proc/mtd`, `/proc/cpuinfo`, PCI IDs |

---

## 4. Follow-Up Engineering Milestones (Completed)

The offline reverse-engineering and OpenWrt bring-up documented in this report were completed in subsequent stages:
1. Extracted `vmlinux.bin` and the appended FDT from `0uImage.bin` and unpacked stock JFFS2 (`mtd7_kernel1.bin`) to verify the SPI-NAND partition table, `uni_phy` MDIO map, GPIO/LED/button table, PCIe reset pin, `0x168` slot-header format, and `MT7916AN` calibration layout (`PROJECT_FINDINGS_F6600P.md`).
2. Authored `port/dts/zx279128s-zte-f6600p.dts` and `port/pack_f6600p.py` (`360/360` byte-exact header self-test), built OpenWrt `6.18.55` (`sanechips`), and verified live hardware bring-up including Ethernet, AX3000 Wi-Fi 6, USB 3.0, LEDs, `sysupgrade`, and `v2.0` IDM+PPE hardware offload (`BRINGUP_LOG_F6600P.md`).
