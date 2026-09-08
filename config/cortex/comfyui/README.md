# Cortex ComfyUI Image Provider

Cortex uses ComfyUI as its first production local image-synthesis backend.

1. Install/run ComfyUI locally (default `127.0.0.1:8188`).
2. Put a compatible checkpoint in ComfyUI.
3. Set `OPEN2D_COMFYUI_WORKFLOW` to this API workflow template (or your own exported API-format workflow).
4. Pass the checkpoint name through the Cortex `image.generate` tool's `model` argument.

Supported placeholders in API workflow JSON:

- `{{PROMPT}}`
- `{{NEGATIVE_PROMPT}}`
- `{{MODEL}}` / `{{CHECKPOINT}}`
- `{{WIDTH}}`
- `{{HEIGHT}}`
- `{{SEED}}`

Generated outputs stay under `.open2d/cortex/image_artifacts/` until promoted.
