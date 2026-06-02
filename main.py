"""
main.py — CLI entrypoint for the LTL Büchi monitor.

Formulas are supplied via -f flags or a --formulas-file JSON file.

Usage examples:
    python3 main.py -f "F(goal)" -f "G(!obstacle)"
    python3 main.py --formulas-file formulas.json
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
from std_msgs.msg import String

from monitor import MonitorStatus, MultiMonitor, LTLMonitor

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
    ) -> None:
        self.formulas            = formulas
        self.names               = names
        self.skill_name          = skill_name
        self.description         = description
        self.atomic_propositions = atomic_propositions or {}
        self.execution_phases    = execution_phases or []
        
        terminal_success = terminal_success or {}
        self.terminal_success_condition = terminal_success.get("condition", "False")
        self.terminal_success_description = terminal_success.get("description", "")

        terminal_failure = terminal_failure or {}
        self.terminal_failure_condition = terminal_failure.get("condition", "False")
        self.terminal_failure_description = terminal_failure.get("description", "")

        self.terminal_success_aps: set[str] = _extract_aps_from_condition(self.terminal_success_condition)
        self.terminal_failure_aps: set[str] = _extract_aps_from_condition(self.terminal_failure_condition)
        self.terminal_aps: set[str] = self.terminal_success_aps | self.terminal_failure_aps


def load_formulas_from_file(path: Path) -> SkillSpec:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        print(f"Error reading formulas file: {exc}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, list):
        return SkillSpec(formulas=data, names=data)

    raw_formulas = data.get("ltl_formulas", [])
    formulas, names = [], []
    for entry in raw_formulas:
        formulas.append(entry["formula"])
        names.append(entry.get("name", entry["formula"]))

    return SkillSpec(
        formulas            = formulas,
        names               = names,
        skill_name          = data.get("skill_name", ""),
        description         = data.get("description", ""),
        atomic_propositions = data.get("atomic_propositions", {}),
        execution_phases    = data.get("execution_phases", []),
        terminal_success    = data.get("terminal_success"),
        terminal_failure    = data.get("terminal_failure"),
    )


def detect_phase(phases: list[dict], observation: dict[str, bool]) -> str:
    current = "—"
    for phase in phases:
        condition = _sanitize_condition(phase.get("condition", "False"))
        try:
            if eval(condition, {"__builtins__": {}}, observation):
                current = phase["phase"]
        except Exception:
            pass
    return current


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


def _print_formula_table(multi: MultiMonitor, output_dir: Path = Path("output")) -> None:
    print(f"\n{BOLD}Formulas & Büchi Automata Structure:{RESET}")
    for mon in multi:
        print(mon.format_automaton())
        save_automaton_image(mon, output_dir)
        print()

    try:
        combined_formula = " && ".join(f"({m.formula})" for m in multi.monitors)
        combined_mon = LTLMonitor(combined_formula, name="CombinedSkillSpec")
        print(f"{BOLD}Combined/Product Büchi Automaton — Whole Skill Specification:{RESET}")
        print(combined_mon.format_automaton())
        print()
        save_automaton_image(combined_mon, output_dir)
    except Exception as e:
        print(f"Note: Could not build combined product automaton: {e}")


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

    phase_str = f"  {CYAN}[{phase}]{RESET}" if phase and phase != "—" else ""
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
        self.halted = False

        # Watch formulas file for changes
        self.formulas_file = args.formulas_file
        self.last_mtime = 0
        if self.formulas_file and os.path.exists(self.formulas_file):
            self.last_mtime = os.path.getmtime(self.formulas_file)

        self.aps_pub = self.create_publisher(String, '/ltl/required_aps', 10)
        self.state_desc_pub = self.create_publisher(String, '/ltl/state_description', 10)
        self.eval_sub = self.create_subscription(String, '/ltl/evaluations', self.eval_callback, 10)

        self.timer = self.create_timer(1.0, self.publish_current_state)

        self.get_logger().info('LTL Monitor ROS 2 Node started.')

        # Publish initial state
        self.publish_current_state()

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

    def reload_specs(self):
        self.get_logger().info("Reloading formulas and AP specs from formulas.json...")
        spec = load_formulas_from_file(self.formulas_file)
        self.spec = spec
        self.has_phases = bool(spec.execution_phases)
        try:
            self.multi = MultiMonitor(spec.formulas, names=spec.names)
        except Exception as exc:
            self.get_logger().error(f"Failed to build reloaded automaton: {exc}")
            return

        self.prev_statuses = dict(self.multi.statuses())
        self.step_idx = 0
        self.halted = False
        self.current_phase = ""
        self.current_observation = {}

        # Print new skill header and formulas/automaton table to stdout
        _print_skill_header(spec)
        _print_formula_table(self.multi, self.args.output_dir)

        print(f"\n{BOLD}{'─' * 64}{RESET}")
        print(f"{BOLD}  Monitoring Trace (Reloaded specs){RESET}")
        print(f"{BOLD}{'─' * 64}{RESET}")
        
        init_phase = detect_phase(spec.execution_phases, {}) if self.has_phases else None
        _print_step_block("init", self.multi, {}, init_phase)
        self.get_logger().info("Monitor reset successfully with new specs.")

    def _enter_idle(self, reason: str) -> None:
        """Halt monitoring and enter the idle state, waiting for the next skill."""
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

        # Publish empty APs + idle state description so LLM client halts
        aps_msg = String()
        aps_msg.data = json.dumps([])
        self.aps_pub.publish(aps_msg)

        idle_desc = {
            "state": "idle",
            "skill_name": self.spec.skill_name,
            "reason": reason,
        }
        desc_msg = String()
        desc_msg.data = json.dumps(idle_desc)
        self.state_desc_pub.publish(desc_msg)

    def _reset_for_new_skill(self) -> None:
        """Reset automaton state and resume monitoring for a new skill execution."""
        self.multi.reset()
        self.prev_statuses = dict(self.multi.statuses())
        self.step_idx = 0
        self.halted = False
        self.current_phase = ""
        print(f"\n{BOLD}{'─' * 64}{RESET}")
        print(f"{BOLD}  Monitoring Trace (New Execution){RESET}")
        print(f"{BOLD}{'─' * 64}{RESET}")
        init_phase = detect_phase(self.spec.execution_phases, {}) if self.has_phases else None
        _print_step_block("init", self.multi, {}, init_phase)
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

        # Capture current automaton states before stepping
        prev_states = {m.name: m.current_state for m in self.multi.monitors}

        # Step the automaton
        statuses = self.multi.step(observation)
        self.current_phase = detect_phase(self.spec.execution_phases, observation) if self.has_phases else ""

        # Print standard console step block
        _print_step_block(
            self.step_idx, self.multi, observation, self.current_phase,
            changed_only=self.args.changes_only,
            prev_statuses=self.prev_statuses,
            prev_states=prev_states,
        )

        # Log current states to ROS logs
        for mon in self.multi.monitors:
            prev_s = prev_states[mon.name]
            curr_s = mon.current_state
            self.get_logger().info(
                f"[{mon.name}] {prev_s} ──► {curr_s}{_state_label(mon, curr_s)} | {mon.status.name}"
            )
        if self.current_phase:
            self.get_logger().info(f"Current phase: {self.current_phase}")

        self.prev_statuses = dict(statuses)
        self.step_idx += 1

        if self.args.stop_on_violation and self.multi.any_violated():
            self.get_logger().error(f"Stopping early — formula permanently VIOLATED at step {self.step_idx}.")
            _print_summary(self.multi)
            rclpy.shutdown()
            return

        # Check if we reached a terminal observation
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

        # Determine required APs for next step — always include terminal APs so
        # the LLM evaluates them with full terminal-context descriptions.
        required_aps = self.multi.get_required_aps() | self.spec.terminal_aps
        aps_msg = String()
        aps_msg.data = json.dumps(list(required_aps))
        self.aps_pub.publish(aps_msg)

        # Publish state description — include terminal context so the LLM
        # prompt can describe success/failure conditions explicitly.
        state_desc = {
            "phase": self.current_phase,
            "skill_name": self.spec.skill_name,
            "description": self.spec.description,
            "ap_descriptions": self.spec.atomic_propositions,
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
        multi = MultiMonitor(spec.formulas, names=spec.names)
    except Exception as exc:
        print(f"\nError building automaton: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = parsed_args.output_dir
    _print_formula_table(multi, output_dir)

    node = LtlMonitorNode(spec, multi, parsed_args)

    print(f"\n{BOLD}{'─' * 64}{RESET}")
    print(f"{BOLD}  Monitoring Trace{RESET}")
    print(f"{BOLD}{'─' * 64}{RESET}")
    
    init_phase = detect_phase(spec.execution_phases, {}) if bool(spec.execution_phases) else None
    _print_step_block("init", multi, {}, init_phase)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__ == "__main__":
    main()
