# Cortex Native Models — C3–C7 Consolidated Authority

Cortex Native Models is the default local inference authority. LM Studio remains an optional compatibility provider only.

## Runtime ownership

`cortex_desktop.exe` owns both `cortex.exe service run` and `cortex_model_host.exe`. The model host owns its `llama-server.exe` child. The RPC service and model host watch the Desktop PID and exit when that owner disappears. Clean shutdown additionally stops the llama child first. No Cortex inference/service daemon is intended to survive after Desktop closes.

## GGUF model library

The primary model root is `<Cortex Library>/Models`, normally `D:\Cortex\Models`, with role folders for Chat, Coding, Reasoning, Vision, Embeddings and Imported. Existing GGUF files in standard/configured LM Studio folders are discovered in place and are not copied.

## llama.cpp router

Cortex uses a pinned, SHA-256 verified Windows Vulkan llama.cpp runtime and launches `llama-server` in router mode with a generated INI preset. Router autoload is used; `native_models_max` limits simultaneous loaded models.

## Provider router

`cortex_provider_router::CortexProvider` selects either Cortex Native Models or LM Studio compatibility. Chat, structured tools, vision, Vault embeddings and observability embeddings use the same provider abstraction.

## Compatibility recovery

If the user explicitly selects LM Studio and it is offline, Cortex attempts headless `lms server start --port <port> --bind 127.0.0.1`, then re-probes. Failure returns to the normal provider-recovery state.

## Certification

The normal Cortex checkpoint forces `CORTEX_PROVIDER=native` for live certification. It builds the model-host binary if necessary and runs the same streamed chat/persistence/reopen test used previously for LM Studio. After certification it verifies that no owned model-host/llama runtime remains.

## Third-party runtime and model licensing

The managed llama.cpp runtime is a third-party MIT-licensed component pinned by release and SHA-256. The incremental Open2D handoff does not embed the large runtime archive; Cortex downloads and verifies that pinned Windows runtime on first native-model use. A future Windows installer may prebundle the same verified runtime for offline installation.

GGUF model files remain user/content-library assets with their own licenses. Cortex records/discovers them but does not assume redistribution rights from the GGUF format itself.
