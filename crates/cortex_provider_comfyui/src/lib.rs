//! Local ComfyUI image-generation provider.
//!
//! Workflows are exported from ComfyUI in API format and may contain the
//! placeholders {{PROMPT}}, {{NEGATIVE_PROMPT}}, {{WIDTH}}, {{HEIGHT}} and
//! {{SEED}} in string or numeric fields.

use cortex_http::HttpClient;
use cortex_protocol::{
    ImageArtifact, ImageArtifactStatus, ImageGenerationRequest, ImageProvider, ProviderError,
};
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct ComfyUiProvider {
    pub base_url: String,
    pub workflow_template: PathBuf,
    pub poll_interval: Duration,
    pub poll_attempts: usize,
    http: HttpClient,
}

impl ComfyUiProvider {
    pub fn new(base_url: impl Into<String>, workflow_template: impl Into<PathBuf>) -> Self {
        Self {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            workflow_template: workflow_template.into(),
            poll_interval: Duration::from_millis(500),
            poll_attempts: 240,
            http: HttpClient::default(),
        }
    }

    pub fn health(&self) -> Result<(), ProviderError> {
        self.http
            .get(&format!("{}/queue", self.base_url))
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?;
        Ok(())
    }

    fn load_workflow(&self, request: &ImageGenerationRequest) -> Result<Value, ProviderError> {
        let workflow_path = request
            .workflow
            .as_ref()
            .map(PathBuf::from)
            .unwrap_or_else(|| self.workflow_template.clone());
        let text = fs::read_to_string(&workflow_path).map_err(|e| {
            ProviderError(format!(
                "failed to read ComfyUI workflow {}: {e}",
                workflow_path.display()
            ))
        })?;
        let seed = request.seed.unwrap_or_else(|| unix_ms() as u64);
        let text = text
            .replace("{{PROMPT}}", &json_string_contents(&request.prompt))
            .replace(
                "{{NEGATIVE_PROMPT}}",
                &json_string_contents(request.negative_prompt.as_deref().unwrap_or("")),
            )
            .replace(
                "{{MODEL}}",
                &json_string_contents(request.model.as_deref().unwrap_or("")),
            )
            .replace(
                "{{CHECKPOINT}}",
                &json_string_contents(request.model.as_deref().unwrap_or("")),
            )
            .replace("\"{{WIDTH}}\"", &request.width.to_string())
            .replace("\"{{HEIGHT}}\"", &request.height.to_string())
            .replace("\"{{SEED}}\"", &seed.to_string())
            .replace("{{WIDTH}}", &request.width.to_string())
            .replace("{{HEIGHT}}", &request.height.to_string())
            .replace("{{SEED}}", &seed.to_string());
        serde_json::from_str(&text)
            .map_err(|e| ProviderError(format!("invalid ComfyUI API workflow: {e}")))
    }

    fn wait_for_outputs(&self, prompt_id: &str) -> Result<Vec<ComfyOutput>, ProviderError> {
        for _ in 0..self.poll_attempts {
            let response = self
                .http
                .get(&format!(
                    "{}/history/{}",
                    self.base_url,
                    percent_encode(prompt_id)
                ))
                .map_err(|e| ProviderError(e.to_string()))?
                .ensure_success()
                .map_err(|e| ProviderError(e.to_string()))?
                .json()
                .map_err(|e| ProviderError(e.to_string()))?;
            if let Some(entry) = response.get(prompt_id) {
                let outputs = extract_outputs(entry);
                if !outputs.is_empty() {
                    return Ok(outputs);
                }
                if entry.pointer("/status/status_str").and_then(Value::as_str) == Some("error") {
                    return Err(ProviderError(format!(
                        "ComfyUI generation failed for {prompt_id}"
                    )));
                }
            }
            thread::sleep(self.poll_interval);
        }
        Err(ProviderError(format!(
            "timed out waiting for ComfyUI prompt {prompt_id}"
        )))
    }

    fn download_output(
        &self,
        output: &ComfyOutput,
        destination: &Path,
    ) -> Result<(), ProviderError> {
        let url = format!(
            "{}/view?filename={}&subfolder={}&type={}",
            self.base_url,
            percent_encode(&output.filename),
            percent_encode(&output.subfolder),
            percent_encode(&output.kind),
        );
        let bytes = self
            .http
            .get(&url)
            .map_err(|e| ProviderError(e.to_string()))?
            .ensure_success()
            .map_err(|e| ProviderError(e.to_string()))?
            .body;
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|e| ProviderError(e.to_string()))?;
        }
        fs::write(destination, bytes).map_err(|e| ProviderError(e.to_string()))
    }
}

impl ImageProvider for ComfyUiProvider {
    fn provider_id(&self) -> &str {
        "comfyui"
    }

    fn generate(
        &self,
        request: &ImageGenerationRequest,
    ) -> Result<Vec<ImageArtifact>, ProviderError> {
        fs::create_dir_all(&request.output_dir).map_err(|e| ProviderError(e.to_string()))?;
        let mut artifacts = Vec::new();
        let count = request.count.clamp(1, 16);
        for index in 0..count {
            let mut run_request = request.clone();
            if run_request.seed.is_none() {
                run_request.seed = Some((unix_ms() as u64).wrapping_add(index as u64));
            }
            let workflow = self.load_workflow(&run_request)?;
            let client_id = format!("open2d-cortex-{}-{}", std::process::id(), unix_ms());
            let submitted = self
                .http
                .post_json(
                    &format!("{}/prompt", self.base_url),
                    &json!({"prompt": workflow, "client_id": client_id}),
                )
                .map_err(|e| ProviderError(e.to_string()))?
                .ensure_success()
                .map_err(|e| ProviderError(e.to_string()))?
                .json()
                .map_err(|e| ProviderError(e.to_string()))?;
            let prompt_id = submitted
                .get("prompt_id")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    ProviderError("ComfyUI response did not include prompt_id".into())
                })?;
            let outputs = self.wait_for_outputs(prompt_id)?;
            for (output_index, output) in outputs.into_iter().enumerate() {
                let extension = Path::new(&output.filename)
                    .extension()
                    .and_then(|v| v.to_str())
                    .unwrap_or("png");
                let id = format!("{}-{}-{}", prompt_id, index, output_index);
                let destination =
                    request
                        .output_dir
                        .join(format!("{}.{}", safe_name(&id), extension));
                self.download_output(&output, &destination)?;
                artifacts.push(ImageArtifact {
                    id,
                    provider: self.provider_id().to_string(),
                    path: destination,
                    metadata_path: None,
                    prompt: run_request.prompt.clone(),
                    negative_prompt: run_request.negative_prompt.clone(),
                    model: run_request.model.clone(),
                    width: run_request.width,
                    height: run_request.height,
                    seed: run_request.seed,
                    status: ImageArtifactStatus::Draft,
                    tags: run_request.tags.clone(),
                });
            }
        }
        Ok(artifacts)
    }
}

#[derive(Clone, Debug)]
struct ComfyOutput {
    filename: String,
    subfolder: String,
    kind: String,
}

fn extract_outputs(history: &Value) -> Vec<ComfyOutput> {
    let mut result = Vec::new();
    let Some(outputs) = history.get("outputs").and_then(Value::as_object) else {
        return result;
    };
    for output in outputs.values() {
        for field in ["images", "gifs"] {
            if let Some(items) = output.get(field).and_then(Value::as_array) {
                for item in items {
                    if let Some(filename) = item.get("filename").and_then(Value::as_str) {
                        result.push(ComfyOutput {
                            filename: filename.to_string(),
                            subfolder: item
                                .get("subfolder")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .to_string(),
                            kind: item
                                .get("type")
                                .and_then(Value::as_str)
                                .unwrap_or("output")
                                .to_string(),
                        });
                    }
                }
            }
        }
    }
    result
}

fn json_string_contents(value: &str) -> String {
    let quoted = serde_json::to_string(value).unwrap_or_else(|_| "\"\"".into());
    quoted.trim_matches('"').to_string()
}

fn percent_encode(value: &str) -> String {
    let mut out = String::new();
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{:02X}", byte));
        }
    }
    out
}

fn safe_name(value: &str) -> String {
    value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.') {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn query_encoding_works() {
        assert_eq!(percent_encode("a b.png"), "a%20b.png");
    }
}
