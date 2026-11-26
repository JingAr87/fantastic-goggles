# ZTE ZXHN F6600P — Live Bring-Up & U-Boot TFTP Recovery Log

**Updated:** 2026-11-26  
**Device:** ZTE `ZXHN F6600P` (`ZX279128S` + `MT7916AN`, 256 MiB RAM, 128 MiB SPI-NAND)  
**Stock Firmware:** `ZXHN F6600P UNI V9.1.10P2N7` (`U-Boot V9.1.10P10N9`, Non-Secure Boot)  
**TFTP Host Setup:** `192.168.1.100/24` (U-Boot `serverip`) serving `upgrade.bin`.

---

## 1. Verified Hardware & UART Pinout

4-pin UART header on F6600P PCB (top to bottom):
1. **Pin 1:** GND
2. **Pin 2:** Router RX (connect CH340 TX via `1k + 2k` voltage divider → ~3.08 V)
3. **Pin 3:** Router TX (connect CH340 RX direct, 3.3 V)
4. **Pin 4:** 3.3 V VCC (**leave unconnected**)

Serial settings: `115200 8N1`, no flow control.

- **SPL output:** Prints `Boot SPI NAND / start read bootheader / start read secondboot / non secure boot / Jump / SPI NAND / non secure uboot`.
- **Stage-2 U-Boot UART is stubbed:** `zte_serial` (`0x4603faec`) has `putc`/`getc`/`tstc` compiled as no-ops (`bx lr` / `return 0`), so stage-2 U-Boot produces no UART output and cannot be interrupted via serial.
- **Note on `Boot NAND / no nand! ERR!!!`:** If power dips or UART wires bump during boot, BootROM can misread the boot-mode strap as parallel NAND instead of SPI-NAND. Power-cycling cleanly (unplug 10 s, reconnect) restores normal `Boot SPI NAND`.
- **Stock Telnet/SSH quirk:** Stock LAN IP is `192.168.1.2` (`tmadmin` / `Adm@XXXX`, last 4 hex digits of MAC). Telnet/SSH toggles in Stock Web UI must be cycled off→save→on→save after a reboot to re-open ports `22`/`23`. Stock Telnet uses a whitelisted BusyBox shell (`cat`, `ls`, `hexdump` work; `dd`, `tftp`, `fw_flashing` return `Access Denied`). Stock Web UI (`httpd`) enforces a userspace ZTE signature check (`/var/tmp/sign-cfg`).

---

## 2. Disassembled Stage-2 U-Boot Findings (`mtd1_uboot.bin`, VA `0x46000000`)

| Function / Address | Purpose & Key Behavior |
| :--- | :--- |
| `0x46012630` (`reset_key_recovery`) | Called from `main_loop` (`0x4600fbb8`). Sets `ipaddr=192.168.1.1`, `serverip=192.168.1.100`, polls `KEY_RESTORE` (`&gpio1 2`, active-low) for **5 s** (`0x4602d800`). If held, runs `downver version`, sleeps 2 s (`0x1e8480` µs), and runs `reset`. |
| `0x4600fb5c` (`run_command`) | Wraps `builtin_run_command` (`0x4600f820`) and maps `-1 → 1`, else `→ 0`. **Never returns `< 0`**, so `0x46012668` (`blt 0x46012680`) is dead code and `reset_key_recovery` **always calls `reset` even when `downver version` fails**. |
| `0x46011340` (`do_downver`) | For `downver version`: runs `tftp 42000000 $(fullfile)` (`fullfile=upgrade.bin`), checks `NetState == 2` (`0x4608b224`), `filesize < 0x2200000` (`0x4608d150`), outer magic `99999999 44444444 55555555 aaaaaaaa`, `header_crc` (`[0x3c:0x108] == [0x108]`), `payload_crc` (`[0x168:0x168+payload_sz] == [0x78]`), `ver_type == 0` (`[0x6a]`), reads `BootImageNum` (`0x46011128` → `0` = Slot 0 `kernel1`, `1` = Slot 1 `kernel2`), calls `flash_write` (`0x460112c8`: `nand_erase` + `nand_write`). **Zero RSA/signature verification.** |
| `0x46010c74` / `0x46010b5c` | Standard IEEE 802.3 CRC32 (`0x04c11db7`, matches Python `zlib.crc32()` 100%). |
| `0x4603ea2c` (Partition table) | 128 MiB SPI-NAND: `uboot` `0x00000000` (2 MiB), `kernel1` `0x01a00000` (32 MiB, part 2), `kernel2` `0x03a00000` (32 MiB, part 3), `others` `0x00200000` (4 MiB, part 6). |
| `0x46011a34` (`search_version`) | Scans 128 KiB blocks for outer magic + `header_crc`, requires `[0x11c] == 0`, sets `flags = 0x83` (`[0x120]==0xffffffff`) or `0x82` (`[0x120]==0x0`). |
| `0x46011cd4` (`select_and_fsload`) | Reads `BootImageNum` from `mtd2` (`others`, currently `0x00000000`), loads slot to `0x44000000`, checks magic + `payload_crc`, runs `fsload 0x44000000 0uImage` (`part->offset = 0x01a20000`, `part->size = total_size - 0x20000`). On failure, falls back to the alternate slot (`kernel2`). |
| `0x4601dd58` (`jffs2_1pass_load`) | Standard U-Boot JFFS2 loader supporting `NONE`, `ZERO`, `RTIME`, `DYNRUBIN`, `ZLIB` (`compr=6`). |

---

## 3. TFTP Recovery Analysis (`TftpHandler` OACK Auth Root Cause)

### Initial Observation
- Built OpenWrt `sanechips` Linux `6.18.55` images:
  - `openwrt-sanechips-generic-zte_zxhn-f6600p-initramfs.uImage` (9.67 MiB, `load=0x48008000`)
  - `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-factory.bin` (12.1 MiB, kernel `3.31 MiB` `load=0x40008000` + SquashFS at `+0x500000`)
  - `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-sysupgrade.bin`
- After initial TFTP recovery attempts with standard `dnsmasq`, live Telnet verification confirmed **both `mtd7` and `mtd8` were still untouched Stock** (`total_size=0x01580000`, `payload_crc=0xc87b9f31`).

### Root Cause Identified (`tcpdump` + `TftpHandler` `0x4602b380`)
- `tcpdump` captured the exact failure in 9 packets:
  - U-Boot sends `RRQ "upgrade.bin" octet timeout 5 blksize 1468`.
  - `dnsmasq` replies with `OACK blksize 1468`.
  - U-Boot **immediately aborts TFTP** (`NetState = 3`) without sending `ACK 0` or receiving any data, then sleeps 2 s and calls `reset`.
- Disassembling `TftpHandler` (`0x4602b380..0x4602b52c`) revealed that when Reset-button recovery is active (`0x46088418 == 1`), ZTE's U-Boot enforces a **custom TFTP OACK authentication check**:
  - Requires `user` and `pass` options in the TFTP `OACK` packet (`Get UserName or PassWord from Tftp failed!`), verified via AES-128 against `env_na` / `env_pa` (`UserName or PassWord ERROR! Not retrying...`).
  - Standard TFTP servers (`dnsmasq`) do not send `user`/`pass` OACK options, so U-Boot aborts before transferring a single data block.

### Summary of All Flashing Paths on Stock F6600P (`V9.1.10P2N7`)
1. **Stock Web UI (`httpd`):** Enforces ZTE signature verification (`/var/tmp/sign-cfg`).
2. **Stock Telnet (`tmadmin`):** Whitelisted BusyBox shell (`dd`, `tftp`, `fw_flashing` return `Access Denied`).
3. **U-Boot Reset-Button TFTP (`downver version`):** Requires ZTE's authenticated TFTP server (`user`/`pass` OACK options); stage-2 U-Boot UART is stubbed (no interactive prompt).
4. **Hardware SPI-NAND Programming (Unblocked):** Secure Boot is **OFF** (`non secure boot` / `non secure uboot`, zero RSA keys in SPL/U-Boot). Writing our verified OpenWrt `squashfs-factory.bin` (`-s 4096`) to `kernel1` (`0x01a00000`) via an external SPI-NAND programmer (e.g., XGecu T48 / CH341A) while keeping Stock untouched in `kernel2` (`0x03a00000`) will boot OpenWrt Linux `6.18.55` directly.


---

## 4. Successful Live Bring-Up on OpenWrt `6.18.55` (2026-11-23)

### A. `downver version` Container Verification (`0x4601155c..0x460117b0`)
- Disassembled `downver version` in stage-2 U-Boot (`mtd1_uboot.bin`, VMA `0x46000000`):
  - Expects our exact **`0x168`-header slot image** directly as `upgrade.bin` (no outer multi-partition wrapper) with **zero RSA/signature checks**.
  - Validates outer magic (`99999999 44444444 55555555 aaaaaaaa`), Header CRC32 (`0x03c..0x107` vs `0x108`), Payload CRC32 (`0x168..total_size` vs `0x078`), and `ver_type == 0` (`hdr[0x6a:0x6c]`).
  - Reads `BootImageNum` (`0`) and writes **only Slot 0 (`kernel1` @ `0x01a00000`)**. Because `fssize == 0` (`hdr[0x7c:0x80]`) and `uboot_en == 0` (`hdr[0xc8:0xca]`), `u-boot` (`mtd1`) and Stock `kernel2` (`mtd8`) are never touched.
  - Updated `port/pack_f6600p.py` to use `mkfs.jffs2 -s 0x1000` (4096 B, matching Stock `dsize=4096`) and capped `banner <= 32 B` so `hdr[0xc8:0xca]` stays `0000`.

### B. First Live Boot & Full Hardware Verification
- Flashed `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-factory.bin` (`12,713,984 B` / `12.12 MiB`) via Reset-button TFTP recovery (`~13.4 MB/s`), using ZTE TFTP OACK authentication.
- **Kernel & System:** `Linux OpenWrt 6.18.55 #0 SMP armv7l` booted cleanly on the first try; `248 MiB` usable RAM, `19.9 MiB` JFFS2 `/overlay` (`mtd4`, auto-split inside Slot 0 tail; `mtd5` renamed to read-only `pluginlog`).
- **Ethernet (1-to-1 Chassis Mapping Verified):**
  - Chassis **LAN1** → `wan` (`phy 0x0a`), factory WAN MAC (`+0x6e`, DHCP tested live against upstream `192.168.0.x` router).
  - Chassis **LAN2 / LAN3 / LAN4** → `lan1 / lan2 / lan3` (`phy 0x0b / 0x0c / 0x0d`), factory LAN MAC (`+0x62`), `1Gbps/Full`, hardware flow offload (`FFE/PPE`) active.
- **Dual-Band Wi-Fi 6 (`MT7916AN` AX3000):**
  - Both PCIe links (`14c3:7906` + `14c3:790a`) up; `/dev/mtdblock8` (`wlan` JFFS2 `caldata`, `196,608 B`) staged automatically via `11-mt76-caldata` + `e2631-wifi-eeprom` to `/lib/firmware/mediatek/mt7916_eeprom.bin`.
  - Both 2.4 GHz (`HE40`) and 5 GHz (`HE160` on Ch 100 / Ch 128, `MY` regdomain) verified stable at max TX power with 3 simultaneous clients (PC + 2 phones) once powered by a proper **12 V 5 A** supply. *(Note: an undersized 12 V adapter caused zero-oops brownout resets + `Boot NAND / no nand! ERR!!!` during Wi-Fi PA TX spikes.)*
- **Front-Panel LEDs (All 14 Entries / 13 Cutouts Verified):**
  - All active-low GPIOs matched 1-to-1 (`power` solid green, `lan1..lan4` + `wan` + `wlan` + `wlan5g` wired to `netdev` link/tx/rx triggers; `wps` is dual-color green/red).
- **Dual-Slot Stock Rollback:**
  - `x3060z-fwslot status` confirmed Slot 0 (`BootImageNum=0x00000000`) active and Stock `V9.1.10P2N7` untouched in Slot 1 (`kernel2`).

### C. Native `sysupgrade` (TFTP-Free Future Upgrades)
- Removed `read-only;` from Slot 0 (`kernel` + `rootfs`) in `port/dts/zx279128s-zte-f6600p.dts` (keeping `u-boot`, `kernel2`, `usercfg`, `middleware`, `plugin`, `pluginlog` `read-only`).
- Changed `IMAGE/sysupgrade.bin` in `port/image/Makefile.f6600p` to `f6600p-factory | append-metadata` (`FWx0` JSON metadata for `zte,zxhn-f6600p`).
- Added `port/base-files/lib/upgrade/platform.sh` (`platform_check_image()` validates outer magic, JFFS2/SquashFS magics, `uboot_en == 0000`, and 128 KiB-aligned `total_size`; `platform_do_upgrade()` writes `kernel` 5 MiB and erases/writes `rootfs` via `mtd`).
- Flashed the `sysupgrade`-enabled image via one final TFTP flash; all subsequent OpenWrt upgrades (e.g., enabling USB 3.0, installing packages/builds) can be performed directly via LuCI (`System → Backup / Flash Firmware`) or `sysupgrade` over SSH.

### D. USB 2.0 / 3.0 SuperSpeed & `iperf3` Verification
- Enabled `&usb` (`dwc3 @ 0x09100000`, GIC SPI 50 / IRQ 82) in `port/dts/zx279128s-zte-f6600p.dts`, added `kmod-usb3`, `kmod-usb-dwc3`, `kmod-usb-storage`, `kmod-usb-ledtrig-usbport`, `kmod-fs-ext4`, `kmod-fs-vfat` (+ NLS), `usbutils`, and `iperf3` to `port/image/Makefile.f6600p`, and wired `f6600p:green:usb` (`usbport`) in `port/base-files/etc/board.d/01_leds`.
- **Native LuCI `sysupgrade` verified live:** Flashed `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-sysupgrade.bin` (`13.00 MiB`) directly via LuCI (`System → Backup / Flash Firmware`) with zero TFTP required, then restored settings from backup archive cleanly.
- **USB 3.0 SuperSpeed (`5 Gbps`) + USB 2.0 (`480 Mbps`) verified live:** Added `CONFIG_USB_DWC3_GENERIC_PLAT=y` to `target/linux/sanechips/config-6.18` (and persisted `dwc3-generic-plat.ko` on the running board); verified Genesys Logic USB 3.0 Hub (`05e3:0626` @ `5000M`) + USB 2.0 Hub (`05e3:0610` @ `480M`) + FAT32 pen drive (`/dev/sda1`, `ESD-USB`).
- **`iperf3` Wi-Fi 6 ↔ GbE baseline (pre-IDM v1.0):** ~500 Mbps upload (phone → wired GbE host) and ~153 Mbps avg / 227 Mbps peak download (`-R` at 20 dBm, CPU-bound without HW Wi-Fi offload); zero crashes across sustained traffic.
- **UART no longer required:** All administration, upgrades, and recovery work over Ethernet/Wi-Fi (SSH, LuCI `sysupgrade`, `x3060z-fwslot`, or Reset-button TFTP).

---

## 5. `v2.0` Update — IDM/NPP + PPE Wi-Fi Hardware Offload & `ZX279128S` Fixes (2026-11-25)

- **IDM/NPP + PPE Wi-Fi ↔ Ethernet Hardware Offload (`GIC_SPI 38`):** Added `<GIC_SPI 38 IRQ_TYPE_LEVEL_HIGH>` to `&gmac` in `port/dts/zx279128s-zte-f6600p.dts`, enabling the `ZX279128S` Integrated DMA (`0x921c8000`) fastpath with `page_pool` zero-copy recycling and HW PPE resolution for `phy0-ap0` (`bp6`) and `phy1-ap0` (`bp7`).
- **`ZX279128S` vs `ZX279128R` Ethernet Init Gating:** Gated `ZX279128R`-specific NPP/TM/SMCT (`11/220/200`) and per-port MAC-reset register init in `zx279128s-main.c` on `of_machine_is_compatible("zte,zx279128r")`, preserving clean Gigabit RX/TX on `ZX279128S` (`plat-zxylzb_9128S.ko` defaults).
- **On-Die Thermal Sensor:** Live SoC temperature exposed at `/sys/class/thermal/thermal_zone0/temp` (`temp@94100034`) alongside `MT7916AN` `hwmon` sensors.
- **Verified live on hardware:** `wan` (`LAN1`) + `lan1..3` (`LAN2..4`) Gigabit full-duplex, `ppe_flows` active, `idm_wifi_devs=phy0-ap0(bp6,s0) phy1-ap0(bp7,s0)`, `hw_resets=0`, persistent `19.0 MiB` `/overlay`.
