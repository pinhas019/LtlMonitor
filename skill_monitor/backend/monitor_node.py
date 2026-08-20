"""The monitor node — steps the automata once per tick and publishes the verdict.

Formulas are supplied via -f flags or a --formulas-file JSON file. `--formulas-file`
takes a **bare spec name** as readily as a path: the compose files pass
`formulas_g1.json` and the lookup resolves through `skill_monitor.spec_path()`, so a
container finds the spec on its /config volume, or the packaged one if nothing is
mounted.

Usage examples:
    python3 -m skill_monitor.backend.monitor_node -f "F(goal)" -f "G(!obstacle)"
    python3 -m skill_monitor.backend.monitor_node --formulas-file formulas_g1.json

Two things this node is careful about, both of which used to be wrong here:

**One automaton step per tick, keyed on the received `seq`.** The step used to be driven
by message arrival, while the evaluator publishes from a worker thread behind a queue --
so under model backlog tick N's automaton was stepped against tick N-k's observation
with nothing in the record to say so. `manifest.TickLedger` now decides: one step per
distinct advancing tick index, a redelivered index changes nothing, and a gap is
published in `missed_ticks` rather than interpolated away.

**The intervention rung is decided here.** It ships inside the verdict, so the enforcing
node has nothing left to decide and the choice is in the recorded stream rather than
implicit in the robot's behaviour.

Skill-type agnosticism: --formulas-file is just the default/initial spec. If something
publishes a skill label on /active_skill (std_msgs/String), and a matching
formulas_<label>.json exists, this node swaps to it. No publisher exists for G1 yet
(only one skill, navigation); this is inert future-proofing, not a behavior change.
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

import skill_monitor
import skill_monitor.core.manifest as manifest_mod
import skill_monitor.core.spec_contract as spec_contract
from skill_monitor.core import api
from skill_monitor.core.automata import FailureModeInfo, MonitorStatus, MultiMonitor, LTLMonitor

# ---------------------------------------------------------------------------
# Legacy topics — dual-run window
# ---------------------------------------------------------------------------
#
# The rename is `/ltl/*` -> `/monitor/*` (docs/api.md, "Migration from /ltl/*"). The
# monitor sits between an evaluator that has not moved yet (P3) and a supervisor and a
# frontend that have not moved yet (P5, P7), so for one release it speaks both: it
# subscribes to the legacy observation topic as well as api.OBSERVATION, and publishes
# the legacy state description alongside api.VERDICT.
#
# Every constant below dies with the package named against it. Nothing new may be added
# to this block, and `tests/test_api.py` keeps this file on AWAITING_MIGRATION until it
# is empty.
_LEGACY_EVALUATIONS = "/ltl/evaluations"      # in  — dies when P3 publishes api.OBSERVATION
_LEGACY_STATE_DESC = "/ltl/state_description"  # out — dies when P5 and P7 read api.VERDICT
_LEGACY_REQUIRED_APS = "/ltl/required_aps"    # out — folded into the verdict; dies with P3
_LEGACY_MANIFEST = "/ltl/manifest"            # out — dies with P7
_LEGACY_ADAPTER = "/ltl/adapter"              # in  — dies with P3
_LEGACY_LOAD_SPEC = "/ltl/load_spec"          # in  — dies with P7
_LEGACY_SPEC_STATUS = "/ltl/spec_status"      # out — dies with P7

# Latched: the spec and the adapter description change rarely and matter to every
# late-joining client, so they are published TRANSIENT_LOCAL rather than repeated on
# a timer. Anyone subscribing after the fact still receives the last value.
_LATCHED = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

BOLD  = "\033[1m"
RESET = "\033[0m"
DIM   = "\033[2m"
CYAN  = "\033[36m"

_STATUS_LABELS = {
    MonitorStatus.INCONCLUSIVE: "\033[33m●\033[0m",   # yellow dot
    MonitorStatus.ACCEPTED:     "\033[32m✔\033[0m",   # green check
    MonitorStatus.VIOLATED:     "\033[31m✘\033[0m",   # red cross
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LTL_OPS = re.compile(r'\b(G|F|X)\s*\(')
# Rule extraction is shared with the evaluator and the contract test, so the rule
# printed in this console table is exactly the rule that gets evaluated.
_TRUE_WHEN_RE = spec_contract.TRUE_WHEN_RE

def _sanitize_condition(condition: str) -> str:
    """Translate LTL/C-style boolean syntax to Python-eval-compatible syntax.

    Handles: && → and, || → or, ! → not, G/F/X(...) → (...).
    """
    # Strip LTL temporal operators iteratively (handles nesting like G(F(x)))
    prev = None
    while prev != condition:
        prev = condition
        condition = _LTL_OPS.sub('(', condition)
    condition = condition.replace('&&', ' and ')
    condition = condition.replace('||', ' or ')
    condition = re.sub(r'!(?!=)', 'not ', condition)
    return condition


def _phase_fault_entry(
    *,
    phase: str,
    kind: str,
    category: str | None,
    expression: str,
    reason: str,
    recoverable: bool,
) -> dict:
    """A phase-machine fault in the shape `verdict.failure_modes` wants.

    The phase machine is the monitor's second fault detector and, until now, the silent
    one: `failure_modes` came only from the spec's *named* modes, so a phase invariant
    breach halted this process while the token it published said CONTINUE. All three
    phases in the shipped G1 spec declare `invariant_fault_category: "SAFETY"`, and P5
    is contracted to obey the token and nothing else -- so a compliant supervisor had no
    reason to stop the robot. G1's named modes cover the same ground by coincidence;
    TIMEOUT and precondition faults have no such cover.

    `name` is synthesised, since a spec names its own failure modes but not its phase
    faults, and is stable per (phase, kind) so a consumer can key on it. `reason`,
    `expression` and `recoverable` ride along for the node's own use; the wire builder
    reads only name/fault_category/status.
    """
    return {
        "name": f"phase:{phase}:{kind}",
        "fault_category": category,
        "status": MonitorStatus.VIOLATED.name,
        "reason": reason,
        "expression": expression,
        "recoverable": recoverable,
    }


def _extract_aps_from_condition(condition: str) -> set[str]:
    """Return all AP identifier names used in a boolean condition expression."""
    try:
        tree = ast.parse(_sanitize_condition(condition), mode='eval')
        return {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and not keyword.iskeyword(node.id)
        }
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Rich formula spec
# ---------------------------------------------------------------------------

class SkillSpec:
    def __init__(
        self,
        formulas: list[str],
        names: list[str],
        skill_name: str = "",
        description: str = "",
        atomic_propositions: dict[str, str] | None = None,
        execution_phases: list[dict] | None = None,
        terminal_success: dict | None = None,
        terminal_failure: dict | None = None,
        named_failure_modes: list[dict] | None = None,
        raw: dict | None = None,
    ) -> None:
        # The spec exactly as authored. Kept so the monitor can hand the whole thing
        # to clients on the manifest topic without reconstructing it from parsed pieces.
        self.raw                 = raw or {}
        self.formulas            = formulas
        self.names               = names
        self.skill_name          = skill_name
        self.description         = description
        self.atomic_propositions = atomic_propositions or {}
        self.execution_phases    = execution_phases or []

        # Named failure modes: LTL formulas whose VIOLATION signals a specific fault.
        # Each entry: {name, formula, fault_category, description?}
        self.named_failure_modes: list[dict] = named_failure_modes or []

        terminal_success = terminal_success or {}
        self.terminal_success_condition   = terminal_success.get("condition",   "False")
        self.terminal_success_description = terminal_success.get("description", "")

        terminal_failure = terminal_failure or {}
        self.terminal_failure_condition   = terminal_failure.get("condition",   "False")
        self.terminal_failure_description = terminal_failure.get("description", "")

        self.terminal_success_aps: set[str] = _extract_aps_from_condition(self.terminal_success_condition)
        self.terminal_failure_aps: set[str] = _extract_aps_from_condition(self.terminal_failure_condition)
        self.terminal_aps: set[str]          = self.terminal_success_aps | self.terminal_failure_aps

        # APs needed across all phase conditions:
        # enter + precondition + invariant + progress + exit
        self.phase_aps: set[str] = set()
        for phase in self.execution_phases:
            for key in (
                "enter_condition", "condition",
                "precondition",
                "invariant",
                "progress_condition",
                "exit_condition",
            ):
                self.phase_aps |= _extract_aps_from_condition(phase.get(key, ""))

    def build_failure_mode_infos(self) -> list[FailureModeInfo | None]:
        """
        Return a parallel list of FailureModeInfo for each named failure formula,
        sized to match the combined formula list (property formulas first, then
        failure-mode formulas).  Use alongside ``all_formulas`` / ``all_names``.
        """
        return [None] * len(self.formulas) + [
            FailureModeInfo(
                name=fm["name"],
                fault_category=fm.get("fault_category", "UNKNOWN"),
                description=fm.get("description", ""),
            )
            for fm in self.named_failure_modes
        ]

    @property
    def all_formulas(self) -> list[str]:
        """Property formulas + named-failure-mode formulas, in that order."""
        return self.formulas + [fm["formula"] for fm in self.named_failure_modes]

    @property
    def all_names(self) -> list[str]:
        return self.names + [fm["name"] for fm in self.named_failure_modes]


def load_formulas_from_file(path) -> SkillSpec:
    """A spec from `--formulas-file`, which may be a path OR a bare spec name.

    Resolution goes through `manifest.resolve_spec_path`, i.e. through
    `skill_monitor.spec_path()`, because the compose files pass `formulas_g1.json` and
    expect it to be found on the /config volume -- or in the image when nothing is
    mounted. Reading the flag as a plain relative path made a containerised monitor
    fail to find a spec it was shipped with.
    """
    try:
        resolved = manifest_mod.resolve_spec_path(path)
    except FileNotFoundError as exc:
        print(f"Error resolving formulas file: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(resolved.read_text())
    except Exception as exc:
        print(f"Error reading formulas file: {exc}", file=sys.stderr)
        sys.exit(1)
    return spec_from_dict(data)


def spec_from_dict(data) -> SkillSpec:
    """A spec from already-parsed JSON -- the same code path whether it came off disk
    or off the load_spec topic, so a pushed spec can never be interpreted differently
    from a loaded one."""
    if isinstance(data, list):
        return SkillSpec(formulas=data, names=data, raw={"ltl_formulas": data})

    raw_formulas = data.get("ltl_formulas", [])
    formulas, names = [], []
    for entry in raw_formulas:
        formulas.append(entry["formula"])
        names.append(entry.get("name", entry["formula"]))

    return SkillSpec(
        formulas             = formulas,
        names                = names,
        skill_name           = data.get("skill_name", ""),
        description          = data.get("description", ""),
        atomic_propositions  = data.get("atomic_propositions", {}),
        execution_phases     = data.get("execution_phases", []),
        terminal_success     = data.get("terminal_success"),
        terminal_failure     = data.get("terminal_failure"),
        named_failure_modes  = data.get("named_failure_modes", []),
        raw                  = data,
    )


# Declared in core so the pure risk block and this node's phase machine cannot drift.
_PHASE_VIOLATION_LIMIT = manifest_mod.PHASE_VIOLATION_LIMIT

#: One warn line per this many consecutively refused observations, after the first.
#: A refusal burst is bounded now, but "bounded" was 5001 lines before it was one lost
#: tick, and a log that drowns its own signal is its own outage.
_REFUSAL_LOG_EVERY = 100

#: Clock pulses with no admitted step before the monitor says so on api.VERDICT.
#: The clock is a *different* publisher from the evaluator, so it keeps pulsing through
#: every cause of stepping silence -- a dead evaluator, a demoted wire, a refused epoch
#: -- and it is the only thing in this process that knows time is still passing.
_STALL_TICKS = 5

#: Clock pulses with no admitted step before the legacy wire is allowed to step again.
#: Longer than `_STALL_TICKS` on purpose: the indication is free and the re-admission is
#: not. Legacy arrivals carry no `seq` and are numbered from their own counter, so they
#: are not deduplicated against envelope indices -- re-admitting a merely *slow*
#: envelope double-steps the tick they share. Five seconds of silence at 2 Hz is not a
#: slow envelope, and the demotion is restored by the next envelope that arrives.
_LEGACY_READMIT_TICKS = 10


def _infer_state_annotations(
    mon: LTLMonitor, spec: "SkillSpec"
) -> dict[int, dict]:
    """
    Map each automaton state to the execution phase it represents.

    Strategy — works reliably for sequential formulas such as
        F(p1 && F(p2 && F(p3 && ...)))

    For each progress state we inspect the automaton's own forward transitions
    (edges that leave the current state) to find which AP advances it, then
    step with that AP to reach the next state.  Phases are assigned in
    declaration order: state 0 → phase 0, state after stepping p1 → phase 1, …

    Returns a dict mapping automaton-state-index → phase metadata dict.
    """
    phases = spec.execution_phases
    if not phases or mon.status is MonitorStatus.VIOLATED:
        return {}

    annotations: dict[int, dict] = {}

    saved_state  = mon.current_state
    saved_status = mon.status
    mon.current_state = mon._initial_state
    mon.status        = mon._compute_status()

    def _phase_meta(p: dict) -> dict:
        return {
            "phase_name":                  p["phase"],
            "description":                 p.get("description", ""),
            "precondition":                p.get("precondition", ""),
            "precondition_fault_category": p.get("precondition_fault_category", "PRECONDITION"),
            "invariant":                   p.get("invariant", ""),
            "invariant_fault_category":    p.get("invariant_fault_category", "INVARIANT"),
            "timing_bounds":               p.get("timing_bounds", {}),
        }

    all_known_aps: dict[str, bool] = {str(ap): False for ap in mon.aut.ap()}

    # Initial state → first phase
    annotations[mon.current_state] = _phase_meta(phases[0])

    # Walk one step per phase transition using the AP that the automaton
    # itself requires to advance from the current state.
    for phase_idx in range(len(phases) - 1):
        # Collect APs on edges that leave the current state (non-self-loop)
        forward_aps: set[str] = set()
        for edge in mon.aut.out(mon.current_state):
            if edge.dst != mon.current_state and edge.dst not in mon._sink_states:
                forward_aps |= mon._get_edge_aps(edge)

        if not forward_aps:
            break  # accepting or sink — nothing more to walk

        # Try each forward AP until one actually advances the state
        advanced = False
        for ap in sorted(forward_aps):          # sorted for determinism
            obs = dict(all_known_aps)
            obs[ap] = True
            obs_bdd   = mon._observation_to_bdd(obs)
            next_s    = mon._find_successor(obs_bdd)
            if next_s is not None and next_s != mon.current_state:
                prev = mon.current_state
                mon.step(obs)
                if mon.current_state != prev and mon.status is not MonitorStatus.VIOLATED:
                    annotations[mon.current_state] = _phase_meta(phases[phase_idx + 1])
                    advanced = True
                break

        if not advanced:
            break

    # Mark accepting states not yet annotated as "Done"
    for s in range(mon.aut.num_states()):
        if mon.aut.state_is_accepting(s) and s not in annotations:
            annotations[s] = {
                "phase_name":  "Done",
                "description": "All phases complete — formula accepted.",
            }

    mon.current_state = saved_state
    mon.status        = saved_status
    return annotations


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

NAME_W = 42

def _print_skill_header(spec: SkillSpec) -> None:
    if spec.skill_name:
        print(f"\n{BOLD}{'═' * 64}{RESET}")
        print(f"{BOLD}  Skill : {CYAN}{spec.skill_name}{RESET}")
        if spec.description:
            print(f"  {DIM}{spec.description}{RESET}")
        print(f"{BOLD}{'═' * 64}{RESET}")


def _print_formula_table(multi: MultiMonitor, spec: SkillSpec, output_dir: Path = Path("output")) -> None:
    ap_descs = spec.atomic_propositions or None

    # ── Property formulas (annotated with phase info) ─────────────
    prop_monitors  = multi.get_property_monitors()
    fault_monitors = multi.get_failure_mode_monitors()

    if prop_monitors:
        print(f"\n{BOLD}Property Formulas & Büchi Automata:{RESET}")
    for mon in prop_monitors:
        state_ann = _infer_state_annotations(mon, spec)
        print(mon.format_automaton(ap_descriptions=ap_descs, state_annotations=state_ann))
        save_automaton_image(mon, output_dir)
        print()

    # ── Named failure-mode formulas ───────────────────────────────
    if fault_monitors:
        RED = "\033[31m"
        print(f"\n{BOLD}Named Failure-Mode Automata:{RESET}")
    for mon in fault_monitors:
        finfo = mon.failure_mode
        RED = "\033[31m"
        print(f"  {BOLD}{RED}[{finfo.fault_category}] {finfo.name}{RESET}  —  {finfo.description}")
        print(mon.format_automaton(ap_descriptions=ap_descs))
        save_automaton_image(mon, output_dir)
        print()

    # ── Combined product automaton ────────────────────────────────
    try:
        combined_formula = " && ".join(f"({m.formula})" for m in multi.monitors)
        combined_mon = LTLMonitor(combined_formula, name="CombinedSkillSpec")
        print(f"{BOLD}Combined/Product Büchi Automaton — Full Skill Specification:{RESET}")
        print(combined_mon.format_automaton(ap_descriptions=ap_descs))
        print()
        save_automaton_image(combined_mon, output_dir)
    except Exception as e:
        print(f"Note: Could not build combined product automaton: {e}")

    _print_evaluation_rules(spec)


def _print_evaluation_rules(spec: SkillSpec) -> None:
    """Print the AP evaluation rules table, terminal conditions, and phase summary."""
    GREEN = "\033[32m"
    RED   = "\033[31m"
    YELLOW = "\033[33m"

    # ── AP rules table ────────────────────────────────────────────
    if spec.atomic_propositions:
        max_ap = max(len(ap) for ap in spec.atomic_propositions)
        max_ap = max(max_ap, 10)

        print(f"\n{BOLD}  Atomic Propositions & Evaluation Rules:{RESET}")
        print(f"  {'─' * 64}")
        for ap_name, desc in spec.atomic_propositions.items():
            m = _TRUE_WHEN_RE.search(desc)
            if m:
                rule = m.group(1).strip().rstrip('.')
                method = f"{YELLOW}⚡ Rule{RESET}"
            else:
                rule = desc
                method = f"{CYAN}🤖 LLM{RESET}"
            print(f"    {CYAN}{ap_name:<{max_ap}}{RESET}  {DIM}│{RESET}  {rule}  {DIM}[{RESET}{method}{DIM}]{RESET}")
        print(f"  {'─' * 64}")

    # ── Terminal conditions ────────────────────────────────────────
    has_success = spec.terminal_success_condition != "False"
    has_failure = spec.terminal_failure_condition != "False"
    if has_success or has_failure:
        print(f"\n{BOLD}  Terminal Conditions:{RESET}")
        if has_success:
            print(f"    {GREEN}✔ SUCCESS:{RESET}  {spec.terminal_success_condition}")
            if spec.terminal_success_description:
                print(f"      {DIM}{spec.terminal_success_description}{RESET}")
        if has_failure:
            print(f"    {RED}✘ FAILURE:{RESET}  {spec.terminal_failure_condition}")
            if spec.terminal_failure_description:
                print(f"      {DIM}{spec.terminal_failure_description}{RESET}")

    # ── Named failure modes ───────────────────────────────────────
    if spec.named_failure_modes:
        max_fm = max(len(fm["name"]) for fm in spec.named_failure_modes)
        max_fm = max(max_fm, 12)
        print(f"\n{BOLD}  Named Failure Modes:{RESET}")
        print(f"  {'─' * 64}")
        for fm in spec.named_failure_modes:
            cat  = fm.get("fault_category", "UNKNOWN")
            desc = fm.get("description", "")
            print(f"    {RED}{fm['name']:<{max_fm}}{RESET}  {DIM}│{RESET}  formula: {DIM}{fm['formula']}{RESET}")
            print(f"    {' ' * max_fm}  {DIM}│  [{cat}]{RESET}  {desc}")
        print(f"  {'─' * 64}")

    # ── Execution phases ──────────────────────────────────────────
    if spec.execution_phases:
        print(f"\n{BOLD}  Execution Phases:{RESET}")
        for i, phase in enumerate(spec.execution_phases):
            enter    = phase.get("enter_condition") or phase.get("condition", "—")
            exit_c   = phase.get("exit_condition", "—")
            progress = phase.get("progress_condition", "True")
            precond  = phase.get("precondition", "")
            invariant = phase.get("invariant", "")
            timing   = phase.get("timing_bounds", {})
            next_name = spec.execution_phases[i + 1]["phase"] if i + 1 < len(spec.execution_phases) else "Done"

            print(f"    {BOLD}{i + 1}. {CYAN}{phase['phase']}{RESET}")
            if phase.get("description"):
                print(f"       {DIM}{phase['description']}{RESET}")
            print(f"       {DIM}enter     :{RESET} {enter}")
            if precond:
                print(f"       {DIM}precond   :{RESET} {precond}  {DIM}[checked on entry]{RESET}")
            if invariant:
                inv_cat = phase.get("invariant_fault_category", "INVARIANT")
                print(f"       {DIM}invariant :{RESET} {invariant}  {DIM}[{inv_cat} — immediate failure]{RESET}")
            print(f"       {DIM}progress  :{RESET} {progress}")
            print(f"       {DIM}exit → {next_name}:{RESET} {exit_c}")
            if timing:
                min_s = timing.get("min_steps", "—")
                max_s = timing.get("max_steps", "—")
                print(f"       {DIM}timing    :{RESET} min {min_s} steps / max {max_s} steps")
        print()


def _state_label(mon: LTLMonitor, state: int) -> str:
    labels = []
    if state == mon._initial_state:
        labels.append("initial")
    if mon.aut.state_is_accepting(state):
        labels.append("accepting")
    if state in mon._sink_states:
        labels.append("sink/trap")
    return f" [{', '.join(labels)}]" if labels else ""


def _print_step_block(
    step: int | str,
    multi: MultiMonitor,
    observation: dict[str, bool],
    phase: str | None,
    changed_only: bool = False,
    prev_statuses: dict[str, MonitorStatus] | None = None,
    prev_states: dict[str, int] | None = None,
    phase_violations: int = 0,
) -> None:
    has_changes = False
    if prev_statuses:
        for mon in multi.monitors:
            if prev_statuses.get(mon.name) != mon.status:
                has_changes = True
    if prev_states:
        for mon in multi.monitors:
            if prev_states.get(mon.name) != mon.current_state:
                has_changes = True

    if changed_only and not has_changes and step != "init":
        return

    phase_label = phase if phase else "Idle"
    phase_str = f"  {CYAN}[{phase_label}]{RESET}"
    print(f"  {BOLD}┌── Step {step}{phase_str} {'─' * 30}{RESET}")

    # AP truth table — one line for TRUE, one for FALSE
    clean_obs = {k: v for k, v in observation.items() if not k.startswith("__")}
    if clean_obs:
        true_aps  = [k for k, v in clean_obs.items() if v]
        false_aps = [k for k, v in clean_obs.items() if not v]
        if true_aps:
            parts = "  ".join(f"\033[32m{k}\033[0m" for k in true_aps)
            print(f"  │ {DIM}TRUE :{RESET}  {parts}")
        if false_aps:
            parts = "  ".join(f"\033[31m{k}\033[0m" for k in false_aps)
            print(f"  │ {DIM}FALSE:{RESET}  {parts}")
        print(f"  │ {'─' * 52}")

    if phase_violations > 0:
        YELLOW = "\033[33m"
        print(f"  │ {BOLD}{YELLOW}⚠  Phase progress violations: {phase_violations}/{_PHASE_VIOLATION_LIMIT}{RESET}")
        print(f"  │ {'─' * 52}")

    # Formula status with current automaton state and labels
    for mon in multi.monitors:
        s = mon.status
        icon = _STATUS_LABELS[s]
        curr = mon.current_state
        curr_lbl = _state_label(mon, curr)

        if prev_states and mon.name in prev_states:
            prev_s = prev_states[mon.name]
            if prev_s != curr:
                prev_lbl = _state_label(mon, prev_s)
                state_str = f"S{prev_s}{prev_lbl} → S{curr}{curr_lbl}"
            else:
                state_str = f"S{curr}{curr_lbl}"
        else:
            state_str = f"S{curr}{curr_lbl}"

        marker = ""
        if prev_statuses is not None and prev_statuses.get(mon.name) != s:
            marker = f"  {BOLD}← {s.name}{RESET}"

        print(f"  │ {icon} {mon.name:<{NAME_W}} {DIM}{state_str}{RESET}{marker}")
    print(f"  {BOLD}└{'─' * 50}{RESET}")


def save_automaton_image(mon: LTLMonitor, output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        dot_str = mon.export_dot()
        dot_file = output_dir / f"{mon.name}.dot"
        dot_file.write_text(dot_str)
        
        import subprocess
        png_file = output_dir / f"{mon.name}.png"
        subprocess.run(["dot", "-Tpng", str(dot_file), "-o", str(png_file)], check=True)
        
        svg_file = output_dir / f"{mon.name}.svg"
        subprocess.run(["dot", "-Tsvg", str(dot_file), "-o", str(svg_file)], check=True)
        
        print(f"[+] Saved Büchi automaton images for '{mon.name}' in {output_dir}")
    except Exception as e:
        print(f"Warning: Failed to generate automaton image for '{mon.name}': {e}", file=sys.stderr)


def _print_summary(multi: MultiMonitor) -> None:
    print(f"\n{BOLD}{'═' * 64}{RESET}")
    print(f"{BOLD}  Final Summary{RESET}")
    print(f"{BOLD}{'═' * 64}{RESET}")

    accepted, violated, inconclusive = [], [], []
    for mon in multi:
        s = mon.status
        if s is MonitorStatus.ACCEPTED: accepted.append(mon)
        elif s is MonitorStatus.VIOLATED: violated.append(mon)
        else: inconclusive.append(mon)

    if violated:
        print(f"\n  {BOLD}\033[31m✘ VIOLATED ({len(violated)}):{RESET}")
        for mon in violated:
            print(f"    \033[31m✘\033[0m {mon.name}\n      {DIM}{mon.formula}{RESET}")

    if inconclusive:
        print(f"\n  {BOLD}\033[33m● INCONCLUSIVE ({len(inconclusive)}):{RESET}")
        for mon in inconclusive:
            print(f"    \033[33m●\033[0m {mon.name}\n      {DIM}{mon.formula}{RESET}")

    if accepted:
        print(f"\n  {BOLD}\033[32m✔ ACCEPTED ({len(accepted)}):{RESET}")
        for mon in accepted:
            print(f"    \033[32m✔\033[0m {mon.name}\n      {DIM}{mon.formula}{RESET}")

    print(f"\n{BOLD}{'─' * 64}{RESET}")
    total = len(list(multi))
    if multi.all_accepted():
        print(f"  {BOLD}\033[32m✔  All {total} formulas ACCEPTED.{RESET}")
    elif multi.any_violated():
        print(f"  {BOLD}\033[31m✘  {len(violated)}/{total} formula(s) VIOLATED.{RESET}")
    else:
        print(f"  {BOLD}\033[33m?  {len(inconclusive)}/{total} formula(s) INCONCLUSIVE.{RESET}")
    print()


# ---------------------------------------------------------------------------
# ROS 2 Node
# ---------------------------------------------------------------------------

class LtlMonitorNode(Node):
    def __init__(self, spec: SkillSpec, multi: MultiMonitor, args: argparse.Namespace):
        super().__init__('ltl_monitor_node')
        self.spec = spec
        self.multi = multi
        self.args = args
        self.step_idx = 0
        self.prev_statuses = dict(multi.statuses())
        self.has_phases = bool(spec.execution_phases)

        self.current_phase = ""
        self.phase_idx = -1           # index into spec.execution_phases; -1 = Idle
        self.phase_violation_count = 0
        self.phase_step_count = 0     # steps elapsed in the current phase
        self.halted = False
        self.paused = False
        # Confidence in the latest observation (sensor freshness, from the evaluator).
        # 1.0 until told otherwise, so an evaluator that does not report it behaves
        # exactly as before.
        self._confidence = 1.0
        self._stale_sources: list = []
        self._has_data = False
        self._terminal: str | None = None
        # The phase machine's own fault for this tick, in the shape
        # `verdict.failure_modes` wants. It travels in the verdict because P5 is
        # contracted to obey the token and nothing else -- a phase invariant breach that
        # halted this process while publishing CONTINUE left a compliant supervisor with
        # no reason to stop the robot.
        self._phase_fault: dict | None = None
        #: Faults already announced on the console, so a de-escalated one is reported
        #: once rather than on every tick for the rest of the run.
        self._reported_faults: set[str] = set()

        # The tick index is authoritative: the ledger, not message arrival, decides
        # whether an observation may step the automaton. See manifest.TickLedger.
        self.ledger = manifest_mod.TickLedger()
        self._tick_seq = 0
        self._tick_t = 0.0
        self._missed_ticks = 0
        #: Observations refused in a row since the last admitted step. Throttles the
        #: refusal warning; see `_note_refusal`.
        self._refused_run = 0
        #: The clock index at the last admitted step, i.e. where the current stretch of
        #: stepping silence began. None until a clock is on the graph. See
        #: `_watch_for_stepping_silence` -- this is what makes a monitor that has
        #: stopped stepping say so instead of publishing nothing.
        self._silent_since: int | None = None
        #: True while the stall is being announced on api.VERDICT, so entering and
        #: leaving it are one log line each rather than one per tick.
        self._stalled = False
        #: Which observation topics have delivered at least once, so the dual-run
        #: window is announced once per wire instead of once per tick.
        self._wires_seen: set[str] = set()

        # The clock's own pulse. `tick_hz` is the *effective* rate after any override,
        # which is what turns a tick-denominated bound into seconds; `t` is the clock's
        # time at the tick boundary, so a verdict is stamped with the clock that drove
        # it rather than with this process's wall time.
        self.tick_hz = 1.0
        self.clock_t = 0.0
        self.clock_seq = 0
        self._clock_seen = False
        # The clock's `t0`, i.e. which run of the clock the current `seq` stream belongs
        # to. A restarted clock republishes from seq 0; without this the ledger refused
        # every one of those as stale and the monitor never stepped again. None until a
        # clock that publishes `t0` is on the graph.
        self.clock_epoch: float | None = None

        # Watch formulas file for changes
        self.formulas_file = args.formulas_file
        self.last_mtime = 0
        if self.formulas_file and os.path.exists(self.formulas_file):
            self.last_mtime = os.path.getmtime(self.formulas_file)

        # Skill-type agnosticism: an external skill executor may publish its active
        # skill's label on /active_skill (e.g. "explore", "cooperate_push", matching
        # the formulas_<skill>.json convention ltl_skill_monitor.py already uses for
        # MiniGrid/CoopBoxPush). No publisher exists for G1 yet -- this is inert until
        # one does, and behavior is unchanged: falls back to --formulas-file/-f, same
        # as today, whenever no matching formulas_<label>.json is found.
        # Resolved the same way as --formulas-file, so a skill switch finds a spec on
        # the mounted volume rather than only beside whatever file this run started on.
        self.skills_dir = skill_monitor.specs_dir()
        self.active_skill_label: str | None = None
        self.active_skill_sub = self.create_subscription(
            String, '/active_skill', self.active_skill_callback, 10
        )

        # ── The verdict, and the pulse that paces it ──────────────
        self.verdict_pub = self.create_publisher(String, api.VERDICT, 10)
        self.create_subscription(String, api.TICK, self.tick_callback, 10)
        self.create_subscription(String, api.OBSERVATION, self.observation_callback, 10)
        self.create_subscription(String, api.COMMAND, self.command_callback, 10)

        # Dual subscription for one release. P3 still publishes the legacy observation
        # topic, and the sim stack has to keep running at every commit, so both are
        # accepted and each arrival says which wire it came in on. DELETE THIS
        # SUBSCRIPTION, AND `_LEGACY_EVALUATIONS`, WHEN P3 LANDS -- from then on a
        # message here means something is running an image older than the contract.
        self.create_subscription(
            String, _LEGACY_EVALUATIONS, self.legacy_eval_callback, 10
        )
        #: True once api.OBSERVATION has delivered. From then on the legacy copy of the
        #: same tick is not stepped -- see `_on_observation`.
        self._envelope_seen = False
        #: True while the demotion above is suspended because the envelope wire went
        #: quiet for `_LEGACY_READMIT_TICKS` clock pulses. Cleared by the next envelope.
        self._legacy_readmitted = False

        # The manifest is the whole spec, latched: a GUI or any other client that
        # connects mid-mission gets it immediately instead of having to find the file
        # on a disk it may not share, and needs no import of this package to read it.
        self.manifest_pub = self.create_publisher(String, api.MANIFEST, _LATCHED)
        self.spec_status_pub = self.create_publisher(String, api.SPEC_STATUS, _LATCHED)

        # A spec can also arrive over the wire. Same code path as a file load, and
        # validated against the adapter's schema first -- a spec whose rules mention
        # fields this robot does not publish would otherwise run as silently-false APs.
        self.create_subscription(String, api.LOAD_SPEC, self.load_spec_callback, 10)
        self.adapter_manifest: dict = {}
        self.create_subscription(String, api.ADAPTER, self.adapter_callback, _LATCHED)

        # ── Legacy mirrors, same dual-run window ──────────────────
        self.aps_pub = self.create_publisher(String, _LEGACY_REQUIRED_APS, 10)
        self.state_desc_pub = self.create_publisher(String, _LEGACY_STATE_DESC, 10)
        self.legacy_manifest_pub = self.create_publisher(
            String, _LEGACY_MANIFEST, _LATCHED
        )
        self.legacy_spec_status_pub = self.create_publisher(
            String, _LEGACY_SPEC_STATUS, _LATCHED
        )
        self.create_subscription(
            String, _LEGACY_LOAD_SPEC, self.load_spec_callback, 10
        )
        self.create_subscription(
            String, _LEGACY_ADAPTER, self.adapter_callback, _LATCHED
        )

        # Latest sensor values and AP truth values from the evaluator, passed through
        # so a client sees the numbers the APs were computed from, not just the APs'
        # names.
        self.sensors: dict = {}
        self.last_observation: dict = {}

        # A heartbeat, not a step: it re-announces the current verdict for late joiners
        # and picks up an edited spec file. It never advances the automaton -- only an
        # observation the ledger admitted does that.
        self.timer = self.create_timer(1.0, self.heartbeat)

        self.get_logger().info(
            f"Monitor node started. Verdict on {api.VERDICT}; also mirroring "
            f"{_LEGACY_STATE_DESC} until P5 and P7 land."
        )

        # Announce what this monitor is. Deliberately NOT a verdict: the verdict topic
        # carries exactly one message per tick that actually happened, and a startup
        # frame for a tick nobody clocked would be the first lie in the record. A
        # standalone monitor with no evaluator is discoverable from its latched
        # manifest, which is what a panel needs to describe it.
        self.publish_manifest()
        self.publish_legacy_state()

    # -- manifest / spec push -------------------------------------------------

    def publish_manifest(self, source: str | None = None) -> None:
        payload = json.dumps(self.manifest(source))
        self.manifest_pub.publish(String(data=payload))
        self.legacy_manifest_pub.publish(String(data=payload))

    def manifest(self, source: str | None = None) -> dict:
        return manifest_mod.skill_manifest(
            self.spec.raw,
            source or (str(self.formulas_file) if self.formulas_file else "inline"),
        )

    def adapter_callback(self, msg: String) -> None:
        try:
            self.adapter_manifest = json.loads(msg.data)
        except Exception as exc:
            self.get_logger().warn(f"Unparseable adapter manifest: {exc}")
            return
        tick_hz = self.adapter_manifest.get("tick_hz")
        if isinstance(tick_hz, (int, float)) and tick_hz > 0 and not self._clock_seen:
            # A fallback only: the pulse is the authority on the effective rate. This
            # keeps `seconds_to_timeout` honest when no clock is on the graph yet.
            self.tick_hz = float(tick_hz)

    def tick_callback(self, msg: String) -> None:
        """The clock's pulse. It does NOT step the automaton.

        The monitor advances on the tick index carried *inside the observation*, so that
        the automaton and the evidence it consumes are the same tick. The pulse supplies
        the effective rate, the clock's own time, and which run of the clock this is --
        and nothing else.
        """
        try:
            tick = json.loads(msg.data)
        except Exception as exc:
            self.get_logger().warn(f"Unparseable tick: {exc}")
            return
        # A field this build does not know about is not a malformed tick: `t0` is being
        # added by P1 and `api.validate_tick` closes the payload, so judging on the raw
        # list would make this monitor drop every pulse from a clock one release newer.
        problems = manifest_mod.tick_problems_that_matter(api.validate_tick(tick))
        if problems:
            self.get_logger().warn(f"Malformed tick, ignoring: {problems}")
            return
        self._clock_seen = True
        self.clock_seq = tick["seq"]
        self.clock_t = float(tick["t"])
        if tick["tick_hz"] > 0:
            self.tick_hz = float(tick["tick_hz"])

        epoch = manifest_mod.tick_epoch(tick)
        if epoch is not None and epoch != self.clock_epoch:
            if self.clock_epoch is not None:
                self.get_logger().warn(
                    f"Clock restarted (t0 {self.clock_epoch} → {epoch}); the tick "
                    f"stream begins again and the ledger starts over."
                )
            self.clock_epoch = epoch
            self._begin_silence_window()

        # Last, so it judges against this pulse rather than the one before it.
        self._watch_for_stepping_silence()

    def command_callback(self, msg: String) -> None:
        """`arm` | `reset` | `pause` | `resume` from the frontend."""
        try:
            payload = json.loads(msg.data)
        except Exception as exc:
            self.get_logger().warn(f"Unparseable command: {exc}")
            return
        problems = api.validate_command(payload)
        if problems:
            self.get_logger().warn(f"Rejected command: {problems}")
            return
        command = payload["command"]
        self.get_logger().info(f"Command: {command}")
        if command in ("arm", "reset"):
            self.paused = False
            self._reset_for_new_skill()
        elif command == "pause":
            self.paused = True
        elif command == "resume":
            self.paused = False

    def load_spec_callback(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except Exception as exc:
            self._spec_status(False, [f"not valid JSON: {exc}"])
            return
        problems = self.validate_spec(data)
        if problems:
            self.get_logger().warn(f"Rejected pushed spec: {problems}")
            self._spec_status(False, problems, data.get("skill_name", ""))
            return
        self.get_logger().info(f"Accepted pushed spec '{data.get('skill_name','')}'")
        self.reload_specs(spec_data=data)
        self._spec_status(True, [], data.get("skill_name", ""))

    def validate_spec(self, data: dict) -> list[str]:
        """Problems that make a spec unrunnable here. Schema checks only happen once
        an adapter has announced itself -- with no adapter on the graph we cannot tell
        an unknown sensor field from an unseen one, and refusing every spec until then
        would make the monitor unusable in replay/offline setups.

        The fault-category check needs no adapter and runs either way: a category this
        build cannot classify grades to a non-halting rung at runtime, so a spec that
        ships one has a fault the monitor will never act on. Rejecting it here is the
        only place the author still sees the name they mistyped."""
        schema_keys = (self.adapter_manifest.get("schema") or {}).keys()
        problems = manifest_mod.fault_category_problems(data)
        if not schema_keys:
            return problems + spec_contract.validate_structure(data)
        return problems + spec_contract.validate(data, schema_keys)

    def _spec_status(self, ok: bool, problems: list, skill_name: str = "") -> None:
        payload = json.dumps(api.build_spec_status(
            ok=ok, problems=problems, skill_name=skill_name,
        ))
        self.spec_status_pub.publish(String(data=payload))
        self.legacy_spec_status_pub.publish(String(data=payload))

    def check_formulas_file_changed(self) -> bool:
        if not self.formulas_file or not os.path.exists(self.formulas_file):
            return False
        try:
            mtime = os.path.getmtime(self.formulas_file)
            if mtime > self.last_mtime:
                self.last_mtime = mtime
                return True
        except Exception:
            pass
        return False

    def terminal_observation(self, observation: dict[str, bool]) -> str | None:
        """`"SUCCESS"`, `"FAILURE"`, or None if the run has not ended.

        Which one is now reported rather than just "one of them happened": the verdict
        carries `terminal`, and a consumer reading a recorded stream should not have to
        re-evaluate the spec's conditions to find out how the episode finished.
        """
        # Skip terminal checks until the skill has actually started:
        # - When phases are defined, wait until the first phase is entered.
        # - Always enforce a minimum step count (grace period) to absorb
        #   stale sensor state and LLM warm-up hallucinations.
        if self.step_idx < 2:
            return None
        if self.has_phases and self.phase_idx < 0:
            return None

        success_cond_raw = getattr(self.spec, "terminal_success_condition", "False")
        success_cond = _sanitize_condition(success_cond_raw)
        try:
            if eval(success_cond, {"__builtins__": {}}, observation):
                desc = getattr(self.spec, "terminal_success_description", "")
                self.get_logger().info(f"Terminal SUCCESS: {success_cond_raw} ({desc})")
                return "SUCCESS"
        except Exception as e:
            self.get_logger().warn(f"Failed to evaluate terminal success condition '{success_cond_raw}': {e}")

        failure_cond_raw = getattr(self.spec, "terminal_failure_condition", "False")
        failure_cond = _sanitize_condition(failure_cond_raw)
        try:
            if eval(failure_cond, {"__builtins__": {}}, observation):
                desc = getattr(self.spec, "terminal_failure_description", "")
                self.get_logger().info(f"Terminal FAILURE: {failure_cond_raw} ({desc})")
                return "FAILURE"
        except Exception as e:
            self.get_logger().warn(f"Failed to evaluate terminal failure condition '{failure_cond_raw}': {e}")

        return None

    def active_skill_callback(self, msg: String):
        label = msg.data.strip()
        if not label or label == self.active_skill_label:
            return
        try:
            skill_path = manifest_mod.resolve_spec_path(label)
        except FileNotFoundError as exc:
            self.get_logger().warn(
                f"No spec for active skill '{label}' ({exc}) — "
                f"continuing with the current spec ('{self.spec.skill_name}')."
            )
            return
        self.get_logger().info(f"Active skill changed → '{label}', loading {skill_path}")
        self.active_skill_label = label
        self.reload_specs(skill_path)

    def reload_specs(self, formulas_path: str | None = None, spec_data: dict | None = None):
        if spec_data is not None:
            # Pushed over the load_spec topic: there is no file, and adopting one would
            # make the file watcher immediately reload over the top of it.
            self.get_logger().info("Reloading from pushed spec...")
            spec = spec_from_dict(spec_data)
            self.formulas_file = None
        else:
            path = manifest_mod.resolve_spec_path(formulas_path or self.formulas_file)
            self.get_logger().info(f"Reloading formulas and AP specs from {path}...")
            spec = load_formulas_from_file(path)
            self.formulas_file = path
            if os.path.exists(path):
                self.last_mtime = os.path.getmtime(path)
        self.spec = spec
        self.has_phases = bool(spec.execution_phases)
        try:
            self.multi = MultiMonitor(
                spec.all_formulas,
                names=spec.all_names,
                failure_modes=spec.build_failure_mode_infos(),
            )
        except Exception as exc:
            self.get_logger().error(f"Failed to build reloaded automaton: {exc}")
            return

        self.prev_statuses = dict(self.multi.statuses())
        self.step_idx = 0
        self.halted = False
        self._phase_fault = None
        self._reported_faults.clear()
        self._reset_phase_state()

        # Print new skill header and formulas/automaton table to stdout
        _print_skill_header(spec)
        _print_formula_table(self.multi, self.spec, self.args.output_dir)

        print(f"\n{BOLD}{'─' * 64}{RESET}")
        print(f"{BOLD}  Monitoring Trace (Reloaded specs){RESET}")
        print(f"{BOLD}{'─' * 64}{RESET}")

        _print_step_block("init", self.multi, {}, "Idle")
        self.publish_manifest("pushed" if spec_data is not None else None)
        self.get_logger().info("Monitor reset successfully with new specs.")

    def _update_phase_state(
        self, observation: dict[str, bool]
    ) -> tuple[str, dict | None]:
        """
        Advance the phase state machine one step.

        Returns
        -------
        (phase_name, fault)

        `fault` is None when no failure occurred, else the dict `_phase_fault_entry`
        builds: a `verdict.failure_modes` row with the reason, the condition it came
        from and whether it is recoverable carried alongside.

        recoverable=True  → enter IDLE (e.g. progress violations, awaitable)
        recoverable=False → halt  (e.g. invariant, timeout, precondition), subject to
                            the intervention token -- see `_advance`.
        """
        phases = self.spec.execution_phases
        if not phases:
            return "Idle", None

        def _eval(raw: str, default: bool) -> bool:
            try:
                return bool(eval(_sanitize_condition(raw), {"__builtins__": {}}, observation))
            except Exception:
                return default

        def _enter_phase(idx: int) -> tuple[str, dict] | None:
            """Try to enter phase[idx]; return the failure if the precondition fails."""
            p = phases[idx]
            self.phase_idx = idx
            self.phase_step_count = 0
            self.phase_violation_count = 0
            self.get_logger().info(f"Phase enter: '{p['phase']}'")
            precond = p.get("precondition", "")
            if precond and not _eval(precond, True):
                return (
                    p["phase"],
                    _phase_fault_entry(
                        phase=p["phase"],
                        kind="precondition",
                        category=p.get("precondition_fault_category", "PRECONDITION"),
                        expression=precond,
                        reason=(
                            f"Precondition not met on entry to phase "
                            f"'{p['phase']}': {precond}"
                        ),
                        recoverable=False,
                    ),
                )
            return None

        # ── Idle → enter phase 0 ──────────────────────────────────
        if self.phase_idx < 0:
            p0 = phases[0]
            enter = p0.get("enter_condition") or p0.get("condition", "False")
            if _eval(enter, False):
                fail = _enter_phase(0)
                if fail:
                    return fail

        if self.phase_idx < 0:
            return "Idle", None

        p     = phases[self.phase_idx]
        name  = p["phase"]
        limit = p.get("progress_violation_limit", _PHASE_VIOLATION_LIMIT)

        # ── Hard invariant (immediate failure) ────────────────────
        invariant = p.get("invariant", "")
        if invariant and not _eval(invariant, True):
            return (
                name,
                _phase_fault_entry(
                    phase=name,
                    kind="invariant",
                    category=p.get("invariant_fault_category", "INVARIANT"),
                    expression=invariant,
                    reason=f"Invariant violated in phase '{name}': {invariant}",
                    recoverable=False,
                ),
            )

        # ── Timing: max_steps ─────────────────────────────────────
        timing    = p.get("timing_bounds", {})
        max_steps = timing.get("max_steps")
        if max_steps is not None and self.phase_step_count >= max_steps:
            return (
                name,
                _phase_fault_entry(
                    phase=name,
                    kind="timeout",
                    category="TIMEOUT",
                    # A timeout is counted in ticks, not sensed: no condition was
                    # evaluated, so no sensor's freshness bears on it.
                    expression="",
                    reason=(
                        f"Phase '{name}' timed out: {self.phase_step_count} steps "
                        f"elapsed (max={max_steps})"
                    ),
                    recoverable=False,
                ),
            )

        # ── Progress condition (counted violations) ───────────────
        progress_condition = p.get("progress_condition", "True")
        if not _eval(progress_condition, True):
            self.phase_violation_count += 1
            self.get_logger().warn(
                f"Phase '{name}' progress violation {self.phase_violation_count}/{limit}"
            )
            if self.phase_violation_count >= limit:
                return (
                    name,
                    _phase_fault_entry(
                        phase=name,
                        kind="progress",
                        category="PROGRESS",
                        expression=progress_condition,
                        reason=(
                            f"Phase '{name}' progress conditions violated {limit} "
                            f"consecutive step(s)"
                        ),
                        recoverable=True,  # await new skill execution
                    ),
                )
        else:
            if self.phase_violation_count > 0:
                self.get_logger().info(f"Phase '{name}' progress restored")
            self.phase_violation_count = 0

        # ── Exit condition (respects min_steps) ───────────────────
        min_steps = timing.get("min_steps", 0)
        if self.phase_step_count >= min_steps and _eval(p.get("exit_condition", "False"), False):
            next_idx = self.phase_idx + 1
            if next_idx < len(phases):
                np_ = phases[next_idx]
                np_enter = np_.get("enter_condition") or np_.get("condition", "True")
                if _eval(np_enter, True):
                    self.get_logger().info(f"Phase: '{name}' → '{np_['phase']}'")
                    fail = _enter_phase(next_idx)
                    if fail:
                        return fail
            else:
                self.get_logger().info(f"Phase '{name}' complete — all phases done")
                self.phase_idx = -1
                self.phase_step_count = 0
                return "Done", None

        self.phase_step_count += 1
        if 0 <= self.phase_idx < len(phases):
            return phases[self.phase_idx]["phase"], None
        return "Idle", None

    def _reset_phase_state(self) -> None:
        self.phase_idx = -1
        self.phase_violation_count = 0
        self.phase_step_count = 0
        self.current_phase = "Idle"

    def _print_phase_context(self) -> None:
        """Print a banner showing the current phase's full constraint set."""
        phases = self.spec.execution_phases
        if self.phase_idx < 0 or self.phase_idx >= len(phases):
            return
        p = phases[self.phase_idx]
        YELLOW = "\033[33m"
        RED    = "\033[31m"

        enter     = p.get("enter_condition") or p.get("condition", "—")
        precond   = p.get("precondition", "")
        invariant = p.get("invariant", "")
        progress  = p.get("progress_condition", "True")
        exit_c    = p.get("exit_condition", "False")
        limit     = p.get("progress_violation_limit", _PHASE_VIOLATION_LIMIT)
        timing    = p.get("timing_bounds", {})
        from_name = phases[self.phase_idx - 1]["phase"] if self.phase_idx > 0 else "Idle"
        to_name   = phases[self.phase_idx + 1]["phase"] if self.phase_idx + 1 < len(phases) else "Done"

        print(f"\n  {BOLD}{'═' * 64}{RESET}")
        print(f"  {BOLD}{YELLOW}▶  Phase: {p['phase']}{RESET}")
        if p.get("description"):
            print(f"  {DIM}{p['description']}{RESET}")
        print(f"  {BOLD}{'─' * 64}{RESET}")
        print(f"  {DIM}Enter from   :{RESET}  {from_name}  →  when: {enter}")
        if precond:
            inv_cat = p.get("precondition_fault_category", "PRECONDITION")
            print(f"  {DIM}Precondition :{RESET}  {precond}  {DIM}[{inv_cat}]{RESET}")
        if invariant:
            inv_cat = p.get("invariant_fault_category", "INVARIANT")
            print(f"  {RED}Invariant    :{RESET}  {invariant}  {DIM}[{inv_cat} — immediate halt]{RESET}")
        print(f"  {DIM}Progress     :{RESET}  {progress}  {DIM}(fail after {limit} violations){RESET}")
        print(f"  {DIM}Exit to      :{RESET}  {to_name}  →  when: {exit_c}")
        if timing:
            min_s = timing.get("min_steps", "—")
            max_s = timing.get("max_steps", "—")
            print(f"  {DIM}Timing       :{RESET}  min {min_s} steps  /  max {max_s} steps  {DIM}[TIMEOUT on exceed]{RESET}")
        print(f"  {BOLD}{'═' * 64}{RESET}\n")

    def _halt(self, reason: str) -> None:
        """Terminal state reached — signal LLM client then shut down both nodes.

        In --passive mode this degrades to _enter_idle: a passive monitor exists to
        observe every episode, so ending the process at the first fault would throw
        away the rest of the session. The evaluator only shuts down on state=="halt",
        so routing here keeps BOTH nodes alive.
        """
        if getattr(self.args, "passive", False):
            self._enter_idle(f"[passive] {reason}")
            return
        self.halted = True
        self._terminal = self._terminal or "FAILURE"
        RED = "\033[31m"
        print(f"\n{BOLD}{'═' * 64}{RESET}")
        print(f"{BOLD}{RED}  ■  MONITOR HALTED{RESET}")
        print(f"  Reason : {reason}")
        print(f"{BOLD}{'═' * 64}{RESET}\n")
        self.get_logger().info(f"Monitor halting. Reason: {reason}")

        # The verdict carrying `terminal` is published by the caller, once, after this
        # returns -- so the run's last message is the verdict that ended it and not a
        # second frame for the same tick.

        # Tell the LLM client to shut down
        aps_msg = String()
        aps_msg.data = json.dumps([])
        self.aps_pub.publish(aps_msg)

        halt_desc = {"state": "halt", "skill_name": self.spec.skill_name, "reason": reason}
        desc_msg = String()
        desc_msg.data = json.dumps(halt_desc)
        self.state_desc_pub.publish(desc_msg)

        # Shut down after a brief delay so the messages can be delivered
        self._halt_timer = self.create_timer(0.5, self._do_shutdown)

    def _do_shutdown(self) -> None:
        self._halt_timer.destroy()
        rclpy.shutdown()

    def _enter_idle(self, reason: str) -> None:
        """Suspend monitoring and wait for reset (recoverable — e.g. progress failure)."""
        self.halted = True
        self._terminal = self._terminal or "FAILURE"
        YELLOW = "\033[33m"
        print(f"\n{BOLD}{'═' * 64}{RESET}")
        print(f"{BOLD}{YELLOW}  ◉  MONITOR IDLE{RESET}")
        print(f"  Reason   : {reason}")
        print(f"  Awaiting : new skill execution")
        print(f"  Resume   : send {{\"command\": \"reset\"}} on {api.COMMAND}")
        print(f"           : or update the spec file to reload automatically")
        print(f"{BOLD}{'═' * 64}{RESET}\n")
        self.get_logger().info(f"Monitor entering IDLE state. Reason: {reason}")

        aps_msg = String()
        aps_msg.data = json.dumps([])
        self.aps_pub.publish(aps_msg)

        idle_desc = {"state": "idle", "skill_name": self.spec.skill_name, "reason": reason}
        desc_msg = String()
        desc_msg.data = json.dumps(idle_desc)
        self.state_desc_pub.publish(desc_msg)

    def _reset_for_new_skill(self) -> None:
        """Reset automaton state and resume monitoring for a new skill execution."""
        self.multi.reset()
        self.prev_statuses = dict(self.multi.statuses())
        self.step_idx = 0
        self.halted = False
        self._terminal = None
        self._has_data = False
        self._phase_fault = None
        self._reported_faults.clear()
        # The episode restarts; the tick stream does not. `last_seq` and the clock epoch
        # deliberately survive, so a redelivery from before the reset cannot be mistaken
        # for the first tick of the new episode -- while a genuinely restarted clock,
        # which arrives with a new epoch, still is.
        self.ledger.reset()
        self._reset_phase_state()
        print(f"\n{BOLD}{'─' * 64}{RESET}")
        print(f"{BOLD}  Monitoring Trace (New Execution){RESET}")
        print(f"{BOLD}{'─' * 64}{RESET}")
        _print_step_block("init", self.multi, {}, "Idle")
        self.publish_legacy_state()

    # -- one tick in, one verdict out -----------------------------------------

    def observation_callback(self, msg: String) -> None:
        self._on_observation(msg.data, wire=api.OBSERVATION)

    def legacy_eval_callback(self, msg: String) -> None:
        """DIES WHEN P3 LANDS, together with `_LEGACY_EVALUATIONS`.

        Until then the evaluator publishes only on the legacy topic, and a monitor that
        listened solely to api.OBSERVATION would run a whole release seeing nothing.
        """
        self._on_observation(msg.data, wire=_LEGACY_EVALUATIONS)

    def _on_observation(self, data: str, *, wire: str) -> None:
        try:
            payload = json.loads(data)
        except Exception as exc:
            self.get_logger().error(f"Failed to parse observation from {wire}: {exc}")
            return

        obs = manifest_mod.normalize_observation(payload)
        if obs is None:
            self.get_logger().warn(f"Ignoring non-object observation from {wire}")
            return

        # Which wire carried it. Logged the first time each is seen and then left
        # alone: the point is that a stack still on the legacy topic says so, not that
        # a line is printed per tick for the rest of the run.
        if wire not in self._wires_seen:
            self._wires_seen.add(wire)
            note = " (legacy — P3 has not migrated yet)" if obs.legacy else ""
            self.get_logger().info(f"Observations arriving on {wire}{note}")

        if obs.control == "done":
            self.get_logger().info("Received termination signal.")
            _print_summary(self.multi)
            rclpy.shutdown()
            return

        # While halted, only an explicit reset restarts the run.
        if self.halted:
            if obs.control == "reset":
                self.get_logger().info(
                    "Reset signal received. Starting new skill execution..."
                )
                self._reset_for_new_skill()
            return

        if self.paused:
            return

        # ── One tick, two wires, one step ─────────────────────────
        #
        # docs/api.md guarantees both wires are live during the migration, so from the
        # moment P3 lands every tick arrives twice: once as an envelope on
        # api.OBSERVATION and once as a flat legacy dict with no `seq` at all. Stepping
        # both means two automaton steps per tick -- the drift this PR exists to remove,
        # reintroduced from the other side.
        #
        # The envelope wins, because it is the only one of the two that says which tick
        # it describes. Its control keys are still honoured above (the LLM client's
        # `__done__`/`__reset__` ride the legacy wire), but it does not step.
        if wire == api.OBSERVATION:
            if self._legacy_readmitted:
                self._legacy_readmitted = False
                self.get_logger().info(
                    f"{api.OBSERVATION} is back; the legacy copy stops stepping again."
                )
            if not self._envelope_seen:
                self._envelope_seen = True
                self.get_logger().info(
                    f"{api.OBSERVATION} is live; the legacy copy of each tick will no "
                    f"longer step the automaton."
                )
        elif self._envelope_seen and not self._legacy_readmitted:
            return

        # The tick index decides, not the arrival. A redelivered tick must not advance
        # a debounce or a phase counter a second time, so it is refused here rather
        # than deduplicated somewhere downstream where the counters already moved.
        # `epoch` is the clock's `t0`: a restarted clock renumbers from 0, and without
        # it every tick after a restart reads as stale forever.
        #
        # `clock_seq` bounds what the ledger will adopt as a first index. Both numbers
        # are here, on the same object, so the check costs nothing: an observation that
        # names a tick the clock has not published is the tail of the epoch that just
        # ended, and adopting it as the high-water mark refuses the whole restarted
        # stream underneath it -- 5001 consecutive refusals for an epoch that reached
        # 5000, and never at all for a corrupt index.
        admission = self.ledger.admit(
            obs.seq,
            epoch=self.clock_epoch,
            clock_seq=self.clock_seq if self._clock_seen else None,
        )
        if admission.reason == "epoch":
            self.get_logger().warn(
                f"New tick epoch adopted at seq {admission.seq}; a backwards index is "
                f"a restarted clock, not a stale message, and is stepped."
            )
        if not admission.step:
            self._note_refusal(admission)
            return
        self._note_step_resumed()
        if admission.missed:
            # Counted and published, never interpolated: fabricating the observations
            # that did not arrive would put invented evidence in the automaton's past.
            self.get_logger().warn(
                f"Missed {admission.missed} tick(s) before seq {admission.seq}"
            )

        self._step_once(obs, admission)

    def _note_refusal(self, admission) -> None:
        """Say that an observation was refused, without saying it 5001 times.

        The reason decides the sentence: `redelivered`/`stale` is a tick already stepped
        past, while `ahead` is one the clock itself has not reached -- a different fault
        with a different cause, and printing "already stepped through seq None" for it
        was actively misleading.
        """
        self._refused_run += 1
        if self._refused_run != 1 and self._refused_run % _REFUSAL_LOG_EVERY:
            return
        run = (
            "" if self._refused_run == 1
            else f" ({self._refused_run} refused in a row)"
        )
        if admission.reason == "ahead":
            self.get_logger().warn(
                f"Tick {admission.seq} is ahead of the clock's own seq "
                f"{self.clock_seq}; it belongs to a stream this ledger is not in and "
                f"is not adopted as the epoch's first tick{run}"
            )
        else:
            self.get_logger().warn(
                f"Tick {admission.seq} {admission.reason}; already stepped through "
                f"seq {self.ledger.last_seq} — not stepping again{run}"
            )

    def _note_step_resumed(self) -> None:
        """Close a refusal burst on the console, once, with its length."""
        if self._refused_run:
            self.get_logger().info(
                f"Stepping again after {self._refused_run} refused observation(s)."
            )
            self._refused_run = 0

    def _begin_silence_window(self) -> None:
        """Start the stall window over, because a new clock's ticks are a new stream.

        `_silent_since` is a `seq`, and a `seq` only means anything inside the epoch it
        was read in. Carried across a restart it was measured against a clock counting
        from its own beginning, so `clock_seq - _silent_since` went *negative*:
        `missed_ticks` below zero on a field the wire says is a count, and -- whenever
        the run before the restart got further than the new one has -- a stall that
        never fires at all. Fifty-nine pulses of total silence with `silent` at -141 and
        not one frame published: the detector blind in exactly the scenario it exists
        for, which is a monitor that has stopped monitoring failing to say so.

        `_stalled` is deliberately *not* cleared here. Whether the automaton is
        advancing is a property of this process, and a monitor that had stopped stepping
        has not started again because the clock it listens to restarted. Clearing it
        would re-arm the announcement from scratch and buy `_STALL_TICKS` more pulses of
        the same silence -- a smaller version of the bug above. `_legacy_readmitted` is
        left for the same reason: it says which *observation* wire may step, which no
        clock has an opinion about, and the next envelope clears it anyway.
        """
        self._silent_since = self.clock_seq

    def _watch_for_stepping_silence(self) -> None:
        """Say so on api.VERDICT when the clock advances and the automaton does not.

        Called from the pulse, because the clock is a *different* publisher from the
        evaluator: it keeps ticking through a dead evaluator, a demoted wire and a
        refused epoch alike, and so it is the only thing in this process that knows
        time is passing while nothing is being decided.

        Without this the monitor's failure mode is silence, which on a topic that is
        quiet whenever nothing is wrong is indistinguishable from health. A supervisor
        cannot tell "no verdict because the run is calm" from "no verdict because the
        monitor stopped a minute ago".
        """
        if self.halted or self.clock_seq is None:
            # A halted monitor is *supposed* to be quiet; crying wolf there would teach
            # an operator to ignore the one indication that matters.
            return
        if self._silent_since is None:
            self._silent_since = self.clock_seq
            return

        # Clamped, so that a `_silent_since` from some other counting -- an epoch this
        # window was not opened in, a future bug of the same shape -- cannot put a
        # negative count of pulses on the wire. `_begin_silence_window` is the fix; this
        # is the guarantee that `missed_ticks` stays a count whatever else goes wrong.
        silent = max(0, self.clock_seq - self._silent_since)
        if silent >= _STALL_TICKS and not self._stalled:
            self._stalled = True
            self.get_logger().error(
                f"{silent} clock pulses with no step: the automaton is not advancing. "
                f"Announcing it on {api.VERDICT}."
            )
        if self._stalled:
            self._publish_stall_verdict(silent)

        # Re-admitting the legacy wire is deliberately slower than announcing, because
        # the indication is free and this is not: legacy arrivals carry no `seq` and are
        # numbered from their own counter, so they are not deduplicated against envelope
        # indices. Re-admitting a merely *slow* envelope double-steps the tick they
        # share. The next envelope restores the demotion.
        if (silent >= _LEGACY_READMIT_TICKS and self._envelope_seen
                and not self._legacy_readmitted):
            self._legacy_readmitted = True
            self.get_logger().warn(
                f"No step for {silent} pulses and {api.OBSERVATION} is quiet; letting "
                f"the legacy wire step again until it returns."
            )

    def _publish_stall_verdict(self, silent: int) -> None:
        """A verdict carrying the CLOCK's index, saying this tick decided nothing.

        The seq is the clock's rather than the last observation's: the point of the
        frame is that no observation arrived for it, and repeating a stale index would
        make the stall look like a redelivery of the tick before it.
        """
        self.publish_verdict(
            seq=self.clock_seq, t=self.clock_t, missed_ticks=silent, has_data=False,
        )

    def _note_stepping_resumed(self) -> None:
        """Clear a stall, once, when a step finally lands."""
        if self._stalled:
            self.get_logger().info("Stepping again; the stall is over.")
            self._stalled = False
        self._silent_since = self.clock_seq

    def _step_once(self, obs, admission) -> None:
        """Advance the automata and the phase machine exactly one tick, then publish.

        Publishing happens here, once, at the end -- including on the paths that end
        the run, so a recorded stream always finishes with the verdict that finished it.
        """
        # A step landed, so whatever stretch of silence was running is over. Recorded
        # before any of the work below, so an exception mid-step cannot leave the node
        # believing it is still stalled.
        self._note_stepping_resumed()

        self._confidence = obs.confidence
        self._stale_sources = list(obs.stale_sources)
        self.sensors = dict(obs.sensors)
        self.last_observation = dict(obs.ap_values)
        self._has_data = obs.has_data
        self._tick_seq = admission.seq
        self._missed_ticks = admission.missed
        # The observation's own `t` is the boundary of the tick it describes, which is
        # the timestamp this verdict belongs at; the clock's latest pulse is the
        # fallback for a legacy payload that carries no envelope.
        self._tick_t = float(obs.t) if obs.t is not None else self.clock_t

        if obs.unknown_aps:
            # Three-valued APs are P10's. Until then an AP that could not be evaluated
            # is simply absent from ap_values; logged so it is not invisible, but the
            # step is unchanged by it.
            self.get_logger().info(
                f"unknown_aps at seq {admission.seq}: {list(obs.unknown_aps)}"
            )

        self._advance(dict(obs.ap_values))

        if rclpy.ok():
            self.publish_verdict()
            # A halt or idle path has already sent its own legacy signal; publishing
            # the generic one on top would overwrite `state: halt` with `state: idle`,
            # and the evaluator shuts down only on the former.
            if not self.halted:
                self.publish_legacy_state()

    def _advance(self, observation: dict) -> None:
        """The step itself. Returns early on every run-ending path; the caller
        publishes afterwards either way."""
        # Capture current automaton states before stepping
        prev_states = {m.name: m.current_state for m in self.multi.monitors}

        # Step the automaton (property formulas + named-failure-mode formulas)
        statuses = self.multi.step(observation)

        # ── Named failure modes: detect newly violated formulas ───
        triggered_failures = self.multi.get_violated_failure_modes()

        # Advance phase state machine. Its fault is recorded before anything is graded,
        # because it is one of the rows the verdict grades.
        phase_fault: dict | None = None
        if self.has_phases:
            prev_phase_idx = self.phase_idx
            phase_name, phase_fault = self._update_phase_state(observation)
            self.current_phase = phase_name
            if self.phase_idx != prev_phase_idx and self.phase_idx >= 0:
                self._print_phase_context()
        self._phase_fault = phase_fault

        # Print standard console step block
        _print_step_block(
            self.step_idx, self.multi, observation, self.current_phase,
            changed_only=self.args.changes_only,
            prev_statuses=self.prev_statuses,
            prev_states=prev_states,
            phase_violations=self.phase_violation_count,
        )

        # ── Named failure mode triggered → halt if the token halts ─
        if triggered_failures:
            worst = self._worst_triggered(triggered_failures)
            mon, finfo = triggered_failures[worst]
            entry = {
                "name": finfo.name,
                "fault_category": finfo.fault_category,
                "status": MonitorStatus.VIOLATED.name,
            }
            if finfo.name not in self._reported_faults:
                self._reported_faults.add(finfo.name)
                RED = "\033[31m"
                print(f"\n{BOLD}{'─' * 64}{RESET}")
                print(f"{BOLD}{RED}  ✘  NAMED FAILURE: {finfo.name}{RESET}")
                print(f"  Fault category : {finfo.fault_category}")
                if finfo.description:
                    print(f"  Description    : {finfo.description}")
                print(f"  Formula        : {mon.formula}")
                if len(triggered_failures) > 1:
                    extras = ", ".join(
                        f.name
                        for i, (_, f) in enumerate(triggered_failures) if i != worst
                    )
                    print(f"  Also triggered : {extras}")
                print(f"{BOLD}{'─' * 64}{RESET}")
                self.get_logger().error(
                    f"Named failure [{finfo.fault_category}] '{finfo.name}': "
                    f"{finfo.description}"
                )
            if self._fault_stops_the_run(entry):
                _print_summary(self.multi)
                self._terminal = "FAILURE"
                self._halt(f"[{finfo.fault_category}] {finfo.name}: {finfo.description}")
                return
            # De-escalated by its own confidence: the verdict published on this tick
            # does not say "stop", so neither does this process. Monitoring continues,
            # and the same fault halts as soon as the data backing it is fresh again.
            self._report_de_escalation(entry)

        # ── Phase failure ─────────────────────────────────────────
        if phase_fault is not None:
            if phase_fault["recoverable"]:
                _print_summary(self.multi)
                self._terminal = "FAILURE"
                self._enter_idle(phase_fault["reason"])
                return
            if self._fault_stops_the_run(phase_fault):
                _print_summary(self.multi)
                self._terminal = "FAILURE"
                self._halt(f"[{phase_fault['fault_category']}] {phase_fault['reason']}")
                return
            self._report_de_escalation(phase_fault)

        # Log current states to ROS logs
        for mon in self.multi.monitors:
            prev_s = prev_states[mon.name]
            curr_s = mon.current_state
            suffix = ""
            if mon.failure_mode and mon.status is MonitorStatus.VIOLATED:
                suffix = f" ← NAMED FAILURE [{mon.failure_mode.fault_category}]"
            self.get_logger().info(
                f"[{mon.name}] {prev_s} ──► {curr_s}{_state_label(mon, curr_s)} | {mon.status.name}{suffix}"
            )
        self.get_logger().info(f"Phase: {self.current_phase}")

        self.prev_statuses = dict(statuses)
        self.step_idx += 1

        if self.args.stop_on_violation and self.multi.any_violated():
            self.get_logger().error(
                f"Stopping early — formula permanently VIOLATED at step {self.step_idx}."
            )
            _print_summary(self.multi)
            self._terminal = "FAILURE"
            self.publish_verdict()
            rclpy.shutdown()
            return

        # Check if we reached a terminal observation → enter idle/waiting state
        terminal = self.terminal_observation(observation)
        if terminal is not None:
            _print_summary(self.multi)
            self._terminal = terminal
            self._enter_idle("Terminal state reached (success or failure)")
            return

    # -- grading --------------------------------------------------------------

    def _worst_triggered(self, triggered) -> int:
        """Which of several breaches on one tick this process acts on.

        The token is graded from the breach that grades worst on the ladder, so the halt
        has to be decided from that same breach or the process and the frame it just
        published disagree about the same tick -- and the frame is what the supervisor
        obeys. Acting on whichever mode the spec authored first meant a `fell_over` the
        odometry proved at 1.0 was answered for by a `collision_imminent` its own dead
        camera graded at 0.0: verdict ABORT, robot still walking.
        """
        graded = manifest_mod.failure_mode_entries(
            [
                {"name": finfo.name, "fault_category": finfo.fault_category,
                 "status": MonitorStatus.VIOLATED.name}
                for _, finfo in triggered
            ],
            self._confidence,
            mode_sources=self._mode_sources(),
            stale_sources=self._stale_sources,
        )
        worst = manifest_mod.breached_mode(graded)
        return next(i for i, entry in enumerate(graded) if entry is worst)

    def _fault_stops_the_run(self, entry: dict) -> bool:
        """Whether this fault, graded exactly as the verdict grades it, stops the run.

        One decision, read twice. The node used to halt on any triggered failure mode
        regardless of the rung it published, so on a `collision_imminent` derived from a
        stale depth camera it told the supervisor WARN and shut itself down on the same
        tick.
        """
        graded = manifest_mod.failure_mode_entries(
            [entry], self._confidence,
            mode_sources=self._mode_sources(),
            stale_sources=self._stale_sources,
        )[0]
        return manifest_mod.fault_stops_the_run(graded)

    def _report_de_escalation(self, entry: dict) -> None:
        """Say once, loudly, that a fault was graded below HALT and why."""
        key = f"de-escalated:{entry.get('name')}"
        if key in self._reported_faults:
            return
        self._reported_faults.add(key)
        self.get_logger().warn(
            f"'{entry.get('name')}' [{entry.get('fault_category')}] is breached but "
            f"graded below HALT on this tick's evidence "
            f"(stale sources: {self._stale_sources or 'none'}). The verdict says so, "
            f"and monitoring continues rather than acting on a fault this data cannot "
            f"support."
        )

    def _mode_sources(self) -> dict | None:
        """Failure-mode name -> the adapter sources its APs are computed from.

        Rebuilt per tick rather than cached: the spec and the adapter manifest both
        arrive over the wire and either can change mid-run, and a cache keyed on neither
        is how a monitor ends up grading a new spec's modes against an old spec's
        sources. None when no adapter has announced itself, which is the signal to
        `failure_mode_entries` that per-mode freshness is not knowable here.
        """
        expressions = {
            m.failure_mode.name: m.formula
            for m in self.multi.get_failure_mode_monitors()
        }
        if self._phase_fault is not None:
            expressions[self._phase_fault["name"]] = self._phase_fault["expression"]
        return manifest_mod.expression_source_map(
            expressions,
            manifest_mod.ap_source_map(
                self.spec.atomic_propositions, self.adapter_manifest
            ),
        )

    def _failure_mode_rows(self) -> list[dict]:
        """The spec's named failure modes, and the phase machine's own fault after
        them. Order matters: `publish_legacy_state` pairs the first N with the monitors
        they came from."""
        rows = [
            {
                "name": m.failure_mode.name,
                "fault_category": m.failure_mode.fault_category,
                "status": m.status.name,
            }
            for m in self.multi.get_failure_mode_monitors()
        ]
        if self._phase_fault is not None:
            rows.append(self._phase_fault)
        return rows

    # -- the verdict ----------------------------------------------------------

    def verdict(
        self,
        *,
        seq: int | None = None,
        t: float | None = None,
        missed_ticks: int | None = None,
        has_data: bool | None = None,
    ) -> dict:
        """This tick's api.VERDICT payload.

        Assembled entirely by `manifest.build_verdict_payload`, so no field name in the
        wire contract is spelled out in this node -- and so the same payload can be
        built, and validated, in a test with no ROS on the machine.

        The four overrides exist for one caller, `_publish_stall_verdict`: a frame that
        describes a tick the automaton did *not* step is stamped with the clock's own
        index and time rather than the last stepped tick's, and says so through the two
        fields that already mean it. Nothing else may pass them -- every other frame is
        this node's own state, unedited.
        """
        phases = self.spec.execution_phases
        in_phase = 0 <= self.phase_idx < len(phases)
        steps_to_timeout = None
        violations_to_fault = None
        if in_phase:
            p = phases[self.phase_idx]
            limit = p.get("progress_violation_limit", _PHASE_VIOLATION_LIMIT)
            max_steps = (p.get("timing_bounds") or {}).get("max_steps")
            if max_steps is not None:
                steps_to_timeout = max_steps - self.phase_step_count
            violations_to_fault = limit - self.phase_violation_count

        return manifest_mod.build_verdict_payload(
            seq=self._tick_seq if seq is None else seq,
            t=self._tick_t if t is None else t,
            step=self.step_idx,
            skill_name=self.spec.skill_name,
            phase=self.current_phase or None,
            # null, not -1: "no phase is active" is an absence, and a consumer indexing
            # a phase list with -1 would silently get the last one.
            phase_index=self.phase_idx if in_phase else None,
            formula_statuses=[
                (m.name, m.status) for m in self.multi.get_property_monitors()
            ],
            failure_modes=self._failure_mode_rows(),
            confidence=self._confidence,
            stale_sources=self._stale_sources,
            # Per mode, not one number for all of them: a quiet battery topic must not
            # de-escalate a collision the depth camera saw perfectly well.
            mode_sources=self._mode_sources(),
            steps_to_timeout=steps_to_timeout,
            violations_to_fault=violations_to_fault,
            violations_seen=self.phase_violation_count,
            tick_hz=self.tick_hz,
            terminal=self._terminal,
            missed_ticks=self._missed_ticks if missed_ticks is None else missed_ticks,
            has_data=self._has_data if has_data is None else has_data,
        )

    def publish_verdict(self, **overrides) -> None:
        payload = self.verdict(**overrides)
        problems = api.validate_verdict(payload)
        if problems:
            # A verdict that fails its own schema is a bug in this node, not at the
            # consumer, and it is reported here rather than discovered downstream.
            # Published anyway: a supervisor holding a slightly wrong verdict is better
            # placed than one holding silence.
            self.get_logger().error(f"Verdict failed its own schema: {problems}")
        self.verdict_pub.publish(String(data=json.dumps(payload)))

    # -- legacy mirror --------------------------------------------------------

    def required_aps(self) -> list:
        """Automaton APs + terminal APs + phase APs — all evaluated every step."""
        return sorted(
            self.multi.get_required_aps() | self.spec.terminal_aps | self.spec.phase_aps
        )

    def heartbeat(self) -> None:
        """Picks up an edited spec file and keeps the legacy channels alive.

        It never steps the automaton. Only an observation the ledger admitted does
        that, which is what makes "exactly one step per tick" true rather than
        approximately true.
        """
        if self.check_formulas_file_changed():
            self.reload_specs()
        self.publish_legacy_state()

    def _legacy_failure_modes(self, verdict: dict) -> list[dict]:
        """`/ltl/state_description`'s `named_failure_modes`, graded exactly as the
        verdict grades them.

        The phase fault is included rather than zipped away: the legacy supervisor reads
        this list and nothing else, so leaving it out would keep the un-migrated half of
        the stack blind to a phase invariant breach for the whole dual-run window.
        """
        monitors = self.multi.get_failure_mode_monitors()
        entries = verdict["failure_modes"]
        rows = [
            dict(entry, description=m.failure_mode.description, formula=m.formula)
            for entry, m in zip(entries, monitors)
        ]
        for entry in entries[len(monitors):]:
            fault = self._phase_fault or {}
            rows.append(dict(
                entry,
                description=fault.get("reason", ""),
                formula=fault.get("expression", ""),
            ))
        return rows

    def publish_legacy_state(self) -> None:
        """The `/ltl/*` half of the dual-run window.

        DIES WHEN P5 AND P7 LAND. Every consumer of `/ltl/state_description` and
        `/ltl/required_aps` is owned by a package that has not migrated yet, and
        dropping these before they do would leave the sim stack unrunnable at this
        commit for no gain.
        """
        if self.halted:
            # Periodically re-publish the idle signal so late-joining LLM clients also
            # pick up the idle state.
            self.aps_pub.publish(String(data=json.dumps([])))
            self.state_desc_pub.publish(String(data=json.dumps(
                {"state": "idle", "skill_name": self.spec.skill_name})))
            return

        self.aps_pub.publish(String(data=json.dumps(self.required_aps())))

        # Build phase_info for the LLM client (full per-phase constraint set)
        phases = self.spec.execution_phases
        phase_info: dict = {}
        if 0 <= self.phase_idx < len(phases):
            p = phases[self.phase_idx]
            next_name = phases[self.phase_idx + 1]["phase"] if self.phase_idx + 1 < len(phases) else "Done"
            timing    = p.get("timing_bounds", {})
            phase_info = {
                "enter_condition":      p.get("enter_condition") or p.get("condition", ""),
                "precondition":         p.get("precondition", ""),
                "invariant":            p.get("invariant", ""),
                "invariant_fault_category": p.get("invariant_fault_category", "INVARIANT"),
                "progress_condition":   p.get("progress_condition", "True"),
                "exit_condition":       p.get("exit_condition", "False"),
                "next_phase":           next_name,
                "violation_count":      self.phase_violation_count,
                "violation_limit":      p.get("progress_violation_limit", _PHASE_VIOLATION_LIMIT),
                "step_count":           self.phase_step_count,
                "timing_bounds":        timing,
            }

        verdict = self.verdict()
        state_desc = {
            "phase": self.current_phase,
            "phase_index": self.phase_idx,
            "phases": manifest_mod.phase_names(phases),
            "step": self.step_idx,
            "seq": verdict["seq"],
            "sensors": self.sensors,
            "ap_values": self.last_observation,
            # The same risk and intervention blocks the verdict carries, so a consumer
            # that has not migrated yet still sees the confidence-bearing numbers.
            "risk": verdict["risk"],
            "intervention": verdict["intervention"],
            "skill_name": self.spec.skill_name,
            "description": self.spec.description,
            "ap_descriptions": self.spec.atomic_propositions,
            "phase_info": phase_info,
            "terminal_success": {
                "condition": self.spec.terminal_success_condition,
                "description": self.spec.terminal_success_description,
                "aps": list(self.spec.terminal_success_aps),
            },
            "terminal_failure": {
                "condition": self.spec.terminal_failure_condition,
                "description": self.spec.terminal_failure_description,
                "aps": list(self.spec.terminal_failure_aps),
            },
            # `confidence` on every entry, mirroring the verdict. The legacy consumers
            # are the ones the missing key actually broke: supervisor_logic's VIOLATED
            # branch reads it here, and defaulted a dead-sensor fault to 1.0.
            "named_failure_modes": self._legacy_failure_modes(verdict),
        }
        self.state_desc_pub.publish(String(data=json.dumps(state_desc)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ltl-monitor",
        description="Monitor LTL formula(s) against a stream of ROS 2 observations.",
    )
    formula_group = parser.add_mutually_exclusive_group(required=True)
    formula_group.add_argument("-f", "--formula", action="append", dest="formulas")
    formula_group.add_argument(
        "--formulas-file",
        help="a spec: either a path, or a bare name like 'formulas_g1.json' resolved "
             "against the config volume's specs/ and then the packaged specs",
    )
    parser.add_argument("--changes-only", action="store_true")
    parser.add_argument("--stop-on-violation", action="store_true")
    parser.add_argument(
        "--passive", action="store_true",
        help="Observation-only mode: on a terminal state or fault, report it and go "
             "IDLE instead of shutting both nodes down, so the monitor survives to "
             "observe the next skill execution. Resume with a 'reset' command.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    skill_monitor.add_config_argument(parser)
    return parser.parse_args()


def main(args=None) -> None:
    rclpy.init(args=args)
    parsed_args = parse_args()
    # Before anything resolves a spec: --config beats $SKILL_MONITOR_CONFIG beats the
    # packaged defaults, and the choice is announced so a container that quietly read
    # its baked-in spec instead of the mounted one says so.
    skill_monitor.set_config_dir(parsed_args.config)
    print(skill_monitor.config_report())

    if parsed_args.formulas_file:
        # Resolved once, here, so the file watcher and the manifest's `source` both
        # name a real path rather than the bare argument.
        try:
            parsed_args.formulas_file = manifest_mod.resolve_spec_path(
                parsed_args.formulas_file
            )
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        spec = load_formulas_from_file(parsed_args.formulas_file)
    else:
        spec = SkillSpec(formulas=parsed_args.formulas, names=parsed_args.formulas)

    if not spec.formulas:
        print("Error: at least one formula is required.", file=sys.stderr)
        sys.exit(1)

    _print_skill_header(spec)

    try:
        multi = MultiMonitor(
            spec.all_formulas,
            names=spec.all_names,
            failure_modes=spec.build_failure_mode_infos(),
        )
    except Exception as exc:
        print(f"\nError building automaton: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = parsed_args.output_dir
    _print_formula_table(multi, spec, output_dir)

    node = LtlMonitorNode(spec, multi, parsed_args)

    print(f"\n{BOLD}{'─' * 64}{RESET}")
    print(f"{BOLD}  Monitoring Trace{RESET}")
    print(f"{BOLD}{'─' * 64}{RESET}")
    
    _print_step_block("init", multi, {}, "Idle")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__ == "__main__":
    main()
