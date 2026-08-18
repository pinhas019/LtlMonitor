"""Skill Monitor -- runtime progress monitoring for robot skills.

Layers, strictly one-directional (core knows nothing about the layers above it):

    core/       pure logic. No ROS, no Tk, no network. Unit-testable anywhere:
                Buchi automata, the spec-contract oracle, guard/threshold helpers.
    backend/    the ROS layer. Monitor + evaluator nodes, and adapters/ -- one per
                embodiment, each declaring the sensor schema that embodiment offers.
    frontend/   the operator surface. Skill Center control panel.
    describer/  free-language skill description -> validated formulas_<skill>.json.
    specs/      the specs themselves.

Config resolution -- **CLI flag > SKILL_MONITOR_CONFIG env > packaged defaults** --
lives here and only here, so that every layer answers "where do adapters and specs
come from?" the same way. Artifacts live on a volume and code lives in the image: a
skill or a robot changes without a rebuild, and a robot can carry a spec the image
never saw.

The packaged fallback is load-bearing, not a hedge. `python3 -m pytest` and a bare
`python3 -m skill_monitor...` must work on a machine with nothing mounted -- that is
how every test in this repo runs, in CI and on the dev host. Images still COPY the
package, so a container with no /config volume boots on the bundled defaults; it is
expected to say which it used, via `config_report()`.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Environment variable naming the config root -- the directory holding `adapters/`
#: and `specs/`. `/config` in every image shipped from deploy/.
CONFIG_ENV = "SKILL_MONITOR_CONFIG"

PACKAGE_ROOT = Path(__file__).resolve().parent

#: Packaged defaults: what ships inside the image/wheel, and the last resort of
#: every lookup below.
PACKAGED_SPECS_DIR = PACKAGE_ROOT / "specs"
PACKAGED_ADAPTERS_DIR = PACKAGE_ROOT / "adapters"

#: Retained name -- pre-existing callers import this as "the specs directory".
SPECS_DIR = PACKAGED_SPECS_DIR

#: Set by `set_config_dir()`, which an entry point calls from its --config flag.
#: A module-level slot rather than a parameter threaded through every call site:
#: the choice is made once per process, at argv-parsing time.
_cli_config_dir: Path | None = None


# --------------------------------------------------------------- config root

def set_config_dir(path: str | Path | None) -> None:
    """Record the --config flag. Highest precedence; `None` clears it.

    Entry points call this once, straight after parsing argv, before anything
    resolves a spec or a descriptor.
    """
    global _cli_config_dir
    _cli_config_dir = Path(path).expanduser() if path is not None else None


def add_config_argument(parser, flag: str = "--config") -> None:
    """Add the standard --config flag to an argparse parser.

    Here rather than copied into each entry point so the flag cannot drift in
    name or help text between services.
    """
    parser.add_argument(
        flag, default=None, metavar="DIR",
        help=(f"config root holding adapters/ and specs/ (default: ${CONFIG_ENV}, "
              "else the packaged defaults)"),
    )


def config_dir() -> Path | None:
    """The resolved config root, or None when the packaged defaults are in force.

    A configured-but-absent directory resolves to None rather than raising: a
    container started without its volume must still boot and report what it used.
    `config_source()` distinguishes the two Nones.
    """
    for candidate in (_cli_config_dir, _env_config_dir()):
        if candidate is not None and candidate.is_dir():
            return candidate
    return None


def config_source() -> str:
    """Which rung of the ladder won: ``"cli"``, ``"env"`` or ``"packaged"``."""
    if _cli_config_dir is not None and _cli_config_dir.is_dir():
        return "cli"
    env = _env_config_dir()
    if env is not None and env.is_dir():
        return "env"
    return "packaged"


def config_report() -> str:
    """One line naming every directory in use and why -- print this at startup.

    A stack that silently reads the baked-in spec instead of the mounted one is
    the failure this exists to make visible.
    """
    parts = [f"config: {config_dir() or 'packaged defaults'} (from {config_source()})"]
    for name, resolved, packaged in (
        ("adapters", adapters_dir(), PACKAGED_ADAPTERS_DIR),
        ("specs", specs_dir(), PACKAGED_SPECS_DIR),
    ):
        origin = "packaged" if resolved == packaged else "volume"
        parts.append(f"{name}: {resolved} ({origin})")
    missing = _configured_but_missing()
    if missing:
        parts.append(f"WARNING: {missing} does not exist -- fell back to packaged")
    return "; ".join(parts)


# ---------------------------------------------------------- the two artifacts

def adapters_dir() -> Path:
    """Where adapter descriptors and sensor schemas are read from.

    `<config>/adapters` when that directory exists, else the packaged copy. The
    fallback is per-directory, not per-root: mounting a /config that carries only
    specs must not take the descriptors away with it.
    """
    return _subdir("adapters", PACKAGED_ADAPTERS_DIR)


def specs_dir() -> Path:
    """Where skill specs are read from. `<config>/specs`, else the packaged copy."""
    return _subdir("specs", PACKAGED_SPECS_DIR)


def spec_path(name: str) -> Path:
    """Locate a spec by file name or bare skill label.

    Everything that needs a spec -- tests, the engine's --formulas-file default,
    the describer's output target, the Docker images -- goes through here, so the
    specs can move without another hunt through relative paths.

    The mounted directory is searched before the packaged one, so a volume's spec
    wins over the baked one of the same name; a spec present only in the image
    still resolves, which is what keeps pytest green with nothing mounted.
    """
    fname = name if name.endswith(".json") else f"formulas_{name}.json"
    searched: list[Path] = []
    for directory in _dedup(specs_dir(), PACKAGED_SPECS_DIR):
        searched.append(directory)
        candidate = directory / fname
        if candidate.exists():
            return candidate
    available = sorted({q.name for d in searched for q in d.glob("*.json")})
    where = " or ".join(str(d) for d in searched)
    raise FileNotFoundError(f"no spec {fname!r} in {where} (have: {available})")


# -------------------------------------------------------------------- helpers

def _env_config_dir() -> Path | None:
    raw = os.environ.get(CONFIG_ENV)
    return Path(raw).expanduser() if raw else None


def _configured_but_missing() -> Path | None:
    """A config root that was asked for but is not on disk, if any."""
    for candidate in (_cli_config_dir, _env_config_dir()):
        if candidate is not None and not candidate.is_dir():
            return candidate
    return None


def _subdir(name: str, packaged: Path) -> Path:
    root = config_dir()
    if root is not None:
        candidate = root / name
        if candidate.is_dir():
            return candidate
    return packaged


def _dedup(*paths: Path) -> list[Path]:
    seen: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.append(p)
    return seen
