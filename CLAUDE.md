# Interrogation_room

## Local ports - shared machine-wide register

This machine runs several local projects side by side. Before starting any local dev or
preview server, consult the machine-wide port register at `~/.claude/PORTS.md`, take a free
port in the correct band, and append your allocation there. Never reuse a port the register
lists as taken.

Ports reserved for this repo: **backend 8013, frontend 5185** (reserved pair, provisional -
reclaim the half not used). See `~/.claude/PORTS.md` for the full map (bands: frontends
5173-5199, backends 8000-8099, speech 7650-7699).

## Pre-merge review gate

Before fast-forwarding or merging a branch into `main` - or before calling a
substantial chunk of work done, if it was committed straight to `main` - run the
cleanup gate, so quality rides along with the feature instead of accumulating as
debt:

- **`/code-review`** on the diff - correctness bugs plus reuse / simplification /
  efficiency findings.
- **`/simplify`** - applies reuse / simplification / efficiency / altitude
  cleanups to the changed code.

**What to review:** the branch diff (`git diff main...HEAD`), or - for work
committed directly to `main` - the accumulated range since the last review
(`git diff <base>..HEAD`), not a single commit. One review over the finished
whole beats several over tiny slices, and `/code-review` can spin up multiple
agents, so run it ONCE at the end of a chunk rather than per commit.

**Claude must prompt before performing any merge to `main`.** When asked to merge
(or to push-on-merge), first surface "run `/code-review` + `/simplify` on the diff
first?" and wait for the go-ahead - do not merge silently. Both are user-triggered
skills, so Claude cannot run them itself; its job is to *prompt*, then fold
confirmed findings into the change or, when a finding is not worth fixing inline,
record it in `TECH_DEBT.md` at the repo root (create the file if it does not exist).

The gate is **advisory, not blocking** - waive it for a trivial or doc-only merge.
But the default is to offer it every time, and it is a *reminder*, not an
enforcement mechanism: nothing stops a merge made outside a Claude session, so it
only helps if Claude is the one doing the merge.
