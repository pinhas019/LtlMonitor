"""The producer half of `/monitor/raw_echo`: the encoder, the summaries, the buffer and
the evaluator wiring that publishes them.

Three properties are worth stating up front, because they are what these tests are for.

**Nothing is echoed until something asks.** A camera on a robot is bandwidth an operator
opted into; an echo that starts by itself would be a leak nobody chose and a queue nobody
budgeted for.

**A frame that cannot be rendered produces a summary that says why.** The two failures
that are indistinguishable to an operator -- a broken picture and no picture -- are both
worse than a sentence naming the encoding, so the unsupported-encoding, bad-stride,
truncated and over-cap paths all end in `kind: image_unavailable` with a `reason`.

**The PNG is checked against a decoder, not against itself.** `decode_png` below verifies
every chunk CRC and inflates the IDAT stream, so "the encoder round-trips" means the
bytes are a PNG a stranger could read -- not merely that this module agrees with itself.

No ROS, no Pillow, no numpy: `zlib`, `struct` and `base64` are the whole dependency list
on both sides of these tests, which is the same claim the module under test makes.
"""

from __future__ import annotations

import base64
import json
import random
import struct
import zlib

import pytest

import ros_stub

pytestmark = pytest.mark.skipif(
    ros_stub.real_ros_present(),
    reason="a real rclpy is installed; these tests drive a stub and must not shadow it",
)

ros_stub.install()

from skill_monitor.backend.adapters import raw_echo                  # noqa: E402
from skill_monitor.backend.adapters.base import SensorAdapter        # noqa: E402
from skill_monitor.backend.adapters.declarative import (             # noqa: E402
    DeclarativeAdapter,
)
from skill_monitor.backend import evaluator_node                     # noqa: E402
from skill_monitor.core import api                                   # noqa: E402


# =============================================================================
# Fixtures: a PNG decoder, a fake Image message, a descriptor
# =============================================================================


def decode_png(blob: bytes):
    """(width, height, [(r, g, b), ...]) from PNG bytes, verifying every CRC.

    Deliberately independent of the encoder: it walks the chunk framing, checks each
    CRC-32, inflates IDAT and strips the per-scanline filter byte. Only filter 0 is
    understood, which is all `encode_png` emits -- a filtered scanline would fail loudly
    here rather than be silently mis-decoded.
    """
    assert blob[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    chunks = []
    at = 8
    while at < len(blob):
        (length,) = struct.unpack(">I", blob[at:at + 4])
        tag = blob[at + 4:at + 8]
        data = blob[at + 8:at + 8 + length]
        (crc,) = struct.unpack(">I", blob[at + 8 + length:at + 12 + length])
        assert crc == zlib.crc32(tag + data) & 0xFFFFFFFF, f"bad CRC on {tag!r}"
        chunks.append((tag, data))
        at += 12 + length

    assert [tag for tag, _ in chunks] == [b"IHDR", b"IDAT", b"IEND"]
    width, height, depth, colour, comp, filt, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1])
    assert (depth, colour, comp, filt, interlace) == (8, 2, 0, 0, 0)

    raw = zlib.decompress(chunks[1][1])
    stride = width * 3
    assert len(raw) == height * (stride + 1)
    pixels = []
    for y in range(height):
        row = y * (stride + 1)
        assert raw[row] == 0, "only filter type 0 is emitted"
        line = raw[row + 1:row + 1 + stride]
        pixels += [tuple(line[x:x + 3]) for x in range(0, stride, 3)]
    return width, height, pixels


class FakeImage:
    """`sensor_msgs/msg/Image`, as much of it as the echo touches."""

    def __init__(self, width, height, encoding, data, step=None):
        self.width = width
        self.height = height
        self.encoding = encoding
        self.step = width * 3 if step is None else step
        self.data = data


class FakeOdom:
    """Anything that is not an image. No `width`/`encoding`/`step`."""

    def __init__(self, x=0.0):
        self.x = x


def photographic(width, height, seed=7) -> bytes:
    """A frame that compresses like a camera frame and not like a test pattern.

    Pure noise is the honest fixture for the size cap: PNG's filters and zlib buy nothing
    on it, so it is the worst case the cap exists for. A gradient would compress ~40x and
    every bound below would pass for the wrong reason.
    """
    return random.Random(seed).randbytes(width * height * 3)


# A descriptor with one image source and one ordinary one. Written to a tmp file rather
# than added to skill_monitor/adapters/: the real descriptors are another package's.
ECHO_DESCRIPTOR = {
    "name": "echo_test",
    "doc": "Two sources: a colour camera and an odometry topic.",
    "schema": {
        "linear_vel": {"doc": "m/s", "default": 0.0},
        "base_height": {"doc": "m", "default": 0.0},
    },
    "describe": ["linear_vel"],
    "sources": [
        {
            "id": "camera",
            "topic": "/depth_anything/color_image",
            "type": "sensor_msgs/msg/Image",
            "tracked": False,
            "steps": [],
        },
        {
            "id": "odom",
            "topic": "/t265/odom/sample",
            "type": "nav_msgs/msg/Odometry",
            "tracked": True,
            "steps": [
                {"key": "linear_vel", "field": "twist.twist.linear.x", "round": 2},
                {"key": "base_height", "field": "pose.pose.position.z", "round": 3},
            ],
        },
    ],
}


@pytest.fixture
def adapter(tmp_path):
    path = tmp_path / "echo_test.json"
    path.write_text(json.dumps(ECHO_DESCRIPTOR))
    return DeclarativeAdapter(descriptor=str(path))


def source_of(adapter, source_id):
    return next(s for s in adapter.spec.sources if s.id == source_id)


class Odometry:
    """Just enough nested attributes for the descriptor's two field paths."""

    def __init__(self, vx, z):
        self.twist = type("T", (), {"twist": type("T", (), {
            "linear": type("L", (), {"x": vx})()})()})()
        self.pose = type("P", (), {"pose": type("P", (), {
            "position": type("Pos", (), {"z": z})()})()})()


# =============================================================================
# The PNG encoder
# =============================================================================


def test_the_png_encoder_round_trips_a_known_pixel_pattern():
    """3x2, every channel distinct, so a transposed row or a swapped channel shows up as
    an inequality rather than as a picture that merely looks odd."""
    pattern = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (1, 2, 3), (250, 251, 252), (0, 0, 0),
    ]
    blob = raw_echo.encode_png(3, 2, bytes(b for pixel in pattern for b in pixel))

    width, height, pixels = decode_png(blob)
    assert (width, height) == (3, 2)
    assert pixels == pattern


def test_the_png_encoder_refuses_a_buffer_that_is_not_the_stated_size():
    """The mismatch that would otherwise emit a valid-looking PNG of shifted pixels."""
    with pytest.raises(ValueError, match="needs 12 rgb bytes"):
        raw_echo.encode_png(2, 2, b"\x00" * 11)


# =============================================================================
# Image summaries
# =============================================================================


def test_an_rgb_frame_becomes_a_bounded_png_data_uri():
    msg = FakeImage(640, 480, "rgb8", photographic(640, 480))
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=3)

    assert summary["kind"] == "image"
    assert summary["encoding"] == "png"
    assert (summary["width"], summary["height"]) == (160, 120)
    assert summary["samples_this_tick"] == 3
    assert summary["source_encoding"] == "rgb8"
    assert (summary["source_width"], summary["source_height"]) == (640, 480)
    assert summary["data_uri"].startswith("data:image/png;base64,")
    assert len(summary["data_uri"]) <= raw_echo.MAX_DATA_URI_BYTES

    # The advertised size is the picture that is actually in the URI.
    payload = summary["data_uri"].split(",", 1)[1]
    width, height, _pixels = decode_png(base64.b64decode(payload))
    assert (width, height) == (160, 120)
    assert summary["bytes"] == len(base64.b64decode(payload))


def test_bgr_is_channel_swapped_rather_than_shown_backwards():
    """The G1's `/depth_anything/color_image` is `bgr8`, so this is the normal path."""
    msg = FakeImage(1, 1, "bgr8", bytes([10, 20, 30]))
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1)

    payload = summary["data_uri"].split(",", 1)[1]
    _w, _h, pixels = decode_png(base64.b64decode(payload))
    assert pixels == [(30, 20, 10)]

    rgb = raw_echo.summarize(topic="/cam", samples_this_tick=1,
                             msg=FakeImage(1, 1, "rgb8", bytes([10, 20, 30])))
    _w, _h, pixels = decode_png(base64.b64decode(rgb["data_uri"].split(",", 1)[1]))
    assert pixels == [(10, 20, 30)]


def test_a_padded_row_stride_is_honoured_rather_than_assumed():
    """A publisher whose `step` exceeds width*3 pads each row. Computing the offset as
    `y * width * 3` instead shears the picture diagonally -- a plausible-looking image
    that is wrong, which is the failure this echo must never produce."""
    padding = b"\xee" * 5
    rows = [bytes([1, 2, 3, 4, 5, 6]), bytes([7, 8, 9, 10, 11, 12])]
    msg = FakeImage(2, 2, "rgb8", rows[0] + padding + rows[1] + padding,
                    step=2 * 3 + len(padding))

    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1)
    payload = summary["data_uri"].split(",", 1)[1]
    _w, _h, pixels = decode_png(base64.b64decode(payload))
    assert pixels == [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]


def test_a_stride_too_small_to_hold_a_row_is_reported_not_rendered():
    msg = FakeImage(8, 4, "rgb8", b"\x00" * 400, step=4)
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1)

    assert summary["kind"] == "image_unavailable"
    assert "data_uri" not in summary
    assert "stride is 4" in summary["reason"]
    assert "24" in summary["reason"]                    # what a row actually needs


def test_a_truncated_frame_is_reported_not_padded_with_garbage():
    msg = FakeImage(16, 16, "bgr8", b"\x00" * 100)
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1)

    assert summary["kind"] == "image_unavailable"
    assert "truncated" in summary["reason"]
    assert summary["source_bytes"] == 100


@pytest.mark.parametrize("encoding", ["16UC1", "bgra8", "mono8", ""])
def test_an_unsupported_encoding_says_so_instead_of_crashing(encoding):
    """A depth stream pointed at the colour echo must produce a sentence, not a
    traceback in a subscription callback and not a picture that is wrong."""
    msg = FakeImage(32, 24, encoding, b"\x11" * (32 * 24 * 3))
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=2)

    assert summary["kind"] == "image_unavailable"
    assert repr(encoding) in summary["reason"]
    assert "rgb8, bgr8" in summary["reason"]
    assert summary["samples_this_tick"] == 2
    json.dumps(summary)                                 # still a wire-legal summary


def test_a_frame_over_the_cap_is_downscaled_again_and_says_so():
    """Cap driven far below what a noisy 160x120 costs, which is the only way to reach
    the fallback deterministically."""
    msg = FakeImage(640, 480, "rgb8", photographic(640, 480))
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1,
                                 max_bytes=8 * 1024)

    assert summary["kind"] == "image"
    assert len(summary["data_uri"]) <= 8 * 1024
    assert (summary["width"], summary["height"]) < (160, 120)
    assert summary["downscaled_to_fit"] is True
    assert summary["cap_bytes"] == 8 * 1024


def test_a_frame_that_cannot_be_made_to_fit_is_reported_rather_than_sent():
    msg = FakeImage(640, 480, "rgb8", photographic(640, 480))
    summary = raw_echo.summarize(topic="/cam", msg=msg, samples_this_tick=1,
                                 max_bytes=64)

    assert summary["kind"] == "image_unavailable"
    assert "cap" in summary["reason"]
    assert "data_uri" not in summary


def test_a_zero_sized_frame_is_reported_rather_than_encoded():
    summary = raw_echo.summarize(topic="/cam", samples_this_tick=1,
                                 msg=FakeImage(0, 0, "rgb8", b""))
    assert summary["kind"] == "image_unavailable"
    assert "0x0" in summary["reason"]


def test_a_measured_realsense_frame_costs_what_the_module_documents():
    """320x240 bgr8, the shape the G1 actually publishes, downscaled to the default box.

    Pins the two numbers the module's docstring states -- the frame lands at 160x120 and
    inside the cap -- so a change to the box or the cap that breaks the budget shows up
    here rather than on a console watching frames evict its verdicts.
    """
    msg = FakeImage(320, 240, "bgr8", photographic(320, 240, seed=11))
    summary = raw_echo.summarize(topic="/depth_anything/color_image", msg=msg,
                                 samples_this_tick=1)

    assert (summary["width"], summary["height"]) == (160, 120)
    assert len(summary["data_uri"]) <= raw_echo.MAX_DATA_URI_BYTES
    assert "downscaled_to_fit" not in summary        # the default cap has headroom


# =============================================================================
# Non-image summaries
# =============================================================================


def test_a_non_image_source_gets_a_fields_summary():
    summary = raw_echo.summarize(topic="/t265/odom/sample", msg=FakeOdom(),
                                 samples_this_tick=14,
                                 values={"linear_vel": 1.2, "base_height": 0.71})

    assert summary == {
        "kind": "fields",
        "topic": "/t265/odom/sample",
        "samples_this_tick": 14,
        "values": {"linear_vel": 1.2, "base_height": 0.71},
    }


def test_field_values_survive_json_even_when_the_adapter_returns_exotic_scalars():
    class Numpyish:
        def __float__(self):
            return 0.5

    summary = raw_echo.summarize(topic="/x", msg=FakeOdom(), samples_this_tick=1,
                                 values={"a": Numpyish(), "b": object()})
    assert summary["values"]["a"] == 0.5
    assert isinstance(summary["values"]["b"], str)
    json.dumps(summary)


# =============================================================================
# The buffer: opt-in, one at a time, rate-bounded
# =============================================================================


def echo_of(**kwargs):
    return raw_echo.RawEcho({"camera": "/cam", "odom": "/odom"}, **kwargs)


def test_nothing_is_echoed_until_a_source_is_requested():
    echo = echo_of()
    echo.offer("camera", FakeImage(4, 4, "rgb8", b"\x00" * 48))
    echo.offer("odom", FakeOdom())

    assert echo.selected is None
    assert echo.take() is None


def test_a_request_selects_exactly_one_source():
    echo = echo_of()
    assert echo.select("odom") is True

    echo.offer("camera", FakeImage(4, 4, "rgb8", b"\x00" * 48))
    echo.offer("odom", FakeOdom(), {"linear_vel": 0.4})

    source_id, summary = echo.take()
    assert source_id == "odom"
    assert summary["topic"] == "/odom"
    assert summary["values"] == {"linear_vel": 0.4}
    assert summary["samples_this_tick"] == 1


def test_a_second_request_replaces_the_first_and_drops_its_buffer():
    echo = echo_of()
    echo.select("odom")
    echo.offer("odom", FakeOdom(), {"linear_vel": 0.4})

    echo.select("camera")
    assert echo.selected == "camera"
    assert echo.take() is None                  # the odom frame went with the selection

    echo.offer("camera", FakeImage(2, 2, "rgb8", b"\x01" * 12))
    source_id, summary = echo.take()
    assert (source_id, summary["kind"]) == ("camera", "image")


def test_null_stops_the_echo():
    echo = echo_of()
    echo.select("camera")
    echo.offer("camera", FakeImage(2, 2, "rgb8", b"\x01" * 12))

    assert echo.select(None) is True
    assert echo.selected is None
    echo.offer("camera", FakeImage(2, 2, "rgb8", b"\x01" * 12))
    assert echo.take() is None


def test_an_unknown_source_is_refused_and_leaves_a_running_echo_alone():
    """A typo must not silently turn off the camera an operator is watching."""
    echo = echo_of()
    echo.select("odom")

    assert echo.select("nosuch") is False
    assert echo.selected == "odom"


def test_taking_closes_the_window():
    echo = echo_of()
    echo.select("odom")
    echo.offer("odom", FakeOdom(), {"linear_vel": 0.1})
    echo.offer("odom", FakeOdom(), {"linear_vel": 0.2})

    _id, summary = echo.take()
    assert summary["samples_this_tick"] == 2
    assert summary["values"] == {"linear_vel": 0.2}     # the newest, not the first
    assert echo.take() is None                          # silence means silence


def test_the_rate_limit_is_a_stride_of_ticks_and_is_reported():
    echo = echo_of(tick_hz=10.0, max_echo_hz=1.0)
    assert (echo.every_n_ticks, echo.rate_hz) == (10, 1.0)
    echo.select("odom")

    # First frame after a selection goes out at once: the stride is a rate limit, not a
    # warm-up, and an operator who just asked for a source should not wait ten ticks.
    echo.offer("odom", FakeOdom(), {"linear_vel": 0.1})
    _id, first = echo.take()
    assert first["rate_hz"] == 1.0 and first["every_n_ticks"] == 10

    emitted = []
    for tick in range(20):
        echo.offer("odom", FakeOdom(), {"linear_vel": float(tick)})
        taken = echo.take()
        if taken is not None:
            emitted.append(taken[1])

    assert len(emitted) == 2                            # 20 ticks at a stride of 10
    # The rate limit costs latency, never accounting: the window's samples are all
    # counted and the frame sent is the newest one in it.
    assert [s["samples_this_tick"] for s in emitted] == [10, 10]
    assert [s["values"]["linear_vel"] for s in emitted] == [9.0, 19.0]


def test_a_tick_slower_than_the_cap_is_not_strided_at_all():
    echo = echo_of(tick_hz=1.0)
    assert (echo.every_n_ticks, echo.rate_hz) == (1, 1.0)


# =============================================================================
# The declarative adapter: where the raw message still exists
# =============================================================================


def test_the_adapter_echoes_nothing_until_asked(adapter):
    adapter._on_message(source_of(adapter, "odom"), Odometry(0.4, 0.7))
    adapter._on_message(source_of(adapter, "camera"),
                        FakeImage(4, 4, "bgr8", b"\x02" * 48))

    assert adapter.take_raw_echo() is None


def test_the_adapter_echoes_the_selected_source_and_only_it(adapter):
    assert adapter.set_raw_echo("odom") is True

    adapter._on_message(source_of(adapter, "camera"),
                        FakeImage(4, 4, "bgr8", b"\x02" * 48))
    adapter._on_message(source_of(adapter, "odom"), Odometry(0.4, 0.71))

    source_id, summary = adapter.take_raw_echo()
    assert source_id == "odom"
    assert summary["kind"] == "fields"
    assert summary["topic"] == "/t265/odom/sample"
    # The keys this source folds, from the message that was just folded -- not the whole
    # observation, which would attribute another topic's values to this one.
    assert summary["values"] == {"base_height": 0.71, "linear_vel": 0.4}


def test_the_adapter_echoes_a_camera_source_as_a_picture(adapter):
    adapter.set_raw_echo("camera")
    adapter._on_message(source_of(adapter, "camera"),
                        FakeImage(320, 240, "bgr8", photographic(320, 240, seed=3)))

    source_id, summary = adapter.take_raw_echo()
    assert (source_id, summary["kind"]) == ("camera", "image")
    assert summary["topic"] == "/depth_anything/color_image"
    assert (summary["width"], summary["height"]) == (160, 120)
    assert len(summary["data_uri"]) <= raw_echo.MAX_DATA_URI_BYTES


def test_the_adapter_refuses_a_source_it_does_not_have(adapter):
    assert adapter.set_raw_echo("lidar") is False
    assert adapter.take_raw_echo() is None


def test_an_adapter_that_cannot_echo_refuses_rather_than_going_quiet():
    """The default on the base class. A hand-written adapter that accepted a selection
    and then never produced a frame would read as a dead sensor."""
    assert SensorAdapter.set_raw_echo(object(), "camera") is False
    assert SensorAdapter.set_raw_echo(object(), None) is True
    assert SensorAdapter.take_raw_echo(object()) is None


# =============================================================================
# The evaluator: request in, echo out
# =============================================================================


class FakeAdapter(SensorAdapter):
    """Records what the node asked of it and hands back a summary on demand."""

    SCHEMA = {"linear_vel": "m/s"}

    def __init__(self):
        self.selections = []
        self.known = {"camera", "odom"}
        self.pending = None

    def register_subscriptions(self, node):
        pass

    def get_sensor_eval(self):
        return {"linear_vel": 0.0}

    def set_raw_echo(self, source_id):
        if source_id is not None and source_id not in self.known:
            return False
        self.selections.append(source_id)
        return True

    def take_raw_echo(self):
        taken, self.pending = self.pending, None
        return taken


@pytest.fixture
def node():
    made = evaluator_node.GenericClientNode(
        FakeAdapter(), api_url="http://nowhere.invalid", model="none")
    yield made
    made.destroy_node()


def echoes(node):
    return [json.loads(text)
            for text in node.publishers[api.RAW_ECHO].sent]


def request(node, payload):
    """Deliver a raw echo request the way the executor would."""
    for callback in node.subscriptions[api.RAW_ECHO_REQUEST]:
        callback(ros_stub.Message(data=json.dumps(payload)))


def test_the_evaluator_publishes_no_echo_until_one_is_requested(node):
    """Ten pulses with nothing requested: no selection was made and the topic is silent.
    The echo is bandwidth an operator opted into, so it cannot start by itself."""
    for _ in range(10):
        node.evaluate_and_publish()

    assert node.adapter.selections == []
    assert node.publishers[api.RAW_ECHO].sent == []


def test_a_request_selects_the_source_and_the_echo_validates(node):
    request(node, api.build_raw_echo_request(source_id="camera"))
    assert node.adapter.selections == ["camera"]

    node.adapter.pending = ("camera", {
        "kind": "image", "topic": "/depth_anything/color_image",
        "width": 160, "height": 120, "encoding": "png",
        "data_uri": "data:image/png;base64,AAAA",
        "samples_this_tick": 3, "bytes": 4,
    })
    node.evaluate_and_publish()

    published = echoes(node)
    assert len(published) == 1
    assert api.validate_raw_echo(published[0]) == []
    assert published[0]["source_id"] == "camera"
    assert published[0]["summary"]["kind"] == "image"
    assert published[0]["step"] is None          # the evaluator tracks no episode


def test_the_echo_runs_while_the_monitor_is_idle(node):
    """An operator points the console at a camera *before* arming a skill. An echo that
    only worked with a spec loaded would be missing exactly when it is wanted."""
    assert node.idle is True
    request(node, api.build_raw_echo_request(source_id="odom"))
    node.adapter.pending = ("odom", {"kind": "fields", "topic": "/odom",
                                     "samples_this_tick": 2, "values": {"v": 1.0}})
    node.evaluate_and_publish()

    assert len(echoes(node)) == 1


def test_a_second_request_replaces_the_first_and_null_stops_it(node):
    request(node, api.build_raw_echo_request(source_id="camera"))
    request(node, api.build_raw_echo_request(source_id="odom"))
    request(node, api.build_raw_echo_request(source_id=None))

    assert node.adapter.selections == ["camera", "odom", None]


def test_a_request_for_a_source_the_adapter_lacks_is_refused_and_logged(node):
    request(node, api.build_raw_echo_request(source_id="camera"))
    request(node, api.build_raw_echo_request(source_id="lidar"))

    assert node.adapter.selections == ["camera"]        # the running echo is untouched
    assert any("lidar" in line for line in node.get_logger().at("error"))


@pytest.mark.parametrize("body", [
    "not json at all",
    json.dumps({"schema_version": 1, "source_id": 42}),
    json.dumps([1, 2, 3]),
])
def test_a_malformed_request_is_reported_and_changes_nothing(node, body):
    for callback in node.subscriptions[api.RAW_ECHO_REQUEST]:
        callback(ros_stub.Message(data=body))

    assert node.adapter.selections == []
    assert node.get_logger().at("error")


def test_an_echo_the_contract_refuses_is_not_published(node):
    """The node builds this payload, so one that fails validation is this node's bug --
    it says so and publishes nothing, rather than putting it on the wire."""
    request(node, api.build_raw_echo_request(source_id="odom"))
    node.adapter.pending = (42, {"kind": "fields", "topic": "/odom",
                                 "samples_this_tick": 1, "values": {}})
    node.evaluate_and_publish()

    assert node.publishers[api.RAW_ECHO].sent == []
    assert node.get_logger().at("error")


def test_the_echo_is_stamped_with_a_sequence_that_advances(node):
    request(node, api.build_raw_echo_request(source_id="odom"))
    for _ in range(3):
        node.adapter.pending = ("odom", {"kind": "fields", "topic": "/odom",
                                         "samples_this_tick": 1, "values": {}})
        node.evaluate_and_publish()

    assert [frame["seq"] for frame in echoes(node)] == [0, 1, 2]
    assert all(frame["t"] > 0 for frame in echoes(node))
