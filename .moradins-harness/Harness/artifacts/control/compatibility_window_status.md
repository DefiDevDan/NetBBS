---
title: "Moradin Forge Compatibility Window"
status: public-contract
owner: moradin-forge
---

# Moradin Forge Compatibility Window

- `canonical_payload`: `Harness/moradin_payload/manifest.yaml`
- `sidecar_default_dir`: `.moradins-harness`
- `legacy_aliases_enabled`: true
- `compatibility_scope`: legacy aliases are sanitizer-only compatibility
  history; first-read docs use Moradin payload names.
- `removal_gate`: one public compatibility window after downstream users have
  moved to Moradin payload commands.
