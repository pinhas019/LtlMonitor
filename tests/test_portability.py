"""Every text-mode file read and write in the tree names its encoding.

A `Path.read_text()` with no `encoding=` does not read UTF-8. It reads whatever
`locale.getpreferredencoding(False)` says on the machine that happens to be running,
which is UTF-8 in the Linux test container and cp1255 on the Windows host this project
is also developed from. The same bytes on disk therefore decode to two different
strings depending on where the process started, and nothing in the code says so.

That matters here more than it would elsewhere. P9's acceptance test for the
hardware-agnosticism claim is verdict equality between two replays of one recorded
episode -- and the recording is written by `backend/replay_node.py`. If the recorder
takes its encoding from the host, the comparison that is supposed to prove the monitor
is hardware-agnostic is itself not machine-agnostic, and a run recorded on the laptop
replays as mojibake on the robot.

This file is separate from `tests/test_api.py` on purpose: no package in the ownership
matrix of `docs/packages/README.md` owns cross-cutting portability, and `test_api.py`
is P0's. The scan is modelled on `test_no_hardcoded_topic_literals` there and has the
same shape and the same point -- a NEW unencoded read or write fails immediately, for
whoever wrote it.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]

SCANNED = ("skill_monitor", "tests", "tools", "sim")

# `open` is not always a file open. These namespaces have one that takes no encoding
# and never touches a text stream, so `.open` reached through them is not a finding.
# `urllib.request.urlopen` needs no entry: its name is `urlopen`, not `open`.
NOT_A_FILE_OPEN = {"webbrowser", "os", "socket", "subprocess"}

# Where `encoding` sits when it is passed positionally instead of by keyword. The
# builtin `open(file, mode, buffering, encoding)` and `Path.open(mode, buffering,
# encoding)` differ by one, because the path is the receiver in the second -- hence
# two entries for the one name.
_ENCODING_POSITION = {
    "read_text": 0,          # Path.read_text(encoding, errors)
    "write_text": 1,         # Path.write_text(data, encoding, errors)
    "open": 3,               # open(file, mode, buffering, encoding)
    "open_attribute": 2,     # Path.open(mode, buffering, encoding)
}


def _root_name(node: ast.AST) -> str | None:
    """The leftmost name of a dotted expression: `urllib.request.foo` -> `urllib`."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _mode_expr(call: ast.Call, positional_index: int) -> ast.AST | None:
    """The `mode` argument of an `open` call, or None when it was left to default."""
    for kw in call.keywords:
        if kw.arg == "mode":
            return kw.value
    if len(call.args) > positional_index:
        return call.args[positional_index]
    return None


def _literal_modes(expr: ast.AST | None) -> list[str] | None:
    """Every mode string `expr` can evaluate to, or None if that is not knowable.

    A conditional is resolved rather than given up on, because `"a" if append else "w"`
    is the shape the recorder actually uses and both of its branches are as readable as
    a plain literal.
    """
    if expr is None:
        return ["r"]                       # the default when mode is omitted
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.IfExp):
        left, right = _literal_modes(expr.body), _literal_modes(expr.orelse)
        return None if left is None or right is None else left + right
    return None


def _names_encoding(call: ast.Call, positional_index: int) -> bool:
    if any(kw.arg == "encoding" for kw in call.keywords):
        return True
    # A `**kwargs` splat could be carrying it and the AST cannot say. Give it the
    # benefit of the doubt rather than report a finding nobody can act on.
    if any(kw.arg is None for kw in call.keywords):
        return True
    return len(call.args) > positional_index


def _unencoded_text_io(source: str, filename: str) -> list[tuple[int, str]]:
    """`(lineno, why)` for every text-mode read or write in `source` with no encoding.

    Binary opens are exempt -- `encoding=` on one is a ValueError, not a fix.

    An `open` whose mode is a plain variable *is* reported, even though the scan cannot
    prove it opens text. A mode a reader cannot see is an encoding nobody can verify,
    and the fix is to make the mode literal rather than to add an argument that may
    then be illegal. The tree has none today, so that arm is covered by the probe below
    instead.
    """
    tree = ast.parse(source, filename=filename)
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if isinstance(func, ast.Name):
            name, receiver = func.id, None
        elif isinstance(func, ast.Attribute):
            name, receiver = func.attr, func.value
        else:
            continue

        if name in ("read_text", "write_text"):
            # Both are text-mode by definition. The binary spellings are `read_bytes`
            # and `write_bytes`, different names, so there is nothing to exempt.
            if not _names_encoding(node, _ENCODING_POSITION[name]):
                found.append((node.lineno, f"{name}() with no encoding="))
            continue

        if name != "open":
            continue
        if receiver is not None and _root_name(receiver) in NOT_A_FILE_OPEN:
            continue

        builtin = receiver is None or _root_name(receiver) == "io"
        mode_index = 1 if builtin else 0
        encoding_index = _ENCODING_POSITION["open" if builtin else "open_attribute"]

        modes = _literal_modes(_mode_expr(node, mode_index))
        if modes is None:
            found.append((node.lineno, "open() with a mode this scan cannot read; make "
                                       "the mode literal so its encoding can be "
                                       "checked"))
            continue
        if all("b" in mode for mode in modes):
            continue
        if any("b" in mode for mode in modes):
            found.append((node.lineno, "open() whose mode may be either text or "
                                       "binary; no one encoding= is legal for both"))
            continue

        if not _names_encoding(node, encoding_index):
            found.append((node.lineno, "open() in text mode with no encoding="))

    found.sort(key=lambda item: item[0])
    return found


def _python_files():
    for top in SCANNED:
        for path in sorted((REPO / top).rglob("*.py")):
            yield path, path.relative_to(REPO).as_posix()


def test_every_text_read_and_write_names_its_encoding():
    """An unencoded read or write makes a file's meaning a property of the host.

    What breaks: a recording written on Windows under cp1255 and replayed on the robot
    under UTF-8 decodes to different text, so P9's two-replay verdict comparison --
    the acceptance test for the hardware-agnosticism claim -- compares two things that
    were never the same episode. Short of that, the suite itself goes red on any host
    whose default codepage cannot decode the em-dashes in `docs/api.md`.

    This fails for whoever writes the call, which is the only moment it is one line to
    fix.
    """
    offenders = []
    for path, rel in _python_files():
        for lineno, why in _unencoded_text_io(path.read_text(encoding="utf-8"), rel):
            offenders.append(f"{rel}:{lineno}: {why}")
    assert not offenders, (
        'text-mode file access with no explicit encoding; add encoding="utf-8" so the '
        "file means the same thing on every machine:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_can_tell_the_cases_apart():
    """A scanner that reports nothing passes whether or not the tree is clean.

    What breaks without this: the guard above quietly stops guarding the first time
    someone edits the matching logic, and the next unencoded write ships green.
    """
    source = "\n".join([
        "p.read_text()",                       # 1  offender
        "p.read_text(encoding='utf-8')",       # 2  clean, by keyword
        "p.read_text('utf-8')",                # 3  clean, positionally
        "p.write_text(s)",                     # 4  offender
        "p.write_text(s, encoding='utf-8')",   # 5  clean
        "open(f)",                             # 6  offender, defaults to text mode
        "open(f, 'w')",                        # 7  offender
        "open(f, 'rb')",                       # 8  exempt, binary
        "open(f, mode='wb')",                  # 9  exempt, binary by keyword
        "open(f, 'w', encoding='utf-8')",      # 10 clean
        "p.open('w')",                         # 11 offender, Path.open
        "p.open('w', -1, 'utf-8')",            # 12 clean, positionally
        "webbrowser.open(url)",                # 13 not a file open
        "urllib.request.urlopen(req)",         # 14 not a file open
        "open(f, some_mode)",                  # 15 offender, mode a reader cannot see
        "p.read_bytes()",                      # 16 binary spelling, exempt
        "open(f, 'a' if x else 'w')",          # 17 offender, both branches text
        "open(f, 'ab' if x else 'wb')",        # 18 exempt, both branches binary
        "open(f, 'a' if x else 'wb')",         # 19 offender, no encoding fits both
    ])
    assert [line for line, _ in _unencoded_text_io(source, "<probe>")] == [
        1, 4, 6, 7, 11, 15, 17, 19,
    ]
