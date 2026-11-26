# SPDX-License-Identifier: GPL-2.0-only
# Native sysupgrade support for ZTE ZXHN F6600P (Slot 0: kernel + rootfs).
# Rewrites Slot 0 in place; u-boot (mtd0) and Stock kernel2 (mtd2) are read-only
# and never touched.

PART_NAME=firmware
REQUIRE_IMAGE_METADATA=1

f6600p_check_image() {
	local img="$1"
	local magic jffs2_magic sq_magic uboot_en total_size file_size

	magic=$(hexdump -v -n 16 -e '16/1 "%02x"' "$img" 2>/dev/null)
	if [ "$magic" != "999999994444444455555555aaaaaaaa" ]; then
		echo "Invalid F6600P outer magic: $magic" >&2
		return 1
	fi

	jffs2_magic=$(hexdump -v -s 131072 -n 2 -e '2/1 "%02x"' "$img" 2>/dev/null)
	if [ "$jffs2_magic" != "8519" ]; then
		echo "Invalid JFFS2 magic at 0x20000: $jffs2_magic" >&2
		return 1
	fi

	sq_magic=$(hexdump -v -s 5242880 -n 4 -e '4/1 "%02x"' "$img" 2>/dev/null)
	if [ "$sq_magic" != "68737173" ]; then
		echo "Invalid SquashFS magic at 0x500000: $sq_magic" >&2
		return 1
	fi

	uboot_en=$(hexdump -v -s 200 -n 2 -e '2/1 "%02x"' "$img" 2>/dev/null)
	if [ "$uboot_en" != "0000" ]; then
		echo "Refusing image with non-zero u-boot flag: $uboot_en" >&2
		return 1
	fi

	total_size=$(hexdump -v -s 108 -n 4 -e '1/4 "%u"' "$img" 2>/dev/null)
	file_size=$(wc -c < "$img" 2>/dev/null || echo 0)
	if [ -z "$total_size" ] || [ "$total_size" -le 5242880 ] || \
	   [ "$total_size" -gt 33554432 ] || [ $((total_size % 131072)) -ne 0 ] || \
	   [ "$file_size" -lt "$total_size" ]; then
		echo "Invalid F6600P total_size=$total_size (file_size=$file_size)" >&2
		return 1
	fi

	return 0
}

platform_check_image() {
	[ "$#" -gt 1 ] && return 1

	case "$(board_name)" in
	zte,zxhn-f6600p)
		f6600p_check_image "$1"
		return $?
		;;
	*)
		echo "Sysupgrade is not implemented for $(board_name)" >&2
		return 1
		;;
	esac
}

platform_do_upgrade() {
	local img="$1"
	local total_size rootfs_blocks

	case "$(board_name)" in
	zte,zxhn-f6600p)
		total_size=$(hexdump -v -s 108 -n 4 -e '1/4 "%u"' "$img")
		rootfs_blocks=$(( (total_size - 5242880) / 131072 ))

		echo "f6600p-upgrade: writing kernel (5 MiB) to mtd 'kernel'..."
		dd if="$img" bs=131072 count=40 2>/dev/null | mtd write - kernel

		echo "f6600p-upgrade: erasing & writing rootfs ($rootfs_blocks x 128 KiB) to mtd 'rootfs'..."
		dd if="$img" bs=131072 skip=40 count="$rootfs_blocks" 2>/dev/null | \
			mtd -e rootfs write - rootfs
		;;
	esac
}
