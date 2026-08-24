"""The camera bridge's framing and resampling, with no network in sight.

The bridge carries one `sensor_msgs/Image` topic from the robot to the dev PC, because
the robot's DDS does not cross wifi and its containers are Python 3.8 while
`skill_monitor` needs 3.10. Everything worth getting wrong in it is a pure function
over bytes, which is why `read_frame` takes a `recv` callable instead of a socket:
short reads are the interesting case and a live socket reproduces them only by luck.

No sockets, no ROS, no robot. `tools/` is not a package, so the import below adds it
to the path the same way the entrypoints do when run as scripts.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import camera_bridge as cb                                            # noqa: E402


# =============================================================================
# What the bridge will and will not carry
# =============================================================================

def test_only_colour_encodings_are_carried():
    """A depth frame needs a colourisation *decision* -- range, palette, what "far"
    looks like -- and inventing one in a transport would put a picture on an operator's
    screen whose meaning nothing had agreed."""
    assert cb.channels_for("rgb8") == 3
    assert cb.channels_for("bgr8") == 3
    assert cb.channels_for("16UC1") is None
    assert cb.channels_for("mono8") is None


# =============================================================================
# Resampling
# =============================================================================

def _frame(width, height, step=None, channels=3):
    """A frame whose every pixel encodes its own coordinates, so a mis-indexed
    resample produces provably wrong pixels rather than plausible ones."""
    step = step or width * channels
    data = bytearray(height * step)
    for y in range(height):
        for x in range(width):
            i = y * step + x * channels
            data[i:i + 3] = bytes((x % 256, y % 256, 7))
    return bytes(data)


def test_downscale_takes_the_pixels_it_claims_to():
    data = _frame(320, 240)
    out, w, h = cb.resample(data, 320, 240, 960, 160, 120, 3)
    assert (w, h) == (160, 120)
    assert len(out) == 160 * 120 * 3
    # Stride 2 in both axes: output (x, y) must be input (2x, 2y), not a neighbour.
    for (ox, oy) in ((0, 0), (17, 33), (159, 119)):
        px = out[(oy * 160 + ox) * 3:(oy * 160 + ox) * 3 + 3]
        assert px == bytes(((2 * ox) % 256, (2 * oy) % 256, 7)), f"wrong pixel at {ox},{oy}"


def test_a_row_stride_wider_than_the_pixels_is_honoured():
    """`step` is not guaranteed to equal width*channels. Read as if it were, the image
    comes out sheared -- which looks like a camera fault and gets chased in the wrong
    place, so this is pinned rather than left to the one stream it was written for."""
    padded = _frame(64, 48, step=64 * 3 + 11)
    out, w, h = cb.resample(padded, 64, 48, 64 * 3 + 11, 32, 24, 3)
    assert (w, h) == (32, 24)
    assert out[:3] == bytes((0, 0, 7))
    assert out[3:6] == bytes((2, 0, 7))          # x stride 2, and not shifted by padding
    row1 = out[32 * 3:32 * 3 + 3]
    assert row1 == bytes((0, 2, 7))              # y stride 2, padding skipped


def test_the_output_size_is_what_was_achieved_not_what_was_asked():
    """Integer strides only. A caller asking for 100x100 from 320x240 gets whatever
    even division lands on, and is told -- the numbers printed beside a thumbnail have
    to be true even when they are not round."""
    out, w, h = cb.resample(_frame(320, 240), 320, 240, 960, 100, 100, 3)
    assert (w, h) == (80, 60)                    # stride 4 both ways, inside the box
    assert len(out) == w * h * 3


def test_a_downscale_never_changes_the_shape_of_the_picture():
    """One stride for both axes. Independent strides hit the requested box more
    exactly and squash the image doing it -- 320x240 into 100x100 would come out
    106x120, a 0.88:1 picture of a 4:3 scene, which reads as a lens fault rather than
    a resample and gets chased in the wrong place."""
    for (sw, sh, rw, rh) in ((320, 240, 100, 100), (320, 240, 160, 120),
                             (640, 480, 160, 120), (640, 360, 100, 100)):
        _out, w, h = cb.resample(_frame(sw, sh), sw, sh, sw * 3, rw, rh, 3)
        assert abs(w / h - sw / sh) < 0.02, f"{sw}x{sh} -> {w}x{h} changed the aspect"
        assert w <= rw and h <= rh, f"{w}x{h} overshot the {rw}x{rh} box"


def test_a_frame_smaller_than_the_request_is_passed_through_whole():
    out, w, h = cb.resample(_frame(16, 12), 16, 12, 48, 160, 120, 3)
    assert (w, h) == (16, 12)
    assert out == _frame(16, 12)


@pytest.mark.parametrize("kwargs, fragment", [
    (dict(width=0, height=10, step=0, channels=3), "no pixels"),
    (dict(width=10, height=0, step=30, channels=3), "no pixels"),
    (dict(width=10, height=10, step=10, channels=3), "shorter than one packed row"),
])
def test_an_impossible_geometry_is_refused_by_name(kwargs, fragment):
    with pytest.raises(ValueError) as exc:
        cb.resample(b"\x00" * 4096, out_width=8, out_height=8, **kwargs)
    assert fragment in str(exc.value)


def test_a_truncated_buffer_is_refused_rather_than_read_past():
    """A short buffer sliced blindly yields a frame padded with whatever follows it in
    memory -- or a shorter one nobody checked. Either way the picture is a lie."""
    with pytest.raises(ValueError) as exc:
        cb.resample(b"\x00" * 100, 320, 240, 960, 160, 120, 3)
    assert "short of the" in str(exc.value)


# =============================================================================
# Framing
# =============================================================================

def _reader(*chunks):
    """A `recv` that hands back exactly these chunks, then end-of-stream."""
    queue = list(chunks)

    def recv(n):
        if not queue:
            return b""
        head = queue.pop(0)
        if len(head) > n:                        # give back only what was asked for
            queue.insert(0, head[n:])
            return head[:n]
        return head
    return recv


def test_a_frame_survives_the_round_trip():
    header = cb.header_for("bgr8", 4, 3, 3, 320, 240,
                           frame_id="camera_color_optical_frame", sec=12, nsec=345)
    payload = bytes(range(4 * 3 * 3))
    got_header, got_payload = cb.read_frame(_reader(cb.pack_frame(header, payload)))
    assert got_header == header
    assert got_payload == payload
    assert got_header["step"] == 12               # width * channels
    assert got_header["src_w"] == 320             # the source size travels too


def test_a_frame_split_across_arbitrary_reads_is_reassembled():
    """The reason `read_frame` takes `recv` and not a socket. A real socket returns
    short reads whenever it feels like it; here every boundary is exercised on purpose."""
    header = cb.header_for("rgb8", 8, 4, 3, 640, 480)
    payload = bytes(range(96))
    blob = cb.pack_frame(header, payload)
    for cut in (1, 2, 3, 4, 5, 17, len(blob) - 1):
        got = cb.read_frame(_reader(*[blob[i:i + cut] for i in range(0, len(blob), cut)]))
        assert got is not None, f"failed when read in {cut}-byte chunks"
        assert got == (header, payload)


def test_two_frames_back_to_back_do_not_bleed_into_each_other():
    h1 = cb.header_for("bgr8", 2, 2, 3, 320, 240, sec=1)
    h2 = cb.header_for("bgr8", 2, 2, 3, 320, 240, sec=2)
    p1, p2 = b"\x01" * 12, b"\x02" * 12
    recv = _reader(cb.pack_frame(h1, p1) + cb.pack_frame(h2, p2))
    assert cb.read_frame(recv) == (h1, p1)
    assert cb.read_frame(recv) == (h2, p2)
    assert cb.read_frame(recv) is None


@pytest.mark.parametrize("where", ["length", "header", "payload"])
def test_a_stream_that_ends_mid_frame_returns_none_rather_than_raising(where):
    """A peer disappearing is ordinary -- the robot restarts, the wifi drops -- and the
    caller's answer is to reconnect. A traceback would make routine into an incident."""
    blob = cb.pack_frame(cb.header_for("bgr8", 4, 4, 3, 320, 240), b"\x00" * 48)
    cutoff = {"length": 2, "header": 6, "payload": len(blob) - 5}[where]
    assert cb.read_frame(_reader(blob[:cutoff])) is None


def test_an_empty_stream_is_end_of_stream_not_an_error():
    assert cb.read_frame(_reader()) is None


def test_an_implausible_header_length_is_refused_before_allocating():
    """The length prefix is attacker-controlled the moment this port is reachable, and
    it is reachable by design -- the whole point is another machine connecting to it."""
    recv = _reader(struct.pack(">I", 500 * 1024 * 1024))
    with pytest.raises(ValueError) as exc:
        cb.read_frame(recv)
    assert "refusing to allocate" in str(exc.value)


def test_packing_refuses_an_implausible_header():
    with pytest.raises(ValueError):
        cb.pack_frame({"junk": "x" * (cb.MAX_HEADER_BYTES + 1)}, b"")


def test_the_header_carries_the_cameras_own_time_not_the_bridges():
    """A consumer lining frames up against odometry needs the time the camera says,
    not the time the wifi finished. The bridge never stamps anything itself."""
    h = cb.header_for("bgr8", 160, 120, 3, 320, 240,
                      frame_id="camera_color_optical_frame", sec=1787578755, nsec=61)
    assert (h["sec"], h["nsec"]) == (1787578755, 61)
    assert h["frame_id"] == "camera_color_optical_frame"
    assert json.loads(json.dumps(h)) == h        # it has to survive the wire


# =============================================================================
# The two halves agree
# =============================================================================

class _Stamp:
    def __init__(self, sec, nanosec): self.sec, self.nanosec = sec, nanosec


class _Header:
    def __init__(self, frame_id, sec, nsec):
        self.frame_id, self.stamp = frame_id, _Stamp(sec, nsec)


class _Image:
    """Enough of `sensor_msgs/Image` to drive the sender without ROS installed."""
    def __init__(self, encoding, width, height, data, step=None, frame_id="cam"):
        self.encoding, self.width, self.height = encoding, width, height
        self.step = step or width * 3
        self.data = data
        self.header = _Header(frame_id, 7, 8)


def test_the_sender_turns_an_image_into_a_frame_the_reader_accepts():
    import bridge_tx
    msg = _Image("bgr8", 320, 240, _frame(320, 240))
    header, pixels = bridge_tx.frame_from_image(msg, 160, 120)
    got = cb.read_frame(_reader(cb.pack_frame(header, pixels)))
    assert got == (header, pixels)
    assert header["encoding"] == "bgr8"          # passed through, never converted
    assert (header["w"], header["h"]) == (160, 120)
    assert (header["src_w"], header["src_h"]) == (320, 240)
    assert len(pixels) == 160 * 120 * 3


def test_the_sender_declines_an_encoding_it_cannot_carry():
    import bridge_tx
    depth = _Image("16UC1", 640, 480, b"\x00" * (640 * 480 * 2), step=640 * 2)
    assert bridge_tx.frame_from_image(depth, 160, 120) is None


def test_the_receiver_rebuilds_the_message_without_rewriting_colour():
    """`bgr8` in, `bgr8` out. The one component that knows about channel order is the
    raw-echo encoder, which is tested for it; a bridge that quietly swapped channels
    would be a second implementation of that in the place nobody looks."""
    import bridge_rx
    header = cb.header_for("bgr8", 4, 3, 3, 320, 240, frame_id="cam", sec=5, nsec=6)
    payload = bytes(range(36))
    m = bridge_rx.to_image(header, payload, _Image_ctor)
    assert m.encoding == "bgr8"
    assert (m.width, m.height, m.step) == (4, 3, 12)
    assert bytes(m.data) == payload
    assert (m.header.stamp.sec, m.header.stamp.nanosec) == (5, 6)
    assert m.header.frame_id == "cam"


class _Image_ctor:
    """A zero-arg `Image()` stand-in, which is how `to_image` builds one."""
    def __init__(self):
        self.header = _Header("", 0, 0)
        self.height = self.width = self.step = 0
        self.encoding = ""
        self.is_bigendian = 0
        self.data = []


def test_the_republished_topic_defaults_to_the_robots_own_name():
    """The descriptor names a topic; the bridge must not require a different one on
    each side, or a descriptor written for the robot stops working on the dev PC."""
    import bridge_rx
    import bridge_tx
    tx = bridge_tx.build_parser().parse_args([])
    rx = bridge_rx.build_parser().parse_args(["--host", "10.0.0.1"])
    assert tx.topic == rx.topic == "/depth_anything/color_image"
