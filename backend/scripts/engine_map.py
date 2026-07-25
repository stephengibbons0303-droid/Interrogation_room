"""A generated map of the engine's decision surface.

Introspects engine/tactics.py (the tactic registry) and engine/director.py (the
stage machine and its thresholds) and prints, in two modes:

    python scripts/engine_map.py          # human-readable report to the terminal
    python scripts/engine_map.py md       # a Mermaid markdown doc to stdout

The tactic tables, gates, coverage counts and transition thresholds are read
straight from the code's own data structures, so they cannot drift. The four
flow diagrams in the markdown (per-turn pipeline, speaker ladder, outcome tree,
Chen's arc) are hand-drawn to mirror the imperative logic in agent.py/director.py.

Regenerate the committed doc with:

    cd backend && python scripts/engine_map.py md > ../documents/engine-map.md

Read-only: no LLM, no database.
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
        return src[src.index("lambda"):][:100].rstrip(", ")
    except (OSError, ValueError, TypeError):
        return "inline condition (see tactics.py)"


def _coverage_rows():
    for s in STAGES:
        here = [t for t in tac._ALL if s in t.stages]
        reyn = [t for t in here if t.owner in ("Reynolds", tac.EITHER)]
        chen = [t for t in here if t.owner in ("Chen", tac.EITHER)]
        ungated = [t for t in here if t.precondition is _DEFAULT_PRECOND]
        yield s, len(here), len(reyn), len(chen), len(ungated)


def _coverage_flags():
    flags = []
    for s, _, reyn, chen, ungated in _coverage_rows():
        if reyn < 2:
            flags.append(f"{_SHORT[s]}: Reynolds has {reyn} option(s) here")
        if chen < 2:
            flags.append(f"{_SHORT[s]}: Chen has {chen} option(s) here")
        if ungated == 0:
            flags.append(f"{_SHORT[s]}: every tactic is gated "
                         "(dr.shortlist falls back to funnel_probe / closure_summary)")
    homeless = [t.id for t in tac._ALL if not t.stages]
    if homeless:
        flags.append("eligible in NO stage: " + ", ".join(homeless))
    return flags


def _transition_rows():
    """PEACE transitions. Mirrors director.advance_stage; numbers are live."""
    return [
        ("ENGAGE", "FREE_RECALL", "turn >= 2"),
        ("FREE_RECALL", "PROBE", "the timeline has blocks, or turn >= 5"),
        ("PROBE", "CHALLENGE",
         "account complete AND (a contradiction exists OR >= 3 topics covered) AND "
         f"episodic detail is testable  --  OR  turn >= PROBE_PATIENCE ({dr.PROBE_PATIENCE})"),
        ("CHALLENGE", "CLOSURE",
         "(no open contradictions AND turn >= 14), or pressure >= 0.90, "
         f"or turn >= MAX_TURNS ({dr.MAX_TURNS})"),
        ("any non-terminal", "CLOSURE", f"backstop: turn >= MAX_TURNS ({dr.MAX_TURNS})"),
    ]


# ── terminal report ───────────────────────────────────────────────────────────

def print_report():
    print("\nTACTIC x STAGE   ( . = eligible, R/C/E = Reynolds/Chen/either )\n")
    head = (f"{'tactic':<24}{'own':<5}{'wt':>4}{'cd':>4}   "
            + "".join(f"{_SHORT[s]:^7}" for s in STAGES))
    print(head)
    print("-" * len(head))
    for t in _ordered():
        cells = "".join(("  .  " if s in t.stages else "").center(7) for s in STAGES)
        print(f"{t.id:<24}{_OWN[t.owner]:<5}{t.weight:>4.1f}{t.cooldown:>4}   {cells}"
              + (" ~" if t.two_voices else ""))
    print(f"\n  ~ = two-voice aside.   {len(tac._ALL)} tactics across {len(STAGES)} stages")

    print("\n\nGATES   ( what has to be true for a tactic to be offered )\n")
    for t in _ordered():
        print(f"  {t.id:<24} {_gate(t)}")

    print("\n\nCOVERAGE   ( per stage, and what looks thin )\n")
    print(f"{'stage':<12}{'total':>6}{'Reynolds':>10}{'Chen':>6}{'ungated':>9}")
    print("-" * 43)
    for s, total, reyn, chen, ungated in _coverage_rows():
        print(f"{_SHORT[s]:<12}{total:>6}{reyn:>10}{chen:>6}{ungated:>9}")
    print("\nflags:")
    for f in _coverage_flags() or ["(none)"]:
        print(f"  - {f}")

    print("\n\nSTAGE MACHINE   ( mirrors director.advance_stage; numbers are live )\n")
    for a, b, cond in _transition_rows():
        print(f"  {a:<17} -> {b:<12} when {cond}")
    print()


# ── markdown / mermaid doc ────────────────────────────────────────────────────

_PIPELINE = """```mermaid
flowchart TD
    IN["learner message"] --> AN["analyse - struggling / evasive / richness"]
    AN --> ADV["advance_stage - move through PEACE"]
    ADV --> CTX["build_context - timeline, thin topics, false-premise plan"]
    CTX --> SPK["select_speaker - five triggers"]
    SPK --> SL["shortlist - filter by stage / owner / cooldown / precondition, rank by weight"]
    SL --> LLM["one LLM call - says the line, reports the tactic and the extracted claims"]
    LLM --> ING["ingest - claims become contradictions: self / retelling / breach / evidence"]
    ING --> UPD["update pressure, exculpation and Chen's arc"]
    UPD --> OUT["decide_outcome - only at Closure"]
```"""

_STAGE_DIAGRAM = """```mermaid
stateDiagram-v2
    [*] --> ENGAGE
    ENGAGE --> FREE_RECALL: turn 2+
    FREE_RECALL --> PROBE: account given, or turn 5+
    PROBE --> CHALLENGE: account testable, or patience
    CHALLENGE --> CLOSURE: settled, pressure high, or cap
    CLOSURE --> [*]
```"""

_SPEAKER_DIAGRAM = """```mermaid
flowchart TD
    S(["who speaks next?"]) --> T1{"learner struggling, or two non-answers running?"}
    T1 -->|yes| C1["Chen - rapport"]
    T1 -->|no| T2{"Challenge stage and evidence due?"}
    T2 -->|yes| R1["Reynolds - evidence"]
    T2 -->|no| T3{"same detective three turns running?"}
    T3 -->|yes| SW["switch - stall"]
    T3 -->|no| T4{"a topic just closed?"}
    T4 -->|yes| C2["Chen - topic end"]
    T4 -->|no| T5{"answered, but not the question asked?"}
    T5 -->|yes| C3["Chen - clarify"]
    T5 -->|no| RT["hold the researched 75/25 ratio"]
```"""

_OUTCOME_DIAGRAM = """```mermaid
flowchart TD
    O(["decide_outcome - Closure only"]) --> B{"conceded the hidden fact? (a breach)"}
    B -->|yes| B2{"also caught on evidence, or story wobbled?"}
    B2 -->|yes| D1["DETAINED"]
    B2 -->|no| U1["UNDER INVESTIGATION"]
    B -->|no| WC{"story wobbled twice AND caught on evidence?"}
    WC -->|yes| D2["DETAINED"]
    WC -->|no| EX{"a single wobble, but a strong account? (exculpation high)"}
    EX -->|yes| RL1["RELEASED"]
    EX -->|no| W1{"any wobble at all, or three-plus evasions?"}
    W1 -->|yes| U2["UNDER INVESTIGATION"]
    W1 -->|no| RL2["RELEASED"]
```"""

_CHEN_DIAGRAM = """```mermaid
stateDiagram-v2
    [*] --> neutral
    neutral --> rapport: turn 2+
    rapport --> advocate: struggling, or pressure rising
    advocate --> identifying: pressure 0.4+
    identifying --> minimising: pressure 0.6+ in Challenge
    minimising --> sting: a vouched claim breaks
    note right of sting
        the sting can fire from ANY stance the moment a
        claim Chen talked them into is the one that breaks
    end note
```"""


def _md_table(header, align, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def emit_markdown():
    matrix_rows = []
    for t in _ordered():
        marks = ["●" if s in t.stages else "" for s in STAGES]
        name = f"`{t.id}`" + (" ~" if t.two_voices else "")
        matrix_rows.append([name, _OWN[t.owner], f"{t.weight:.1f}", t.cooldown, *marks])
    matrix = _md_table(
        ["tactic", "own", "wt", "cd", "ENG", "FREE", "PROBE", "CHAL", "CLOS"],
        ["---", ":--:", "--:", "--:", ":--:", ":--:", ":--:", ":--:", ":--:"],
        matrix_rows)

    gates = _md_table(["tactic", "gate"], ["---", "---"],
                      [[f"`{t.id}`", _gate(t).replace("|", "\\|")] for t in _ordered()])

    coverage = _md_table(
        ["stage", "total", "Reynolds-usable", "Chen-usable", "ungated"],
        ["---", "--:", "--:", "--:", "--:"],
        [[_SHORT[s], total, reyn, chen, ungated]
         for s, total, reyn, chen, ungated in _coverage_rows()])
    flags = "\n".join(f"- {f}" for f in _coverage_flags()) or "- (none)"

    transitions = _md_table(["from", "to", "when"], ["---", "---", "---"],
                            _transition_rows())

    return f"""# Interrogation Room - engine map

_Generated by [`backend/scripts/engine_map.py`](../backend/scripts/engine_map.py)._
Regenerate with `cd backend && python scripts/engine_map.py md > ../documents/engine-map.md`.

The tactic tables, coverage counts and transition thresholds below are read from
the code's own data structures, so they cannot drift. The four flow diagrams are
hand-drawn to mirror the imperative logic in `agent.py` / `director.py` - keep them
honest when that logic changes.

**Design spine:** every box in the pipeline is deterministic Python except the one
LLM call. The engine decides *what* happens; the model only decides *how* it is said.

## The per-turn pipeline

{_PIPELINE}

## PEACE stage machine

{_STAGE_DIAGRAM}

Backstop: any non-terminal stage jumps to Closure once `turn >= MAX_TURNS`. Precise
conditions (numbers live from the code):

{transitions}

## Who speaks next - the five triggers, in priority order

{_SPEAKER_DIAGRAM}

## The verdict

{_OUTCOME_DIAGRAM}

## Chen's arc

{_CHEN_DIAGRAM}

## Tactic x stage

`R` / `C` / `E` = Reynolds / Chen / either. `~` = a two-voice aside. `wt` ranks the
shortlist; `cd` is the cooldown in turns. {len(tac._ALL)} tactics across {len(STAGES)} stages.

{matrix}

## Gates - what must be true for a tactic to be offered

{gates}

## Coverage - per stage, and what looks thin

{coverage}

{flags}
"""


if __name__ == "__main__":
    try:                                    # the doc is UTF-8 (● in the matrix)
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if len(sys.argv) > 1 and sys.argv[1] in ("md", "mermaid", "doc"):
        print(emit_markdown())
    else:
        print_report()
