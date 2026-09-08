//! Transport-neutral contracts shared by Cortex providers, tools and clients.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;

pub const CORTEX_PROTOCOL_VERSION: u32 = 1;
/// Minimum service capability revision required by the native Cortex desktop.
pub const CORTEX_DESKTOP_API_REVISION: u32 = 2;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MessageRole {
    System,
    User,
    Assistant,
    Tool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModelMessage {
    pub role: MessageRole,
    pub content: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub parameters: Value,
    pub mutating: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ToolResultInput {
    pub call_id: String,
    pub output: Value,
    pub is_error: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ImageInput {
    pub mime_type: String,
    pub data_base64: String,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ToolChoicePolicy {
    #[default]
    Auto,
    Required,
    None,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModelRequest {
    pub model: Option<String>,
    pub instructions: Option<String>,
    pub messages: Vec<ModelMessage>,
    pub tools: Vec<ToolDefinition>,
    #[serde(default)]
    pub tool_choice: ToolChoicePolicy,
    pub previous_response_id: Option<String>,
    pub tool_results: Vec<ToolResultInput>,
    pub images: Vec<ImageInput>,
}

impl ModelRequest {
    pub fn user(prompt: impl Into<String>) -> Self {
        Self {
            model: None,
            instructions: None,
            messages: vec![ModelMessage {
                role: MessageRole::User,
                content: prompt.into(),
            }],
            tools: Vec::new(),
            tool_choice: ToolChoicePolicy::Auto,
            previous_response_id: None,
            tool_results: Vec::new(),
            images: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ToolCall {
    pub call_id: String,
    pub name: String,
    pub arguments: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ModelResponse {
    pub id: Option<String>,
    pub output_text: String,
    pub tool_calls: Vec<ToolCall>,
    pub raw: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ImageArtifactStatus {
    Draft,
    Promoted,
    Rejected,
    Archived,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ImageGenerationRequest {
    pub prompt: String,
    pub negative_prompt: Option<String>,
    pub model: Option<String>,
    pub width: u32,
    pub height: u32,
    pub seed: Option<u64>,
    pub count: u32,
    pub workflow: Option<String>,
    pub output_dir: PathBuf,
    pub tags: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ImageArtifact {
    pub id: String,
    pub provider: String,
    pub path: PathBuf,
    pub metadata_path: Option<PathBuf>,
    pub prompt: String,
    pub negative_prompt: Option<String>,
    pub model: Option<String>,
    pub width: u32,
    pub height: u32,
    pub seed: Option<u64>,
    pub status: ImageArtifactStatus,
    pub tags: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RpcRequest {
    pub protocol_version: u32,
    pub id: String,
    pub method: String,
    #[serde(default)]
    pub params: Value,
    #[serde(default)]
    pub auth_token: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RpcResponse {
    pub protocol_version: u32,
    pub id: String,
    pub ok: bool,
    pub result: Value,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CortexStreamKind {
    Started,
    Status,
    TextDelta,
    ToolStarted,
    ToolFinished,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct CortexStreamEvent {
    pub request_id: String,
    pub kind: CortexStreamKind,
    pub phase: String,
    pub message: String,
    #[serde(default)]
    pub text_delta: String,
    #[serde(default)]
    pub elapsed_ms: u64,
    #[serde(default)]
    pub data: Value,
}

impl CortexStreamEvent {
    pub fn status(
        request_id: impl Into<String>,
        kind: CortexStreamKind,
        phase: impl Into<String>,
        message: impl Into<String>,
        elapsed_ms: u64,
    ) -> Self {
        Self {
            request_id: request_id.into(),
            kind,
            phase: phase.into(),
            message: message.into(),
            text_delta: String::new(),
            elapsed_ms,
            data: Value::Null,
        }
    }

    pub fn text_delta(
        request_id: impl Into<String>,
        delta: impl Into<String>,
        elapsed_ms: u64,
    ) -> Self {
        Self {
            request_id: request_id.into(),
            kind: CortexStreamKind::TextDelta,
            phase: "receiving_response".into(),
            message: "Receiving response".into(),
            text_delta: delta.into(),
            elapsed_ms,
            data: Value::Null,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "frame", rename_all = "snake_case")]
pub enum RpcStreamFrame {
    Event {
        protocol_version: u32,
        id: String,
        event: CortexStreamEvent,
    },
    Response {
        protocol_version: u32,
        id: String,
        response: RpcResponse,
    },
}

impl RpcStreamFrame {
    pub fn event(id: impl Into<String>, event: CortexStreamEvent) -> Self {
        Self::Event {
            protocol_version: CORTEX_PROTOCOL_VERSION,
            id: id.into(),
            event,
        }
    }

    pub fn response(id: impl Into<String>, response: RpcResponse) -> Self {
        Self::Response {
            protocol_version: CORTEX_PROTOCOL_VERSION,
            id: id.into(),
            response,
        }
    }
}

impl RpcResponse {
    pub fn ok(id: impl Into<String>, result: Value) -> Self {
        Self {
            protocol_version: CORTEX_PROTOCOL_VERSION,
            id: id.into(),
            ok: true,
            result,
            error: None,
        }
    }

    pub fn error(id: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            protocol_version: CORTEX_PROTOCOL_VERSION,
            id: id.into(),
            ok: false,
            result: Value::Null,
            error: Some(message.into()),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ProviderError(pub String);

impl std::fmt::Display for ProviderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for ProviderError {}

pub trait TextProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn list_models(&self) -> Result<Vec<String>, ProviderError>;
    fn respond(&self, request: &ModelRequest) -> Result<ModelResponse, ProviderError>;

    /// Whether this provider can continue an OpenAI Responses-style chain by
    /// sending `previous_response_id` plus `function_call_output` items.
    /// Providers that do not implement that stateful contract must return
    /// false so Cortex can replay bounded conversation/tool evidence as normal
    /// messages instead of emitting an unsupported wire field.
    fn supports_previous_response_id(&self) -> bool {
        true
    }

    fn respond_stream(
        &self,
        request: &ModelRequest,
        on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelResponse, ProviderError> {
        let response = self.respond(request)?;
        if !response.output_text.is_empty() {
            on_delta(&response.output_text);
        }
        Ok(response)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct EmbeddingRequest {
    pub model: Option<String>,
    pub input: Vec<String>,
}

pub trait EmbeddingProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn embed(&self, request: &EmbeddingRequest) -> Result<Vec<Vec<f32>>, ProviderError>;
}

pub trait VisionProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn inspect(
        &self,
        image: &ImageInput,
        prompt: &str,
        model: Option<&str>,
    ) -> Result<String, ProviderError>;
}

pub trait ImageProvider: Send + Sync {
    fn provider_id(&self) -> &str;
    fn generate(
        &self,
        request: &ImageGenerationRequest,
    ) -> Result<Vec<ImageArtifact>, ProviderError>;
}

pub trait ToolExecutor {
    fn definitions(&self) -> Vec<ToolDefinition>;
    fn execute(&mut self, call: &ToolCall) -> ToolResultInput;
}

#[cfg(test)]
mod stream_tests {
    use super::*;

    #[test]
    fn stream_event_round_trips() {
        let event = CortexStreamEvent::text_delta("request-1", "hello", 42);
        let encoded = serde_json::to_string(&event).unwrap();
        let decoded: CortexStreamEvent = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded.kind, CortexStreamKind::TextDelta);
        assert_eq!(decoded.text_delta, "hello");
        assert_eq!(decoded.elapsed_ms, 42);
    }
}
