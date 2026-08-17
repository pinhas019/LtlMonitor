"""
main.py — CLI entrypoint for the LTL Büchi monitor.

Formulas are supplied via -f flags or a --formulas-file JSON file.

Usage examples:
    python3 main.py -f "F(goal)" -f "G(!obstacle)"
    python3 main.py --formulas-file formulas.json

Skill-type agnosticism: --formulas-file is just the default/initial spec. If something
publishes a skill label on /active_skill (std_msgs/String), and a matching
formulas_<label>.json exists beside --formulas-file, this node swaps to it -- the same
formulas_<skill>.json convention minigrid/skill_monitor/ltl_skill_monitor.py already
uses for MiniGrid/CoopBoxPush skills, generalized here so a G1 skill executor could use
it too. No publisher exists for G1 yet (only one skill, navigation); this is inert
future-proofing, not a behavior change -- with nothing publishing /active_skill,
--formulas-file remains the spec for the whole run, exactly as before.
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

import skill_monitor.core.manifest as manifest_mod
import skill_monitor.core.spec_contract as spec_contract
from skill_monitor.core.automata import FailureModeInfo, MonitorStatus, MultiMonitor, LTLMonitor

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
        # to clients on /ltl/manifest without reconstructing it from parsed pieces.
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


def load_formulas_from_file(path: Path) -> SkillSpec:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(f"Error reading formulas file: {exc}", file=sys.stderr)
        sys.exit(1)
    return spec_from_dict(data)


def spec_from_dict(data) -> SkillSpec:
    """A spec from already-parsed JSON -- the same code path whether it came off disk
    or off /ltl/load_spec, so a pushed spec can never be interpreted differently from
    a loaded one."""
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


_PHASE_VIOLATION_LIMIT = 3  # default consecutive-step limit before a phase failure


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
        # Confidence in the latest observation, from the evaluator's reserved
        # __confidence__ key (sensor freshness). 1.0 until told otherwise, so an
        # evaluator that does not report it behaves exactly as before.
        self._confidence = 1.0
        self._stale_sources: list = []

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
        self.skills_dir = (
            os.path.dirname(os.path.abspath(self.formulas_file)) if self.formulas_file else "."
        )
        self.active_skill_label: str | None = None
        self.active_skill_sub = self.create_subscription(
            String, '/active_skill', self.active_skill_callback, 10
        )

        self.aps_pub = self.create_publisher(String, '/ltl/required_aps', 10)
        self.state_desc_pub = self.create_publisher(String, '/ltl/state_description', 10)
        self.eval_sub = self.create_subscription(String, '/ltl/evaluations', self.eval_callback, 10)

        # The manifest is the whole spec, latched: a GUI or any other client that
        # connects mid-mission gets it immediately instead of having to find the file
        # on a disk it may not share, and needs no import of this package to read it.
        self.manifest_pub = self.create_publisher(String, '/ltl/manifest', _LATCHED)
        self.spec_status_pub = self.create_publisher(String, '/ltl/spec_status', _LATCHED)

        # A spec can also arrive over the wire. Same code path as a file load, and
        # validated against the adapter's schema first -- a spec whose rules mention
        # fields this robot does not publish would otherwise run as silently-false APs.
        self.create_subscription(String, '/ltl/load_spec', self.load_spec_callback, 10)
        self.adapter_manifest: dict = {}
        self.create_subscription(String, '/ltl/adapter', self.adapter_callback, _LATCHED)

        # Latest sensor_eval and AP truth values from the evaluator, passed through to
        # state_description so a client sees the numbers the APs were computed from,
        # not just the APs' names.
        self.sensors: dict = {}
        self.last_observation: dict = {}

        self.timer = self.create_timer(1.0, self.publish_current_state)

        self.get_logger().info('LTL Monitor ROS 2 Node started.')

        # Publish initial state
        self.publish_manifest()
        self.publish_current_state()

    # -- manifest / spec push -------------------------------------------------

    def publish_manifest(self, source: str | None = None) -> None:
        self.manifest_pub.publish(String(data=json.dumps(self.manifest(source))))

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
        would make the monitor unusable in replay/offline setups."""
        schema_keys = (self.adapter_manifest.get("schema") or {}).keys()
        if not schema_keys:
            return spec_contract.validate_structure(data)
        return spec_contract.validate(data, schema_keys)

    def _spec_status(self, ok: bool, problems: list, skill_name: str = "") -> None:
        self.spec_status_pub.publish(String(data=json.dumps(
            {"ok": ok, "problems": problems, "skill_name": skill_name})))

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

    def is_terminal_observation(self, observation: dict[str, bool]) -> bool:
        # Skip terminal checks until the skill has actually started:
        # - When phases are defined, wait until the first phase is entered.
        # - Always enforce a minimum step count (grace period) to absorb
        #   stale sensor state and LLM warm-up hallucinations.
        if self.step_idx < 2:
            return False
        if self.has_phases and self.phase_idx < 0:
            return False

        success_cond_raw = getattr(self.spec, "terminal_success_condition", "False")
        success_cond = _sanitize_condition(success_cond_raw)
        try:
            if eval(success_cond, {"__builtins__": {}}, observation):
                desc = getattr(self.spec, "terminal_success_description", "")
                self.get_logger().info(f"Terminal SUCCESS: {success_cond_raw} ({desc})")
                return True
        except Exception as e:
            self.get_logger().warn(f"Failed to evaluate terminal success condition '{success_cond_raw}': {e}")

        failure_cond_raw = getattr(self.spec, "terminal_failure_condition", "False")
        failure_cond = _sanitize_condition(failure_cond_raw)
        try:
            if eval(failure_cond, {"__builtins__": {}}, observation):
                desc = getattr(self.spec, "terminal_failure_description", "")
                self.get_logger().info(f"Terminal FAILURE: {failure_cond_raw} ({desc})")
                return True
        except Exception as e:
            self.get_logger().warn(f"Failed to evaluate terminal failure condition '{failure_cond_raw}': {e}")

        return False

    def active_skill_callback(self, msg: String):
        label = msg.data.strip()
        if not label or label == self.active_skill_label:
            return
        skill_path = Path(self.skills_dir) / f"formulas_{label}.json"
        if not skill_path.exists():
            self.get_logger().warn(
                f"No spec file for active skill '{label}' (expected {skill_path}) — "
                f"continuing with the current spec ('{self.spec.skill_name}')."
            )
            return
        self.get_logger().info(f"Active skill changed → '{label}', loading {skill_path}")
        self.active_skill_label = label
        self.reload_specs(skill_path)

    def reload_specs(self, formulas_path: str | None = None, spec_data: dict | None = None):
        if spec_data is not None:
            # Pushed over /ltl/load_spec: there is no file, and adopting one would
            # make the file watcher immediately reload over the top of it.
            self.get_logger().info("Reloading from pushed spec...")
            spec = spec_from_dict(spec_data)
            self.formulas_file = None
        else:
            path = formulas_path or self.formulas_file
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
    ) -> tuple[str, str | None, str | None, bool]:
        """
        Advance the phase state machine one step.

        Returns
        -------
        (phase_name, failure_reason, fault_category, recoverable)

        failure_reason is None when no failure occurred.
        recoverable=True  → enter IDLE (e.g. progress violations, awaitable)
        recoverable=False → halt permanently  (e.g. invariant, timeout, precondition)
        """
        phases = self.spec.execution_phases
        if not phases:
            return "Idle", None, None, False

        def _eval(raw: str, default: bool) -> bool:
            try:
                return bool(eval(_sanitize_condition(raw), {"__builtins__": {}}, observation))
            except Exception:
                return default

        def _enter_phase(idx: int) -> tuple[str, str | None, str | None, bool] | None:
            """Try to enter phase[idx]; return failure tuple if precondition fails."""
            p = phases[idx]
            self.phase_idx = idx
            self.phase_step_count = 0
            self.phase_violation_count = 0
            self.get_logger().info(f"Phase enter: '{p['phase']}'")
            precond = p.get("precondition", "")
            if precond and not _eval(precond, True):
                cat = p.get("precondition_fault_category", "PRECONDITION")
                return (
                    p["phase"],
                    f"Precondition not met on entry to phase '{p['phase']}': {precond}",
                    cat,
                    False,
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
            return "Idle", None, None, False

        p     = phases[self.phase_idx]
        name  = p["phase"]
        limit = p.get("progress_violation_limit", _PHASE_VIOLATION_LIMIT)

        # ── Hard invariant (immediate failure) ────────────────────
        invariant = p.get("invariant", "")
        if invariant and not _eval(invariant, True):
            cat = p.get("invariant_fault_category", "INVARIANT")
            return (
                name,
                f"Invariant violated in phase '{name}': {invariant}",
                cat,
                False,
            )

        # ── Timing: max_steps ─────────────────────────────────────
        timing    = p.get("timing_bounds", {})
        max_steps = timing.get("max_steps")
        if max_steps is not None and self.phase_step_count >= max_steps:
            return (
                name,
                f"Phase '{name}' timed out: {self.phase_step_count} steps elapsed (max={max_steps})",
                "TIMEOUT",
                False,
            )

        # ── Progress condition (counted violations) ───────────────
        if not _eval(p.get("progress_condition", "True"), True):
            self.phase_violation_count += 1
            self.get_logger().warn(
                f"Phase '{name}' progress violation {self.phase_violation_count}/{limit}"
            )
            if self.phase_violation_count >= limit:
                return (
                    name,
                    f"Phase '{name}' progress conditions violated {limit} consecutive step(s)",
                    "PROGRESS",
                    True,  # recoverable — await new skill execution
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
                return "Done", None, None, False

        self.phase_step_count += 1
        if 0 <= self.phase_idx < len(phases):
            return phases[self.phase_idx]["phase"], None, None, False
        return "Idle", None, None, False

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
        RED = "\033[31m"
        print(f"\n{BOLD}{'═' * 64}{RESET}")
        print(f"{BOLD}{RED}  ■  MONITOR HALTED{RESET}")
        print(f"  Reason : {reason}")
        print(f"{BOLD}{'═' * 64}{RESET}\n")
        self.get_logger().info(f"Monitor halting. Reason: {reason}")

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
        YELLOW = "\033[33m"
        print(f"\n{BOLD}{'═' * 64}{RESET}")
        print(f"{BOLD}{YELLOW}  ◉  MONITOR IDLE{RESET}")
        print(f"  Reason   : {reason}")
        print(f"  Awaiting : new skill execution")
        print(f"  Resume   : send {{\"__reset__\": true}} on /ltl/evaluations")
        print(f"           : or update formulas.json to reload automatically")
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
        self._reset_phase_state()
        print(f"\n{BOLD}{'─' * 64}{RESET}")
        print(f"{BOLD}  Monitoring Trace (New Execution){RESET}")
        print(f"{BOLD}{'─' * 64}{RESET}")
        _print_step_block("init", self.multi, {}, "Idle")
        self.publish_current_state()

    def eval_callback(self, msg: String):
        try:
            observation = json.loads(msg.data)
        except Exception as e:
            self.get_logger().error(f"Failed to parse evaluation JSON: {e}")
            return

        # Check for termination signal
        if observation.get("__done__", False):
            self.get_logger().info("Received termination signal.")
            _print_summary(self.multi)
            rclpy.shutdown()
            return

        # While halted, only accept an explicit reset signal
        if self.halted:
            if observation.get("__reset__", False):
                self.get_logger().info("Reset signal received. Starting new skill execution...")
                self._reset_for_new_skill()
            # All other messages are ignored while idle
            return

        # Reserved keys are metadata about the observation, not part of it. Strip
        # them before stepping so they can never reach a guard's eval namespace.
        self._confidence = float(observation.pop("__confidence__", 1.0))
        self._stale_sources = list(observation.pop("__stale__", []))
        self.sensors = dict(observation.pop("__sensors__", {}) or {})
        self.last_observation = dict(observation)

        # Capture current automaton states before stepping
        prev_states = {m.name: m.current_state for m in self.multi.monitors}

        # Step the automaton (property formulas + named-failure-mode formulas)
        statuses = self.multi.step(observation)

        # ── Named failure modes: detect newly violated formulas ───
        triggered_failures = self.multi.get_violated_failure_modes()

        # Advance phase state machine
        phase_fail_reason: str | None = None
        phase_fault_cat:   str | None = None
        phase_recoverable: bool       = False
        if self.has_phases:
            prev_phase_idx = self.phase_idx
            phase_name, phase_fail_reason, phase_fault_cat, phase_recoverable = \
                self._update_phase_state(observation)
            self.current_phase = phase_name
            if self.phase_idx != prev_phase_idx and self.phase_idx >= 0:
                self._print_phase_context()
        else:
            pass

        # Print standard console step block
        _print_step_block(
            self.step_idx, self.multi, observation, self.current_phase,
            changed_only=self.args.changes_only,
            prev_statuses=self.prev_statuses,
            prev_states=prev_states,
            phase_violations=self.phase_violation_count,
        )

        # ── Named failure mode triggered → halt with fault info ───
        if triggered_failures:
            mon, finfo = triggered_failures[0]  # first triggered is reported
            RED = "\033[31m"
            print(f"\n{BOLD}{'─' * 64}{RESET}")
            print(f"{BOLD}{RED}  ✘  NAMED FAILURE: {finfo.name}{RESET}")
            print(f"  Fault category : {finfo.fault_category}")
            if finfo.description:
                print(f"  Description    : {finfo.description}")
            print(f"  Formula        : {mon.formula}")
            if len(triggered_failures) > 1:
                extras = ", ".join(f.name for _, f in triggered_failures[1:])
                print(f"  Also triggered : {extras}")
            print(f"{BOLD}{'─' * 64}{RESET}")
            self.get_logger().error(
                f"Named failure [{finfo.fault_category}] '{finfo.name}': {finfo.description}"
            )
            _print_summary(self.multi)
            self._halt(f"[{finfo.fault_category}] {finfo.name}: {finfo.description}")
            return

        # ── Phase failure ─────────────────────────────────────────
        if phase_fail_reason is not None:
            _print_summary(self.multi)
            if phase_recoverable:
                self._enter_idle(phase_fail_reason)
            else:
                self._halt(f"[{phase_fault_cat}] {phase_fail_reason}")
            return

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
            self.get_logger().error(f"Stopping early — formula permanently VIOLATED at step {self.step_idx}.")
            _print_summary(self.multi)
            rclpy.shutdown()
            return

        # Check if we reached a terminal observation → enter idle/waiting state
        if self.is_terminal_observation(observation):
            _print_summary(self.multi)
            self._enter_idle("Terminal state reached (success or failure)")
            return

        # Publish state info for the next step immediately
        self.publish_current_state()

    def publish_current_state(self):
        # Auto-reload if formulas file changed
        if self.check_formulas_file_changed():
            self.reload_specs()

        if self.halted:
            # Periodically re-publish the idle signal so late-joining LLM clients
            # also pick up the idle state.
            aps_msg = String()
            aps_msg.data = json.dumps([])
            self.aps_pub.publish(aps_msg)
            idle_desc = {"state": "idle", "skill_name": self.spec.skill_name}
            desc_msg = String()
            desc_msg.data = json.dumps(idle_desc)
            self.state_desc_pub.publish(desc_msg)
            return

        # Automaton APs + terminal APs + phase APs — all must be evaluated each step.
        required_aps = self.multi.get_required_aps() | self.spec.terminal_aps | self.spec.phase_aps
        aps_msg = String()
        aps_msg.data = json.dumps(list(required_aps))
        self.aps_pub.publish(aps_msg)

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

        # Predictive imminence for the intervention supervisor (pre-emptive rung before
        # the hard fault). trigger_confidence comes from the evaluator's sensor
        # freshness: the rule-based APs themselves are exact, but an AP computed from
        # a topic that stopped publishing is a stale reading dressed as a fact, and
        # the supervisor's confidence gate is what de-escalates on it.
        risk: dict = {}
        if 0 <= self.phase_idx < len(phases):
            _max_steps = phase_info["timing_bounds"].get("max_steps")
            _sto = (_max_steps - self.phase_step_count) if _max_steps is not None else None
            _vtf = phase_info["violation_limit"] - self.phase_violation_count
            _warn_t = _sto is not None and _sto <= 3
            _warn_p = self.phase_violation_count > 0 and _vtf <= 3
            risk = {
                "steps_to_timeout": _sto,
                "violations_to_fault": _vtf,
                "trigger_confidence": self._confidence,
                "stale_sources": list(self._stale_sources),
                "warn": bool(_warn_t or _warn_p),
                "severity": "TIMEOUT" if _warn_t else ("PROGRESS" if _warn_p else None),
            }

        state_desc = {
            "phase": self.current_phase,
            "phase_index": self.phase_idx,
            "phases": manifest_mod.phase_names(phases),
            "step": self.step_idx,
            # The numbers the APs were computed from, forwarded from the evaluator's
            # reserved __sensors__ key so a client sees observation and conclusion
            # together rather than having to subscribe to the robot's raw topics.
            "sensors": self.sensors,
            "ap_values": self.last_observation,
            "risk": risk,
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
            "named_failure_modes": [
                {
                    "name":           m.failure_mode.name,
                    "fault_category": m.failure_mode.fault_category,
                    "description":    m.failure_mode.description,
                    "formula":        m.formula,
                    "status":         m.status.name,
                }
                for m in self.multi.get_failure_mode_monitors()
            ],
        }
        desc_msg = String()
        desc_msg.data = json.dumps(state_desc)
        self.state_desc_pub.publish(desc_msg)


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
    formula_group.add_argument("--formulas-file", type=Path)
    parser.add_argument("--changes-only", action="store_true")
    parser.add_argument("--stop-on-violation", action="store_true")
    parser.add_argument(
        "--passive", action="store_true",
        help="Observation-only mode: on a terminal state or fault, report it and go "
             "IDLE instead of shutting both nodes down, so the monitor survives to "
             "observe the next skill execution. Resume by publishing "
             "{\"__reset__\": true} on /ltl/evaluations.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    return parser.parse_args()


def main(args=None) -> None:
    rclpy.init(args=args)
    parsed_args = parse_args()

    if parsed_args.formulas_file:
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
