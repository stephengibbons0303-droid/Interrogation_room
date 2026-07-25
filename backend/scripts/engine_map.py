"""A generated map of the engine's decision surface.

Introspects engine/tactics.py (the tactic registry) and engine/director.py (the
stage machine and its thresholds) and prints:

  - the tactic x stage matrix (who may do what, where),
  - each tactic's gate (precondition) and cost (cooldown / weight),
  - a coverage report that flags thin or lopsided stages,
  - the PEACE stage-transition table.

The matrix, gates and costs are read straight from the code's own data
structures, so they cannot drift from it. The transition table mirrors
advance_stage() by hand - that logic is imperative, not data - but pulls its
numbers live from director's constants.

Read-only: no LLM, no database. Run from backend/:

    python scripts/engine_map.py
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import director as dr          # noqa: E402
from engine import tactics as tac          # noqa: E402
from engine.state import Stage             # noqa: E402

STAGES = list(Stage)
_SHORT = {Stage.ENGAGE: "ENG", Stage.FREE_RECALL: "FREE", Stage.PROBE: "PROBE",
          Stage.CHALLENGE: "CHAL", Stage.CLOSURE: "CLOS"}
_OWN = {"Reynolds": "R", "Chen": "C", tac.EITHER: "E"}
_DEFAULT_PRECOND = tac.Tactic.__dataclass_fields__["precondition"].default


def _first_stage(t):
    return min(STAGES.index(s) for s in t.stages)


def _ordered():
    return sorted(tac._ALL, key=lambda t: (_first_stage(t), -t.weight, t.id))


def _gate(t):
    """One-line description of a tactic's precondition, from the code itself."""
    fn = t.precondition
    if fn is _DEFAULT_PRECOND:
        return "always available"
    name = getattr(fn, "__name__", "")
    if name and name != "<lambda>":
        doc = (fn.__doc__ or "").strip().splitlines()
        return f"{name} - {doc[0].strip()}" if doc else name
    try:                                    # an inline lambda: show its source
        src = " ".join(inspect.getsource(fn).split())
        expr = src[src.index("lambda"):]
        return expr[:100].rstrip(", ")
    except (OSError, ValueError, TypeError):
        return "inline condition (see tactics.py)"


def print_matrix():
    print("\nTACTIC x STAGE   ( . = eligible, R/C/E = Reynolds/Chen/either )\n")
    head = (f"{'tactic':<24}{'own':<5}{'wt':>4}{'cd':>4}   "
            + "".join(f"{_SHORT[s]:^7}" for s in STAGES))
    print(head)
    print("-" * len(head))
    for t in _ordered():
        cells = "".join(("  .  " if s in t.stages else "").center(7) for s in STAGES)
        aside = " ~" if t.two_voices else ""
        print(f"{t.id:<24}{_OWN[t.owner]:<5}{t.weight:>4.1f}{t.cooldown:>4}   {cells}{aside}")
    print("\n  ~ = emits a two-voice aside, not a single line")
    print(f"  {len(tac._ALL)} tactics across {len(STAGES)} stages")


def print_gates():
    print("\n\nGATES   ( what has to be true for a tactic to be offered )\n")
    for t in _ordered():
        print(f"  {t.id:<24} {_gate(t)}")


def print_coverage():
    print("\n\nCOVERAGE   ( per stage, and what looks thin )\n")
    print(f"{'stage':<12}{'total':>6}{'Reynolds':>10}{'Chen':>6}{'ungated':>9}")
    print("-" * 43)
    flags = []
    for s in STAGES:
        here = [t for t in tac._ALL if s in t.stages]
        reyn = [t for t in here if t.owner in ("Reynolds", tac.EITHER)]
        chen = [t for t in here if t.owner in ("Chen", tac.EITHER)]
        ungated = [t for t in here if t.precondition is _DEFAULT_PRECOND]
        print(f"{_SHORT[s]:<12}{len(here):>6}{len(reyn):>10}{len(chen):>6}{len(ungated):>9}")
        if len(reyn) < 2:
            flags.append(f"{_SHORT[s]}: Reynolds has {len(reyn)} option(s) here")
        if len(chen) < 2:
            flags.append(f"{_SHORT[s]}: Chen has {len(chen)} option(s) here")
        if not ungated:
            flags.append(f"{_SHORT[s]}: every tactic is gated - a state that satisfies "
                         "none would leave the shortlist empty (the funnel_probe/"
                         "closure_summary fallback in dr.shortlist catches this)")
    homeless = [t.id for t in tac._ALL if not t.stages]
    if homeless:
        flags.append("eligible in NO stage: " + ", ".join(homeless))
    print("\nflags:")
    for f in flags or ["  (none)"]:
        print(f"  - {f}")


def print_transitions():
    print("\n\nSTAGE MACHINE   ( mirrors director.advance_stage; numbers are live )\n")
    rows = [
        ("ENGAGE", "FREE_RECALL", "turn >= 2"),
        ("FREE_RECALL", "PROBE", "the timeline has blocks, or turn >= 5"),
        ("PROBE", "CHALLENGE",
         "account complete AND (a contradiction exists OR >= 3 topics covered) "
         f"AND episodic detail is testable  --  OR  turn >= PROBE_PATIENCE ({dr.PROBE_PATIENCE})"),
        ("CHALLENGE", "CLOSURE",
         "(no open contradictions AND turn >= 14), or pressure >= 0.90, "
         f"or turn >= MAX_TURNS ({dr.MAX_TURNS})"),
        ("any non-terminal", "CLOSURE", f"backstop: turn >= MAX_TURNS ({dr.MAX_TURNS})"),
    ]
    for a, b, cond in rows:
        print(f"  {a:<17} -> {b:<12} when {cond}")


if __name__ == "__main__":
    print_matrix()
    print_gates()
    print_coverage()
    print_transitions()
    print()
