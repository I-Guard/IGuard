# Sample recovery policy

Policies are YAML allowlists loaded from `recovery/policies/`. There is no way to run arbitrary
commands: `action_type` is one of the supported types, `target` must match a known container or a
script in `recovery/scripts/`, critical targets (databases etc.) are rejected, and anything marked
`sensitive` is never automatic. Validate with `make validate-config`.
