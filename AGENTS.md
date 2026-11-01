# Repository agent instructions

- Read `docs/development-handoff.md` before changing code, tests, or acceptance documentation. It
  is the active cross-machine findings list and defines which checks require Blender.
- Treat contributor and Blender acceptance runner as capability roles, not machine identities. A
  green Python suite does not close a Blender-dependent finding.
- Keep local parcel data private. Never commit or quote real listing links, addresses, parcel
  identifiers, coordinates, local paths or usernames, private GIS extracts, or location-revealing
  outputs. Use repository-relative paths, placeholders, and synthetic fixtures.
- Inspect the complete diff and exact staged file list before committing. Do not force-add ignored
  parcel data or generated artifacts.
- Do not commit or push unless the current task explicitly requests it.
