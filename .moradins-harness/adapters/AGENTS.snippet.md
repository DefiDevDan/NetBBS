<!-- moradin-forge:start -->
## Moradin's Forge

- Local sidecar: `.moradins-harness/`
- Agent entrypoint: `.moradins-harness/FORGE.md`
- Harness entrypoint: `.moradins-harness/Harness/entrypoints/forge.md`
- Keep Moradin local unless the user explicitly requests external tooling.
- Treat host tool installation as request-only: write install requests, do not run installs.
- Preserve existing repo workflows and prefer repo-local deterministic commands.
<!-- moradin-forge:end -->
