# O2D-R051N1 — Generic Cortex Protocol / HTTP / RPC Authorities

## Purpose

Normalize the lowest dependency roots of the standalone Cortex product before
moving higher-level agent, tools, provider, desktop and context responsibilities.

## New canonical crates

- `cortex_protocol`
- `cortex_http`
- `cortex_rpc`

These are project-agnostic and are now the canonical wire/transport authorities.

## Compatibility policy

The historical crates remain in the workspace temporarily:

- `open2d_cortex_protocol`
- `open2d_cortex_http`
- `open2d_cortex_rpc`

Each is now a thin re-export facade only. They own no protocol or transport
implementation. New code must not depend on them.

## Consumer migration

All current consumers of these three old roots are moved to the generic crates,
including transitional Open2D-named Cortex components. This deliberately avoids
creating two separate `RpcRequest`, provider-trait, tool-definition, image or
RPC type systems during the remaining normalization passes.

The significant generic edges improve immediately:

```text
cortex_client
  old: open2d_cortex_protocol + open2d_cortex_rpc
  new: cortex_protocol + cortex_rpc

cortex_cli
  old wire deps: open2d_cortex_protocol + open2d_cortex_rpc
  new wire deps: cortex_protocol + cortex_rpc

cortex_vault
  old wire dep: open2d_cortex_protocol
  new wire dep: cortex_protocol
```

Transitional providers, tools, capture, image and agent core also consume the
generic protocol/HTTP/RPC roots now, even though those higher crates keep their
historical names until their assigned normalization passes.

## Dependency direction after R051N1

```text
cortex_protocol
      ↑
cortex_rpc

cortex_http

providers/core/tools/client/CLI/Vault/etc.
      ↓
generic protocol/http/rpc only

open2d_cortex_protocol/http/rpc
      ↓
thin compatibility re-export facades
```

## Certification

Expected workspace closure increases from 54 to 57 members because the three
generic authorities coexist temporarily with their compatibility facades.

Cortex tool count remains 47.

The project-wide checkpoint must remain green before R051N2 begins.
