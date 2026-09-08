//! Cortex Native Models provider.
//!
//! The transport speaks to Cortex-owned llama.cpp router mode over loopback.
//! The existing OpenAI-compatible request implementation is reused from the
//! LM Studio adapter during the migration, but no LM Studio process is needed.

use cortex_http::HttpClient;
use cortex_protocol::{
    EmbeddingProvider, EmbeddingRequest, ImageInput, ModelRequest, ModelResponse, ProviderError,
    TextProvider, VisionProvider,
};
use cortex_provider_lmstudio::{LmStudioModelCapability, LmStudioProvider};
use serde_json::Value;
use std::time::Duration;

#[derive(Clone, Debug)]
pub struct NativeProvider {
    pub base_url: String,
    pub default_model: Option<String>,
    inner: LmStudioProvider,
    control_http: HttpClient,
}

impl NativeProvider {
    pub fn new(base_url: impl Into<String>, default_model: Option<String>) -> Self {
        Self::with_optional_timeout(base_url, default_model, None)
    }

    pub fn with_timeout(
        base_url: impl Into<String>,
        default_model: Option<String>,
        timeout: Duration,
    ) -> Self {
        Self::with_optional_timeout(base_url, default_model, Some(timeout))
    }

    pub fn with_optional_timeout(
        base_url: impl Into<String>,
        default_model: Option<String>,
        timeout: Option<Duration>,
    ) -> Self {
        let base_url = base_url.into().trim_end_matches('/').to_string();
        let inner = match timeout {
            Some(timeout) => {
                LmStudioProvider::with_timeout(&base_url, default_model.clone(), timeout)
            }
            None => LmStudioProvider::new(&base_url, default_model.clone()),
        };
        Self {
            base_url,
            default_model,
            inner,
            control_http: HttpClient::with_timeout(Duration::from_secs(30)),
        }
    }

    pub fn inference_timeout(&self) -> Option<Duration> {
        self.inner.inference_timeout()
    }

    pub fn resolve_model(&self) -> Result<String, ProviderError> {
        self.inner.resolve_model().map_err(native_error)
    }

    pub fn model_capabilities(&self) -> Result<Vec<LmStudioModelCapability>, ProviderError> {
        let root = self
            .base_url
            .strip_suffix("/v1")
            .unwrap_or(self.base_url.as_str())
            .trim_end_matches('/');
        let value = self
            .control_http
            .get(&format!("{root}/models?reload=1"))
            .map_err(|error| ProviderError(error.to_string()))?
            .ensure_success()
            .map_err(|error| ProviderError(error.to_string()))?
            .json()
            .map_err(|error| ProviderError(error.to_string()))?;
        Ok(value
            .get("data")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(native_capability)
            .collect())
    }

    pub fn capability_for_model(
        &self,
        model_id: &str,
    ) -> Result<Option<LmStudioModelCapability>, ProviderError> {
        Ok(self.model_capabilities()?.into_iter().find(|model| {
            model.key == model_id
                || model
                    .loaded_instance_ids
                    .iter()
                    .any(|loaded| loaded == model_id)
        }))
    }

    pub fn health(&self) -> Result<(), ProviderError> {
        let root = self
            .base_url
            .strip_suffix("/v1")
            .unwrap_or(self.base_url.as_str())
            .trim_end_matches('/');
        self.control_http
            .get(&format!("{root}/health"))
            .map_err(|error| ProviderError(error.to_string()))?
            .ensure_success()
            .map_err(|error| ProviderError(error.to_string()))?;
        Ok(())
    }
}

impl TextProvider for NativeProvider {
    fn provider_id(&self) -> &str {
        "cortex_native"
    }

    fn supports_previous_response_id(&self) -> bool {
        // llama.cpp's OpenAI-compatible Responses endpoint does not implement
        // the OpenAI server-side response-chain state used by
        // `previous_response_id`. Cortex therefore replays bounded evidence as
        // ordinary messages for native-model agent continuations.
        false
    }

    fn list_models(&self) -> Result<Vec<String>, ProviderError> {
        self.inner.list_models().map_err(native_error)
    }

    fn respond(&self, request: &ModelRequest) -> Result<ModelResponse, ProviderError> {
        self.inner.respond(request).map_err(native_error)
    }

    fn respond_stream(
        &self,
        request: &ModelRequest,
        on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelResponse, ProviderError> {
        self.inner
            .respond_stream(request, on_delta)
            .map_err(native_error)
    }
}

impl EmbeddingProvider for NativeProvider {
    fn provider_id(&self) -> &str {
        "cortex_native"
    }

    fn embed(&self, request: &EmbeddingRequest) -> Result<Vec<Vec<f32>>, ProviderError> {
        self.inner.embed(request).map_err(native_error)
    }
}

impl VisionProvider for NativeProvider {
    fn provider_id(&self) -> &str {
        "cortex_native"
    }

    fn inspect(
        &self,
        image: &ImageInput,
        prompt: &str,
        model: Option<&str>,
    ) -> Result<String, ProviderError> {
        self.inner
            .inspect(image, prompt, model)
            .map_err(native_error)
    }
}

fn native_capability(value: &Value) -> Option<LmStudioModelCapability> {
    let key = value.get("id")?.as_str()?.to_string();
    let status = value
        .pointer("/status/value")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let modalities = value
        .pointer("/architecture/input_modalities")
        .and_then(Value::as_array);
    let vision = modalities.map(|items| {
        items
            .iter()
            .filter_map(Value::as_str)
            .any(|value| matches!(value, "image" | "video"))
    });
    Some(LmStudioModelCapability {
        key: key.clone(),
        display_name: value
            .get("name")
            .or_else(|| value.get("id"))
            .and_then(Value::as_str)
            .map(str::to_string),
        // llama.cpp ships an explicit Qwen 3.5 tool-aware Jinja template and
        // GPT-OSS also has native function-call handling.  Advertising those
        // known families lets the Cortex Tool role avoid blindly selecting a
        // reasoning-only model simply because it appears first in /models.
        // Unknown families remain unknown rather than being falsely rejected.
        trained_for_tool_use: native_tool_use_hint(&key),
        vision,
        loaded_instance_ids: if status == "loaded" {
            vec![key]
        } else {
            Vec::new()
        },
    })
}

fn native_tool_use_hint(model_id: &str) -> Option<bool> {
    let lower = model_id.to_ascii_lowercase();
    if lower.contains("embed") || lower.contains("embedding") || lower.contains("rerank") {
        return Some(false);
    }
    if lower.contains("qwen3.5")
        || lower.contains("qwen-3.5")
        || lower.contains("qwen2.5-coder")
        || lower.contains("qwen-2.5-coder")
        || lower.contains("gpt-oss")
    {
        return Some(true);
    }
    None
}

fn native_error(error: ProviderError) -> ProviderError {
    ProviderError(
        error
            .0
            .replace("LM Studio", "Cortex Native Models")
            .replace("lmstudio", "cortex-native"),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn native_provider_declares_stateless_response_continuation() {
        let provider = NativeProvider::new("http://127.0.0.1:12400/v1", Some("model".into()));
        assert!(!provider.supports_previous_response_id());
    }

    #[test]
    fn router_metadata_becomes_cortex_capability() {
        let value = json!({
            "id":"Qwen3.5-9B-Q4_K_M-1234",
            "status":{"value":"loaded"},
            "architecture":{"input_modalities":["text","image"]}
        });
        let capability = native_capability(&value).unwrap();
        assert_eq!(capability.key, "Qwen3.5-9B-Q4_K_M-1234");
        assert_eq!(capability.trained_for_tool_use, Some(true));
        assert_eq!(capability.vision, Some(true));
        assert_eq!(capability.loaded_instance_ids.len(), 1);
    }

    #[test]
    fn pure_reasoning_model_is_not_falsely_certified_for_tool_use() {
        assert_eq!(
            native_tool_use_hint("DeepSeek-R1-0528-Qwen3-8B-Q8_0-1234"),
            None
        );
    }
}
