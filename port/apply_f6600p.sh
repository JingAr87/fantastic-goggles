#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Layer ZTE F6600P DTS, 0x168 packer, image Makefile, and additive base-files
# onto an existing sanechips OpenWrt build tree without disrupting D-Link targets.

set -eu

TREE="${1:-openwrt}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ -d "$TREE/target/linux/sanechips" ] || {
	echo "ERROR: $TREE/target/linux/sanechips not found." >&2
	exit 1
}

echo "[1/4] Installing F6600P Device Tree..."
cp "$HERE/dts/zx279128s-zte-f6600p.dts" \
   "$TREE/target/linux/sanechips/dts/zx279128s-zte-f6600p.dts"

echo "[2/4] Updating sanechips base-files additively for F6600P..."
BF="$TREE/target/linux/sanechips/base-files"
cp "$HERE/base-files/etc/hotplug.d/firmware/11-mt76-caldata" "$BF/etc/hotplug.d/firmware/11-mt76-caldata"
cp "$HERE/base-files/etc/board.d/01_leds" "$BF/etc/board.d/01_leds"
cp "$HERE/base-files/etc/board.d/02_network" "$BF/etc/board.d/02_network"
cp "$HERE/base-files/sbin/x3060z-fwslot" "$BF/sbin/x3060z-fwslot"
chmod +x \
	"$BF/etc/hotplug.d/firmware/11-mt76-caldata" \
	"$BF/etc/board.d/01_leds" \
	"$BF/etc/board.d/02_network" \
	"$BF/sbin/x3060z-fwslot"

echo "[3/4] Installing F6600P 0x168 firmware packer (tools/pack_f6600p.py)..."
cp "$HERE/pack_f6600p.py" "$TREE/tools/pack_f6600p.py"
chmod +x "$TREE/tools/pack_f6600p.py"

echo "[4/4] Wiring image/Makefile.f6600p into target/linux/sanechips/image/Makefile..."
cp "$HERE/image/Makefile.f6600p" "$TREE/target/linux/sanechips/image/Makefile.f6600p"
IMG="$TREE/target/linux/sanechips/image/Makefile"
if ! grep -q 'Makefile.f6600p' "$IMG"; then
	sed -i 's|^$(eval $(call BuildImage))$|include $(TOPDIR)/target/linux/sanechips/image/Makefile.f6600p\n\n$(eval $(call BuildImage))|' "$IMG"
fi

echo "Done! Enable CONFIG_TARGET_DEVICE_sanechips_generic_DEVICE_zte_zxhn-f6600p=y and build."
