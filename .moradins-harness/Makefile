.PHONY: test payload-validate payload-smoke forge-explain forge-readiness forge-plan forge-adopt forge-verify forge-rollback forge-smoke

TARGET ?=
APPROVE ?=
OVERWRITE ?=
PATCH_AGENTS ?=

test:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run pytest

payload-validate:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/manage_moradin_payload.py validate

payload-smoke:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/manage_moradin_payload.py smoke-test

forge-explain:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py explain

forge-readiness:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py readiness

forge-plan:
	@if [ -z "$(TARGET)" ]; then echo "Usage: make forge-plan TARGET=<repo-path>"; exit 1; fi
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py plan --target "$(TARGET)" --write-install-request

forge-adopt:
	@if [ -z "$(TARGET)" ] || [ "$(APPROVE)" != "1" ]; then echo "Usage: make forge-adopt TARGET=<repo-path> APPROVE=1"; exit 1; fi
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py apply --target "$(TARGET)" --approve $(if $(OVERWRITE),--overwrite-sidecar,) $(if $(PATCH_AGENTS),--patch-agents,) --write-install-request

forge-verify:
	@if [ -z "$(TARGET)" ]; then echo "Usage: make forge-verify TARGET=<repo-path>"; exit 1; fi
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py verify --target "$(TARGET)"

forge-rollback:
	@if [ -z "$(TARGET)" ] || [ "$(APPROVE)" != "1" ]; then echo "Usage: make forge-rollback TARGET=<repo-path> APPROVE=1"; exit 1; fi
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/moradin_forge.py rollback --target "$(TARGET)" --approve

forge-smoke:
	PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/public_export.py sidecar-smoke --output /tmp/moradin-forge-sidecar-smoke-check --force
