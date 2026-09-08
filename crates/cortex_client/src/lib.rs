//! Authenticated loopback client used by the standalone Cortex desktop.

use cortex_protocol::{CortexStreamEvent, RpcResponse, CORTEX_DESKTOP_API_REVISION};
use cortex_registry::WorkspaceRegistry;
use cortex_rpc::{call, call_stream, default_address, request_with_token};
use cortex_service::{ServiceRegistry, ServiceStatus};
use cortex_workspace::Workspace;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct CortexClient {
    port: u16,
    token: String,
    workspace_root: PathBuf,
}

impl CortexClient {
    pub fn discover(workspace_root: impl AsRef<Path>) -> Result<Self, String> {
        let bootstrap =
            Workspace::open(workspace_root.as_ref()).map_err(|error| error.to_string())?;
        let workspace = if let Ok(registry) = WorkspaceRegistry::open_default() {
            match registry.attach(&bootstrap) {
                Ok(record) => registry.open_workspace(&record).unwrap_or(bootstrap),
                Err(_) => bootstrap,
            }
        } else {
            bootstrap
        };
        let state_root = workspace.cortex_state_dir();
        let registry = ServiceRegistry::new(&state_root, workspace.root())?;
        let state = registry
            .read()?
            .ok_or_else(|| "Cortex service is not running".to_string())?;
        if state.status != ServiceStatus::Running {
            return Err("Cortex service state is stale".into());
        }
        let token_path = state_root.join("rpc.token");
        let token = fs::read_to_string(&token_path)
            .map_err(|error| format!("failed to read {}: {error}", token_path.display()))?;
        let token = token.trim().to_string();
        if token.len() < 24 {
            return Err("Cortex RPC token is invalid".into());
        }
        Ok(Self {
            port: state.port,
            token,
            workspace_root: workspace.root().to_path_buf(),
        })
    }

    pub fn health(&self) -> Result<Value, String> {
        self.request("health", json!({}))
    }

    pub fn require_desktop_api(&self) -> Result<Value, String> {
        let health = self.health()?;
        let revision = health
            .get("desktop_api_revision")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let streaming = health
            .get("streaming_rpc")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let provider_status = health
            .get("provider_status")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let reported_workspace_root = health
            .get("workspace_root")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                "Cortex service/desktop version mismatch: service health omitted workspace_root authority"
                    .to_string()
            })?;
        if !workspace_roots_match(&self.workspace_root, Path::new(reported_workspace_root)) {
            return Err(format!(
                "Cortex workspace authority mismatch: Desktop selected `{}`, but the connected Cortex service reports `{reported_workspace_root}`. Refusing project inspection/mutation until the project-scoped service is rebound.",
                self.workspace_root.display()
            ));
        }
        if revision < u64::from(CORTEX_DESKTOP_API_REVISION) || !streaming || !provider_status {
            return Err(format!(
                "Cortex service/desktop version mismatch: service desktop API revision {revision}, required {}; streaming_rpc={streaming}, provider_status={provider_status}",
                CORTEX_DESKTOP_API_REVISION
            ));
        }
        Ok(health)
    }

    pub fn chat(&self, prompt: &str) -> Result<Value, String> {
        self.request("agent.chat", json!({"prompt": prompt}))
    }

    pub fn chat_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        let id = format!("desktop-stream-{}-{}", std::process::id(), unix_ms());
        let request = request_with_token(
            id,
            "agent.chat.stream",
            json!({"prompt": prompt}),
            self.token.clone(),
        );
        let response = call_stream(default_address(self.port), &request, on_event)?;
        response_value(response)
    }

    pub fn inspect(&self, prompt: &str) -> Result<Value, String> {
        self.request_agent_stream("agent.inspect.stream", json!({"prompt": prompt}))
    }

    pub fn plan(&self, prompt: &str) -> Result<Value, String> {
        self.request_agent_stream("agent.plan.stream", json!({"prompt": prompt}))
    }

    pub fn apply(&self, prompt: &str) -> Result<Value, String> {
        self.request_agent_stream("agent.apply.stream", json!({"prompt": prompt}))
    }

    pub fn apply_reuse_transaction(&self, prompt: &str) -> Result<Value, String> {
        self.request(
            "agent.apply",
            json!({"prompt": prompt, "reuse_transaction": true}),
        )
    }

    pub fn repair(&self, prompt: &str) -> Result<Value, String> {
        self.request_agent_stream("agent.repair.stream", json!({"prompt": prompt}))
    }

    pub fn repair_reuse_transaction(&self, prompt: &str) -> Result<Value, String> {
        self.request_agent_stream(
            "agent.repair.stream",
            json!({"prompt": prompt, "reuse_transaction": true}),
        )
    }

    pub fn inspect_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.inspect.stream",
            json!({"prompt": prompt}),
            on_event,
        )
    }

    pub fn plan_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.plan.stream",
            json!({"prompt": prompt}),
            on_event,
        )
    }

    pub fn apply_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.apply.stream",
            json!({"prompt": prompt}),
            on_event,
        )
    }

    pub fn repair_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.repair.stream",
            json!({"prompt": prompt}),
            on_event,
        )
    }

    pub fn apply_reuse_transaction_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.apply.stream",
            json!({"prompt": prompt, "reuse_transaction": true}),
            on_event,
        )
    }

    pub fn repair_reuse_transaction_stream(
        &self,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        self.request_agent_stream_with_callback(
            "agent.repair.stream",
            json!({"prompt": prompt, "reuse_transaction": true}),
            on_event,
        )
    }
    pub fn tool(&self, name: &str, arguments: Value) -> Result<Value, String> {
        self.request("tools.call", json!({"name": name, "arguments": arguments}))
    }

    pub fn models(&self) -> Result<Value, String> {
        self.request("models.list", json!({}))
    }

    pub fn provider_status(&self) -> Result<Value, String> {
        self.request("provider.status", json!({}))
    }

    pub fn provider_tool_smoke(&self) -> Result<Value, String> {
        self.request("provider.tool_smoke", json!({}))
    }

    // O2D-R051N9M9A5_SAFE_AGENT_STREAM_TELEMETRY
    fn request_agent_stream(&self, method: &str, params: Value) -> Result<Value, String> {
        let mut discard = |_event: CortexStreamEvent| {};
        self.request_agent_stream_with_callback(method, params, &mut discard)
    }
    fn request_agent_stream_with_callback(
        &self,
        method: &str,
        params: Value,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<Value, String> {
        let id = format!("desktop-agent-stream-{}-{}", std::process::id(), unix_ms());
        let request = request_with_token(id, method, params, self.token.clone());
        let response = call_stream(default_address(self.port), &request, on_event)?;
        response_value(response)
    }

    pub fn request(&self, method: &str, params: Value) -> Result<Value, String> {
        let id = format!("desktop-{}-{}", std::process::id(), unix_ms());
        let request = request_with_token(id, method, params, self.token.clone());
        let response = call(default_address(self.port), &request)?;
        response_value(response)
    }
}

fn workspace_roots_match(expected: &Path, reported: &Path) -> bool {
    fn normalized(path: &Path) -> String {
        let raw = path.to_string_lossy().replace('/', "\\");
        let without_extended_prefix = raw.strip_prefix(r"\\?\").unwrap_or(raw.as_str());
        without_extended_prefix
            .trim_end_matches('\\')
            .to_ascii_lowercase()
    }

    normalized(expected) == normalized(reported)
}

fn response_value(response: RpcResponse) -> Result<Value, String> {
    if response.ok {
        Ok(response.result)
    } else {
        Err(response
            .error
            .unwrap_or_else(|| "Cortex RPC request failed".into()))
    }
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[cfg(test)]
mod workspace_authority_tests {
    use super::*;

    #[test]
    fn extended_windows_prefix_and_case_do_not_break_workspace_authority() {
        assert!(workspace_roots_match(
            Path::new(r"\\?\C:\Users\Shifty\Desktop\hello3d"),
            Path::new(r"c:\users\shifty\desktop\hello3d\\"),
        ));
    }

    #[test]
    fn different_projects_fail_workspace_authority() {
        assert!(!workspace_roots_match(
            Path::new(r"C:\Users\Shifty\Desktop\hello3d"),
            Path::new(r"C:\Users\Shifty\Desktop\O2DF"),
        ));
    }
}
