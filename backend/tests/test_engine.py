"""Engine unit tests. No LLM, no network, no database.

Run:  backend/.venv/Scripts/python.exe backend/tests/test_engine.py

Deliberately dependency-free - the project has no test framework yet and this
should not be the change that introduces one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import timeline as tl                       # noqa: E402
from engine.analysis import analyse                     # noqa: E402
from engine.state import Claim                          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{'' if cond else '  <- ' + detail}")


def block(cid, start_h, start_m, end_h, end_m, loc, text="", seq=1):
    return Claim(id=cid, turn_seq=seq, text=text or cid,
                 start_min=start_h * 60 + start_m, end_min=end_h * 60 + end_m,
                 location=loc)


print("\nTIMELINE VALIDATOR")

# Full account, no problems.
r = tl.build([block("a", 17, 0, 20, 0, "cafe"),
              block("b", 20, 0, 20, 45, "station"),
              block("c", 20, 45, 23, 59, "home")])
check("full account has no gaps", not r.gaps, f"gaps={[g.describe() for g in r.gaps]}")
check("full account is 'complete'", r.complete, f"coverage={r.coverage:.2f}")
check("coverage is ~100%", r.coverage > 0.99, f"{r.coverage:.3f}")

# A hole in the middle.
r = tl.build([block("a", 17, 0, 20, 0, "cafe"),
              block("c", 22, 0, 23, 59, "home")])
check("detects the 20:00-22:00 hole", len(r.gaps) == 1 and r.gaps[0].minutes == 120,
      str([g.describe() for g in r.gaps]))

# Two places at once.
r = tl.build([block("a", 20, 0, 22, 0, "cafe"),
              block("b", 21, 0, 22, 30, "bridge")])
check("detects being in two places at once", len(r.overlaps) == 1,
      str([o.describe() for o in r.overlaps]))

# Cafe -> bridge is 25 minutes on foot; only 5 claimed.
r = tl.build([block("a", 20, 0, 21, 0, "cafe"),
              block("b", 21, 5, 22, 0, "bridge")])
check("detects an impossible journey", len(r.impossible) == 1,
      str([m.describe() for m in r.impossible]))

# Same journey with enough time is fine.
r = tl.build([block("a", 20, 0, 21, 0, "cafe"),
              block("b", 21, 30, 22, 0, "bridge")])
check("allows the journey when time permits", not r.impossible)

# The gate that reverse chronology depends on.
r = tl.build([])
check("empty timeline is NOT complete", not r.complete)
r = tl.build([block("a", 17, 0, 18, 0, "cafe")])
check("one thin block is NOT complete", not r.complete, f"coverage={r.coverage:.2f}")

# Superseded claims drop out.
old = block("old", 17, 0, 20, 0, "cafe")
old.superseded_by = "new"
r = tl.build([old, block("new", 17, 0, 21, 0, "cafe")])
check("superseded claims are excluded", len(r.blocks) == 1 and r.blocks[0].id == "new")


print("\nSTATEMENT ANALYSIS  (language must never raise pressure)")

a = analyse("At the cafe.", responsive=True)
check("short BUT responsive is not evasive", not a.evasive, f"words={a.words}")

a = analyse("Sorry, I don't understand.", responsive=False)
check("struggling learner is not evasive", not a.evasive and a.struggling)

a = analyse("How do you say... the place with the coffee?", responsive=False)
check("reaching for a word is not evasive", not a.evasive and a.struggling)

a = analyse("Maybe.", responsive=False)
check("very short + hedged reads as struggling", not a.evasive and a.struggling)

a = analyse("I'm not answering that.", responsive=False)
check("explicit refusal IS evasive", a.evasive and a.refusal)

a = analyse("Anyway, the weather that week was unusual for the season.", responsive=False)
check("fluent deflection IS evasive", a.evasive, "long, fluent, not addressing the question")

a = analyse("I walked home.", responsive=True)
check("responsive answer is never evasive regardless of length", not a.evasive)

# Hedging and self-correction are CBCA truthfulness markers, not suspicion.
plain = analyse("I went home.", responsive=True)
rich = analyse("I left about eight, no wait, half eight. It was cold and the "
               "bridge was noisy. I think I got home around nine.", responsive=True)
check("hedges/corrections counted as truthful detail", rich.hedges > 0 and rich.corrections > 0)
check("richer account scores higher", rich.richness > plain.richness,
      f"{rich.richness} vs {plain.richness}")
check("richness never negative for hedging", analyse("Maybe about nine, I think.").richness > 0)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
