"""The producer half of `/monitor/raw_echo`: one selected source, one summary per tick.

`api.build_raw_echo` leaves `summary` deliberately opaque -- "its shape is the adapter's
business, and pinning it here would mean every new sensor type edits the wire contract".
This module is that business, and the only thing it adds to the contract is a convention
a consumer can branch on without the wire knowing what a camera is:

    {"kind": "image",  "topic": ..., "width": 160, "height": 120, "encoding": "png",
     "data_uri": "data:image/png;base64,...", "samples_this_tick": 3, "bytes": 41234}

    {"kind": "fields", "topic": ..., "samples_this_tick": 14, "values": {...}}

    {"kind": "image_unavailable", "topic": ..., "reason": "...", ...}

`kind` is the discriminator and it is open: a new sensor type invents its own kind here
and a page that has never heard of it falls back to dumping the JSON, which is why the
reason for an unrenderable frame is a *string in the summary* rather than a dropped
message or an exception. A camera that publishes `16UC1` must produce a summary that
says so; silence and a broken <img> are the two answers an operator cannot act on.

Stdlib only, on purpose
-----------------------
`pyproject.toml` declares no `install_requires` and the gateway makes a point of being
stdlib-only. A PNG of an 8-bit RGB frame is a fixed header, one zlib stream and three
CRCs -- `encode_png` below -- so the alternative (Pillow or cv2, present on the robot and
absent on a laptop) would buy nothing but a second code path that only one of the two
machines ever executes, and a divergence nobody would notice until the console showed
different pixels than the tests.

Bounded, on purpose
-------------------
The gateway gives each websocket client a queue of 256 frames and drops oldest. A
megabyte of camera per tick would evict every observation and verdict a console is
watching, so three separate things are bounded.

**Size.** The frame is downscaled to fit `MAX_WIDTH` x `MAX_HEIGHT` -- 160x120, enough to
see what the camera sees and not enough to read a serial number. Measured on a real
`/depth_anything/color_image` frame off the G1 (320x240 `bgr8`, photographic content,
which compresses far worse in PNG than any synthetic gradient):

    320x240 native   176 KB png -> 235 KB base64      not viable
    160x120           48 KB png ->  64 KB base64      the default
    128x96            31 KB png ->  41 KB base64

**Bytes.** The `data:` URI is capped at `MAX_DATA_URI_BYTES` (96 KiB -- half again over
the measured 64 KB, so a noisier or larger frame has headroom before the fallback). A
frame over the cap is halved and re-encoded, and says so with `downscaled_to_fit`; one
that is still over at the smallest size tried becomes an `image_unavailable` summary
giving its size. The summary always states what was actually sent.

**Rate.** Opt-in and one-at-a-time bound *how many* sources are echoed, not how often:
64 KB/frame at a 10 Hz tick is 640 KB/s. So the echo emits at most `MAX_ECHO_HZ` frames
per second, derived from the descriptor's `tick_hz` into a stride of whole ticks, and
every summary carries `rate_hz` and `every_n_ticks` -- an operator can see the cost of
what they turned on. Samples from the skipped ticks are not lost to the count:
`samples_this_tick` covers the whole window and the frame sent is the newest in it.

`zlib` level 6, not 9: on the real frame above the two are byte-identical, and the robot
running Depth-Anything has no CPU to spare for a compression level that buys nothing.

The cost is paid once per emitted frame, not once per message: `RawEcho.offer` keeps a
reference to the last message and a count, and all the resampling and compression happens
in `take()`, on the tick that publishes.
"""

from __future__ import annotations

import base64
import math
import struct
import threading
import zlib
from typing import Any

#: The echoed frame is downscaled to fit inside this box, aspect preserved.
MAX_WIDTH = 160
MAX_HEIGHT = 120

#: Cap on the `data:` URI -- the thing that actually travels. A 160x120 photographic PNG
#: measured 64 KB base64 off the real robot, so this is half again over the normal case:
#: enough headroom that the halving fallback is for pathological frames (sensor noise,
#: which does not compress at all) rather than for every frame from a busy scene.
MAX_DATA_URI_BYTES = 96 * 1024

#: Frames per second, at most, whatever the tick rate is. The contract bounds how many
#: sources are echoed and not how often, and 64 KB at a 10 Hz tick is 640 KB/s through a
#: queue that also carries every observation and verdict.
MAX_ECHO_HZ = 1.0

#: What a RealSense colour stream actually publishes -- `/depth_anything/color_image` on
#: the G1 is `bgr8`, so the channel swap is the normal path and not a fallback. Anything
#: else is reported, not guessed at: reading `bgra8` as `bgr8` produces a picture that is
#: wrong in a way that looks plausible, which is worse than no picture.
SUPPORTED_ENCODINGS = ("rgb8", "bgr8")

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Attributes that make a message an `sensor_msgs/msg/Image`. Duck-typed rather than
#: matched on the descriptor's type string, so a bag replaying a compatible message
#: renders and a mistyped descriptor does not silently produce a `fields` summary.
_IMAGE_ATTRS = ("width", "height", "encoding", "step", "data")


# ------------------------------------------------------------------------- PNG


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """8-bit RGB, no interlace, filter 0 on every scanline -> PNG bytes.

    `rgb` is packed `width * height * 3` bytes. Filter 0 ("none") is chosen over the
    adaptive filters a real encoder would try because the frames here are already
    downscaled to a few hundred pixels a side: the filter would cost a pass over the
    data and save single-digit percent of something already under the cap.
    """
    expected = width * height * 3
    if width <= 0 or height <= 0:
        raise ValueError(f"png is {width}x{height}; both must be positive")
    if len(rgb) != expected:
        raise ValueError(
            f"png is {width}x{height} and needs {expected} rgb bytes, got {len(rgb)}")
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)                                   # filter type: none
        raw += rgb[y * stride:(y + 1) * stride]
    return (
        _PNG_MAGIC
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


# ------------------------------------------------------------------ summarising


def _as_int(value: Any) -> int:
    """A message field as an int, or -1 for anything that is not one. -1 then fails the
    dimension checks below and is reported, rather than raising inside a subscription
    callback where the exception would take the whole echo down."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _jsonable(value: Any) -> Any:
    """The same coercion the evaluator applies to `__sensors__`: an adapter may hand
    back a numpy scalar, and `json.dumps` would raise on it at publish time."""
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return float(value) if hasattr(value, "__float__") else str(value)


def _fit(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    scale = min(max_width / width, max_height / height, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale))


def _resample(data, width, height, step, out_width, out_height, swap_rb) -> bytes:
    """Nearest-neighbour subsample of one packed 3-byte-per-pixel frame.

    `step` is the source's row stride in bytes and is honoured rather than assumed:
    a padded row (step > width * 3) is exactly the case where computing the offset as
    `y * width * 3` shears the picture diagonally instead of failing.
    """
    out = bytearray(out_width * out_height * 3)
    at = 0
    for y in range(out_height):
        row = (y * height // out_height) * step
        for x in range(out_width):
            i = row + (x * width // out_width) * 3
            red, green, blue = data[i], data[i + 1], data[i + 2]
            if swap_rb:
                red, blue = blue, red
            out[at] = red
            out[at + 1] = green
            out[at + 2] = blue
            at += 3
    return bytes(out)


def looks_like_image(msg: Any) -> bool:
    return all(hasattr(msg, attr) for attr in _IMAGE_ATTRS)


def _image_summary(topic, msg, samples_this_tick, max_width, max_height, max_bytes):
    width = _as_int(msg.width)
    height = _as_int(msg.height)
    step = _as_int(msg.step)
    encoding = str(getattr(msg, "encoding", "") or "")
    try:
        data = bytes(msg.data or b"")
    except (TypeError, ValueError):
        data = b""

    def unavailable(reason: str) -> dict:
        return {
            "kind": "image_unavailable",
            "topic": topic,
            "samples_this_tick": samples_this_tick,
            "source_encoding": encoding,
            "source_width": width,
            "source_height": height,
            "source_bytes": len(data),
            "reason": reason,
        }

    if encoding not in SUPPORTED_ENCODINGS:
        return unavailable(
            f"encoding {encoding!r} is not one this echo can render "
            f"({', '.join(SUPPORTED_ENCODINGS)})")
    if width <= 0 or height <= 0:
        return unavailable(f"frame is {width}x{height}")
    row_bytes = width * 3
    if step < row_bytes:
        return unavailable(
            f"row stride is {step} bytes but a {width}px {encoding} row needs "
            f"{row_bytes}; the frame would render as diagonal garbage")
    needed = (height - 1) * step + row_bytes
    if len(data) < needed:
        return unavailable(
            f"frame is truncated: {len(data)} bytes for a {width}x{height} frame "
            f"with stride {step}, which needs {needed}")

    out_width, out_height = _fit(width, height, max_width, max_height)
    swap_rb = encoding == "bgr8"
    halvings = 0
    while True:
        png = encode_png(out_width, out_height,
                         _resample(data, width, height, step,
                                   out_width, out_height, swap_rb))
        data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        if len(data_uri) <= max_bytes:
            break
        if out_width <= 8 or out_height <= 8:
            return unavailable(
                f"encoded frame is {len(data_uri)} bytes at {out_width}x{out_height}, "
                f"over the {max_bytes}-byte cap even at the smallest size tried")
        out_width, out_height = max(1, out_width // 2), max(1, out_height // 2)
        halvings += 1

    summary = {
        "kind": "image",
        "topic": topic,
        "width": out_width,
        "height": out_height,
        "encoding": "png",
        "data_uri": data_uri,
        "samples_this_tick": samples_this_tick,
        # The encoded PNG, i.e. what the pixels cost before base64 inflates them by a
        # third. The `data_uri` is what the cap is applied to.
        "bytes": len(png),
        "source_encoding": encoding,
        "source_width": width,
        "source_height": height,
    }
    if halvings:
        # Never silently: a console showing a smaller picture than the box it drew must
        # be able to say why, and an operator wondering where the detail went is owed
        # the number rather than a guess about the network.
        summary["downscaled_to_fit"] = True
        summary["cap_bytes"] = max_bytes
    return summary


def summarize(*, topic: str, msg: Any, samples_this_tick: int,
              values: dict | None = None,
              max_width: int = MAX_WIDTH, max_height: int = MAX_HEIGHT,
              max_bytes: int = MAX_DATA_URI_BYTES) -> dict:
    """One source's last message as a `summary` for `api.build_raw_echo`.

    An image becomes a downscaled PNG; anything else becomes the values this source
    folded, which is what an operator watching a `fields` source came for. Never raises:
    every failure it can name becomes a summary that names it.
    """
    if looks_like_image(msg):
        return _image_summary(topic, msg, samples_this_tick,
                              max_width, max_height, max_bytes)
    return {
        "kind": "fields",
        "topic": topic,
        "samples_this_tick": samples_this_tick,
        "values": {k: _jsonable(v) for k, v in (values or {}).items()},
    }


# --------------------------------------------------------------------- the buffer


class RawEcho:
    """The one-source-at-a-time echo buffer, off until something selects a source.

    Opt-in and singular is the contract's own rule ("One at a time, opt-in, because a
    point cloud per frame is not free"), so it is enforced here rather than trusted to
    the caller: selecting a second source replaces the first, and there is no state in
    which two sources are being echoed.

    Rate is bounded here too, in whole ticks: `tick_hz` and `max_echo_hz` become a stride
    `every_n_ticks`, and every summary reports the resulting `rate_hz`. A stride rather
    than a wall-clock interval because the tick is what this system counts in -- a replay
    clock at 100x would otherwise emit at the rate of the machine instead of the rate of
    the recording. A tick here is one call to `take()`, i.e. the evaluator's pulse, and
    `tick_hz` must therefore be the rate that pulse actually runs at.

    Locked because `offer` runs in a subscription callback and `take` on the tick. That
    is one thread under today's single-threaded executor and two the moment anyone adds
    a callback group -- the same reason `SensorState` holds one.
    """

    def __init__(self, topics: dict[str, str], *, tick_hz: float = 1.0,
                 max_echo_hz: float = MAX_ECHO_HZ,
                 max_width: int = MAX_WIDTH, max_height: int = MAX_HEIGHT,
                 max_bytes: int = MAX_DATA_URI_BYTES):
        self._topics = dict(topics)                    # source_id -> topic name
        self._max = (max_width, max_height, max_bytes)
        self._every = max(1, math.ceil(float(tick_hz) / float(max_echo_hz)))
        self._rate_hz = round(float(tick_hz) / self._every, 3)
        self._lock = threading.Lock()
        self._selected: str | None = None
        self._samples = 0
        self._ticks = 0
        self._last: tuple[Any, dict] | None = None

    @property
    def every_n_ticks(self) -> int:
        """Ticks between echoed frames. 1 when the tick is already slow enough."""
        return self._every

    @property
    def rate_hz(self) -> float:
        """The rate an operator actually gets, which is what the summary reports."""
        return self._rate_hz

    @property
    def selected(self) -> str | None:
        """The source being echoed, or None. An unlocked read, deliberately: it is the
        hot-path guard in `_on_message` and a stale answer costs one sample."""
        return self._selected

    def select(self, source_id: str | None) -> bool:
        """Echo `source_id` and nothing else; None stops. False when this adapter has no
        such source, in which case the echo is left exactly as it was -- a typo must not
        silently turn off an echo an operator is watching.
        """
        if source_id is not None and source_id not in self._topics:
            return False
        with self._lock:
            self._selected = source_id
            # Whatever was buffered belonged to the previous selection.
            self._samples = 0
            self._last = None
            # The stride is a rate limit, not a warm-up: an operator who just asked for
            # a camera gets the first frame that arrives, not one N ticks from now.
            self._ticks = self._every
        return True

    def offer(self, source_id: str, msg: Any, values: dict | None = None) -> None:
        """One message off a subscription. Cheap by construction: a reference and a
        counter, no decode, no copy of the pixels."""
        with self._lock:
            if source_id != self._selected:
                return
            self._samples += 1
            self._last = (msg, dict(values or {}))

    def take(self) -> tuple[str, dict] | None:
        """`(source_id, summary)` for this tick, or None when there is nothing to say.

        Closes the window when it emits. None means "no source selected", "the selected
        source has published nothing since the last echo", or "the rate limit says not
        this tick" -- in the first two cases silence on the echo topic is silence on the
        source's topic, and a console never has to tell a re-sent frame from a fresh one.

        A skipped tick keeps the buffer: the frame that eventually goes out is the newest
        one seen and `samples_this_tick` counts the whole window, so the rate limit costs
        latency and never accounting.
        """
        with self._lock:
            self._ticks += 1
            if self._selected is None or self._last is None:
                return None
            if self._ticks < self._every:
                return None
            source_id, last, samples = self._selected, self._last, self._samples
            self._ticks = 0
            self._samples = 0
            self._last = None
        msg, values = last
        max_width, max_height, max_bytes = self._max
        # Outside the lock: this is the expensive half and it must not block a
        # subscription callback on another topic.
        summary = summarize(
            topic=self._topics.get(source_id, source_id), msg=msg,
            samples_this_tick=samples, values=values,
            max_width=max_width, max_height=max_height, max_bytes=max_bytes,
        )
        # What the operator turned on actually costs, on every summary and not only the
        # image ones: a `fields` echo of a 200 Hz odometry topic is a rate question too.
        summary["every_n_ticks"] = self._every
        summary["rate_hz"] = self._rate_hz
        return source_id, summary
