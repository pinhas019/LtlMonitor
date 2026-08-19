"""Who is on the graph, and whether they are still alive.

Discovery mirrors the topic contract rather than keeping a registry: a monitor *is*
something publishing ``<ns>/monitor/verdict``. A monitor nobody registered still
appears, and one that dies stops appearing on its own.

These functions live in ``core/`` because **two** processes answer the same question
about the same graph -- the gateway (P6) over HTTP and the Skill Center (P7) on the
operator's desktop -- and an operator watching both must never see two answers to "is
this monitor alive". They were duplicated once; the copy that drifts is the bug this
module exists to prevent.

Pure, ROS-free and network-free, per the rule on ``core``: everything here is testable
with a list of strings and a float.
"""

from __future__ import annotations

import re

from skill_monitor.core import api

# A monitor silent this long is presumed dead. One number, one meaning, both clients.
STALE_AFTER = 5.0


def parse_namespaces(topic_names, key_topic: str = api.VERDICT) -> list[str]:
    """Namespaces of every discovered monitor, ``''`` for the unnamespaced one.

    ``key_topic`` is the discovery key -- the topic whose presence *defines* a monitor.
    It is a parameter rather than a constant because P7 still keys off the pre-migration
    name until it moves (docs/api.md § Migration), and both callers must be able to say
    which topic they mean without a second implementation of the suffix arithmetic.

    Anything that is not a string is ignored rather than raising: the input is a ROS
    graph query, and one odd entry must not take discovery down with it.
    """
    suffix = key_topic if key_topic.startswith("/") else "/" + key_topic
    out = set()
    for name in topic_names or ():
        if not isinstance(name, str):
            continue
        if name == suffix:
            out.add("")
        elif name.endswith(suffix):
            out.add(name[: -len(suffix)])
    return sorted(out)


def health(last_seen, now: float, stale_after: float = STALE_AFTER) -> str:
    """``'live'`` | ``'stale'`` | ``'gone'``.

    A monitor that published and then stopped is NOT the same as one that never
    published: the first is a crash, the second is a stack that was never started, and
    the operator needs to tell them apart. ``gone`` is the second -- the topic is
    advertised but no message has ever arrived.
    """
    if last_seen is None:
        return "gone"
    return "live" if (now - last_seen) <= stale_after else "stale"


# ------------------------------------------------------------------ name legality

# Long enough for any namespace a human writes, short enough that a name cannot be used
# to push kilobytes into a log line or a DDS discovery packet.
MAX_NAMESPACE_CHARS = 128

# The ROS 2 name grammar for a single token: an alphabetic or underscore first
# character, then alphanumerics and underscores. Deliberately no `~`, no `{}`
# substitution, no digits leading -- rclpy rejects all three, and a name it rejects must
# come back to a client as a refusal from *our* code with a reason, not as a traceback.
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def namespace_problem(ns: str) -> str | None:
    """Why ``ns`` is not a legal ROS namespace, or None if it is.

    ``''`` -- the global namespace -- is legal. Anything else must be absolute and must
    spell each token in the ROS name grammar.

    This exists because a namespace that arrives from outside the process (a URL
    segment, a config file) is otherwise handed straight to ``create_publisher``, where
    an illegal name surfaces as an exception from rclpy several frames away from the
    thing that caused it. Checking it here turns that into one sentence a caller can
    hand back to whoever sent the name.
    """
    if not isinstance(ns, str):
        return f"namespace must be a string, not {type(ns).__name__}"
    if ns == "":
        return None
    if len(ns) > MAX_NAMESPACE_CHARS:
        return f"namespace is {len(ns)} characters; the limit is {MAX_NAMESPACE_CHARS}"
    if not ns.startswith("/"):
        return f"namespace {ns!r} is not absolute"
    if ns.endswith("/"):
        return f"namespace {ns!r} ends in a separator"
    for token in ns[1:].split("/"):
        if not _TOKEN.match(token):
            return (
                f"namespace {ns!r}: {token!r} is not a legal ROS name token "
                "(letters, digits and underscore, not starting with a digit)"
            )
    return None
