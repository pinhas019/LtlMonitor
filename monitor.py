"""
monitor.py — Core LTL monitoring engine using the Spot library.

Builds a deterministic, complete Büchi automaton for each LTL formula and
steps it forward one observation at a time.

Classes:
    MonitorStatus  — Enum for the three possible monitor states.
    LTLMonitor     — Monitors a single LTL formula (one Büchi automaton).
    MultiMonitor   — Runs multiple LTLMonitor instances in parallel.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator

import spot


# ---------------------------------------------------------------------------
# Named failure mode descriptor
# ---------------------------------------------------------------------------

@dataclass
class FailureModeInfo:
    """
    Metadata attached to an LTL formula that represents a named failure mode.

    When the formula's monitor reaches VIOLATED the fault is reported under
    this name and category rather than as a generic LTL violation.

    Attributes
    ----------
    name          : Short machine-readable identifier, e.g. "collision_detected".
    fault_category: Semantic fault bucket, e.g. "SAFETY", "NAVIGATION", "TIMEOUT".
    description   : Human-readable explanation for logs/display.
    """
    name: str
    fault_category: str
    description: str = ""


# ---------------------------------------------------------------------------
# Status model
# ---------------------------------------------------------------------------

class MonitorStatus(Enum):
    """
    The status of an LTL monitor after processing an observation.

    INCONCLUSIVE : The prefix seen so far neither proves nor refutes the
                   property. The automaton is in a non-accepting state but
                   can still reach an accepting state.
    ACCEPTED     : The automaton is in an accepting state. For a Büchi
                   automaton this means the property holds over the finite
                   prefix observed so far.
    VIOLATED     : The automaton has entered a sink/trap state from which no
                   accepting state is reachable. The property is permanently
                   falsified.
    """
    INCONCLUSIVE = auto()
    ACCEPTED     = auto()
    VIOLATED     = auto()

    def __str__(self) -> str:
        colors = {
            MonitorStatus.INCONCLUSIVE: "\033[33m",  # yellow
            MonitorStatus.ACCEPTED:     "\033[32m",  # green
            MonitorStatus.VIOLATED:     "\033[31m",  # red
        }
        return f"{colors[self]}{self.name}\033[0m"


# ---------------------------------------------------------------------------
# Single-formula monitor (Büchi automaton)
# ---------------------------------------------------------------------------

class LTLMonitor:
    """
    Monitors a single LTL formula using a deterministic complete Büchi automaton.

    The automaton is built once at construction time via Spot's translation.
    Calling ``step()`` advances it one observation at a time.

    Parameters
    ----------
    formula : str
        An LTL formula string, e.g. ``"F(goal)"``, ``"G(!obstacle)"``.
    """

    def __init__(
        self,
        formula: str,
        name: str | None = None,
        failure_mode: FailureModeInfo | None = None,
    ) -> None:
        self.formula = formula
        self.name: str = name if name is not None else formula
        self.failure_mode: FailureModeInfo | None = failure_mode

        # Translate to a deterministic, complete, state-based Büchi automaton.
        #   'Buchi'    → state-based Büchi acceptance (accepting states).
        #   'det'      → deterministic (at most one matching transition per input).
        #   'complete' → every state has a transition for every possible input,
        #                so a no-match is impossible.
        self.aut: spot.twa_graph = spot.translate(
            formula, "Buchi", "det", "complete", "sbacc"
        )
        self.bdict: spot.bdd_dict = self.aut.get_dict()
        self._initial_state: int  = self.aut.get_init_state_number()
        self.current_state: int   = self._initial_state

        # Pre-compute which states are dead-end sinks (non-accepting with only
        # a self-loop on bddtrue → no accepting state is reachable).
        self._sink_states: set[int] = self._find_sink_states()

        self.status: MonitorStatus = self._compute_status()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(self, observation: dict[str, bool]) -> MonitorStatus:
        """
        Advance the automaton by one observation.

        Parameters
        ----------
        observation : dict[str, bool]
            Maps atomic proposition names to boolean values for this step.
            Propositions not used by this formula are ignored.

        Returns
        -------
        MonitorStatus
            The monitor's status after processing this observation.
        """
        if self.status is MonitorStatus.VIOLATED:
            # Sink state is absorbing — no further evaluation needed.
            return self.status

        obs_bdd    = self._observation_to_bdd(observation)
        next_state = self._find_successor(obs_bdd)

        # Because the automaton is 'complete', next_state is always found.
        # This assertion guards against unexpected library edge cases.
        assert next_state is not None, (
            f"No successor found in a 'complete' automaton — "
            f"formula: '{self.formula}', state: {self.current_state}. "
            "This should never happen; please report a bug."
        )

        self.current_state = next_state
        self.status        = self._compute_status()
        return self.status

    def reset(self) -> None:
        """Reset the monitor to its initial state."""
        self.current_state = self._initial_state
        self.status        = self._compute_status()

    def export_dot(self) -> str:
        """Return the Büchi automaton in DOT format for visualization."""
        return self.aut.to_str("dot")

    def format_automaton(
        self,
        ap_descriptions: dict[str, str] | None = None,
        state_annotations: dict[int, dict] | None = None,
    ) -> str:
        """Return a human-readable text representation of the Büchi automaton.

        Parameters
        ----------
        ap_descriptions : dict[str, str], optional
            Maps AP names to human-readable descriptions.
        state_annotations : dict[int, dict], optional
            Maps automaton state index to phase metadata inferred from the spec.
            Each dict may contain: phase_name, description, precondition,
            precondition_fault_category, invariant, invariant_fault_category,
            timing_bounds.
        """
        BOLD   = "\033[1m"
        RESET  = "\033[0m"
        DIM    = "\033[2m"
        GREEN  = "\033[32m"
        RED    = "\033[31m"
        YELLOW = "\033[33m"
        CYAN   = "\033[36m"

        lines = []
        lines.append(f"  {BOLD}Büchi Automaton for '{self.name}'{RESET}")
        lines.append(f"  {DIM}Formula: {self.formula}{RESET}")

        for s in range(self.aut.num_states()):
            labels = []
            if s == self._initial_state:
                labels.append("initial")
            if self.aut.state_is_accepting(s):
                labels.append("accepting")
            if s in self._sink_states:
                labels.append("sink/trap")

            # Semantic status hint
            if s in self._sink_states:
                semantic = f"  {RED}✘ VIOLATED — irrecoverable{RESET}"
            elif self.aut.state_is_accepting(s):
                semantic = f"  {GREEN}✔ Property holds{RESET}"
            else:
                semantic = f"  {YELLOW}● Monitoring…{RESET}"

            label_str = f" [{', '.join(labels)}]" if labels else ""
            lines.append(f"    {BOLD}State {s}{label_str}:{RESET}{semantic}")

            # ── Phase annotation ──────────────────────────────────
            if state_annotations and s in state_annotations:
                ann = state_annotations[s]
                phase_name = ann.get("phase_name", "")
                if phase_name:
                    lines.append(f"      {BOLD}{CYAN}Phase: {phase_name}{RESET}")
                if ann.get("description"):
                    lines.append(f"      {DIM}{ann['description']}{RESET}")
                if ann.get("precondition"):
                    pc_cat = ann.get("precondition_fault_category", "PRECONDITION")
                    lines.append(
                        f"      {DIM}Precondition : {ann['precondition']}"
                        f"  [{pc_cat} — checked on entry]{RESET}"
                    )
                if ann.get("invariant"):
                    inv_cat = ann.get("invariant_fault_category", "INVARIANT")
                    lines.append(
                        f"      {RED}Invariant    : {ann['invariant']}"
                        f"  [{inv_cat} — immediate halt]{RESET}"
                    )
                timing = ann.get("timing_bounds", {})
                if timing:
                    min_s = timing.get("min_steps", "—")
                    max_s = timing.get("max_steps", "—")
                    lines.append(
                        f"      {DIM}Timing       : min {min_s} / max {max_s} steps"
                        f"  [TIMEOUT on exceed]{RESET}"
                    )
            # ─────────────────────────────────────────────────────

            for edge in self.aut.out(s):
                cond_str = spot.bdd_format_formula(self.bdict, edge.cond)

                # Destination hint
                if edge.dst in self._sink_states:
                    dst_hint = f"  {RED}→ VIOLATED{RESET}"
                elif self.aut.state_is_accepting(edge.dst):
                    dst_hint = f"  {GREEN}→ ACCEPTED{RESET}"
                else:
                    dst_hint = ""

                if edge.cond == spot.buddy.bddtrue:
                    lines.append(f"      ──► State {edge.dst} on: {cond_str}  {DIM}(any input){RESET}{dst_hint}")
                else:
                    lines.append(f"      ──► State {edge.dst} on: {cond_str}{dst_hint}")
                    if ap_descriptions:
                        for ap_name in sorted(self._get_edge_aps(edge)):
                            if ap_name in ap_descriptions:
                                lines.append(f"          {DIM}{ap_name}: {ap_descriptions[ap_name]}{RESET}")

        return "\n".join(lines)

    def num_states(self) -> int:
        """Return the total number of states in the automaton."""
        return self.aut.num_states()

    def get_required_aps(self) -> set[str]:
        """
        Return the set of atomic proposition names that appear in the
        outgoing edges of the current state.

        These are the only APs that can influence the next transition,
        so the robot only needs to evaluate these.
        """
        if self.status is MonitorStatus.VIOLATED:
            return set()  # sink state — nothing to evaluate

        required: set[str] = set()
        for edge in self.aut.out(self.current_state):
            if edge.cond == spot.buddy.bddtrue:
                continue  # unconditional edge — no APs needed
            required |= self._get_edge_aps(edge)

        return required

    def _get_edge_aps(self, edge) -> set[str]:
        """Extract the set of AP names referenced by a BDD edge condition."""
        var_to_ap: dict[int, str] = {
            self.bdict.varnum(ap): str(ap) for ap in self.aut.ap()
        }
        aps: set[str] = set()
        if edge.cond == spot.buddy.bddtrue or edge.cond == spot.buddy.bddfalse:
            return aps
        support = spot.buddy.bdd_support(edge.cond)
        bdd = support
        while bdd != spot.buddy.bddtrue and bdd != spot.buddy.bddfalse:
            var = spot.buddy.bdd_var(bdd)
            if var in var_to_ap:
                aps.add(var_to_ap[var])
            bdd = spot.buddy.bdd_high(bdd)
        return aps

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _observation_to_bdd(self, observation: dict[str, bool]) -> int:
        """Convert an observation dict to a BDD cube."""
        bdd = spot.buddy.bddtrue
        for ap in self.aut.ap():
            name    = str(ap)
            value   = observation.get(name, False)
            var_bdd = spot.buddy.bdd_ithvar(self.bdict.varnum(ap))
            bdd     = spot.buddy.bdd_and(
                bdd,
                var_bdd if value else spot.buddy.bdd_not(var_bdd),
            )
        return bdd

    def _find_successor(self, obs_bdd: int) -> int | None:
        """Return the destination state for the first matching outgoing edge."""
        for edge in self.aut.out(self.current_state):
            if spot.buddy.bdd_and(edge.cond, obs_bdd) != spot.buddy.bddfalse:
                return edge.dst
        return None

    def _find_sink_states(self) -> set[int]:
        """
        Pre-compute the set of sink states: non-accepting states whose only
        outgoing edge is a self-loop with condition bddtrue.
        These states can never reach an accepting state.
        """
        sinks = set()
        for s in range(self.aut.num_states()):
            if self.aut.state_is_accepting(s):
                continue
            edges = list(self.aut.out(s))
            if len(edges) == 1:
                e = edges[0]
                if e.dst == s and e.cond == spot.buddy.bddtrue:
                    sinks.add(s)
        return sinks

    def _compute_status(self) -> MonitorStatus:
        if self.current_state in self._sink_states:
            return MonitorStatus.VIOLATED
        if self.aut.state_is_accepting(self.current_state):
            return MonitorStatus.ACCEPTED
        return MonitorStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# Multi-formula monitor
# ---------------------------------------------------------------------------

class MultiMonitor:
    """
    Runs multiple :class:`LTLMonitor` instances in parallel against the same
    stream of observations.

    Parameters
    ----------
    formulas : list[str]
        A list of LTL formula strings.
    """

    def __init__(
        self,
        formulas: list[str],
        names: list[str] | None = None,
        failure_modes: list[FailureModeInfo | None] | None = None,
    ) -> None:
        if names is None:
            names = formulas
        if len(names) != len(formulas):
            raise ValueError("Length of 'names' must match length of 'formulas'.")
        if failure_modes is None:
            failure_modes = [None] * len(formulas)
        elif len(failure_modes) != len(formulas):
            raise ValueError("Length of 'failure_modes' must match length of 'formulas'.")
        self.monitors: list[LTLMonitor] = [
            LTLMonitor(f, name=n, failure_mode=fm)
            for f, n, fm in zip(formulas, names, failure_modes)
        ]

    def step(self, observation: dict[str, bool]) -> dict[str, MonitorStatus]:
        """
        Advance all monitors by one observation.

        Returns
        -------
        dict[str, MonitorStatus]
            Maps each formula string to its updated status.
        """
        return {m.name: m.step(observation) for m in self.monitors}

    def statuses(self) -> dict[str, MonitorStatus]:
        """Return the current status of every monitor without stepping."""
        return {m.name: m.status for m in self.monitors}

    def reset(self) -> None:
        """Reset all monitors to their initial states."""
        for m in self.monitors:
            m.reset()

    def all_accepted(self) -> bool:
        """True if every formula is currently ACCEPTED."""
        return all(m.status is MonitorStatus.ACCEPTED for m in self.monitors)

    def any_violated(self) -> bool:
        """True if at least one formula is VIOLATED."""
        return any(m.status is MonitorStatus.VIOLATED for m in self.monitors)

    def __iter__(self) -> Iterator[LTLMonitor]:
        return iter(self.monitors)

    def get_required_aps(self) -> set[str]:
        """
        Return the union of required APs across all non-violated monitors.
        """
        aps: set[str] = set()
        for m in self.monitors:
            aps |= m.get_required_aps()
        return aps

    def get_violated_failure_modes(self) -> list[tuple[LTLMonitor, FailureModeInfo]]:
        """
        Return (monitor, failure_info) for every named-failure-mode monitor that
        has reached VIOLATED.  Regular property monitors (failure_mode=None) are
        excluded — they surface via ``any_violated()`` as before.
        """
        return [
            (m, m.failure_mode)
            for m in self.monitors
            if m.status is MonitorStatus.VIOLATED and m.failure_mode is not None
        ]

    def get_failure_mode_monitors(self) -> list[LTLMonitor]:
        """Return all monitors that carry a FailureModeInfo annotation."""
        return [m for m in self.monitors if m.failure_mode is not None]

    def get_property_monitors(self) -> list[LTLMonitor]:
        """Return monitors that are pure LTL property checks (no failure annotation)."""
        return [m for m in self.monitors if m.failure_mode is None]

