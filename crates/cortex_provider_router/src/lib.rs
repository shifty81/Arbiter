//! Project-agnostic provider selection between Cortex Native Models and optional compatibility hosts.

use cortex_protocol::{
    EmbeddingProvider, EmbeddingRequest, ImageInput, ModelRequest, ModelResponse, ProviderError,
    TextProvider, VisionProvider,
};
use cortex_provider_lmstudio::{LmStudioModelCapability, LmStudioProvider};
use cortex_provider_native::NativeProvider;
use serde_json::{json, Value};
use std::time::Duration;

pub type ModelCapability = LmStudioModelCapability;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProviderKind {
    Native,
    LmStudio,
}

impl ProviderKind {
    pub fn parse(value: &str) -> Self {
        if value.eq_ignore_ascii_case("lmstudio") || value.eq_ignore_ascii_case("lm_studio") {
            Self::LmStudio
        } else {
            Self::Native
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Native => "native",
            Self::LmStudio => "lmstudio",
        }
    }
}

#[derive(Clone, Debug)]
pub enum CortexProvider {
    Native(NativeProvider),
    LmStudio(LmStudioProvider),
}

impl CortexProvider {
    pub fn new(
        kind: ProviderKind,
        base_url: impl Into<String>,
        model: Option<String>,
        timeout: Option<Duration>,
    ) -> Self {
        let base_url = base_url.into();
        match kind {
            ProviderKind::Native => Self::Native(NativeProvider::with_optional_timeout(
                base_url, model, timeout,
            )),
            ProviderKind::LmStudio => Self::LmStudio(match timeout {
                Some(timeout) => LmStudioProvider::with_timeout(base_url, model, timeout),
                None => LmStudioProvider::new(base_url, model),
            }),
        }
    }

    pub fn kind(&self) -> ProviderKind {
        match self {
            Self::Native(_) => ProviderKind::Native,
            Self::LmStudio(_) => ProviderKind::LmStudio,
        }
    }

    pub fn display_name(&self) -> &'static str {
        match self {
            Self::Native(_) => "Cortex Native Models",
            Self::LmStudio(_) => "LM Studio (compatibility)",
        }
    }

    pub fn base_url(&self) -> &str {
        match self {
            Self::Native(provider) => &provider.base_url,
            Self::LmStudio(provider) => &provider.base_url,
        }
    }

    pub fn resolve_model(&self) -> Result<String, ProviderError> {
        match self {
            Self::Native(provider) => provider.resolve_model(),
            Self::LmStudio(provider) => provider.resolve_model(),
        }
    }

    pub fn model_capabilities(&self) -> Result<Vec<ModelCapability>, ProviderError> {
        match self {
            Self::Native(provider) => provider.model_capabilities(),
            Self::LmStudio(provider) => provider.model_capabilities(),
        }
    }

    pub fn capability_for_model(
        &self,
        model: &str,
    ) -> Result<Option<ModelCapability>, ProviderError> {
        match self {
            Self::Native(provider) => provider.capability_for_model(model),
            Self::LmStudio(provider) => provider.capability_for_model(model),
        }
    }

    pub fn status_value(&self) -> Value {
        let models = self.list_models();
        let capabilities = self.model_capabilities().unwrap_or_default();
        let selected_model = self.resolve_model().ok();
        let online = models.is_ok();
        let models = models.unwrap_or_default();
        let ready = online && selected_model.is_some();
        let detail = if !online {
            Some(format!("{} is offline or unreachable", self.display_name()))
        } else if selected_model.is_none() {
            Some(format!(
                "{} is online but no text model is available",
                self.display_name()
            ))
        } else {
            None
        };
        json!({
            "provider": TextProvider::provider_id(self),
            "provider_kind": self.kind().as_str(),
            "provider_name": self.display_name(),
            "base_url": self.base_url(),
            "state": if ready { "ready" } else if online { "online_no_model" } else { "offline" },
            "online": online,
            "ready": ready,
            "configured_model": Value::Null,
            "selected_model": selected_model,
            "models": models,
            "capabilities": capabilities.iter().map(|capability| json!({
                "key": capability.key,
                "display_name": capability.display_name,
                "trained_for_tool_use": capability.trained_for_tool_use,
                "vision": capability.vision,
                "loaded_instance_ids": capability.loaded_instance_ids
            })).collect::<Vec<_>>(),
            "detail": detail
        })
    }
}

impl TextProvider for CortexProvider {
    fn provider_id(&self) -> &str {
        match self {
            Self::Native(provider) => TextProvider::provider_id(provider),
            Self::LmStudio(provider) => TextProvider::provider_id(provider),
        }
    }

    fn supports_previous_response_id(&self) -> bool {
        match self {
            Self::Native(provider) => provider.supports_previous_response_id(),
            Self::LmStudio(provider) => provider.supports_previous_response_id(),
        }
    }

    fn list_models(&self) -> Result<Vec<String>, ProviderError> {
        match self {
            Self::Native(provider) => provider.list_models(),
            Self::LmStudio(provider) => provider.list_models(),
        }
    }

    fn respond(&self, request: &ModelRequest) -> Result<ModelResponse, ProviderError> {
        match self {
            Self::Native(provider) => provider.respond(request),
            Self::LmStudio(provider) => provider.respond(request),
        }
    }

    fn respond_stream(
        &self,
        request: &ModelRequest,
        on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelResponse, ProviderError> {
        match self {
            Self::Native(provider) => provider.respond_stream(request, on_delta),
            Self::LmStudio(provider) => provider.respond_stream(request, on_delta),
        }
    }
}

impl EmbeddingProvider for CortexProvider {
    fn provider_id(&self) -> &str {
        TextProvider::provider_id(self)
    }

    fn embed(&self, request: &EmbeddingRequest) -> Result<Vec<Vec<f32>>, ProviderError> {
        match self {
            Self::Native(provider) => provider.embed(request),
            Self::LmStudio(provider) => provider.embed(request),
        }
    }
}

impl VisionProvider for CortexProvider {
    fn provider_id(&self) -> &str {
        TextProvider::provider_id(self)
    }

    fn inspect(
        &self,
        image: &ImageInput,
        prompt: &str,
        model: Option<&str>,
    ) -> Result<String, ProviderError> {
        match self {
            Self::Native(provider) => provider.inspect(image, prompt, model),
            Self::LmStudio(provider) => provider.inspect(image, prompt, model),
        }
    }
}
