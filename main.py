#!/usr/bin/env python3
"""Package the contest entry image for make.fun's news-image bounty.

The repository holds ``entry.png`` next to this file. The sandbox mounts the
repository read-only at ``/bot`` and gives us a writable ``/output``, so the
image is always resolved relative to ``__file__`` and never from the current
working directory.

What this does: read the image, prove it is a whole PNG that fits the
competition limits, copy it to the requested path through a temporary file,
then re-read the copy and compare the sha256 against the source. Standard
library only, no network, and the output bytes are identical on every run.
"""

import hashlib
import os
import sys
import tempfile

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SIGNATURE_LEN = len(PNG_SIGNATURE)

# Competition limits.
MAX_BYTES = 1048576
MAX_SIDE = 1024

# Chunk framing: 4-byte length, 4-byte type, payload, 4-byte CRC.
CHUNK_HEADER = 8
CHUNK_CRC = 4

DEFAULT_OUTPUT = "/output/entry.png"
SOURCE_NAME = "entry.png"
BLOCK = 1 << 16


def parse_ihdr(data):
    """Return (width, height, bit depth, colour type) from the IHDR chunk."""
    if len(data) < SIGNATURE_LEN + CHUNK_HEADER + 13:
        raise ValueError("file is %d bytes, shorter than a PNG header" % len(data))
    if data[:SIGNATURE_LEN] != PNG_SIGNATURE:
        raise ValueError("missing the 8-byte PNG signature, this is not a PNG")

    length = int.from_bytes(data[SIGNATURE_LEN:SIGNATURE_LEN + 4], "big")
    chunk_type = data[SIGNATURE_LEN + 4:SIGNATURE_LEN + 8]
    if chunk_type != b"IHDR":
        raise ValueError("first chunk is %r, not IHDR" % (chunk_type,))
    if length != 13:
        raise ValueError("IHDR declares %d payload bytes, the spec fixes it at 13" % length)

    body = SIGNATURE_LEN + CHUNK_HEADER
    width = int.from_bytes(data[body:body + 4], "big")
    height = int.from_bytes(data[body + 4:body + 8], "big")
    bit_depth = data[body + 8]
    colour_type = data[body + 9]

    if width == 0 or height == 0:
        raise ValueError("IHDR declares a %dx%d pixel image, both sides must be positive"
                         % (width, height))
    return width, height, bit_depth, colour_type


def check_limits(data, width, height):
    """Enforce the competition rules, naming the one that broke."""
    if len(data) > MAX_BYTES:
        raise ValueError("image is %d bytes, the limit is %d" % (len(data), MAX_BYTES))
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ValueError("image is %dx%d, the limit is %dx%d"
                         % (width, height, MAX_SIDE, MAX_SIDE))
    if width != height:
        raise ValueError("image is %dx%d, the competition wants a square image"
                         % (width, height))


def iter_chunks(data):
    """Yield (type, payload length) for each chunk, ending at IEND."""
    offset = SIGNATURE_LEN
    total = len(data)
    while True:
        if offset + CHUNK_HEADER > total:
            raise ValueError("stream ends at byte %d without an IEND chunk" % offset)
        length = int.from_bytes(data[offset:offset + 4], "big")
        raw_type = data[offset + 4:offset + 8]
        try:
            name = raw_type.decode("ascii")
        except UnicodeDecodeError:
            raise ValueError("chunk at byte %d has a non-ASCII type %r" % (offset, raw_type))

        end = offset + CHUNK_HEADER + length + CHUNK_CRC
        if end > total:
            available = max(0, total - offset - CHUNK_HEADER - CHUNK_CRC)
            raise ValueError(
                "chunk %s at byte %d claims %d payload bytes, %d available"
                % (name, offset, length, available)
            )

        yield name, length
        if name == "IEND":
            return
        offset = end


def copy_atomically(src, dest):
    """Copy src to dest via a temp file in the same directory, then rename."""
    dest_dir = os.path.dirname(os.path.abspath(dest))
    handle, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=".entry-", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            with open(src, "rb") as source:
                while True:
                    block = source.read(BLOCK)
                    if not block:
                        break
                    out.write(block)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, dest)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(BLOCK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main(argv):
    out_path = argv[1] if len(argv) > 1 else DEFAULT_OUTPUT
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), SOURCE_NAME)

    try:
        with open(source, "rb") as handle:
            data = handle.read()

        width, height, bit_depth, colour_type = parse_ihdr(data)
        check_limits(data, width, height)
        chunk_count = sum(1 for _ in iter_chunks(data))

        out_dir = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(out_dir, exist_ok=True)

        copy_atomically(source, out_path)

        source_digest = hashlib.sha256(data).hexdigest()
        copy_digest = sha256_of(out_path)
        if copy_digest != source_digest:
            raise ValueError("copy %s has sha256 %s, source is %s"
                             % (out_path, copy_digest, source_digest))

        print("source     %s" % source)
        print("size       %d bytes" % len(data))
        print("dimensions %dx%d, bit depth %d, colour type %d"
              % (width, height, bit_depth, colour_type))
        print("chunks     %d" % chunk_count)
        print("output     %s" % out_path)
        print("sha256     %s" % copy_digest)
        return 0
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
