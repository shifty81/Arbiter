# CTX-AI-PCC-01R1 - Universal Python PCC Vertical Slice

Baseline: `1da29f61aa2a60839071aab57279cf7931920582` (FULL GREEN).

## Scope

This pass lands the smallest end-to-end Project Control Center provider that Cortex can call safely without replacing the proven Root Project Control Center.

- `tools/pcc`: zero-required-dependency Python 3.11+ provider.
- `cortex_pcc`: typed Rust JSON bridge into the Python provider.
- `cortex_tools`: PCC status/catalog/doctor/archive-audit/gate/exact-command tools.
- `cortex_permissions`: PCC read vs process-execution defaults.
- `project.control.json`: remains the single command/gate authority and retains `fmt.apply` outside all gates.
- Root patch/update application remains owned by hardened Cortex Root intake.

## Deliberate deferrals

The previous CTX-AI-PCC-01 draft bundled provider transport refactors and Python patch intake. Both are deferred:

1. LM Studio / Native Models are not changed here. Shared transport and provider migration belong to `CTX-PROVIDER-01` with explicit parity tests.
2. Python PCC does not apply root patches yet. Transactional patch authority belongs to `CTX-PCC-03` after Plan -> Validate -> Apply -> Verify -> Recover parity is certified.

## Security/authority rules

- Model-facing PCC execution accepts a registered command **key**, never arbitrary argv.
- Mutating command metadata is re-authorized through Cortex permissions.
- Gates reject source/external mutation.
- Archive audit is project-relative, read-only, streaming-hashed, and bounded.
- `python -B` is used for PCC self-tests/wrapper execution to avoid generated `__pycache__` source-tree noise.

## Validation

R1 adds standard-library Python unit tests for status, exact command execution, mutation refusal, gate refusal, archive parity, and path containment. The normal Cortex Full Quality Gate remains the final Windows authority after root intake.
