//! LM Studio provider for Cortex.
//!
//! Agent/tool calls use the OpenAI-compatible Responses endpoint. Visual
//! inspection uses Chat Completions because LM Studio documents image input
//! compatibility there as well.

use cortex_http::HttpClient;
use cortex_protocol::{
    EmbeddingProvider, EmbeddingRequest, ImageInput, MessageRole, ModelRequest, ModelResponse,
    ProviderError, TextProvider, ToolCall, ToolChoicePolicy, VisionProvider,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::time::{Duration, Instant};

const DEFAULT_CONTROL_TIMEOUT: Duration = Duration::from_secs(30);
const DEFAULT_CHAT_MAX_OUTPUT_TOKENS: u64 = 1024;
const DEFAULT_AGENT_MAX_OUTPUT_TOKENS: u64 = 2048;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LmStudioModelCapability {
    pub key: String,
    pub display_name: Option<String>,
    pub trained_for_tool_use: Option<bool>,
    pub vision: Option<bool>,
    pub loaded_instance_ids: Vec<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LmStudioAvailabilityState {
    Offline,
    OnlineNoModel,
    Ready,
}

impl LmStudioAvailabilityState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Offline => "offline",
            Self::OnlineNoModel => "online_no_model",
            Self::Ready => "ready",
        }
    }
}

#[derive(Clone, Debug)]
pub struct LmStudioAvailability {
    pub state: LmStudioAvailabilityState,
    pub base_url: String,
    pub configured_model: Option<String>,
    pub selected_model: Option<String>,
    pub models: Vec<String>,
    pub capabilities: Vec<LmStudioModelCapability>,
    pub detail: Option<String>,
}

impl LmStudioAvailability {
    pub fn ready(&self) -> bool {
        self.state == LmStudioAvailabilityState::Ready && self.selected_model.is_some()
    }
}

#[derive(Clone, Debug)]
pub struct LmStudioProvider {
    pub base_url: String,
    pub default_model: Option<String>,
    control_http: HttpClient,
    inference_http: HttpClient,
}

impl LmStudioProvider {
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
        Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            default_model,
            control_http: HttpClient::with_timeout(DEFAULT_CONTROL_TIMEOUT),
            inference_http: timeout
                .map(HttpClient::with_timeout)
                .unwrap_or_else(HttpClient::without_io_timeout),
        }
    }

    pub fn inference_timeout(&self) -> Option<Duration> {
        self.inference_http.io_timeout()
    }

    pub fn availability(&self) -> LmStudioAvailability {
        let configured_model = self
            .default_model
            .as_ref()
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
            .map(str::to_string);

        let models = match self.list_models() {
            Ok(models) => models,
            Err(error) => {
                return LmStudioAvailability {
                    state: LmStudioAvailabilityState::Offline,
                    base_url: self.base_url.clone(),
                    configured_model,
                    selected_model: None,
                    models: Vec::new(),
                    capabilities: Vec::new(),
                    detail: Some(error.to_string()),
                };
            }
        };
        let capabilities = self.model_capabilities().unwrap_or_default();

        let selected_model = configured_model
            .as_ref()
            .and_then(|configured| {
                models
                    .iter()
                    .find(|model| *model == configured)
                    .cloned()
                    .or_else(|| {
                        capabilities.iter().find_map(|capability| {
                            let configured_matches_key = capability.key == *configured;
                            let configured_matches_loaded = capability
                                .loaded_instance_ids
                                .iter()
                                .any(|loaded| loaded == configured);
                            if configured_matches_loaded
                                || (configured_matches_key
                                    && !capability.loaded_instance_ids.is_empty())
                            {
                                Some(configured.clone())
                            } else {
                                None
                            }
                        })
                    })
            })
            .or_else(|| models.iter().find(|model| is_text_model_id(model)).cloned());

        let detail = if selected_model.is_some() {
            None
        } else if let Some(configured) = configured_model.as_ref() {
            Some(format!(
                "Configured LM Studio text model '{configured}' is not currently loaded/available."
            ))
        } else if models.is_empty() {
            Some("LM Studio is online but no model is currently loaded.".into())
        } else {
            Some("LM Studio is online but no available text model was detected.".into())
        };

        LmStudioAvailability {
            state: if selected_model.is_some() {
                LmStudioAvailabilityState::Ready
            } else {
                LmStudioAvailabilityState::OnlineNoModel
            },
            base_url: self.base_url.clone(),
            configured_model,
            selected_model,
            models,
            capabilities,
            detail,
        }
    }

    pub fn resolve_model(&self) -> Result<String, ProviderError> {
        let availability = self.availability();
        if let Some(model) = availability.selected_model {
            return Ok(model);
        }
        Err(ProviderError(availability.detail.unwrap_or_else(|| {
            "LM Studio has no available text model".into()
        })))
    }

    pub fn model_capabilities(&self) -> Result<Vec<LmStudioModelCapability>, ProviderError> {
        let root = self
            .base_url
            .strip_suffix("/v1")
            .unwrap_or(self.base_url.as_str())
            .trim_end_matches('/');
        let value = self
            .control_http
            .get(&format!("{root}/api/v1/models"))
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?
            .json()
            .map_err(|e| ProviderError(e.to_string()))?;

        let mut output = Vec::new();
        for model in value
            .get("models")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let key = model
                .get("key")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            if key.is_empty() {
                continue;
            }

            let loaded_instance_ids = model
                .get("loaded_instances")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|instance| instance.get("id").and_then(Value::as_str))
                .map(str::to_string)
                .collect::<Vec<_>>();

            output.push(LmStudioModelCapability {
                key,
                display_name: model
                    .get("display_name")
                    .and_then(Value::as_str)
                    .map(str::to_string),
                trained_for_tool_use: model
                    .pointer("/capabilities/trained_for_tool_use")
                    .and_then(Value::as_bool),
                vision: model
                    .pointer("/capabilities/vision")
                    .and_then(Value::as_bool),
                loaded_instance_ids,
            });
        }
        Ok(output)
    }

    pub fn capability_for_model(
        &self,
        model_id: &str,
    ) -> Result<Option<LmStudioModelCapability>, ProviderError> {
        Ok(self.model_capabilities()?.into_iter().find(|info| {
            info.key == model_id
                || info
                    .loaded_instance_ids
                    .iter()
                    .any(|loaded| loaded == model_id)
        }))
    }

    pub fn health(&self) -> Result<(), ProviderError> {
        self.control_http
            .get(&format!("{}/models", self.base_url))
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?;
        Ok(())
    }

    fn ensure_native_tool_model(&self, model: &str) -> Result<(), ProviderError> {
        let Ok(capabilities) = self.model_capabilities() else {
            // Older LM Studio builds may not expose capability metadata. In that
            // case preserve compatibility and let the inference endpoint decide.
            return Ok(());
        };
        let Some(capability) = capabilities.iter().find(|info| {
            info.key == model
                || info
                    .loaded_instance_ids
                    .iter()
                    .any(|loaded| loaded == model)
        }) else {
            return Ok(());
        };
        if capability.trained_for_tool_use != Some(false) {
            return Ok(());
        }

        let suggestions = capabilities
            .iter()
            .filter(|info| info.trained_for_tool_use == Some(true))
            .map(|info| info.key.as_str())
            .take(3)
            .collect::<Vec<_>>();
        let suggestion = if suggestions.is_empty() {
            "Load or install a model that LM Studio reports with trained_for_tool_use=true."
                .to_string()
        } else {
            format!(
                "Compatible model(s) reported by LM Studio: {}. Set one with `cortex model set tool <model-id>`. ",
                suggestions.join(", ")
            )
        };
        Err(ProviderError(format!(
            "LM Studio model '{model}' is not marked as trained for native tool use, so Cortex cannot safely start Inspect/Plan/Apply/Repair with it. {suggestion}General chat may continue using this model."
        )))
    }

    fn prepare_response_request(
        &self,
        request: &ModelRequest,
    ) -> Result<(Value, BTreeMap<String, String>), ProviderError> {
        let model = match &request.model {
            Some(model) => model.clone(),
            None => self.resolve_model()?,
        };

        if !request.tools.is_empty()
            && request.previous_response_id.is_none()
            && request.tool_results.is_empty()
        {
            self.ensure_native_tool_model(&model)?;
        }

        Self::build_response_request(request, model)
    }

    fn stateless_replay_mode_for_model(model: &str) -> StatelessReplayMode {
        let normalized = model.to_ascii_lowercase();
        if normalized.contains("qwen3.5")
            || normalized.contains("qwen3-coder")
            || normalized.contains("qwen3_coder")
        {
            StatelessReplayMode::ObservationMessages
        } else {
            StatelessReplayMode::NativeResponsesItems
        }
    }

    /// Build the OpenAI-compatible Responses payload without contacting the
    /// provider. Runtime preflight remains in `prepare_response_request`; this
    /// pure helper keeps payload/contract unit tests deterministic and offline.
    fn build_response_request(
        request: &ModelRequest,
        model: String,
    ) -> Result<(Value, BTreeMap<String, String>), ProviderError> {
        let replay_mode = Self::stateless_replay_mode_for_model(&model);
        let mut input = Vec::<Value>::new();
        for message in &request.messages {
            if message.role == MessageRole::Tool {
                match replay_mode {
                    StatelessReplayMode::NativeResponsesItems => {
                        if let Some(item) = structured_replay_item(&message.content)? {
                            input.push(item);
                            continue;
                        }
                    }
                    StatelessReplayMode::ObservationMessages => {
                        if let Some(content) = observation_replay_message(&message.content)? {
                            input.push(json!({
                                "type": "message",
                                "role": "user",
                                "content": content
                            }));
                            continue;
                        }
                    }
                }
            }

            let role = match message.role {
                MessageRole::System => "system",
                MessageRole::User => "user",
                MessageRole::Assistant => "assistant",
                MessageRole::Tool => "user",
            };
            input.push(json!({"type": "message", "role": role, "content": message.content}));
        }
        for image in &request.images {
            input.push(json!({
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_image",
                    "image_url": format!("data:{};base64,{}", image.mime_type, image.data_base64)
                }]
            }));
        }
        for result in &request.tool_results {
            input.push(json!({
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": serde_json::to_string(&result.output).unwrap_or_else(|_| "null".into())
            }));
        }

        let mut wire_to_canonical = BTreeMap::<String, String>::new();
        let mut tools = Vec::<Value>::new();
        for tool in &request.tools {
            validate_tool_schema(&tool.name, "$", &tool.parameters)?;
            let wire_name = wire_tool_name(&tool.name);
            if let Some(existing) = wire_to_canonical.insert(wire_name.clone(), tool.name.clone()) {
                if existing != tool.name {
                    return Err(ProviderError(format!(
                        "Cortex tool names collide after OpenAI-compatible sanitization: {existing} and {} -> {wire_name}",
                        tool.name
                    )));
                }
            }
            tools.push(json!({
                "type": "function",
                "name": wire_name,
                "description": tool.description,
                "parameters": tool.parameters
            }));
        }

        let mut body = json!({
            "model": model,
            "input": input,
            "max_output_tokens": if tools.is_empty() {
                DEFAULT_CHAT_MAX_OUTPUT_TOKENS
            } else {
                DEFAULT_AGENT_MAX_OUTPUT_TOKENS
            }
        });
        if let Some(effort) = reasoning_effort_for_model(
            body.get("model")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        ) {
            body["reasoning"] = json!({"effort": effort});
        }
        if !tools.is_empty() {
            body["tools"] = Value::Array(tools);
            body["tool_choice"] = Value::String(
                match request.tool_choice {
                    ToolChoicePolicy::Auto => "auto",
                    ToolChoicePolicy::Required => "required",
                    ToolChoicePolicy::None => "none",
                }
                .into(),
            );
        }
        if let Some(instructions) = &request.instructions {
            body["instructions"] = Value::String(instructions.clone());
        }
        if let Some(previous) = &request.previous_response_id {
            body["previous_response_id"] = Value::String(previous.clone());
        }

        Ok((body, wire_to_canonical))
    }

    pub fn inspect_image(
        &self,
        image: &ImageInput,
        prompt: &str,
        model: Option<&str>,
    ) -> Result<String, ProviderError> {
        let model = match model {
            Some(model) => model.to_string(),
            None => self.resolve_model()?,
        };
        let body = json!({
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": format!("data:{};base64,{}", image.mime_type, image.data_base64)
                        }
                    }
                ]
            }],
            "temperature": 0.1
        });
        let response = self
            .inference_http
            .post_json(&format!("{}/chat/completions", self.base_url), &body)
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?
            .json()
            .map_err(|e| ProviderError(e.to_string()))?;
        Ok(response
            .pointer("/choices/0/message/content")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StatelessReplayMode {
    NativeResponsesItems,
    ObservationMessages,
}

fn structured_replay_item(content: &str) -> Result<Option<Value>, ProviderError> {
    let Ok(value) = serde_json::from_str::<Value>(content) else {
        return Ok(None);
    };
    let Some(kind) = value.get("cortex_replay_type").and_then(Value::as_str) else {
        return Ok(None);
    };

    match kind {
        "function_call" => {
            let call_id = value
                .get("call_id")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    ProviderError(
                        "Cortex structured replay function_call is missing call_id".into(),
                    )
                })?;
            let canonical_name = value.get("name").and_then(Value::as_str).ok_or_else(|| {
                ProviderError("Cortex structured replay function_call is missing name".into())
            })?;
            let arguments = value.get("arguments").cloned().unwrap_or_else(|| json!({}));
            Ok(Some(json!({
                "type": "function_call",
                "call_id": call_id,
                "name": wire_tool_name(canonical_name),
                "arguments": serde_json::to_string(&arguments).unwrap_or_else(|_| "{}".into())
            })))
        }
        "function_call_output" => {
            let call_id = value
                .get("call_id")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    ProviderError(
                        "Cortex structured replay function_call_output is missing call_id".into(),
                    )
                })?;
            let output = json!({
                "is_error": value
                    .get("is_error")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                "output": value.get("output").cloned().unwrap_or(Value::Null),
            });
            Ok(Some(json!({
                "type": "function_call_output",
                "call_id": call_id,
                "output": serde_json::to_string(&output).unwrap_or_else(|_| "null".into())
            })))
        }
        other => Err(ProviderError(format!(
            "Unsupported Cortex structured replay item type: {other}"
        ))),
    }
}

fn observation_replay_message(content: &str) -> Result<Option<String>, ProviderError> {
    let Ok(value) = serde_json::from_str::<Value>(content) else {
        return Ok(None);
    };
    let Some(kind) = value.get("cortex_replay_type").and_then(Value::as_str) else {
        return Ok(None);
    };

    match kind {
        "function_call" => {
            let call_id = value
                .get("call_id")
                .and_then(Value::as_str)
                .unwrap_or("<unknown>");
            let name = value
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("<unknown>");
            let arguments = value.get("arguments").cloned().unwrap_or_else(|| json!({}));
            Ok(Some(format!(
                "Authoritative prior Cortex tool action, already executed; context only. Tool: {name}. Call id: {call_id}. Arguments: {}. Do not imitate this text; continue the task using the currently offered tools.",
                serde_json::to_string(&arguments).unwrap_or_else(|_| "{}".into())
            )))
        }
        "function_call_output" => {
            let call_id = value
                .get("call_id")
                .and_then(Value::as_str)
                .unwrap_or("<unknown>");
            let output = value.get("output").cloned().unwrap_or(Value::Null);
            let is_error = value
                .get("is_error")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            Ok(Some(format!(
                "Authoritative result from previously executed Cortex tool call {call_id}; context only. is_error={is_error}. Result: {}. Use this observation to decide the next real tool call.",
                serde_json::to_string(&output).unwrap_or_else(|_| "null".into())
            )))
        }
        other => Err(ProviderError(format!(
            "Unsupported Cortex observation replay item type: {other}"
        ))),
    }
}

impl EmbeddingProvider for LmStudioProvider {
    fn provider_id(&self) -> &str {
        "lm_studio"
    }
    fn embed(&self, request: &EmbeddingRequest) -> Result<Vec<Vec<f32>>, ProviderError> {
        if request.input.is_empty() {
            return Ok(Vec::new());
        }
        let model = request
            .model
            .clone()
            .or_else(|| self.default_model.clone())
            .ok_or_else(|| ProviderError("LM Studio embedding model is not configured".into()))?;
        let raw = self
            .inference_http
            .post_json(
                &format!("{}/embeddings", self.base_url),
                &json!({"model":model,"input":&request.input}),
            )
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?
            .json()
            .map_err(|e| ProviderError(e.to_string()))?;
        let mut rows = raw
            .get("data")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|e| {
                let i = e.get("index").and_then(Value::as_u64)? as usize;
                let v = e
                    .get("embedding")
                    .and_then(Value::as_array)?
                    .iter()
                    .filter_map(Value::as_f64)
                    .map(|x| x as f32)
                    .collect::<Vec<_>>();
                Some((i, v))
            })
            .collect::<Vec<_>>();
        rows.sort_by_key(|x| x.0);
        let out = rows.into_iter().map(|x| x.1).collect::<Vec<_>>();
        if out.len() != request.input.len() {
            return Err(ProviderError(format!(
                "LM Studio returned {} embeddings for {} inputs",
                out.len(),
                request.input.len()
            )));
        }
        Ok(out)
    }
}

impl VisionProvider for LmStudioProvider {
    fn provider_id(&self) -> &str {
        "lm_studio"
    }
    fn inspect(
        &self,
        image: &ImageInput,
        prompt: &str,
        model: Option<&str>,
    ) -> Result<String, ProviderError> {
        self.inspect_image(image, prompt, model)
    }
}

impl TextProvider for LmStudioProvider {
    fn provider_id(&self) -> &str {
        "lm_studio"
    }

    fn list_models(&self) -> Result<Vec<String>, ProviderError> {
        let value = self
            .control_http
            .get(&format!("{}/models", self.base_url))
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?
            .json()
            .map_err(|e| ProviderError(e.to_string()))?;
        Ok(value
            .get("data")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|entry| entry.get("id").and_then(Value::as_str))
            .map(str::to_string)
            .collect())
    }

    fn respond(&self, request: &ModelRequest) -> Result<ModelResponse, ProviderError> {
        let (body, wire_to_canonical) = self.prepare_response_request(request)?;
        let model = body
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>");
        let raw = self
            .inference_http
            .post_json(&format!("{}/responses", self.base_url), &body)
            .map_err(|e| map_inference_error(model, e.to_string()))?
            .ensure_success()
            .map_err(|e| map_inference_error(model, e.to_string()))?
            .json()
            .map_err(|e| ProviderError(e.to_string()))?;

        parse_response(raw, &wire_to_canonical)
    }

    fn respond_stream(
        &self,
        request: &ModelRequest,
        on_delta: &mut dyn FnMut(&str),
    ) -> Result<ModelResponse, ProviderError> {
        let (mut body, wire_to_canonical) = self.prepare_response_request(request)?;
        body["stream"] = Value::Bool(true);

        let mut pending = Vec::<u8>::new();
        let mut output_text = String::new();
        let mut completed_response: Option<Value> = None;
        let mut last_event = Value::Null;
        let mut stream_error: Option<String> = None;
        let mut last_activity_signal = Instant::now();

        let model = body
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>")
            .to_string();
        self.inference_http
            .post_json_stream(
                &format!("{}/responses", self.base_url),
                &body,
                &mut |chunk| {
                    pending.extend_from_slice(chunk);
                    while let Some(newline) = pending.iter().position(|byte| *byte == b'\n') {
                        let mut line = pending.drain(..=newline).collect::<Vec<_>>();
                        if line.last() == Some(&b'\n') {
                            line.pop();
                        }
                        if line.last() == Some(&b'\r') {
                            line.pop();
                        }
                        let Ok(line) = std::str::from_utf8(&line) else {
                            continue;
                        };
                        let Some(data) = line.strip_prefix("data:") else {
                            continue;
                        };
                        let data = data.trim();
                        if data.is_empty() || data == "[DONE]" {
                            continue;
                        }
                        let Ok(event) = serde_json::from_str::<Value>(data) else {
                            continue;
                        };
                        last_event = event.clone();
                        let event_type = event
                            .get("type")
                            .and_then(Value::as_str)
                            .unwrap_or_default();
                        if event_type == "response.output_text.delta" {
                            if let Some(delta) = event.get("delta").and_then(Value::as_str) {
                                output_text.push_str(delta);
                                on_delta(delta);
                                last_activity_signal = Instant::now();
                            }
                        } else if event_type == "response.completed" {
                            completed_response = event.get("response").cloned();
                        } else if event_type == "response.failed" || event_type == "error" {
                            stream_error = Some(
                                event
                                    .pointer("/error/message")
                                    .or_else(|| event.get("message"))
                                    .and_then(Value::as_str)
                                    .unwrap_or("LM Studio streaming response failed")
                                    .to_string(),
                            );
                        } else if last_activity_signal.elapsed() >= Duration::from_secs(5) {
                            // Reasoning/status SSE traffic is still provider activity even when
                            // it contains no user-visible output. Emit an empty delta as a
                            // transport heartbeat so the outer Cortex RPC watchdog does not
                            // misclassify active inference as a dead provider.
                            on_delta("");
                            last_activity_signal = Instant::now();
                        }
                    }
                    Ok(())
                },
            )
            .map_err(|e| map_inference_error(&model, e.to_string()))?;

        if let Some(error) = stream_error {
            return Err(ProviderError(error));
        }

        if let Some(raw) = completed_response {
            let mut response = parse_response(raw, &wire_to_canonical)?;
            if response.output_text.is_empty() {
                response.output_text = output_text;
            }
            return Ok(response);
        }

        Ok(ModelResponse {
            id: last_event
                .pointer("/response/id")
                .or_else(|| last_event.get("id"))
                .and_then(Value::as_str)
                .map(str::to_string),
            output_text,
            tool_calls: Vec::new(),
            raw: last_event,
        })
    }
}

fn reasoning_effort_for_model(model: &str) -> Option<String> {
    if let Ok(value) = std::env::var("CORTEX_LMSTUDIO_REASONING") {
        let normalized = value.trim().to_ascii_lowercase();
        match normalized.as_str() {
            "" | "auto" => {}
            // Cortex accepts the native-style "off" spelling as a convenience,
            // but /v1/responses requires the OpenAI-compatible effort enum.
            "off" | "none" => return Some("none".into()),
            "minimal" | "low" | "medium" | "high" | "xhigh" => {
                return Some(normalized);
            }
            // "provider" / "default" deliberately omit the field so LM Studio's
            // loaded-model configuration owns reasoning behavior.
            "provider" | "default" => return None,
            _ => {}
        }
    }

    let lower = model.to_ascii_lowercase();

    // LM Studio's native model metadata describes Qwen 3 / 3.5 reasoning as
    // on/off, but Cortex is using the OpenAI-compatible /v1/responses endpoint.
    // That endpoint requires an effort enum and accepts "none" as the disabled
    // state. Never serialize the native word "off" into reasoning.effort.
    if lower.starts_with("qwen/")
        || lower.starts_with("qwen3")
        || lower.contains("/qwen3")
        || lower.contains("/qwen-3")
    {
        return Some("none".into());
    }

    // GPT-OSS is the primary LM Studio Responses model with graded effort.
    if lower.contains("gpt-oss") {
        return Some("low".into());
    }

    // Unknown local models should not receive a reasoning field that may not
    // belong to their Responses contract. Let the provider/model default win.
    None
}

fn is_text_model_id(model: &str) -> bool {
    let lower = model.to_ascii_lowercase();
    !lower.contains("embed") && !lower.contains("embedding") && !lower.contains("rerank")
}

fn map_inference_error(model: &str, error: String) -> ProviderError {
    let lower = error.to_ascii_lowercase();
    if lower.contains("jinja")
        || lower.contains("prompt template")
        || lower.contains("function is not a bool value")
        || lower.contains("no user query found in messages")
    {
        return ProviderError(format!(
            "LM Studio rejected the native tool-call prompt template for model '{model}'. Cortex project modes require a model/template that supports structured tool use. Choose a model LM Studio reports with trained_for_tool_use=true (for example a compatible GPT-OSS or Gemma tool model), or repair that model's LM Studio prompt template. Provider detail: {error}"
        ));
    }
    if lower.contains("cannot determine type of 'item'")
        || lower.contains("cannot determine type of item")
    {
        return ProviderError(format!(
            "LM Studio/llama.cpp rejected a Responses API input item while preparing the project-agent/tool turn for model '{model}'. Cortex now sends the explicit `type: message` discriminator required by current llama.cpp Responses parsing. If this message persists after rebuilding Cortex, update the bundled/native llama.cpp runtime or LM Studio server because the provider is still rejecting the canonical message item shape. Provider detail: {error}"
        ));
    }
    if lower.contains("exceeds the available context size")
        || lower.contains("exceed_context_size_error")
        || (lower.contains("context size") && lower.contains("tokens"))
    {
        return ProviderError(format!(
            "Local model context overflow for '{model}'. Cortex H55 bounds authoritative preflight/tool evidence and the bundled Native Models router uses a 16K context by default. Restart Cortex Native Models after rebuilding so the regenerated router preset takes effect. If an external LM Studio model is still configured with a smaller context, increase that model's context window or select a larger-context Tool model. Provider detail: {error}"
        ));
    }
    if lower.contains("provider response timed out") {
        return ProviderError(format!(
                        "LM Studio inference timed out for model '{model}' because the Cortex provider inactivity watchdog received no response bytes for the configured interval. Increase CORTEX_PROVIDER_TIMEOUT_SECONDS if this model needs a longer first-token window, or set it to 0/off/none/disabled only when intentionally allowing unbounded inference. Provider detail: {error}" 
        ));
    }
    ProviderError(error)
}

fn parse_response(
    raw: Value,
    wire_to_canonical: &BTreeMap<String, String>,
) -> Result<ModelResponse, ProviderError> {
    let id = raw.get("id").and_then(Value::as_str).map(str::to_string);
    let mut output_text = String::new();
    let mut tool_calls = Vec::new();

    if let Some(text) = raw.get("output_text").and_then(Value::as_str) {
        output_text.push_str(text);
    }

    if let Some(output) = raw.get("output").and_then(Value::as_array) {
        for item in output {
            match item.get("type").and_then(Value::as_str) {
                Some("function_call") => {
                    let call_id = item
                        .get("call_id")
                        .or_else(|| item.get("id"))
                        .and_then(Value::as_str)
                        .unwrap_or("tool-call")
                        .to_string();
                    let wire_name = item.get("name").and_then(Value::as_str).unwrap_or_default();
                    let name = wire_to_canonical
                        .get(wire_name)
                        .cloned()
                        .unwrap_or_else(|| wire_name.to_string());
                    let arguments = item
                        .get("arguments")
                        .and_then(Value::as_str)
                        .and_then(|text| serde_json::from_str(text).ok())
                        .unwrap_or_else(|| {
                            item.get("arguments")
                                .cloned()
                                .unwrap_or(Value::Object(Default::default()))
                        });
                    if !name.is_empty() {
                        tool_calls.push(ToolCall {
                            call_id,
                            name,
                            arguments,
                        });
                    }
                }
                Some("message") => {
                    if let Some(content) = item.get("content").and_then(Value::as_array) {
                        for part in content {
                            if matches!(
                                part.get("type").and_then(Value::as_str),
                                Some("output_text" | "text")
                            ) {
                                if let Some(text) = part.get("text").and_then(Value::as_str) {
                                    if !output_text.is_empty() {
                                        output_text.push('\n');
                                    }
                                    output_text.push_str(text);
                                }
                            }
                        }
                    }
                }
                _ => {}
            }
        }
    }

    Ok(ModelResponse {
        id,
        output_text,
        tool_calls,
        raw,
    })
}

fn validate_tool_schema(tool_name: &str, path: &str, schema: &Value) -> Result<(), ProviderError> {
    if schema.get("type").and_then(Value::as_str) == Some("array") && schema.get("items").is_none()
    {
        return Err(ProviderError(format!(
            "Cortex tool schema is invalid before LM Studio dispatch: tool '{tool_name}' has an array without an 'items' schema at {path}. Repair the Cortex tool definition instead of sending a malformed native tool prompt."
        )));
    }

    if let Some(properties) = schema.get("properties").and_then(Value::as_object) {
        for (name, child) in properties {
            validate_tool_schema(tool_name, &format!("{path}.properties.{name}"), child)?;
        }
    }
    if let Some(items) = schema.get("items") {
        validate_tool_schema(tool_name, &format!("{path}.items"), items)?;
    }
    for keyword in ["oneOf", "anyOf", "allOf"] {
        if let Some(children) = schema.get(keyword).and_then(Value::as_array) {
            for (index, child) in children.iter().enumerate() {
                validate_tool_schema(tool_name, &format!("{path}.{keyword}[{index}]"), child)?;
            }
        }
    }
    Ok(())
}

fn wire_tool_name(name: &str) -> String {
    name.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-') {
                ch
            } else {
                '_'
            }
        })
        .take(64)
        .collect()
}

pub fn encode_base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    let mut i = 0;
    while i < bytes.len() {
        let a = bytes[i] as u32;
        let b = bytes.get(i + 1).copied().unwrap_or(0) as u32;
        let c = bytes.get(i + 2).copied().unwrap_or(0) as u32;
        let triple = (a << 16) | (b << 8) | c;
        out.push(TABLE[((triple >> 18) & 63) as usize] as char);
        out.push(TABLE[((triple >> 12) & 63) as usize] as char);
        if i + 1 < bytes.len() {
            out.push(TABLE[((triple >> 6) & 63) as usize] as char);
        } else {
            out.push('=');
        }
        if i + 2 < bytes.len() {
            out.push(TABLE[(triple & 63) as usize] as char);
        } else {
            out.push('=');
        }
        i += 3;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn text_model_classifier_rejects_embedding_models() {
        assert!(is_text_model_id("openai/gpt-oss-20b"));
        assert!(!is_text_model_id("text-embedding-nomic"));
        assert!(!is_text_model_id("embedding-gemma"));
        assert!(!is_text_model_id("rerank-model"));
    }

    #[test]
    fn availability_state_labels_are_stable() {
        assert_eq!(LmStudioAvailabilityState::Offline.as_str(), "offline");
        assert_eq!(
            LmStudioAvailabilityState::OnlineNoModel.as_str(),
            "online_no_model"
        );
        assert_eq!(LmStudioAvailabilityState::Ready.as_str(), "ready");
    }

    #[test]
    fn local_inference_is_unbounded_by_default() {
        assert_eq!(DEFAULT_CONTROL_TIMEOUT, Duration::from_secs(30));
        let provider = LmStudioProvider::new("http://127.0.0.1:1234/v1", None);
        assert_eq!(provider.inference_timeout(), None);

        let bounded = LmStudioProvider::with_timeout(
            "http://127.0.0.1:1234/v1",
            None,
            Duration::from_secs(600),
        );
        assert_eq!(bounded.inference_timeout(), Some(Duration::from_secs(600)));
    }

    #[test]
    fn inference_watchdog_error_is_actionable() {
        let error = map_inference_error(
            "openai/gpt-oss-20b",
            "provider response timed out after 600 seconds (received 0 bytes)".into(),
        );
        assert!(error.0.contains("inactivity watchdog"));
        assert!(error.0.contains("CORTEX_PROVIDER_TIMEOUT_SECONDS"));
        assert!(error.0.contains("openai/gpt-oss-20b"));
    }

    #[test]
    fn base64_smoke() {
        assert_eq!(encode_base64(b"Cortex"), "Q29ydGV4");
    }

    #[test]
    fn dotted_cortex_tool_names_are_wire_safe() {
        assert_eq!(wire_tool_name("project.status"), "project_status");
        assert_eq!(wire_tool_name("source.read"), "source_read");
        assert!(wire_tool_name("vscode.apply_workspace_edit")
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-')));
    }

    #[test]
    fn response_tool_name_maps_back_to_canonical_name() {
        let mut map = BTreeMap::new();
        map.insert("project_status".into(), "project.status".into());
        let parsed = parse_response(
            json!({
                "id":"resp-1",
                "output":[{
                    "type":"function_call",
                    "call_id":"call-1",
                    "name":"project_status",
                    "arguments":"{}"
                }]
            }),
            &map,
        )
        .unwrap();
        assert_eq!(parsed.tool_calls[0].name, "project.status");
    }

    #[test]
    fn responses_use_model_aware_reasoning_and_bounded_output() {
        let chat = ModelRequest::user("hello");

        let (qwen_body, _) =
            LmStudioProvider::build_response_request(&chat, "qwen/qwen3.5-9b".into()).unwrap();
        assert_eq!(
            qwen_body.pointer("/input/0/type").and_then(Value::as_str),
            Some("message"),
            "llama.cpp Responses compatibility requires an explicit message discriminator"
        );
        assert_eq!(
            qwen_body
                .pointer("/reasoning/effort")
                .and_then(Value::as_str),
            Some("none")
        );
        assert_eq!(
            qwen_body.get("max_output_tokens").and_then(Value::as_u64),
            Some(DEFAULT_CHAT_MAX_OUTPUT_TOKENS)
        );

        let (gpt_oss_body, _) =
            LmStudioProvider::build_response_request(&chat, "openai/gpt-oss-20b".into()).unwrap();
        assert_eq!(
            gpt_oss_body
                .pointer("/reasoning/effort")
                .and_then(Value::as_str),
            Some("low")
        );

        let (unknown_body, _) =
            LmStudioProvider::build_response_request(&chat, "generic-model".into()).unwrap();
        assert!(unknown_body.get("reasoning").is_none());

        let mut agent = ModelRequest::user("inspect");
        agent.tools.push(cortex_protocol::ToolDefinition {
            name: "workspace.status".into(),
            description: "status".into(),
            parameters: json!({"type":"object","properties":{}}),
            mutating: false,
        });
        let (agent_body, _) =
            LmStudioProvider::build_response_request(&agent, "qwen/qwen3.5-9b".into()).unwrap();
        assert_eq!(
            agent_body.get("max_output_tokens").and_then(Value::as_u64),
            Some(DEFAULT_AGENT_MAX_OUTPUT_TOKENS)
        );
    }

    #[test]
    fn first_project_turn_uses_auto_tool_choice_after_core_preflight() {
        let mut request = ModelRequest::user("inspect");
        request.tools.push(cortex_protocol::ToolDefinition {
            name: "workspace.status".into(),
            description: "status".into(),
            parameters: json!({"type":"object","properties":{}}),
            mutating: false,
        });
        let (body, _) = LmStudioProvider::build_response_request(&request, "model".into()).unwrap();
        assert_eq!(
            body.get("tool_choice").and_then(Value::as_str),
            Some("auto")
        );
    }

    #[test]
    fn required_tool_choice_is_forwarded_to_responses_api() {
        let mut request = ModelRequest::user("mutate the project");
        request.tools.push(cortex_protocol::ToolDefinition {
            name: "source.write_text".into(),
            description: "write".into(),
            parameters: json!({"type":"object","properties":{}}),
            mutating: true,
        });
        request.tool_choice = ToolChoicePolicy::Required;
        let (body, _) = LmStudioProvider::build_response_request(&request, "model".into()).unwrap();
        assert_eq!(
            body.get("tool_choice").and_then(Value::as_str),
            Some("required")
        );
    }

    #[test]
    fn stateless_tool_replay_uses_native_responses_function_items() {
        let request = ModelRequest {
            model: None,
            instructions: None,
            messages: vec![
                cortex_protocol::ModelMessage {
                    role: MessageRole::User,
                    content: "repair project".into(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Tool,
                    content: json!({
                        "cortex_replay_type":"function_call",
                        "call_id":"call-1",
                        "name":"source.read",
                        "arguments":{"path":"src/main.rs"}
                    })
                    .to_string(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Tool,
                    content: json!({
                        "cortex_replay_type":"function_call_output",
                        "call_id":"call-1",
                        "output":{"content":"fn main() {}"},
                        "is_error":false
                    })
                    .to_string(),
                },
            ],
            tools: vec![cortex_protocol::ToolDefinition {
                name: "source.write_text".into(),
                description: "write".into(),
                parameters: json!({"type":"object","properties":{}}),
                mutating: true,
            }],
            tool_choice: ToolChoicePolicy::Required,
            previous_response_id: None,
            tool_results: Vec::new(),
            images: Vec::new(),
        };

        let (body, _) =
            LmStudioProvider::build_response_request(&request, "openai/gpt-oss-20b".into())
                .unwrap();
        let input = body.get("input").and_then(Value::as_array).unwrap();

        assert_eq!(
            input[0].get("type").and_then(Value::as_str),
            Some("message")
        );
        assert_eq!(
            input[1].get("type").and_then(Value::as_str),
            Some("function_call")
        );
        assert_eq!(
            input[1].get("name").and_then(Value::as_str),
            Some("source_read")
        );
        assert_eq!(
            input[2].get("type").and_then(Value::as_str),
            Some("function_call_output")
        );
        assert!(input.iter().all(|item| {
            !item
                .to_string()
                .contains("[CORTEX STRUCTURED TOOL REQUESTS]")
                && !item
                    .to_string()
                    .contains("[CORTEX AUTHORITATIVE TOOL RESULTS]")
        }));
        assert_eq!(
            body.get("tool_choice").and_then(Value::as_str),
            Some("required")
        );
    }

    #[test]
    fn qwen35_stateless_history_avoids_string_arguments_template_bug() {
        let request = ModelRequest {
            model: None,
            instructions: None,
            messages: vec![
                cortex_protocol::ModelMessage {
                    role: MessageRole::User,
                    content: "repair project".into(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Tool,
                    content: json!({
                        "cortex_replay_type":"function_call",
                        "call_id":"call-1",
                        "name":"source.read",
                        "arguments":{"path":"src/main.rs"}
                    })
                    .to_string(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Tool,
                    content: json!({
                        "cortex_replay_type":"function_call_output",
                        "call_id":"call-1",
                        "output":{"content":"fn main() {}"},
                        "is_error":false
                    })
                    .to_string(),
                },
            ],
            tools: vec![cortex_protocol::ToolDefinition {
                name: "source.write_text".into(),
                description: "write".into(),
                parameters: json!({"type":"object","properties":{}}),
                mutating: true,
            }],
            tool_choice: ToolChoicePolicy::Required,
            previous_response_id: None,
            tool_results: Vec::new(),
            images: Vec::new(),
        };

        let (body, _) =
            LmStudioProvider::build_response_request(&request, "qwen/qwen3.5-9b".into()).unwrap();
        let input = body.get("input").and_then(Value::as_array).unwrap();

        assert!(input
            .iter()
            .all(|item| item.get("type").and_then(Value::as_str) == Some("message")));
        assert!(input.iter().any(|item| item
            .get("content")
            .and_then(Value::as_str)
            .is_some_and(|content| content.contains("Authoritative prior Cortex tool action"))));
        assert!(input.iter().any(|item| item
            .get("content")
            .and_then(Value::as_str)
            .is_some_and(|content| content
                .contains("Authoritative result from previously executed Cortex tool call"))));
        assert!(input.iter().all(|item| {
            item.get("type").and_then(Value::as_str) != Some("function_call")
                && item.get("type").and_then(Value::as_str) != Some("function_call_output")
        }));
        assert_eq!(
            body.get("tool_choice").and_then(Value::as_str),
            Some("required")
        );
    }

    #[test]
    fn malformed_array_tool_schema_is_rejected_before_http_dispatch() {
        let error = validate_tool_schema(
            "broken.tool",
            "$",
            &json!({
                "type":"object",
                "properties":{
                    "edits":{"type":"array"}
                }
            }),
        )
        .unwrap_err();
        assert!(error.0.contains("broken.tool"));
        assert!(error.0.contains("array without an 'items' schema"));
    }

    #[test]
    fn every_responses_conversation_item_has_explicit_message_type() {
        let request = ModelRequest {
            model: None,
            instructions: None,
            messages: vec![
                cortex_protocol::ModelMessage {
                    role: MessageRole::User,
                    content: "user turn".into(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Assistant,
                    content: "assistant turn".into(),
                },
                cortex_protocol::ModelMessage {
                    role: MessageRole::Tool,
                    content: "tool evidence replay".into(),
                },
            ],
            tools: Vec::new(),
            tool_choice: ToolChoicePolicy::Auto,
            previous_response_id: None,
            tool_results: Vec::new(),
            images: Vec::new(),
        };
        let (body, _) =
            LmStudioProvider::build_response_request(&request, "qwen/qwen3.5-9b".into()).unwrap();
        let input = body.get("input").and_then(Value::as_array).unwrap();
        assert_eq!(input.len(), 3);
        assert!(input
            .iter()
            .all(|item| { item.get("type").and_then(Value::as_str) == Some("message") }));
    }

    #[test]
    fn llama_responses_missing_item_type_error_is_actionable() {
        let error = map_inference_error(
            "qwen/qwen3.5-9b",
            "HTTP 400: Cannot determine type of 'item'".into(),
        );
        assert!(error.0.contains("explicit `type: message` discriminator"));
        assert!(error.0.contains("project-agent/tool turn"));
    }

    #[test]
    fn local_context_overflow_is_actionable() {
        let error = map_inference_error(
            "qwen/qwen3.5-9b",
            "HTTP 400: request (8550 tokens) exceeds the available context size (8192 tokens), try increasing it".into(),
        );
        assert!(error.0.contains("context overflow"));
        assert!(error.0.contains("16K context"));
        assert!(error.0.contains("Restart Cortex Native Models"));
    }

    #[test]
    fn lmstudio_template_failures_become_actionable_provider_errors() {
        let error = map_inference_error(
            "qwen/qwen3.5-9b",
            "HTTP 500: While executing If: Error: Function is not a bool value!".into(),
        );
        assert!(error.0.contains("native tool-call prompt template"));
        assert!(error.0.contains("trained_for_tool_use=true"));
        assert!(error.0.contains("qwen/qwen3.5-9b"));
    }
}
