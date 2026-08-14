# Moradin Forge Integration

- generated_at: `2026-07-30T06:08:10+00:00`
- target_repo: `C:<local-path>`
- copied_file_count: `286`
- adapter_status: `patched`
- install_request: `none`

## Changed Paths

- `.moradins-harness/`
- `AGENTS.md`

## Validation

- `.moradins-harness/scripts/moradin_forge.sh verify --target .`
- `Run the target repo's existing deterministic test or verify command.`

## Rollback

- Run `.moradins-harness/scripts/moradin_forge.sh rollback --target . --approve`.
- Rollback refuses modified or unowned managed content.
- No host install commands were executed by Moradin.
