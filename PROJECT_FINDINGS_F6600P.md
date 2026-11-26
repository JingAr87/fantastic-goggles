# ZTE ZXHN F6600P (ZX279128S + MT7916AN) — Complete OpenWrt Porting Report

**Date:** 2026-11-21  
**Device Under Test:** ZTE `ZXHN F6600P` (TM / Unifi Malaysia AX3000 GPON ONT)  
**Hardware Revision:** `V9.1.41` (Board ID `0x95`)  
**Stock Firmware:** `ZXHN F6600P UNI V9.1.10P2N7` (Linux `4.1.25`, built `2025-09-04`)  
**Bootloader:** `U-Boot V9.1.10P10N9` (`20250904100727`, **Non-Secure U-Boot**)  
**Factory MACs (`/tagparam/paramtag`):** LAN MAC at `+0x62` / WAN MAC at `+0x6e` (6 sequential factory MACs + `ZTEG` GPON serial)  
**Build Target:** OpenWrt `sanechips` (`Linux 6.18.55`, dual Cortex-A9 soft-float)

---

## 1. Hardware & Stage 2 Feasibility Summary

| Subsystem | Verified F6600P Specification | OpenWrt `sanechips` Porting Notes |
| :--- | :--- | :--- |
| **SoC** | ZTE / Sanechips `ZX279128S` (dual Cortex-A9 `0xc09`, soft-float) | Identical target (`CONFIG_SOFT_FLOAT=y`, `zte,l2c-io-read-lock`) |
| **RAM** | `256 MiB` DDR3 (`0x40000000`–`0x4fffffff`, `mem=256M`) | Identical to `DIR-X1860Z` / `DIR-X3060Z` |
| **SPI-NAND** | `128 MiB` (`0x08000000`, 2 KiB page, 128 KiB eraseblock) | Dual `32 MiB` slots (`kernel1` @ `0x01a00000`, `kernel2` @ `0x03a00000`) |
| **Bootloader** | `U-Boot V9.1.10P10N9` (**Non-Secure U-Boot**) | `verify_image()` (`0x4602cea4`) has 0 callers; SPL/stage-2 have zero RSA signatures; `/0uImage` is an unsigned legacy `uImage` |
| **Wi-Fi 6** | MediaTek `MT7916AN` (`0x14c3:0x7906` + ext-HIF `0x14c3:0x790a`) | `kmod-mt7915e` + `kmod-mt7916-firmware`; reset `&gpio3 7` (`slot 45 WLAN_MT7613_RST`); caldata `/wlan/caldata` (`196,608` B, magic `16 79`, `0x190=0x12`) |
| **Ethernet** | 4× integrated GbE PHYs (`gphy0..3`, GIC 71–74) | `plat-zxylzb_9128S.ko` `uni_phy` = `{0x0a, 0x0b, 0x0c, 0x0d}`; mapped `phy10=wan`, `phy11..13=lan1..3` |
| **USB** | USB 2.0 (`dwc2_hsotg`, GIC 76) + USB 3.0 (`xhci-hcd`, GIC 82) | `&usb` (`zte,zx279128s-dwc3`) enabled in DTS (`status = "okay"`) |
| **GPON** | Integrated PON MAC + `bob_GN25L95_gpon.bin` | Unused on OpenWrt; Stock stays intact in Slot 0 (`kernel1`) |

---

## 2. SPI-NAND Flash Layout & Dual-Slot Boot Strategy

Extracted directly from `vmlinux.bin` (`0x4fd118`):

| Stock Offset | Size | Stock Name | OpenWrt DTS Partition (`mtdN`) & Purpose |
| :--- | ---: | :--- | :--- |
| `0x00000000` | `2 MiB` | `u-boot` | `mtd0`: `u-boot` (`read-only`) |
| `0x03a00000` | `5 MiB` | `kernel2[0..5M]` | `mtd1`: `kernel` (`0x168` header + JFFS2 `/0uImage`, `read-only`) |
| `0x01a00000` | `32 MiB` | `kernel1` | `mtd2`: `kernel1` (**Stock Slot 0 — untouched for rollback**, `read-only`) |
| `0x03f00000` | `27 MiB` | `kernel2[5..32M]` | `mtd3`: `rootfs` (**SquashFS `/dev/mtdblock3`**, `read-only`) |
| `0x05c00000` | `20 MiB` | `Pluginlog` (empty) | `mtd4`: `rootfs_data` (writable JFFS2 overlay, verified `0` non-`0xFF` bytes in stock) |
| `0x00200000` | `4 MiB` | `others` | `mtd5`: `others` (`BootImageNum=0x00000000` / `0x00000001` selector) |
| `0x00600000` | `4 MiB` | `parameter tags` | `mtd6`: `tagparam` (JFFS2 `/tagparam/paramtag`) |
| `0x00a00000` | `4 MiB` | `wlan` | `mtd7`: `wlan` (JFFS2 `/wlan/caldata`) |
| `0x00e00000` | `8 MiB` | `usercfg` | `mtd8`: `usercfg` (`read-only`) |
| `0x01600000` | `4 MiB` | `middleware` | `mtd9`: `middleware` (`read-only`) |
| `0x05a00000` | `2 MiB` | `Plugin` | `mtd10`: `plugin` (`read-only`) |

Placing `rootfs_data` in the empty `Pluginlog` (`0x05c00000`) keeps runtime writes out of `kernel2` (`0x03a00000`), preserving U-Boot's payload CRC32 over `kernel2` and avoiding extra JFFS2 nodes during `fsload 0x44000000 0uImage`.

---

## 3. F6600P `0x168` Firmware Container & Packer (`port/pack_f6600p.py`)

Disassembled stage-2 U-Boot `V9.1.10P10N9` and verified against `backup_f6600p/mtd7_kernel1.bin` & `mtd8_kernel2.bin`:
- **`0x168` (`360`-byte) header:** Magic `99999999 44444444 55555555 aaaaaaaa`, `hdr_ofs = 0x28` at `+0x010`, software version at `+0x04c`, `image_type = 1` at `+0x068`, `total_size` at `+0x06c`/`+0x080`, `payload_size = total_size - 0x168` at `+0x070`, `payload_offset = 0x168` at `+0x074`, `payload_crc = crc32(image[0x168:total_size])` at `+0x078`, slot geometry at `+0x088..+0x0a7`, banner at `+0x0a8`, `header_crc = crc32(hdr[0x03c:0x108])` at `+0x108`, completion words at `+0x120..+0x127` (`0xffffffff, 0xffffffff` for Slot 0; `0x00000000, 0xffffffff` for Slot 1), and 64-byte flash metadata tail at `+0x128..+0x167`.
- **Self-test (`python port/pack_f6600p.py selftest`):** Reconstructs both `mtd7_kernel1.bin` and `mtd8_kernel2.bin` headers with **`360/360` byte-exact match** (`payload_crc=0xc87b9f31`).
- **Slot 1 layout in `factory.bin`:**
  - `[0x000000..0x020000)`: `0x168` header zero-padded to 128 KiB
  - `[0x020000..0x500000)`: JFFS2 filesystem containing `/0uImage` (`mkfs.jffs2 -l -e 0x20000 -s 0x800 -n -p`, `0xFF`-padded)
  - `[0x500000..total_size)`: SquashFS rootfs (`hsqs`, aligned to 128 KiB)

---

## 4. Verified GPIO Map (`vmlinux.bin @ 0xc070ba2c`, `F6600P V9.1.41`, `bid=0x95`)

- **LEDs (`GPIO_ACTIVE_LOW`):**
  - `led-power`: `&gpio0 5` (`slot 16`, `default-state = "on"`)
  - `led-wan`: `&gpio3 12` (`slot 12`), `led-pon`: `&gpio2 8` (`slot 13`), `led-los`: `&gpio0 8` (`slot 14`)
  - `led-wlan` (2.4G): `&gpio0 10` (`slot 15`), `led-wlan5g` (5G): `&gpio1 5` (`slot 43`)
  - `led-wps-green`: `&gpio0 0` (`slot 11`), `led-wps-red`: `&gpio2 9` (`slot 10`)
  - `led-usb`: `&gpio3 15` (`slot 8`), `led-phone`: `&gpio3 5` (`slot 20`)
  - `led-lan1..4`: `&gpio3 8..11` (`slots 22..25`)
- **Buttons (`gpio-keys-polled`, `poll-interval = <50>`, `GPIO_ACTIVE_LOW`):**
  - `reset`: `&gpio1 2` (`slot 27`, `KEY_RESTART`)
  - `wps`: `&gpio0 3` (`slot 29`, `KEY_WPS_BUTTON`)
  - `wlan`: `&gpio0 1` (`slot 32`, `KEY_RFKILL`)
- **PCIe Wi-Fi Reset:** `pcie0` uses `reset-gpios = <&gpio3 7 GPIO_ACTIVE_LOW>` (`slot 45: WLAN_MT7613_RST`).

---

## 5. Initial Build & Pre-Flight Verification Results (`2026-11-21`)

Built with OpenWrt `sanechips` (`CONFIG_TARGET_DEVICE_sanechips_generic_DEVICE_zte_zxhn-f6600p=y`, Linux `6.18.55`):

| Built Artifact | Size (Bytes) | Pre-Flight Verification |
| :--- | ---: | :--- |
| `openwrt-sanechips-generic-zte_zxhn-f6600p-initramfs.uImage` | `10,144,433` | `uImage` `load=0x48008000`, `ep=0x48008000`, `hcrc=True`, `dcrc=True`, model `'ZTE ZXHN F6600P'` |
| `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-factory.bin` | `12,713,984` (`12.12 MiB`) | `pack_f6600p.py info` PASS: `hdr_crc=0xd3ec318d` OK, `pay_crc=0x63963cc4` OK, JFFS2 `8519` at `+0x20000`, `/0uImage` (`3,467,137` B, `load=0x40008000`, `hcrc=True`, `dcrc=True`, model `'ZTE ZXHN F6600P'`), SquashFS `hsqs` at `+0x500000`, DTB partitions ordered with `rootfs` at `mtdblock3` |
| `openwrt-sanechips-generic-zte_zxhn-f6600p-squashfs-sysupgrade.bin` | `10,875,145` | Generated by `make target/linux/install` |

*(See `BRINGUP_LOG_F6600P.md` for live hardware bring-up, Slot 0 flashing, USB 3.0 enablement, native LuCI `sysupgrade`, and `v2.0` IDM+PPE hardware offload verification.)*
