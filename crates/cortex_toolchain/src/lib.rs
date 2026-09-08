//! Discovery contracts for optional open-source tools Cortex can use locally.
//!
//! Integrations are capability additions, never hidden authorities. Cortex must
//! continue to function when an optional executable is absent.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::process::{Command, Stdio};

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum IntegrationRole {
    ExactSearch,
    SyntaxIndex,
    SemanticLanguageServer,
    SecretScan,
    DependencyAudit,
    DependencyPolicy,
    LicenseScan,
    WasmSandbox,
    VersionControl,
    BuildSystem,
    WebSearch,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IntegrationStatus {
    pub id: String,
    pub role: IntegrationRole,
    pub command: Option<String>,
    pub available: bool,
    pub version: Option<String>,
    pub configured_endpoint: Option<String>,
    pub optional: bool,
    pub notes: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ToolchainStatus {
    pub schema_version: u32,
    pub integrations: Vec<IntegrationStatus>,
}

pub fn inspect_local_toolchain() -> ToolchainStatus {
    let mut integrations = vec![
        command_status(
            "ripgrep",
            IntegrationRole::ExactSearch,
            &["rg", "rg.exe"],
            &["--version"],
            "Fast exact source/file search; Cortex internal search remains the fallback.",
        ),
        command_status(
            "tree-sitter",
            IntegrationRole::SyntaxIndex,
            &["tree-sitter", "tree-sitter.exe"],
            &["--version"],
            "Incremental syntax parsing for symbol-aware code indexing.",
        ),
        command_status(
            "rust-analyzer",
            IntegrationRole::SemanticLanguageServer,
            &["rust-analyzer", "rust-analyzer.exe"],
            &["--version"],
            "Rust semantic/type intelligence and diagnostics.",
        ),
        command_status(
            "gitleaks",
            IntegrationRole::SecretScan,
            &["gitleaks", "gitleaks.exe"],
            &["version"],
            "Secret scanning before packaging, pushing, or exporting artifacts.",
        ),
        command_status(
            "cargo-audit",
            IntegrationRole::DependencyAudit,
            &["cargo-audit", "cargo-audit.exe"],
            &["--version"],
            "RustSec dependency vulnerability audit.",
        ),
        command_status(
            "cargo-deny",
            IntegrationRole::DependencyPolicy,
            &["cargo-deny", "cargo-deny.exe"],
            &["--version"],
            "Rust dependency/license/source policy checks.",
        ),
        command_status(
            "scancode",
            IntegrationRole::LicenseScan,
            &["scancode", "scancode.exe"],
            &["--version"],
            "Deep optional license/copyright/package provenance scanning.",
        ),
        command_status(
            "wasmtime",
            IntegrationRole::WasmSandbox,
            &["wasmtime", "wasmtime.exe"],
            &["--version"],
            "Sandboxed future Cortex/Ember plugin execution.",
        ),
        command_status(
            "git",
            IntegrationRole::VersionControl,
            &["git", "git.exe"],
            &["--version"],
            "Primary Git CLI authority; embedded gix integration may supplement inspection later.",
        ),
        command_status(
            "cmake",
            IntegrationRole::BuildSystem,
            &["cmake", "cmake.exe"],
            &["--version"],
            "CMake project adapter support.",
        ),
    ];

    let endpoint = std::env::var("CORTEX_WEB_SEARCH_URL").ok();
    integrations.push(IntegrationStatus {
        id: "searxng".into(),
        role: IntegrationRole::WebSearch,
        command: None,
        available: endpoint.is_some(),
        version: None,
        configured_endpoint: endpoint,
        optional: true,
        notes: "Self-hosted web-search endpoint used by cortex_web; network use remains an explicit capability.".into(),
    });

    ToolchainStatus {
        schema_version: 1,
        integrations,
    }
}

fn command_status(
    id: &str,
    role: IntegrationRole,
    commands: &[&str],
    args: &[&str],
    notes: &str,
) -> IntegrationStatus {
    for command in commands {
        if let Some(version) = command_version(command, args) {
            return IntegrationStatus {
                id: id.into(),
                role,
                command: Some((*command).into()),
                available: true,
                version: Some(version),
                configured_endpoint: None,
                optional: true,
                notes: notes.into(),
            };
        }
    }
    IntegrationStatus {
        id: id.into(),
        role,
        command: commands.first().map(|value| (*value).to_string()),
        available: false,
        version: None,
        configured_endpoint: None,
        optional: true,
        notes: notes.into(),
    }
}

fn command_version(command: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(command)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let text = if stdout.trim().is_empty() {
        stderr
    } else {
        stdout
    };
    Some(
        text.lines()
            .next()
            .unwrap_or_default()
            .trim()
            .chars()
            .take(240)
            .collect(),
    )
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PluginSandboxPolicy {
    pub schema_version: u32,
    pub runtime: String,
    pub allowed_roots: Vec<PathBuf>,
    pub allow_network: bool,
    pub allow_process_spawn: bool,
    pub allow_project_write: bool,
}

impl Default for PluginSandboxPolicy {
    fn default() -> Self {
        Self {
            schema_version: 1,
            runtime: "wasmtime".into(),
            allowed_roots: Vec::new(),
            allow_network: false,
            allow_process_spawn: false,
            allow_project_write: false,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SecurityGatePlan {
    pub schema_version: u32,
    pub secret_scan: bool,
    pub dependency_audit: bool,
    pub dependency_policy: bool,
    pub license_scan: bool,
    pub block_export_on_detected_secret: bool,
    pub block_release_on_unknown_license: bool,
}

impl Default for SecurityGatePlan {
    fn default() -> Self {
        Self {
            schema_version: 1,
            secret_scan: true,
            dependency_audit: true,
            dependency_policy: true,
            license_scan: true,
            block_export_on_detected_secret: true,
            block_release_on_unknown_license: true,
        }
    }
}
