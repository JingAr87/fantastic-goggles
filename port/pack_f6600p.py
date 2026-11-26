#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""
ZTE ZXHN F6600P (ZX279128S, U-Boot V9.1.10P10N9) 0x168 Firmware Packer & Verifier.

Verified against live mtd7_kernel1.bin (Slot 0) and mtd8_kernel2.bin (Slot 1) dumps
plus disassembled stage-2 U-Boot V9.1.10P10N9:

  Header size : 360 bytes (0x168), zero-padded to the first 128 KiB erase block
                (0x20000).
  Header CRC32: IEEE 802.3 CRC32 over header[0x03c : 0x108] (204 bytes), stored
                little-endian at header[0x108 : 0x10c].
  Payload     : [0x000168 .. 0x020000): zero-padded to eraseblock 1
                [0x020000 .. 0x500000): JFFS2 image containing /0uImage (0xFF padded)
                [0x500000 .. total)   : SquashFS rootfs (padded to 128 KiB eraseblock)
  Payload CRC : IEEE 802.3 CRC32 over image[0x168 : total_size], stored LE at 0x078.

Commands:
  python pack_f6600p.py selftest [--backup-dir <dir>]
  python pack_f6600p.py info --image <file>
  python pack_f6600p.py pack --kernel <uImage> --rootfs <squashfs> --out <factory.bin> [--mkfs-jffs2 <path>]
"""

import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HEADER_SIZE = 0x168
ERASE_BLOCK = 0x20000
KERNEL_REGION_SIZE = 0x500000
JFFS2_MAX_SIZE = KERNEL_REGION_SIZE - ERASE_BLOCK
SLOT_MAX_SIZE = 0x2000000

OUTER_MAGIC = bytes.fromhex("999999994444444455555555aaaaaaaa")
UIMAGE_MAGIC = bytes.fromhex("27051956")
SQUASHFS_MAGIC = b"hsqs"

SLOT_GEOMETRY = struct.pack(
    "<8I",
    0x01A00000, 0x02000000, 0x00000000, 0x00000000,  # Slot 0: kernel1
    0x03A00000, 0x02000000, 0x00000000, 0x00000000,  # Slot 1: kernel2
)

TAIL_META = bytes.fromhex(
    "00000008ffff01000000000000000000"
    "00000000000022020000020000002022"
    "2622204e23222202"
    + "ff" * 24
)


def crc32_u32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def align_up(val: int, align: int) -> int:
    return (val + align - 1) & ~(align - 1)


def put_str(buf: bytearray, offset: int, max_len: int, text: str) -> None:
    raw = text.encode("ascii")
    if len(raw) > max_len:
        raise ValueError(f"String {text!r} exceeds {max_len}-byte field at 0x{offset:03x}")
    buf[offset : offset + max_len] = b"\x00" * max_len
    buf[offset : offset + len(raw)] = raw


def build_header(
    total_size: int,
    payload_crc: int,
    version: str = "V9.1.10P2N7",
    banner: str = "ZXHN F6600P UNI V9.1.10P2N7",
    build_date: str = "20250904100727",
    image_type: int = 1,
    completion_w0: int = 0x00000000,
    completion_w1: int = 0xFFFFFFFF,
) -> bytes:
    """Construct the exact 360-byte (0x168) F6600P slot header."""
    if total_size <= HEADER_SIZE:
        raise ValueError(f"Invalid total_size=0x{total_size:x}")

    hdr = bytearray(HEADER_SIZE)
    hdr[0x000:0x010] = OUTER_MAGIC
    struct.pack_into("<I", hdr, 0x010, 0x28)  # hdr_ofs = 40

    put_str(hdr, 0x04C, 28, version)
    struct.pack_into("<I", hdr, 0x068, image_type)
    struct.pack_into("<I", hdr, 0x06C, total_size)
    struct.pack_into("<I", hdr, 0x070, total_size - HEADER_SIZE)
    struct.pack_into("<I", hdr, 0x074, HEADER_SIZE)
    struct.pack_into("<I", hdr, 0x078, payload_crc)
    struct.pack_into("<I", hdr, 0x080, total_size)

    hdr[0x088:0x0A8] = SLOT_GEOMETRY
    put_str(hdr, 0x0A8, 32, banner)  # Keep <=32B so [0x0C8:0x0CA] stays 0 (no u-boot update in downver)
    struct.pack_into("<I", hdr, 0x104, 1)
    put_str(hdr, 0x10C, 16, build_date)
    struct.pack_into("<2I", hdr, 0x120, completion_w0, completion_w1)
    hdr[0x128:0x168] = TAIL_META

    hdr_crc = crc32_u32(hdr[0x03C:0x108])
    struct.pack_into("<I", hdr, 0x108, hdr_crc)
    return bytes(hdr)


def parse_uimage_info(uimg: bytes) -> dict:
    if len(uimg) < 64 or uimg[:4] != UIMAGE_MAGIC:
        raise ValueError("Missing uImage magic 0x27051956")
    magic, hcrc, ts, sz, load, ep, dcrc, os_, arch, typ, comp, name = struct.unpack(
        ">7I4B32s", uimg[:64]
    )
    hdr_zero = bytearray(uimg[:64])
    hdr_zero[4:8] = b"\x00\x00\x00\x00"
    calc_hcrc = crc32_u32(hdr_zero)
    calc_dcrc = crc32_u32(uimg[64 : 64 + sz])
    fdt_off = uimg.find(b"\xd0\x0d\xfe\xed", 64)
    model = None
    if fdt_off != -1:
        m_idx = uimg.find(b"ZTE ZXHN F6600P", fdt_off)
        if m_idx != -1:
            model = uimg[m_idx : m_idx + 15].decode("ascii")
    return {
        "size": sz,
        "load": load,
        "ep": ep,
        "hcrc_ok": hcrc == calc_hcrc,
        "dcrc_ok": dcrc == calc_dcrc,
        "name": name.rstrip(b"\x00").decode("ascii", "replace"),
        "fdt_off": fdt_off,
        "model": model,
    }


def extract_jffs2_0uimage(region: bytes) -> bytes | None:
    """Scan JFFS2 nodes in `region` and reassemble `/0uImage`."""
    pos = 0
    dirents = {}
    inodes = {}
    n = len(region)
    while pos + 12 <= n:
        magic, nodetype, totlen = struct.unpack_from("<HHI", region, pos)
        if magic != 0x1985:
            if region[pos : pos + 4] == b"\xff\xff\xff\xff":
                nxt = align_up(pos + 1, ERASE_BLOCK)
                if nxt == pos:
                    nxt += ERASE_BLOCK
                pos = min(nxt, n)
            else:
                pos += 4
            continue
        if totlen < 12 or pos + totlen > n:
            break
        if nodetype == 0xE001:  # DIRENT
            pino, ver, ino, _mctime, nsize = struct.unpack_from("<IIIIB", region, pos + 12)
            name = region[pos + 40 : pos + 40 + nsize].decode("ascii", "replace")
            dirents[name] = ino
        elif nodetype == 0xE002:  # INODE
            ino, ver = struct.unpack_from("<II", region, pos + 12)
            isize = struct.unpack_from("<I", region, pos + 28)[0]
            offset, csize, dsize, compr = struct.unpack_from("<IIIB", region, pos + 44)
            inodes.setdefault(ino, []).append((ver, offset, csize, dsize, compr, isize, pos + 68))
        pos += align_up(totlen, 4)

    target_ino = dirents.get("0uImage")
    if target_ino is None or target_ino not in inodes:
        return None
    frags = sorted(inodes[target_ino], key=lambda x: x[0])
    isize = frags[-1][5]
    out = bytearray(isize)
    for _ver, offset, csize, dsize, compr, _isz, data_off in frags:
        raw = region[data_off : data_off + csize]
        if compr == 0:
            dec = raw
        elif compr == 6:
            dec = zlib.decompress(raw)
        elif compr == 1:
            dec = b"\x00" * dsize
        else:
            raise ValueError(f"Unsupported JFFS2 compression type {compr}")
        out[offset : offset + len(dec)] = dec[: len(out) - offset]
    return bytes(out)


def cmd_selftest(args: argparse.Namespace) -> int:
    for fname, cw0, label in [
        ("mtd7_kernel1.bin", 0xFFFFFFFF, "Slot 0 (kernel1)"),
        ("mtd8_kernel2.bin", 0x00000000, "Slot 1 (kernel2)"),
    ]:
        path = os.path.join(args.backup_dir, fname)
        if not os.path.exists(path):
            print(f"ERROR: {path} not found", file=sys.stderr)
            return 1
        data = open(path, "rb").read()
        orig_hdr = data[:HEADER_SIZE]
        total_sz = struct.unpack_from("<I", orig_hdr, 0x06C)[0]
        pay_off = struct.unpack_from("<I", orig_hdr, 0x074)[0]
        pay_sz = struct.unpack_from("<I", orig_hdr, 0x070)[0]
        pay_crc = crc32_u32(data[pay_off : pay_off + pay_sz])
        rebuilt = build_header(
            total_size=total_sz,
            payload_crc=pay_crc,
            completion_w0=cw0,
            completion_w1=0xFFFFFFFF,
        )
        matches = sum(1 for a, b in zip(orig_hdr, rebuilt) if a == b)
        print(f"{label}: {matches}/{HEADER_SIZE} header bytes identical, payload_crc=0x{pay_crc:08x}")
        if matches != HEADER_SIZE:
            for i, (a, b) in enumerate(zip(orig_hdr, rebuilt)):
                if a != b:
                    print(f"  diff @ 0x{i:03x}: orig=0x{a:02x} rebuilt=0x{b:02x}")
            return 1
    print("SELFTEST PASSED: 360/360 byte-exact match on both F6600P slots!")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    data = open(args.image, "rb").read()
    if len(data) < ERASE_BLOCK or data[:16] != OUTER_MAGIC:
        raise SystemExit("ERROR: invalid outer magic or file too small")

    hdr = data[:HEADER_SIZE]
    hdr_ofs = struct.unpack_from("<I", hdr, 0x010)[0]
    img_type = struct.unpack_from("<I", hdr, 0x068)[0]
    total_sz, pay_sz, pay_off, pay_crc = struct.unpack_from("<4I", hdr, 0x06C)
    hdr_crc = struct.unpack_from("<I", hdr, 0x108)[0]
    calc_hcrc = crc32_u32(hdr[0x03C:0x108])
    calc_pcrc = crc32_u32(data[pay_off : pay_off + pay_sz])
    ver = hdr[0x04C:0x068].split(b"\x00")[0].decode("ascii", "replace")
    banner = hdr[0x0A8:0x0EC].split(b"\x00")[0].decode("ascii", "replace")
    cw0, cw1 = struct.unpack_from("<2I", hdr, 0x120)

    print(f"Image        : {args.image} ({len(data)} B, {len(data)/1048576:.2f} MiB)")
    print(f"Version      : {ver!r} | Banner: {banner!r}")
    print(f"Header       : hdr_ofs=0x{hdr_ofs:x} type={img_type} cw=({cw0:#010x}, {cw1:#010x})")
    print(f"Header CRC32 : 0x{hdr_crc:08x} (calc 0x{calc_hcrc:08x}) -> {'OK' if hdr_crc == calc_hcrc else 'FAIL'}")
    print(f"Payload      : off=0x{pay_off:x} size=0x{pay_sz:x} total=0x{total_sz:x}")
    print(f"Payload CRC32: 0x{pay_crc:08x} (calc 0x{calc_pcrc:08x}) -> {'OK' if pay_crc == calc_pcrc else 'FAIL'}")

    assert hdr_crc == calc_hcrc, "Header CRC32 mismatch"
    assert pay_crc == calc_pcrc, "Payload CRC32 mismatch"
    assert total_sz <= SLOT_MAX_SIZE, f"Image exceeds 32 MiB slot ({total_sz})"
    assert all(b == 0 for b in data[HEADER_SIZE:ERASE_BLOCK]), "Header padding [0x168:0x20000] not zero"

    jffs2_magic = data[ERASE_BLOCK : ERASE_BLOCK + 2]
    print(f"JFFS2 @ 0x20000: magic={jffs2_magic.hex()}")
    assert jffs2_magic == b"\x85\x19", "Missing JFFS2 magic at 0x20000"

    uimg = extract_jffs2_0uimage(data[ERASE_BLOCK:KERNEL_REGION_SIZE])
    assert uimg is not None, "/0uImage not found in JFFS2 partition"
    uinfo = parse_uimage_info(uimg)
    print(
        f"/0uImage     : {len(uimg)} B, load=0x{uinfo['load']:08x}, ep=0x{uinfo['ep']:08x}, "
        f"hcrc={uinfo['hcrc_ok']}, dcrc={uinfo['dcrc_ok']}, model={uinfo['model']!r}"
    )
    assert uinfo["hcrc_ok"] and uinfo["dcrc_ok"], "uImage CRC failure"

    if len(data) > KERNEL_REGION_SIZE:
        sq_magic = data[KERNEL_REGION_SIZE : KERNEL_REGION_SIZE + 4]
        print(f"Rootfs @ 0x500000: magic={sq_magic!r}")
        assert sq_magic == SQUASHFS_MAGIC, f"Missing SquashFS magic at 0x500000 (got {sq_magic!r})"
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    uimg = open(args.kernel, "rb").read()
    uinfo = parse_uimage_info(uimg)
    if not (uinfo["hcrc_ok"] and uinfo["dcrc_ok"]):
        raise SystemExit("ERROR: input kernel uImage has invalid CRC")

    rootfs = open(args.rootfs, "rb").read()
    if rootfs[:4] != SQUASHFS_MAGIC:
        raise SystemExit(f"ERROR: rootfs does not start with SquashFS 'hsqs' magic (got {rootfs[:4]!r})")

    mkfs = args.mkfs_jffs2 or shutil.which("mkfs.jffs2")
    if not mkfs or not os.path.exists(mkfs):
        raise SystemExit(f"ERROR: mkfs.jffs2 not found ({mkfs})")

    with tempfile.TemporaryDirectory() as tmpdir:
        root_dir = os.path.join(tmpdir, "root")
        os.makedirs(root_dir)
        shutil.copy2(args.kernel, os.path.join(root_dir, "0uImage"))
        jffs2_path = os.path.join(tmpdir, "kernel.jffs2")
        subprocess.run(
            [
                mkfs,
                "-l",
                "-e", "0x20000",
                "-s", "0x1000",
                "-n",
                "-p",
                "-d", root_dir,
                "-o", jffs2_path,
            ],
            check=True,
        )
        jffs2_data = open(jffs2_path, "rb").read()

    if len(jffs2_data) > JFFS2_MAX_SIZE:
        raise SystemExit(
            f"ERROR: JFFS2 kernel image ({len(jffs2_data)} B) exceeds 0x{JFFS2_MAX_SIZE:x} B limit"
        )

    rootfs_padded = rootfs + b"\xff" * (align_up(len(rootfs), ERASE_BLOCK) - len(rootfs))
    total_size = KERNEL_REGION_SIZE + len(rootfs_padded)
    if total_size > SLOT_MAX_SIZE:
        raise SystemExit(f"ERROR: total slot image ({total_size} B) exceeds 32 MiB slot")

    buf = bytearray(b"\xff" * total_size)
    buf[0:ERASE_BLOCK] = b"\x00" * ERASE_BLOCK
    buf[ERASE_BLOCK : ERASE_BLOCK + len(jffs2_data)] = jffs2_data
    buf[KERNEL_REGION_SIZE : KERNEL_REGION_SIZE + len(rootfs_padded)] = rootfs_padded

    pay_crc = crc32_u32(buf[HEADER_SIZE:total_size])
    hdr = build_header(
        total_size=total_size,
        payload_crc=pay_crc,
        version=args.version,
        banner=args.banner,
        build_date=args.build_date,
        completion_w0=0xFFFFFFFF if args.slot == 0 else 0x00000000,
        completion_w1=0xFFFFFFFF,
    )
    buf[0:HEADER_SIZE] = hdr

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(buf)
    print(
        f"Packed {args.out}: total={total_size} B (jffs2={len(jffs2_data)} B, "
        f"rootfs={len(rootfs)} B -> {len(rootfs_padded)} B), payload_crc=0x{pay_crc:08x}"
    )
    return 0


def main() -> int:
    default_backup = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "backup_f6600p")
    )
    p = argparse.ArgumentParser(description="ZTE F6600P 0x168 Firmware Packer & Verifier")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_st = sub.add_parser("selftest", help="Verify 360/360 byte-exact header against backup dumps")
    sp_st.add_argument("--backup-dir", default=default_backup)
    sp_st.set_defaults(func=cmd_selftest)

    sp_in = sub.add_parser("info", help="Verify and inspect a packed F6600P slot image")
    sp_in.add_argument("--image", required=True)
    sp_in.set_defaults(func=cmd_info)

    sp_pk = sub.add_parser("pack", help="Build a F6600P factory/slot image (0x168 + JFFS2 /0uImage + SquashFS)")
    sp_pk.add_argument("--kernel", required=True, help="Input legacy uImage (zImage + DTB)")
    sp_pk.add_argument("--rootfs", required=True, help="Input SquashFS rootfs")
    sp_pk.add_argument("--out", required=True, help="Output slot factory.bin")
    sp_pk.add_argument("--mkfs-jffs2", default="", help="Path to mkfs.jffs2")
    sp_pk.add_argument("--slot", type=int, choices=[0, 1], default=1)
    sp_pk.add_argument("--version", default="V9.1.10P2N7")
    sp_pk.add_argument("--banner", default="ZXHN F6600P UNI V9.1.10P2N7")
    sp_pk.add_argument("--build-date", default="20250904100727")
    sp_pk.set_defaults(func=cmd_pack)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
