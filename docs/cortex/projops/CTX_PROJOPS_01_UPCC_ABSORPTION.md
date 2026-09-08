# CTX-PROJOPS-01 — UPCC Donor Absorption

## Objective

Use UPCC v0.6.3/B003R3 as immutable design/implementation evidence and create a strict ownership map before writing Cortex Project Operations code.

## Why this is required

The donor contains hardened behavior proven by whole-drive discovery failures and subsequent fixes: pre-queue pruning, project ownership boundaries, scan budgets, stable project state, worktree enumeration, plan/state APIs, patch transaction hardening, evidence generation, and quality-gate history.

Blindly copying its implementation into Cortex would violate the standalone architecture because PCC remains the project-operations authority. The correct migration technique is:

```text
Donor evidence
   -> classify capability ownership
   -> extract behavioral contract
   -> implement only Cortex-owned generic authority
   -> bind PCC-owned operations through a typed client
   -> verify parity with fixtures/contract tests
```

## Acceptance criteria

CTX-PROJOPS-01 is complete when:

- `migration/upcc_v0_6_3` exists and is explicitly evidence-only.
- Actual B003R3 donor source can be imported without changing source files.
- Every imported file receives a SHA-256 entry.
- Donor release identity is pinned and reviewable.
- Feature-parity matrix assigns each capability to one authority.
- No donor implementation becomes an active Cortex runtime dependency.
- CTX-PROJOPS-02..08 have concrete port/delegation inputs.

## Current boundary

The physical 0.6.3/B003R3 rollup is not contained in the standalone-separation architecture handoff. Until the actual rollup is imported, this pass is **scaffold complete / evidence import pending** rather than falsely claiming donor-source parity.
