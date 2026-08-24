"""Framing and resampling for the camera bridge — the half with no I/O in it.

The bridge exists because of a version wall, not a design preference. The G1's ROS
graph is humble inside containers and its DDS is bound to eth0; the robot's host and
every container on it are Python 3.8, and `skill_monitor` needs 3.10. So the monitor
runs on the dev PC, the camera is on the robot, and DDS does not cross the wifi
between them. This carries frames across that gap and republishes them as an ordinary
`sensor_msgs/Image`, so an adapter descriptor names a topic and nothing in
`skill_monitor` learns a bridge was involved. Delete the bridge when the monitor runs
where the camera is, and change nothing else.

**This module must import on Python 3.8**, because the sending half runs inside the
robot's container. That is why there are no builtin generics at runtime and why the
annotations are deferred. It is also why the bridge lives in `tools/` and not in
`skill_monitor/`, which declares `requires-python = ">=3.10"`.

Everything here is a pure function over bytes. The sockets and the ROS node live in
`bridge_tx.py` and `bridge_rx.py`; the seam is `read_frame`, which takes a `recv`
callable rather than a socket so it can be driven by a test with no network at all.

Wire format, per frame:

    4 bytes   big-endian length of the JSON header
    N bytes   JSON header: pixel geometry, encoding, and the robot's own stamp
    H*step    raw pixel bytes, exactly as the camera published them

The pixels are **not** re-encoded in transit. The robot downscales -- shipping 230 KB
frames over wifi to prove DDS could not is its own kind of silly -- but it does not
convert colour. `bgr8` arrives as `bgr8`, so the one place that knows about channel
order is the one place that is tested for it.
"""

from __future__ import annotations

import json
import struct

#: Encodings this bridge will carry, and their bytes per pixel. Anything else is
#: dropped rather than guessed at: a depth frame needs a colourisation *decision*
#: (range, palette, what "far" looks like), and inventing one here would put a
#: picture on an operator's screen that nothing had agreed the meaning of.
SUPPORTED_ENCODINGS = {"rgb8": 3, "bgr8": 3}

#: Length prefix of the JSON header. A header longer than this is a bug or an
#: attacker, and either way not something to allocate for.
MAX_HEADER_BYTES = 64 * 1024

#: Pixels per frame after downscaling. 160x120 of a real scene is ~58 KB raw, which
#: is 115 KB/s at the 2 Hz the bridge defaults to -- a rate wifi carries without
#: complaint and an operator can still read.
DEFAULT_WIDTH = 160
DEFAULT_HEIGHT = 120


def channels_for(encoding):
    """Bytes per pixel for `encoding`, or None if this bridge will not carry it."""
    return SUPPORTED_ENCODINGS.get(encoding)


def resample(data, width, height, step, out_width, out_height, channels):
    """Nearest-neighbour downscale, returning ``(pixels, actual_width, actual_height)``.

    Integer strides only, so the output is whatever even division gets closest to the
    request rather than the request exactly -- the caller is told what it actually got.
    A camera is not a photo editor and an operator watching a 160x120 thumbnail does
    not care that it came out 160x120 rather than 158x119; they care that the numbers
    beside it are true.

    `step` is honoured rather than assumed equal to ``width * channels``. It usually
    is, on the stream this was written for. It is not guaranteed to be by
    `sensor_msgs/Image`, and a row stride read as if it were packed produces an image
    that is subtly sheared -- which looks like a camera fault rather than a decode bug,
    and would be chased in the wrong place.
    """
    if width <= 0 or height <= 0 or channels <= 0:
        raise ValueError("frame has no pixels: %sx%s x%s" % (width, height, channels))
    if step < width * channels:
        raise ValueError(
            "step %d is shorter than one packed row (%d)" % (step, width * channels))
    if len(data) < height * step:
        raise ValueError(
            "buffer holds %d bytes, short of the %d that %dx%d step %d needs"
            % (len(data), height * step, width, height, step))

    # One stride for both axes, not two. Independent strides would satisfy the
    # requested box more exactly and change the aspect ratio doing it: 320x240 asked
    # for 100x100 gives stride 3 across and 2 down, i.e. a picture squashed to 0.88:1
    # that an operator reads as a lens or a camera fault rather than a resample.
    # Taking the coarser stride keeps 4:3 looking like 4:3 and undershoots the box.
    # Rounded up, so the result fits inside the requested box rather than spilling
    # past it: 320 wide at stride 3 is 106, which overshoots a 100 box. Rounding up
    # also keeps the case this was written for exact -- 320x240 into 160x120 is
    # stride 2 either way.
    sx = sy = max(1,
                  -(-width // max(1, out_width)),
                  -(-height // max(1, out_height)))
    ow, oh = width // sx, height // sy
    out = bytearray()
    for y in range(oh):
        row = y * sy * step
        for x in range(ow):
            i = row + x * sx * channels
            out += data[i:i + channels]
    return bytes(out), ow, oh


def pack_frame(header, payload):
    """One frame as bytes: length-prefixed JSON header, then the pixels."""
    blob = json.dumps(header).encode("utf-8")
    if len(blob) > MAX_HEADER_BYTES:
        raise ValueError("header of %d bytes is implausible" % len(blob))
    return struct.pack(">I", len(blob)) + blob + payload


def read_frame(recv):
    """``(header, payload)`` from a `recv(n) -> bytes` callable, or None at end of stream.

    `recv` rather than a socket is the whole testability seam: a socket returns short
    reads whenever it feels like it, which is the interesting case and also the one a
    live test reproduces only by luck. Here it is one line of fixture.

    A stream that ends mid-frame returns None rather than raising. A peer that
    disconnects is ordinary -- the robot restarts, the wifi drops -- and the caller
    reconnects. It is not an error worth a traceback.
    """
    head = _exactly(recv, 4)
    if head is None:
        return None
    (length,) = struct.unpack(">I", head)
    if length > MAX_HEADER_BYTES:
        raise ValueError("header claims %d bytes; refusing to allocate" % length)
    blob = _exactly(recv, length)
    if blob is None:
        return None
    header = json.loads(blob.decode("utf-8"))
    need = int(header["h"]) * int(header["step"])
    payload = _exactly(recv, need)
    if payload is None:
        return None
    return header, payload


def _exactly(recv, n):
    """Exactly `n` bytes, or None if the stream ended first."""
    if n == 0:
        return b""
    buf = bytearray()
    while len(buf) < n:
        chunk = recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def header_for(encoding, out_width, out_height, channels, source_width,
               source_height, frame_id="", sec=0, nsec=0):
    """The JSON header describing one downscaled frame.

    Carries the robot's own `frame_id` and stamp, not the moment the bridge saw it:
    the receiver republishes a real `sensor_msgs/Image`, and a consumer lining that up
    against odometry needs the time the *camera* says, not the time the wifi finished.
    """
    return {
        "w": out_width,
        "h": out_height,
        "encoding": encoding,
        "step": out_width * channels,
        "frame_id": frame_id,
        "sec": int(sec),
        "nsec": int(nsec),
        "src_w": source_width,
        "src_h": source_height,
    }
