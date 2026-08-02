"""Unit tests for the graded action ladder — pure. Run: python3 -m pytest test_monitor_action.py"""

from monitor_action import Action, grade_action


def test_no_category_continues():
    assert grade_action(None) is Action.CONTINUE
    assert grade_action("") is Action.CONTINUE


def test_safety_halts_when_sure_aborts_when_breached():
    assert grade_action("SAFETY", imminence=2, confidence=0.9) is Action.HALT
    assert grade_action("INVARIANT", imminence=None, confidence=1.0) is Action.HALT
    # already violated (imminence<=0) + sure -> unrecoverable
    assert grade_action("SAFETY", imminence=0, confidence=0.9) is Action.ABORT
    # unsure safety signal -> only warn, never actuate on a shaky verdict
    assert grade_action("SAFETY", imminence=0, confidence=0.2) is Action.WARN


def test_timeout_replans_when_imminent_and_sure():
    assert grade_action("TIMEOUT", imminence=2, confidence=0.9) is Action.REPLAN
    assert grade_action("TIMEOUT", imminence=0, confidence=0.9) is Action.REPLAN
    assert grade_action("TIMEOUT", imminence=2, confidence=0.2) is Action.WARN
    assert grade_action("TIMEOUT", imminence=10, confidence=0.9) is Action.CONTINUE
    assert grade_action("TIMEOUT", imminence=None, confidence=0.9) is Action.CONTINUE


def test_progress_slows_when_imminent_and_sure():
    assert grade_action("PROGRESS", imminence=1, confidence=0.9) is Action.SLOW
    assert grade_action("PROGRESS", imminence=1, confidence=0.2) is Action.WARN
    assert grade_action("PROGRESS", imminence=10, confidence=0.9) is Action.CONTINUE
    # a confirmed stall (overdue) re-plans rather than merely slowing
    assert grade_action("PROGRESS", imminence=0, confidence=0.9) is Action.REPLAN


def test_unknown_category():
    assert grade_action("WEIRD", imminence=1, confidence=0.9) is Action.WARN
    assert grade_action("WEIRD", imminence=None, confidence=0.9) is Action.CONTINUE


def test_ladder_is_ordered():
    assert (
        Action.CONTINUE
        < Action.WARN
        < Action.SLOW
        < Action.REPLAN
        < Action.HALT
        < Action.ABORT
    )


def test_min_confidence_threshold_is_tunable():
    # a strict min_confidence de-escalates a mid-confidence safety signal to WARN
    assert (
        grade_action("SAFETY", imminence=2, confidence=0.6, min_confidence=0.8)
        is Action.WARN
    )
    assert (
        grade_action("SAFETY", imminence=2, confidence=0.6, min_confidence=0.5)
        is Action.HALT
    )
