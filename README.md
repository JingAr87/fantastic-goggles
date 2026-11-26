# OpenWrt for ZTE ZXHN F6600P (ZTE/Sanechips ZX279128S)

OpenWrt (`Linux 6.18.55`, `sanechips` target) board port, device tree, native `sysupgrade` handler, and `0x168` firmware container packer for the **ZTE ZXHN F6600P** (`HW V9.1.41`, TM / Unifi Malaysia AX3000 Wi-Fi 6 GPON ONT), configured as a Gigabit Ethernet router / AX3000 Wi-Fi 6 AP while preserving Stock firmware in the alternate flash slot for rollback.

> **Status:** **Live-verified on hardware (`v2.0` IDM/NPP + PPE)!** All 4 Gigabit Ethernet ports (factory MACs + hardware NAT & Wi-Fi PPE/IDM offload), dual-band `MT7916AN` AX3000 Wi-Fi 6 (`HE40` + `HE160`), **USB 2.0 + USB 3.0 SuperSpeed (`5 Gbps`)**, on-die SoC thermal sensor, all 13 front-panel LEDs, persistent `19.0 MiB` JFFS2 overlay, Stock Slot 1 rollback (`x3060z-fwslot`), and **1-click LuCI/SSH `sysupgrade`** with config preservation are all verified on hardware.

---

## Hardware Support Matrix

| Feature | ZTE ZXHN F6600P (HW V9.1.41) |
|---|---|
| **SoC / RAM / Flash** | Sanechips `ZX279128S` (2× Cortex-A9 @ 1 GHz, soft-float) / 256 MiB DDR3 / 128 MiB SPI-NAND (`FORESEE F35SQB001G`) |
| **Wi-Fi 6 Radio** | MediaTek `MT7916AN` (AX3000, PCIe0 `14c3:7906` + PCIe1 `14c3:790a`, 2.4 GHz `HE40` + 5 GHz `HE160`) |
| **Ethernet** | 4× integrated GbE PHYs (`LAN1` = `wan`, `LAN2..4` = `lan1..3`, MDIO `0xa..0xd`, HW PPE/IDM flow offload) |
| **USB** | USB 2.0 (`480 Mbps`) + **USB 3.0 SuperSpeed (`5 Gbps`)** (`dwc3-generic-plat`, `xhci-hcd`, `usb-storage`, FAT32/ext4) |
| **GPON** | Intentionally unused on OpenWrt (Stock firmware preserved in Slot 1 for rollback) |
| **Bootloader** | `U-Boot V9.1.10P10N9` (**Non-Secure Boot**, `0x168` CRC32 container + JFFS2 `/0uImage`) |
| **OpenWrt Flash Slot** | **Slot 0** (`kernel1` @ `0x01a00000`, 32 MiB) — **Stock Slot 1 (`kernel2` @ `0x03a00000`) preserved!** |
| **Writable Overlay** | `19.0 MiB` JFFS2 (`rootfs_data`) |
| **LuCI `sysupgrade`** | Supported & verified (preserves settings, no TFTP needed after initial install) |
| **SoC & Wi-Fi Thermal** | Live SoC temp (`/sys/class/thermal/thermal_zone0/temp`, `temp@94100034`) + `MT7916AN` `hwmon` |
| **LEDs & Buttons** | All 13 front-panel cutouts (14 LED entries) + polled Reset, WPS, and WLAN buttons verified |

---

## Flashing Guide

> **Warning:** Flashing third-party firmware carries inherent risk. Verify your hardware revision (`ZXHN F6600P`, `Non-Secure U-Boot`) and back up your flash first. Installing OpenWrt writes **Slot 0 (`kernel1` @ `0x01a00000`)** and leaves **U-Boot (`mtd0`)** and **Stock Slot 1 (`kernel2` @ `0x03a00000`)** untouched.
>
> **Power Supply Note:** Use a solid **12 V / ≥2 A** power adapter. Undersized 12 V supplies can cause brownout resets (and transient `Boot NAND / no nand! ERR!!!` boot-strap misreads) during `MT7916AN` 5 GHz TX spikes.

### Special Finding: Stock U-Boot TFTP Recovery Authentication (`TftpHandler`)
Disassembling stage-2 `U-Boot V9.1.10P10N9` (`TftpHandler` @ `0x4602b380`) revealed two important quirks on post-2024 ISP-customized F6600P builds (`V9.1.10P2N7`):
1. **Stage-2 U-Boot UART is stubbed:** `zte_serial` (`0x4603faec`) has `putc`/`getc`/`tstc` compiled as no-ops, so serial console produces no stage-2 output and cannot be interrupted via UART.
2. **Reset-Button TFTP Recovery requires ZTE OACK `user`/`pass` auth (`root` / `root`):** Holding the Reset button for **5–6 seconds** on power-on triggers `downver version` (`ipaddr=192.168.1.1`, `serverip=192.168.1.100`, `fullfile=upgrade.bin`) with **zero RSA/signature verification** (only IEEE CRC32 over the `0x168` header and payload). However, when Reset-button recovery is active, `TftpHandler` enforces a custom **TFTP `OACK` authentication check** requiring `user` and `pass` options decrypted via AES-128-ECB with the public **NIST FIPS-197** example key (`2b7e151628aed2a6abf7158809cf4f3c`) and matched against `root` / `root` (decoded from `env_na`/`env_pa` = `=@@;`), yielding the 16-byte OACK token `74 2a 80 a9 22 ce 4b 66 6d 3a ba 66 11 6c 15 b9`. Standard TFTP servers (`dnsmasq`, `tftpd64`) do not send these options, causing U-Boot to abort immediately (`NetState = 3`) and reboot.
   - Full protocol write-up and ready-to-use Python recovery TFTP server (`zte_tftp_server.py`): **[JingAr87/refactored-octo-waffle](https://github.com/JingAr87/refactored-octo-waffle)**

Because **Secure Boot is OFF** (`non secure boot` / `non secure uboot`, zero RSA keys in SPL/U-Boot), there are **two initial installation paths**:

### 1. First-Time Install — Option A: Reset-Button TFTP Recovery (Recommended, No Hardware Tools)
1. Download `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-factory.bin` from [Releases](../../releases), verify its SHA256 against `SHA256SUMS.txt`, and rename it to **`upgrade.bin`**.
2. Assign static IP **`192.168.1.100/24`** (gateway `192.168.1.1`) to your PC's Ethernet adapter and connect it to **LAN1**.
3. Run `zte_tftp_server.py` from [JingAr87/refactored-octo-waffle](https://github.com/JingAr87/refactored-octo-waffle) (sends the required `user`/`pass` OACK tokens for `root`/`root`):
   ```sh
   sudo python3 zte_tftp_server.py upgrade.bin   # Linux / macOS (or run as Administrator on Windows)
   ```
4. Power on the F6600P while holding the **Reset** button for **~6 seconds** until the TFTP transfer begins (`~13 MB/s`). Release Reset and wait ~60–90 seconds for U-Boot to flash Slot 0 and reboot into OpenWrt.

### 1. First-Time Install — Option B: External SPI-NAND Programmer (Offline Fallback)
If you do not have ZTE's TFTP OACK credentials, you can flash the SPI-NAND (`FORESEE F35SQB001G`, 3.3 V, WSON-8) directly with an external SPI-NAND programmer (e.g., XGecu T48 / RT809F / CH341A-style):
1. Back up the full 128 MiB SPI-NAND dump first.
2. Write `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-factory.bin` to **`kernel1` (`0x01a00000`)**, leaving `u-boot` (`0x00000000`) and Stock `kernel2` (`0x03a00000`) untouched.

### 2. First Boot Setup
1. Connect via Ethernet (**LAN2–LAN4** are LAN; **LAN1** is WAN) or open Wi-Fi (`OpenWrt-ZXIC` / `OpenWrt-ZXIC-5G`, which come up ~60 s after boot via deferred radio bind) and open **`http://192.168.1.1/`** (`root`, no password initially).
2. **Immediately** set a root password (**System → Administration**) and WPA2/WPA3 Wi-Fi passwords (**Network → Wireless**).

### 3. Future OpenWrt Upgrades (1-Click LuCI `sysupgrade`)
Once OpenWrt is running, TFTP and UART are no longer needed:
1. Download `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-sysupgrade.bin`.
2. In LuCI, go to **System → Backup / Flash Firmware → Flash new firmware image**.
3. Upload `*-squashfs-sysupgrade.bin`, keep **Keep settings and retain the current configuration** checked, and click **Continue**.

### 4. Rolling Back to Stock Firmware (Slot 1)
Because Stock firmware remains untouched in Slot 1 (`kernel2` @ `0x03a00000`), you can inspect or switch slots over SSH without reflashing:
```sh
x3060z-fwslot status    # Inspect active BootImageNum and both slots
```
To boot Stock Slot 1 (`BootImageNum=0x00000001`), switch the active slot in `others` (`mtd6`) and reboot.

---

## Known Notes
- **Hardware Acceleration & `v2.0` IDM/NPP + PPE Wi-Fi Offload:** Built on the same `v2.0` `ZX279128S` kernel stack as [D-Link DIR-X1860Z / DIR-X3060Z](https://github.com/JingAr87/laughing-waffle): Integrated DMA (`0x921c8000`, `GIC_SPI 38`) exposes `phy0-ap*` / `phy1-ap*` (`bp6`, `bp7`) directly to the hardware switch (`sbrg`) and Packet Processor (`PPE`) with `page_pool` zero-copy recycling and a minimal pre-GRO hook in `mt76_rx_complete()`. `ZX279128R`-specific NPP/TM/SMCT overrides are gated on `of_machine_is_compatible("zte,zx279128r")` so `ZX279128S` retains clean Gigabit RX/TX.
- **Deferred Wi-Fi Startup (~60 s):** `mt7915e` is bound after early boot (`S95`) so SSH/LuCI always come up first. `11-mt76-caldata` automatically extracts `/wlan/caldata` (`196,608 B`) from `mtd8` (`wlan`) to `/lib/firmware/mediatek/mt7916_eeprom.bin`.
- **Chassis Port Mapping:** Physical **LAN1** → `wan` (`phy 0x0a`, factory WAN MAC from `/tagparam/paramtag` `+0x6e`), **LAN2 / LAN3 / LAN4** → `lan1 / lan2 / lan3` (`phy 0x0b..0x0d`, factory LAN MAC `+0x62`).
- **On-Die SoC Thermal Sensor:** `temp@94100034` (`zxic,tempsensor`) exposes live SoC temperature at `/sys/class/thermal/thermal_zone0/temp` alongside `mt7915_phy0`/`phy1` in `/sys/class/hwmon/`.

---

## Repository Layout
- [`port/`](port/) — OpenWrt `sanechips` board overlay:
  - [`port/dts/zx279128s-zte-f6600p.dts`](port/dts/zx279128s-zte-f6600p.dts) — Verified Device Tree (Ethernet PHYs, `GIC_SPI 38` IDM IRQ, `MT7916AN` PCIe, USB 3.0 `dwc3`, 14 LEDs, polled buttons, SPI-NAND layout, thermal sensor).
  - [`port/pack_f6600p.py`](port/pack_f6600p.py) — Standalone `0x168` slot-header packer & verifier (`360/360` byte-exact self-test against stock `kernel1`/`kernel2`).
  - [`port/image/Makefile.f6600p`](port/image/Makefile.f6600p) — OpenWrt `target/linux/sanechips/image/Makefile` device stanza.
  - [`port/base-files/`](port/base-files/) — Calibration loader (`11-mt76-caldata`), factory MAC loader (`02_network`), LED triggers (`01_leds`), native `sysupgrade` (`lib/upgrade/platform.sh`), and slot inspector (`x3060z-fwslot`).
- [`STAGE1_2_REPORT.md`](STAGE1_2_REPORT.md) — SPI-NAND partition inventory & Non-Secure U-Boot verification.
- [`PROJECT_FINDINGS_F6600P.md`](PROJECT_FINDINGS_F6600P.md) — Offline hardware, partition, GPIO/LED, and `0x168` slot-header reverse-engineering.
- [`BRINGUP_LOG_F6600P.md`](BRINGUP_LOG_F6600P.md) — UART pinout, stage-2 U-Boot disassembly, TFTP OACK auth root cause, and live bring-up log.
- [`COMMUNITY_RESEARCH_F6600P.md`](COMMUNITY_RESEARCH_F6600P.md) — Notes on post-2024 ZTE firmware, regional ISP context, and `ZX279128S` OpenWrt projects.

---

## Credits & Acknowledgments
- **Navid Ghahremani** & the **`sanechips` target (`pr-zte-zxhn-h3600`, mirrored at `Zlion-Y/openwrt-sanechips-mirror`)** — Linux 6.18 `ZX279128S` SoC bring-up (`zx279128s-eth`, `pcie-zx279128s`, `zx-qspi`, `L2C-310` IO-read lock, JFFS2 program-once).
- **`Zlion-Y/zte-e2631-openwrt`** — `ZX279128S` router conventions and deferred `mt7915e` Wi-Fi bring-up scripts.
- **OpenWrt & MediaTek `mt76` contributors** — OpenWrt build system, LuCI, and `mt7915e` Wi-Fi 6 driver.

## License
Licensed under **GPL-2.0-only**. Device Tree files are dual-licensed `GPL-2.0-only OR BSD-2-Clause`.
