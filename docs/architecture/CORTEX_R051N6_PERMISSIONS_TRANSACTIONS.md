# O2D-R051N6 — Permissions + Transactions

Permissions are canonical in `cortex_permissions`; plugin discovery re-exports them only for compatibility. Reversible source writes are canonical in `cortex_transactions`; `cortex_workspace` no longer owns transaction implementation.
