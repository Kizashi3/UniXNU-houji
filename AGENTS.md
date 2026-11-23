# Repository instructions

- Commit messages must follow `@commitlint/config-conventional`.
- Active implementation and pinned dependencies are described in `docs/architecture.md` and `sources.lock.json`. `archive/` is historical reference.
- Do not commit operating system images, vendor firmware bytes, SDKs, KDKs, partition backups, generated binaries, or personal device identifiers.
- Keep hardware claims tied to actual evidence. Host policy tests do not emulate the GPU or establish desktop frame rate.
- After staging intended source changes, update `source-manifest.json` with `python3 tools/update-source-manifest.py` and run the public source and host checks.
