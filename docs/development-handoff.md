# Development and Blender acceptance handoff

This is the tracked handoff between contributors who can change and unit-test the code anywhere
and the acceptance runner that has Blender, BlenderGIS, and a local parcel fixture. The product
plan remains in [roadmap.md](roadmap.md); this file records cross-machine responsibilities and
open findings that need both code work and real-environment verification.

These are capability roles, not particular people or machine identities.

Keep this document public-safe. Describe behavior with repository-relative paths, synthetic test
data, and placeholders. Never add real property data such as listing URLs, street addresses,
parcel identifiers, or projected coordinates. Also omit local usernames and absolute paths,
private parcel filenames, and tool/session transcripts. The `parcels/` ignore rule prevents
ordinary Git adds, but it is not a privacy boundary.

## Roles

### Contributor

The contributor does not need Blender or a real parcel. For one open finding at a time:

1. Fetch and fast-forward to the current branch; start from a clean worktree.
2. Reproduce the code-level cause with synthetic inputs where possible.
3. Make the smallest scoped fix and add a regression test under `tests/`.
4. Run `python -m unittest discover -s tests -v` and let CI exercise its Python matrix.
5. Commit only when the task authorizes it. When publication is explicitly authorized, push the
   change and hand off the exact commit hash, changed files, test results, and the real-environment
   checks still required. Unit tests do not close a Blender acceptance item.

### Blender acceptance runner

The acceptance runner validates the handed-off commit without publishing its parcel fixture:

1. Fetch, check out the exact commit in a clean or disposable workspace, and confirm the hash.
2. Run the unit tests, then the real workflow:

   ```bat
   python templates\doctor.py parcels\<parcel>
   templates\run_all.bat parcels\<parcel>
   ```

3. Reopen every generated `.blend`; confirm relative image assets resolve and no unexpected
   external libraries are linked.
4. Inspect `[CHECK]` output, current-versus-previous stats, expected output names, and every render.
5. Run any finding-specific geometry probe below. Report bounded, non-identifying evidence such as
   counts, synthetic cases, and sanitized errors; keep parcel identifiers, coordinates, source
   files, and location-revealing images local.
6. Mark an item accepted only after both its engineering and Blender criteria pass. Record the
   tested commit and Blender version in the public result.

## Findings

The findings were rechecked from base revision `21c550f`. Statuses include the changes in this
update. Acceptance described as local used a private fixture without publishing it; repeat those
checks at the published commit before treating a cross-machine handoff as final.

### CD-001: the visible ribbon and graded footprint diverge at mitered turns

Status: **Open -- engineering fix required, then Blender acceptance.**

`templates/design_geom.py` creates mitered left and right ribbon edges, and
`templates/place_masses.py` uses those edges for the visible drive mesh. Terrain grading instead
selects points by distance from each centerline segment. At an outside miter, part of the visible
ribbon can therefore extend beyond the fully graded footprint.

Engineering acceptance:

- Drive the visible mesh and terrain mask from one ribbon-footprint definition, including capped
  sharp turns and the actual ribbon ends.
- Add synthetic straight, right-angle, and sharp-turn tests that prove the entire visible footprint
  is included in the fully graded region and the blend region begins outside it.
- Preserve the existing grade-line and miter-limit behavior.

Blender acceptance:

- On generated straight and turning drives, sample the terrain beneath every ribbon edge and turn
  vertex. Compare the terrain with the sampled ribbon underside after subtracting `DRIVE_LIFT`,
  using a documented tolerance appropriate to the DEM mesh resolution.
- Inspect the turn from above and at a low angle for floating or buried corners.

### CD-002: design filenames do not guarantee distinct output names

Status: **Engineering complete; local Blender acceptance passed; repeat at the published commit.**

Output stems come from the design JSON's `name`, not its filename. Copying and renaming a JSON file
does not change that internal name. The Milestone 2 instructions now call this out explicitly, but
two design files with the same internal name can still overwrite the same `.blend`, renders,
stats, and previous-stats file.

Engineering acceptance:

- Keep copy workflows explicit about changing the internal output name.
- Have `doctor.py` reject duplicate output names across the design files it validates.
- Add tests proving `doctor.py` accepts distinct names and rejects duplicate names during preflight,
  before `run_all.bat` is launched. If filename/name agreement becomes a rule, document and test it
  explicitly.

Blender acceptance:

- Run at least two designs in one parcel folder and confirm each keeps its own `.blend`, complete
  render set, current stats, and previous stats after a rerun.

Local acceptance on 2026-11-22 used two designs with distinct internal names. Each retained a
separate `.blend`, four renders, current stats, and previous stats after a rerun. The site and both
design scenes reopened headlessly with every file image relative and resolvable and with no linked
libraries. Synthetic tests also pin case-insensitive duplicate rejection through explicit-file and
parcel-folder preflight paths.

### CD-003: `doctor.py` runtime-precondition parity

Status: **Engineering complete; local workflow smoke passed; repeat at the published commit.**

Gaps in the base revision:

- Vegetation bounds are compared only when both `min_h` and `max_h` are explicit; runtime defaults
  can still make the effective minimum exceed the effective maximum.
- A drive-only design can pass design validation even though placement requires at least one house
  or terrace.
- Several dimensions and placement values are type-checked without rejecting non-finite values;
  physical dimensions also lack appropriate bounds.
- Route validation catches exact consecutive duplicates but not all near-zero or reversing
  segments that can create invalid ribbon faces.

Engineering acceptance:

- Validate the effective configuration after defaults are applied.
- Reject designs with no mass or non-finite numeric values. Apply appropriate positive or bounded
  rules to physical dimensions while continuing to allow signed positions and angles, and reject
  route geometry that cannot form a valid ribbon.
- Add one focused test per rejected case and retain valid straight, turning, and stepped examples.

Blender acceptance:

- Confirm `doctor.py` rejects each bad synthetic design and `run_all.bat` is not launched after a
  failed preflight. (`doctor.py` may still perform its own Blender capability probe.)
- Run one valid design through `run_all.bat` to ensure the stricter validator did not reject the
  supported workflow.

The validator now applies vegetation defaults before comparing bounds; requires a house or
terrace; rejects non-finite values, non-positive physical dimensions, non-string IDs, and route
geometry that cannot form a simple ribbon; and continues to allow signed positions and angles plus
separated switchbacks. Local preflight passed 14 checks with no failures, and one supported design
completed an isolated `run_all.bat --no-render` workflow with three steps and no failed checks. The
second local design still reports its already-known over-grade hand-drawn paths; it produced a
complete output set and is not counted as a pipeline regression. All 11 fresh renders were
inspected; some eye-level framing remains later render polish.

### CD-004: design-validator process and cleanup coverage

Status: **Resolved in this update.**

In the base revision, the design-validator tests inspected a selected stdout line but did not
assert the subprocess return code or include stderr when they failed. Their temporary directories
also outlived normal test runs. The acceptance target was a pure validation function or design-only
mode, managed temporary directories, explicit process semantics, and failures that show stdout and
stderr without printing private environment data.

`doctor.py --design-only` now gives design validation independent process semantics. The tests use
managed temporary directories, assert exit code plus stdout and stderr, cover multiple explicit
files and ordinary parcel-folder discovery, and leave no test directories after normal runs. The
70-test suite passes on Python 3.8, 3.10, 3.11, and 3.13.

## Already resolved; do not reopen without contrary evidence

- Blender 5.x physical-sky enum compatibility, sun azimuth, arid vegetation filtering, and linear
  shader colors were fixed and verified in Blender 5.1.1. See the Milestone 2 record in
  [roadmap.md](roadmap.md#milestone-2----a-steep-lot-compound-you-could-pitch).
- A sample route exceeding its configured grade limit is a layout finding, not by itself a pipeline
  defect. Grade-aware access and automatic routing are Milestone 3 work.

## Handoff report

Use this compact report in either direction:

```text
Revision: <full commit hash>
Role: contributor | Blender acceptance runner
Finding: <CD-nnn>
Checks run: <commands or bounded description>
Result: PASS | FAIL | BLOCKED
Public evidence: <synthetic case, aggregate counts, Blender/Python versions>
Still required: <next role and exact acceptance check>
```

Before committing a handoff update, inspect `git status --short`, the complete diff, and the exact
staged file list. Do not force-add ignored parcel data or generated artifacts.
