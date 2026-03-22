# LLM Models Folder

Place your GGUF-format language model files here.

## Recommended Models

| Model | File | VRAM Required |
|---|---|---|
| LLaMA 2 7B 4-bit | `llama-2-7b.Q4_K_M.gguf` | ~4 GB |
| LLaMA 2 7B 8-bit | `llama-2-7b.Q8_0.gguf` | ~8 GB |
| LLaMA 2 13B 4-bit | `llama-2-13b.Q4_K_M.gguf` | ~8 GB |
| LLaMA 2 13B 8-bit | `llama-2-13b.Q8_0.gguf` | ~14 GB |
| Mistral 7B 4-bit | `mistral-7b-v0.1.Q4_K_M.gguf` | ~4 GB |

## Setup

1. Download a GGUF model from [HuggingFace](https://huggingface.co/TheBloke)
2. Place the `.gguf` file in this folder
3. Set the environment variable:
   ```
   ARBITER_MODEL_PATH=C:\path\to\ArbiterPhase0\AIEngine\LLaMA2-13B\your-model.gguf
   ```
4. Install `llama-cpp-python`:
   ```
   pip install llama-cpp-python
   ```

## Notes

- This folder is excluded from Git (models are large binary files)
- Arbiter falls back to a stub responder if no model is configured
- The Python bridge auto-detects GPU VRAM and selects appropriate quantization
