# Cortex AI Runtime — LM Studio Parity + Web + Image

## Product direction

Cortex Native Models is the default local AI runtime. LM Studio and ComfyUI remain optional
compatibility/import sources, not required dependencies.

## LM Studio parity targets

| Capability | Cortex authority |
|---|---|
| Local model library | `D:\Cortex\Models` |
| GGUF discovery | `cortex_model_host` |
| Import existing LM Studio models | `cortex models import-lmstudio` |
| Load/unload multiple models | llama.cpp router managed by `cortex_model_host` |
| Auto-evict / TTL | native model-host policy |
| GPU offload/context presets | native model profile |
| Memory estimation | native model profile/resource estimator |
| Streaming chat | provider router / Responses-compatible transport |
| Stateful chat | Cortex conversation store + previous-response mapping |
| Tool calling | Cortex tool broker |
| Structured output | provider schema/grammar layer |
| Embeddings | native embedding role |
| Vision/image input | native vision role |
| Model download/search | Cortex Models browser, Hugging Face source adapter |
| MCP | Cortex tool/plugin bridge + remote MCP adapter |
| OpenAI-compatible API | Cortex local compatibility facade |
| Anthropic-compatible API | Cortex local compatibility facade |
| API auth/network binding | optional Cortex local API server policy |
| Presets/model profiles | Cortex role/model profiles |
| Logs/metrics | Cortex observability |
| Headless lifecycle | Desktop-owned Cortex service/model host |

## Internal text/model library

`D:\Cortex\Models` is authoritative. Existing LM Studio models can be mirrored into
`Models\Imported\LMStudio`, preserving directory structure, shards, projectors, metadata, and
provenance. Mirroring is explicit because model libraries can be very large.

## Internal image-generation library

```text
D:\Cortex\Models\ImageGeneration\
├─ Checkpoints\
├─ DiffusionModels\
├─ VAE\
├─ LoRA\
├─ ControlNet\
├─ Upscalers\
├─ Embeddings\
├─ Workflows\
└─ Imported\
   └─ ComfyUI\
```

The first native image backend target is stable-diffusion.cpp because it is lightweight,
Windows-capable, Vulkan/CUDA-capable, and supports GGUF/safetensors/checkpoint model families.
ComfyUI remains an advanced workflow compatibility backend/import source.

The existing `image.generate` / promote / reject / archive tool contract remains the user-facing
authority regardless of which backend executes the generation.

## Web research

Cortex exposes permission-gated `web.search` and `web.fetch` tools. Search uses a configured
SearXNG JSON endpoint. Direct fetch is HTTP/HTTPS-only and blocks obvious loopback/private-network
targets. Network access remains separately grantable through `NetworkInternet`.

Future web layers may add:
- browser rendering;
- robots/content policy;
- source snapshots and citations;
- download/artifact capture;
- project research collections;
- self-hosted SearXNG provisioning.
