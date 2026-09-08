//! Universal governed execution transcript, compaction, and deterministic-remediation authority.
//!
//! This crate contains only safe operational state. It must never carry or expose hidden model
//! chain-of-thought. Human-facing transcript entries describe phases, tools, commands, files,
//! diagnostics, verification, and completion evidence.

pub mod spine;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::time::{SystemTime, UNIX_EPOCH};

pub const EXECUTION_TRANSCRIPT_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_CHAT_SNIPPET_CHARS: usize = 6_000;
pub const DEFAULT_COMMAND_OUTPUT_CHARS: usize = 12_000;
pub const DEFAULT_STALL_WARNING_MS: u128 = 90_000;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionPhase {
    Intake,
    Inspect,
    Context,
    Provider,
    Tool,
    Mutation,
    Format,
    Check,
    Test,
    Lint,
    Build,
    Launch,
    Verify,
    Compact,
    Complete,
    Failed,
    Cancelled,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TranscriptVisibility {
    ChatAndActivity,
    ActivityOnly,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SnippetKind {
    Code,
    Diff,
    Command,
    Output,
    Diagnostic,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SafeSnippet {
    pub kind: SnippetKind,
    #[serde(default)]
    pub language: String,
    pub text: String,
    #[serde(default)]
    pub truncated: bool,
}

impl SafeSnippet {
    pub fn bounded(
        kind: SnippetKind,
        language: impl Into<String>,
        text: impl AsRef<str>,
        max_chars: usize,
    ) -> Self {
        let text = text.as_ref();
        let (text, truncated) = bounded_chars(text, max_chars.max(1));
        Self {
            kind,
            language: language.into(),
            text,
            truncated,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExecutionTranscriptEntry {
    pub schema_version: u32,
    pub id: String,
    pub created_unix_ms: u128,
    pub phase: ExecutionPhase,
    pub title: String,
    pub detail: String,
    pub visibility: TranscriptVisibility,
    pub success: Option<bool>,
    #[serde(default)]
    pub elapsed_ms: Option<u128>,
    #[serde(default)]
    pub attempt: Option<u32>,
    #[serde(default)]
    pub provider: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub tool: Option<String>,
    #[serde(default)]
    pub command: Option<String>,
    #[serde(default)]
    pub cwd: Option<String>,
    #[serde(default)]
    pub file: Option<String>,
    #[serde(default)]
    pub snippet: Option<SafeSnippet>,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
}

impl ExecutionTranscriptEntry {
    pub fn new(phase: ExecutionPhase, title: impl Into<String>, detail: impl Into<String>) -> Self {
        let now = unix_ms();
        Self {
            schema_version: EXECUTION_TRANSCRIPT_SCHEMA_VERSION,
            id: format!("{now}-{}-execution", std::process::id()),
            created_unix_ms: now,
            phase,
            title: title.into(),
            detail: detail.into(),
            visibility: TranscriptVisibility::ChatAndActivity,
            success: None,
            elapsed_ms: None,
            attempt: None,
            provider: None,
            model: None,
            tool: None,
            command: None,
            cwd: None,
            file: None,
            snippet: None,
            metadata: BTreeMap::new(),
        }
    }

    pub fn chat_visible(&self) -> bool {
        self.visibility == TranscriptVisibility::ChatAndActivity
    }

    pub fn render_chat_markdown(&self) -> String {
        // Local-time rendering is owned by the UI using created_unix_ms. Keeping the timestamp as
        // structured data avoids baking a timezone into durable conversation content.
        let mut out = format!("**{}**", self.title.trim());
        if !self.detail.trim().is_empty() {
            out.push_str("\n\n");
            out.push_str(self.detail.trim());
        }
        if let Some(command) = self
            .command
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            out.push_str("\n\n```text\n");
            out.push_str(command.trim());
            out.push_str("\n```");
        }
        if let Some(snippet) = &self.snippet {
            let language = snippet.language.trim();
            out.push_str("\n\n```");
            out.push_str(language);
            out.push('\n');
            out.push_str(snippet.text.trim_end());
            if snippet.truncated {
                out.push_str("\n… output truncated …");
            }
            out.push_str("\n```");
        }
        out
    }

    pub fn render_activity_detail(&self) -> String {
        let mut parts = Vec::new();
        if !self.detail.trim().is_empty() {
            parts.push(self.detail.trim().to_string());
        }
        if let Some(tool) = self.tool.as_deref() {
            parts.push(format!("tool={tool}"));
        }
        if let Some(command) = self.command.as_deref() {
            parts.push(format!("command={command}"));
        }
        if let Some(file) = self.file.as_deref() {
            parts.push(format!("file={file}"));
        }
        if let Some(elapsed) = self.elapsed_ms {
            parts.push(format!("elapsed_ms={elapsed}"));
        }
        if let Some(attempt) = self.attempt {
            parts.push(format!("attempt={attempt}"));
        }
        parts.join(" | ")
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProviderHeartbeat {
    pub started_unix_ms: u128,
    pub last_event_unix_ms: u128,
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub context_used: Option<u64>,
    #[serde(default)]
    pub context_limit: Option<u64>,
}

impl ProviderHeartbeat {
    pub fn elapsed_ms(&self, now_unix_ms: u128) -> u128 {
        now_unix_ms.saturating_sub(self.started_unix_ms)
    }

    pub fn idle_ms(&self, now_unix_ms: u128) -> u128 {
        now_unix_ms.saturating_sub(self.last_event_unix_ms)
    }

    pub fn appears_stalled(&self, now_unix_ms: u128, warning_after_ms: u128) -> bool {
        self.idle_ms(now_unix_ms) >= warning_after_ms.max(1)
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum QualityGateStage {
    Format,
    Check,
    Test,
    Lint,
    Build,
    Launch,
    Verify,
    Other,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CommandSpec {
    pub program: String,
    #[serde(default)]
    pub args: Vec<String>,
}

impl CommandSpec {
    pub fn new<I, S>(program: impl Into<String>, args: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            program: program.into(),
            args: args.into_iter().map(Into::into).collect(),
        }
    }

    pub fn display(&self) -> String {
        std::iter::once(self.program.as_str())
            .chain(self.args.iter().map(String::as_str))
            .map(shell_display_argument)
            .collect::<Vec<_>>()
            .join(" ")
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QualityGateFailure {
    pub stage: QualityGateStage,
    pub command: CommandSpec,
    pub exit_code: Option<i32>,
    #[serde(default)]
    pub stdout: String,
    #[serde(default)]
    pub stderr: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct FormatterRemediationSpec {
    pub id: String,
    pub check: CommandSpec,
    pub write: CommandSpec,
}

impl FormatterRemediationSpec {
    pub fn rust_cargo() -> Self {
        Self {
            id: "rust.cargo_fmt".into(),
            check: CommandSpec::new("cargo", ["fmt", "--", "--check"]),
            write: CommandSpec::new("cargo", ["fmt"]),
        }
    }

    /// Rust workspace-wide rustfmt profile used by Cortex build.cargo_fmt_check/build.certify.
    pub fn rust_cargo_workspace() -> Self {
        Self {
            id: "rust.cargo_fmt_workspace".into(),
            check: CommandSpec::new("cargo", ["fmt", "--all", "--", "--check"]),
            write: CommandSpec::new("cargo", ["fmt", "--all"]),
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RemediationKind {
    DeterministicFormatter,
    ModelRepair,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemediationPlan {
    pub kind: RemediationKind,
    pub reason: String,
    #[serde(default)]
    pub action: Option<CommandSpec>,
    #[serde(default)]
    pub recheck: Option<CommandSpec>,
    pub consumes_model_attempt: bool,
}

impl RemediationPlan {
    pub fn model(reason: impl Into<String>) -> Self {
        Self {
            kind: RemediationKind::ModelRepair,
            reason: reason.into(),
            action: None,
            recheck: None,
            consumes_model_attempt: true,
        }
    }
}

pub fn plan_quality_gate_remediation(
    failure: &QualityGateFailure,
    formatter_specs: &[FormatterRemediationSpec],
) -> RemediationPlan {
    if failure.stage == QualityGateStage::Format {
        if let Some(formatter) = formatter_specs
            .iter()
            .find(|formatter| command_equivalent(&failure.command, &formatter.check))
        {
            return RemediationPlan {
                kind: RemediationKind::DeterministicFormatter,
                reason: format!(
                    "{} failed its format check; apply the configured formatter mechanically before asking the model to repair source",
                    formatter.id
                ),
                action: Some(formatter.write.clone()),
                recheck: Some(formatter.check.clone()),
                consumes_model_attempt: false,
            };
        }
    }
    RemediationPlan::model(
        "No safe deterministic project-adapter remediation matches this failure; retain the failure evidence for a bounded model repair turn",
    )
}

pub fn default_formatter_specs() -> Vec<FormatterRemediationSpec> {
    vec![
        FormatterRemediationSpec::rust_cargo(),
        FormatterRemediationSpec::rust_cargo_workspace(),
    ]
}

/// Resolve a safe deterministic remediation that may run before a quality-gate check.
///
/// H68B uses this at the shared process boundary so mechanically repairable formatting does not
/// consume a bounded model Repair attempt. A returned command must itself not match this function,
/// which prevents recursive remediation loops.
pub fn deterministic_preflight_remediation(program: &str, args: &[&str]) -> Option<CommandSpec> {
    let requested = CommandSpec::new(program, args.iter().copied());
    default_formatter_specs()
        .into_iter()
        .find(|formatter| command_equivalent(&requested, &formatter.check))
        .map(|formatter| formatter.write)
}

pub const REPAIR_DOSSIER_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RepairFailureClass {
    Formatter,
    CompilerSyntax,
    BorrowChecker,
    DependencyApiMismatch,
    MissingDependency,
    Linker,
    TestFailure,
    LintFailure,
    RuntimeStartup,
    Unknown,
}

impl RepairFailureClass {
    pub fn label(self) -> &'static str {
        match self {
            Self::Formatter => "formatter",
            Self::CompilerSyntax => "compiler_syntax",
            Self::BorrowChecker => "borrow_checker",
            Self::DependencyApiMismatch => "dependency_api_mismatch",
            Self::MissingDependency => "missing_dependency",
            Self::Linker => "linker",
            Self::TestFailure => "test_failure",
            Self::LintFailure => "lint_failure",
            Self::RuntimeStartup => "runtime_startup",
            Self::Unknown => "unknown",
        }
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RepairStrategy {
    Mechanical,
    Surgical,
    Structural,
    Reconstruction,
}

impl RepairStrategy {
    pub fn label(self) -> &'static str {
        match self {
            Self::Mechanical => "mechanical",
            Self::Surgical => "surgical",
            Self::Structural => "structural",
            Self::Reconstruction => "reconstruction",
        }
    }

    pub fn materially_different(self) -> Self {
        match self {
            Self::Mechanical | Self::Surgical => Self::Structural,
            Self::Structural | Self::Reconstruction => Self::Reconstruction,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct RepairDiagnostic {
    pub level: String,
    #[serde(default)]
    pub code: String,
    #[serde(default)]
    pub file: String,
    #[serde(default)]
    pub line: u64,
    pub message: String,
}

impl RepairDiagnostic {
    pub fn identity(&self) -> String {
        format!(
            "{}|{}|{}|{}|{}",
            self.level, self.code, self.file, self.line, self.message
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiagnosticSnapshot {
    pub schema_version: u32,
    pub source_revision: u64,
    pub failed_stage: String,
    pub errors: usize,
    pub warnings: usize,
    pub fingerprint: String,
    #[serde(default)]
    pub diagnostics: Vec<RepairDiagnostic>,
    #[serde(default)]
    pub raw_log: String,
}

impl DiagnosticSnapshot {
    pub fn from_quality_gate(gate: &Value) -> Self {
        let failed = gate
            .get("stages")
            .and_then(Value::as_array)
            .and_then(|stages| {
                stages.iter().find(|stage| {
                    !stage
                        .get("success")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                })
            });
        let failed_stage = failed
            .and_then(|stage| stage.get("capability"))
            .and_then(Value::as_str)
            .unwrap_or("quality_gate")
            .to_string();
        let result = failed.and_then(|stage| stage.get("result"));
        let diagnostics = result
            .and_then(|result| result.get("diagnostics"))
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| {
                        let message = item.get("message").and_then(Value::as_str)?;
                        Some(RepairDiagnostic {
                            level: item
                                .get("level")
                                .and_then(Value::as_str)
                                .unwrap_or("error")
                                .to_string(),
                            code: item
                                .get("code")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .to_string(),
                            file: item
                                .get("file")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .to_string(),
                            line: item.get("line_start").and_then(Value::as_u64).unwrap_or(0),
                            message: message.to_string(),
                        })
                    })
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let mut errors = result
            .and_then(|result| result.pointer("/cortex_quality/current/errors"))
            .and_then(Value::as_u64)
            .map(|value| value as usize)
            .unwrap_or_else(|| {
                diagnostics
                    .iter()
                    .filter(|diagnostic| diagnostic.level.eq_ignore_ascii_case("error"))
                    .count()
            });
        let mut warnings = result
            .and_then(|result| result.pointer("/cortex_quality/current/warnings"))
            .and_then(Value::as_u64)
            .map(|value| value as usize)
            .unwrap_or_else(|| {
                diagnostics
                    .iter()
                    .filter(|diagnostic| diagnostic.level.eq_ignore_ascii_case("warning"))
                    .count()
            });
        let mut fingerprint = result
            .and_then(|result| result.pointer("/cortex_candidate/quality_fingerprint"))
            .and_then(Value::as_str)
            .unwrap_or("unavailable")
            .to_string();
        let source_revision = result
            .and_then(|result| result.get("source_revision"))
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let raw_log = result
            .and_then(|result| result.get("checkpoint_log"))
            .and_then(Value::as_str)
            .or_else(|| {
                result
                    .and_then(|result| result.get("stderr"))
                    .and_then(Value::as_str)
            })
            .or_else(|| {
                result
                    .and_then(|result| result.get("stdout"))
                    .and_then(Value::as_str)
            })
            .map(|text| bounded_chars(text, 96 * 1024).0)
            .unwrap_or_default();
        if errors == 0 && !raw_log.is_empty() {
            errors = raw_log
                .lines()
                .filter(|line| {
                    let lower = line.to_ascii_lowercase();
                    lower.contains("error[")
                        || lower.starts_with("error:")
                        || lower.contains("[fail]")
                        || lower.contains(" failed")
                })
                .count();
        }
        if warnings == 0 && !raw_log.is_empty() {
            warnings = raw_log
                .lines()
                .filter(|line| {
                    let lower = line.to_ascii_lowercase();
                    lower.contains("warning:") || lower.contains("[warn]")
                })
                .count();
        }
        if fingerprint == "unavailable" {
            fingerprint = format!(
                "checkpoint-{:016x}",
                stable_evidence_hash(&format!("{failed_stage}|{errors}|{warnings}|{raw_log}"))
            );
        }
        Self {
            schema_version: REPAIR_DOSSIER_SCHEMA_VERSION,
            source_revision,
            failed_stage,
            errors,
            warnings,
            fingerprint,
            diagnostics,
            raw_log,
        }
    }

    pub fn failure_class(&self) -> RepairFailureClass {
        let stage = self.failed_stage.to_ascii_lowercase();
        if stage == "format" {
            return RepairFailureClass::Formatter;
        }
        if stage == "test" {
            return RepairFailureClass::TestFailure;
        }
        if stage == "lint" {
            return RepairFailureClass::LintFailure;
        }
        if stage == "launch" || stage == "runtime" {
            return RepairFailureClass::RuntimeStartup;
        }

        let raw_lower = self.raw_log.to_ascii_lowercase();
        let mut api_mismatch = [
            "unresolved import",
            "no method named",
            "could not find",
            "mismatched types",
            "no field named",
        ]
        .into_iter()
        .map(|needle| raw_lower.matches(needle).count())
        .sum::<usize>();
        let mut missing_dependency = [
            "unlinked crate",
            "undeclared crate",
            "use of unresolved module",
        ]
        .into_iter()
        .map(|needle| raw_lower.matches(needle).count())
        .sum::<usize>();
        let mut borrow_checker = 0usize;
        let mut linker = 0usize;
        let mut syntax = 0usize;
        for diagnostic in &self.diagnostics {
            if !diagnostic.level.eq_ignore_ascii_case("error") {
                continue;
            }
            let code = diagnostic.code.as_str();
            let message = diagnostic.message.to_ascii_lowercase();
            if message.contains("unlinked crate")
                || message.contains("unresolved module")
                || message.contains("undeclared crate")
            {
                missing_dependency = missing_dependency.saturating_add(1);
            }
            if matches!(
                code,
                "E0432" | "E0433" | "E0422" | "E0425" | "E0560" | "E0599" | "E0308"
            ) || message.contains("unresolved import")
                || message.contains("cannot find")
                || message.contains("no field named")
                || message.contains("no method named")
                || message.contains("mismatched types")
            {
                api_mismatch = api_mismatch.saturating_add(1);
            }
            if code.starts_with("E05")
                && (message.contains("borrow")
                    || message.contains("moved")
                    || message.contains("lifetime"))
            {
                borrow_checker = borrow_checker.saturating_add(1);
            }
            if message.contains("linking with")
                || message.contains("linker")
                || message.contains("unresolved external")
            {
                linker = linker.saturating_add(1);
            }
            if matches!(code, "E0061" | "E0070" | "E0106" | "E0423") {
                syntax = syntax.saturating_add(1);
            }
        }

        if self.errors >= 3 && api_mismatch >= 3 {
            RepairFailureClass::DependencyApiMismatch
        } else if missing_dependency > 0 {
            RepairFailureClass::MissingDependency
        } else if borrow_checker > 0 {
            RepairFailureClass::BorrowChecker
        } else if linker > 0 {
            RepairFailureClass::Linker
        } else if syntax > 0 {
            RepairFailureClass::CompilerSyntax
        } else {
            RepairFailureClass::Unknown
        }
    }

    pub fn missing_dependency_candidates(&self) -> Vec<String> {
        let mut packages = BTreeSet::new();
        for diagnostic in &self.diagnostics {
            extract_backticked_dependency_candidates(&diagnostic.message, &mut packages);
        }
        extract_backticked_dependency_candidates(&self.raw_log, &mut packages);
        packages.into_iter().collect()
    }

    pub fn recommended_strategy(&self) -> RepairStrategy {
        match self.failure_class() {
            RepairFailureClass::Formatter => RepairStrategy::Mechanical,
            RepairFailureClass::DependencyApiMismatch if self.errors >= 4 => {
                RepairStrategy::Reconstruction
            }
            RepairFailureClass::DependencyApiMismatch
            | RepairFailureClass::MissingDependency
            | RepairFailureClass::Linker => RepairStrategy::Structural,
            _ if self.errors <= 2 => RepairStrategy::Surgical,
            _ => RepairStrategy::Structural,
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct VerificationDelta {
    pub previous_errors: usize,
    pub current_errors: usize,
    pub previous_warnings: usize,
    pub current_warnings: usize,
    pub resolved: usize,
    pub introduced: usize,
    pub improved: bool,
    pub regressed: bool,
    pub unchanged: bool,
}

impl VerificationDelta {
    pub fn between(previous: Option<&DiagnosticSnapshot>, current: &DiagnosticSnapshot) -> Self {
        let Some(previous) = previous else {
            return Self {
                current_errors: current.errors,
                current_warnings: current.warnings,
                ..Self::default()
            };
        };
        let previous_ids = previous
            .diagnostics
            .iter()
            .map(RepairDiagnostic::identity)
            .collect::<BTreeSet<_>>();
        let current_ids = current
            .diagnostics
            .iter()
            .map(RepairDiagnostic::identity)
            .collect::<BTreeSet<_>>();
        let resolved = previous_ids.difference(&current_ids).count();
        let introduced = current_ids.difference(&previous_ids).count();
        let improved = current.errors < previous.errors
            || (current.errors == previous.errors && current.warnings < previous.warnings)
            || (resolved > introduced && current.errors <= previous.errors);
        let regressed = current.errors > previous.errors
            || (current.errors == previous.errors && current.warnings > previous.warnings)
            || (introduced > resolved && current.errors >= previous.errors);
        let unchanged = current.errors == previous.errors
            && current.warnings == previous.warnings
            && resolved == 0
            && introduced == 0;
        Self {
            previous_errors: previous.errors,
            current_errors: current.errors,
            previous_warnings: previous.warnings,
            current_warnings: current.warnings,
            resolved,
            introduced,
            improved,
            regressed,
            unchanged,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RepairDossier {
    pub schema_version: u32,
    pub id: String,
    pub project: String,
    pub goal: String,
    pub attempt: usize,
    pub maximum_attempts: usize,
    pub failure_class: RepairFailureClass,
    pub strategy: RepairStrategy,
    pub snapshot: DiagnosticSnapshot,
    pub delta: VerificationDelta,
    #[serde(default)]
    pub dependency_evidence: BTreeMap<String, Value>,
}

impl RepairDossier {
    pub fn render_model_context(&self) -> String {
        let mut out = String::from("CORTEX REPAIR DOSSIER\n");
        push_field(&mut out, "Repair", &self.id);
        push_field(&mut out, "Project", &self.project);
        push_field(&mut out, "Goal", &self.goal);
        push_field(&mut out, "Failure class", self.failure_class.label());
        push_field(&mut out, "Strategy", self.strategy.label());
        push_field(
            &mut out,
            "Attempt",
            &format!("{} / {}", self.attempt, self.maximum_attempts),
        );
        push_field(&mut out, "Failed stage", &self.snapshot.failed_stage);
        push_field(
            &mut out,
            "Quality",
            &format!(
                "{} error(s), {} warning(s), fingerprint {}",
                self.snapshot.errors, self.snapshot.warnings, self.snapshot.fingerprint
            ),
        );
        if self.delta.previous_errors > 0 || self.delta.previous_warnings > 0 {
            push_field(
                &mut out,
                "Verification delta",
                &format!(
                    "{} -> {} errors, {} -> {} warnings, {} resolved, {} introduced",
                    self.delta.previous_errors,
                    self.delta.current_errors,
                    self.delta.previous_warnings,
                    self.delta.current_warnings,
                    self.delta.resolved,
                    self.delta.introduced
                ),
            );
        }
        if !self.snapshot.diagnostics.is_empty() {
            out.push_str("Diagnostics:\n");
            for diagnostic in self.snapshot.diagnostics.iter().take(16) {
                out.push_str("- ");
                if !diagnostic.file.is_empty() {
                    out.push_str(&diagnostic.file);
                    if diagnostic.line > 0 {
                        out.push(':');
                        out.push_str(&diagnostic.line.to_string());
                    }
                    out.push(' ');
                }
                if !diagnostic.code.is_empty() {
                    out.push_str(&diagnostic.code);
                    out.push_str(": ");
                }
                out.push_str(diagnostic.message.trim());
                out.push('\n');
            }
        }
        let missing_dependencies = self.snapshot.missing_dependency_candidates();
        if !missing_dependencies.is_empty() {
            out.push_str("Missing dependency candidates:\n");
            for package in missing_dependencies {
                out.push_str("- ");
                out.push_str(&package);
                out.push('\n');
            }
        }
        if !self.snapshot.raw_log.trim().is_empty() {
            out.push_str("Authoritative failure log (bounded):\n```text\n");
            out.push_str(self.snapshot.raw_log.trim_end());
            out.push_str("\n```\n");
        }
        if !self.dependency_evidence.is_empty() {
            out.push_str("Dependency evidence:\n");
            for (package, evidence) in &self.dependency_evidence {
                let serialized = serde_json::to_string(evidence).unwrap_or_default();
                let (bounded, truncated) = bounded_chars(&serialized, 2_000);
                out.push_str("- ");
                out.push_str(package);
                out.push_str(": ");
                out.push_str(&bounded);
                if truncated {
                    out.push_str(" …");
                }
                out.push('\n');
            }
        }
        out.push_str("Controller contract:\n");
        out.push_str(
            "- Treat the dossier as authoritative evidence from the completed quality gate.\n",
        );
        out.push_str("- Produce one coherent candidate repair for the classified failure; do not operate transaction/commit/verification machinery.\n");
        out.push_str("- Reconstruction means replace the incompatible implementation coherently rather than patching compiler errors one at a time.\n");
        out
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RepairProgressStage {
    CapturingEvidence,
    Classifying,
    GroundingDependencies,
    PreparingCandidate,
    ApplyingRepair,
    Verifying,
    RuntimeVerifying,
    ProviderRecovery,
    Completed,
    Blocked,
    Failed,
}

impl RepairProgressStage {
    pub fn label(self) -> &'static str {
        match self {
            Self::CapturingEvidence => "Capturing evidence",
            Self::Classifying => "Classifying failure",
            Self::GroundingDependencies => "Grounding dependencies",
            Self::PreparingCandidate => "Preparing candidate",
            Self::ApplyingRepair => "Applying repair",
            Self::Verifying => "Verifying candidate",
            Self::RuntimeVerifying => "Verifying runtime",
            Self::ProviderRecovery => "Recovering provider",
            Self::Completed => "Completed",
            Self::Blocked => "Blocked",
            Self::Failed => "Failed",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionProgressSnapshot {
    pub stage: RepairProgressStage,
    pub headline: String,
    pub current_action: String,
    #[serde(default)]
    pub next_action: String,
    pub attempt: usize,
    pub maximum_attempts: usize,
    pub errors: usize,
    pub warnings: usize,
}

impl ExecutionProgressSnapshot {
    pub fn render_human(&self) -> String {
        let mut lines = vec![
            self.headline.clone(),
            format!("Stage: {}", self.stage.label()),
            format!("Current: {}", self.current_action),
            format!("Attempt: {} / {}", self.attempt, self.maximum_attempts),
            format!(
                "Quality: {} error(s), {} warning(s)",
                self.errors, self.warnings
            ),
        ];
        if !self.next_action.trim().is_empty() {
            lines.push(format!("Next: {}", self.next_action));
        }
        lines.join("\n")
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ChatControl {
    Compact { focus: Option<String> },
    Context,
    Usage,
}

pub fn parse_chat_control(input: &str) -> Option<ChatControl> {
    let trimmed = input.trim();
    if trimmed.eq_ignore_ascii_case("/context") {
        return Some(ChatControl::Context);
    }
    if trimmed.eq_ignore_ascii_case("/usage") {
        return Some(ChatControl::Usage);
    }
    if trimmed.eq_ignore_ascii_case("/compact") {
        return Some(ChatControl::Compact { focus: None });
    }
    let lower = trimmed.to_ascii_lowercase();
    if let Some(rest) = lower.strip_prefix("/compact focus on ") {
        let original_offset = trimmed.len().saturating_sub(rest.len());
        let focus = trimmed.get(original_offset..).unwrap_or("").trim();
        if !focus.is_empty() {
            return Some(ChatControl::Compact {
                focus: Some(focus.to_string()),
            });
        }
    }
    None
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct CompactionSnapshot {
    pub project_identity: String,
    pub current_goal: String,
    #[serde(default)]
    pub accepted_decisions: Vec<String>,
    #[serde(default)]
    pub modified_files: Vec<String>,
    pub quality_gate_state: String,
    #[serde(default)]
    pub outstanding_failures: Vec<String>,
    pub current_milestone: String,
    #[serde(default)]
    pub evidence: Vec<String>,
    #[serde(default)]
    pub next_actions: Vec<String>,
    #[serde(default)]
    pub user_instructions: Vec<String>,
    #[serde(default)]
    pub focus: Option<String>,
}

impl CompactionSnapshot {
    pub fn render_model_context(&self) -> String {
        let mut out = String::from("CORTEX COMPACTED CONTEXT\n");
        push_field(&mut out, "Project", &self.project_identity);
        push_field(&mut out, "Goal", &self.current_goal);
        push_field(&mut out, "Quality gate", &self.quality_gate_state);
        push_field(&mut out, "Milestone", &self.current_milestone);
        if let Some(focus) = self.focus.as_deref() {
            push_field(&mut out, "Focus", focus);
        }
        push_list(&mut out, "Accepted decisions", &self.accepted_decisions);
        push_list(&mut out, "Modified files", &self.modified_files);
        push_list(&mut out, "Outstanding failures", &self.outstanding_failures);
        push_list(&mut out, "Evidence", &self.evidence);
        push_list(&mut out, "Next actions", &self.next_actions);
        push_list(&mut out, "User instructions", &self.user_instructions);
        out
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CompactionNotice {
    pub created_unix_ms: u128,
    pub before_units: u64,
    pub after_units: u64,
    pub units_label: String,
    #[serde(default)]
    pub focus: Option<String>,
}

impl CompactionNotice {
    pub fn new(
        before_units: u64,
        after_units: u64,
        units_label: impl Into<String>,
        focus: Option<String>,
    ) -> Self {
        Self {
            created_unix_ms: unix_ms(),
            before_units,
            after_units,
            units_label: units_label.into(),
            focus,
        }
    }

    pub fn render_chat_markdown(&self) -> String {
        let mut text = format!(
            "**Context compacted**\n\nActive context reduced from {} → {} {}. Full conversation history remains preserved.",
            self.before_units, self.after_units, self.units_label
        );
        if let Some(focus) = self.focus.as_deref() {
            text.push_str("\n\nFocus: ");
            text.push_str(focus);
        }
        text
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionCompletionSummary {
    pub success: bool,
    pub elapsed_ms: u128,
    #[serde(default)]
    pub changed_files: Vec<String>,
    #[serde(default)]
    pub verification: Vec<String>,
    #[serde(default)]
    pub artifacts: Vec<String>,
    pub result: String,
    #[serde(default)]
    pub next_actions: Vec<String>,
}

impl ExecutionCompletionSummary {
    pub fn render_chat_markdown(&self) -> String {
        let heading = if self.success { "Completed" } else { "Stopped" };
        let mut out = format!("**{heading}**\n\nElapsed: {} ms", self.elapsed_ms);
        push_markdown_list(&mut out, "Changed", &self.changed_files);
        push_markdown_list(&mut out, "Verification", &self.verification);
        push_markdown_list(&mut out, "Artifacts", &self.artifacts);
        if !self.result.trim().is_empty() {
            out.push_str("\n\n**Result**\n");
            out.push_str(self.result.trim());
        }
        push_markdown_list(&mut out, "Next", &self.next_actions);
        out
    }
}

fn command_equivalent(left: &CommandSpec, right: &CommandSpec) -> bool {
    left.program.eq_ignore_ascii_case(&right.program) && left.args == right.args
}

fn shell_display_argument(argument: &str) -> String {
    if argument
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || "-_./\\:".contains(ch))
    {
        argument.to_string()
    } else {
        format!("\"{}\"", argument.replace('"', "\\\""))
    }
}

fn extract_backticked_dependency_candidates(text: &str, out: &mut BTreeSet<String>) {
    let lower = text.to_ascii_lowercase();
    let dependency_context = lower.contains("unlinked crate")
        || lower.contains("unresolved module")
        || lower.contains("undeclared crate")
        || lower.contains("use of unresolved module");
    if !dependency_context {
        return;
    }
    let mut cursor = text;
    while let Some(start) = cursor.find('`') {
        let rest = &cursor[start + 1..];
        let Some(end) = rest.find('`') else {
            break;
        };
        let candidate = &rest[..end];
        if !candidate.is_empty()
            && candidate.chars().all(|character| {
                character.is_ascii_alphanumeric() || matches!(character, '-' | '_')
            })
        {
            out.insert(candidate.replace('_', "-"));
        }
        cursor = &rest[end + 1..];
    }
}

fn stable_evidence_hash(text: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in text.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

fn bounded_chars(text: &str, max_chars: usize) -> (String, bool) {
    let count = text.chars().count();
    if count <= max_chars {
        return (text.to_string(), false);
    }
    (text.chars().take(max_chars).collect(), true)
}

fn push_field(out: &mut String, label: &str, value: &str) {
    if value.trim().is_empty() {
        return;
    }
    out.push_str(label);
    out.push_str(": ");
    out.push_str(value.trim());
    out.push('\n');
}

fn push_list(out: &mut String, label: &str, values: &[String]) {
    if values.is_empty() {
        return;
    }
    out.push_str(label);
    out.push_str(":\n");
    for value in values {
        out.push_str("- ");
        out.push_str(value.trim());
        out.push('\n');
    }
}

fn push_markdown_list(out: &mut String, label: &str, values: &[String]) {
    if values.is_empty() {
        return;
    }
    out.push_str("\n\n**");
    out.push_str(label);
    out.push_str("**\n");
    for value in values {
        out.push_str("- ");
        out.push_str(value.trim());
        out.push('\n');
    }
    while out.ends_with('\n') {
        out.pop();
    }
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
    fn rust_format_failure_is_mechanically_repaired_without_model_budget() {
        let failure = QualityGateFailure {
            stage: QualityGateStage::Format,
            command: CommandSpec::new("cargo", ["fmt", "--", "--check"]),
            exit_code: Some(1),
            stdout: "Diff in src/main.rs:79:\n }\n+\n".into(),
            stderr: String::new(),
        };
        let plan = plan_quality_gate_remediation(&failure, &default_formatter_specs());
        assert_eq!(plan.kind, RemediationKind::DeterministicFormatter);
        assert!(!plan.consumes_model_attempt);
        assert_eq!(plan.action.unwrap(), CommandSpec::new("cargo", ["fmt"]));
        assert_eq!(
            plan.recheck.unwrap(),
            CommandSpec::new("cargo", ["fmt", "--", "--check"])
        );
    }

    #[test]
    fn rust_format_check_has_a_deterministic_preflight_action() {
        let action =
            deterministic_preflight_remediation("cargo", &["fmt", "--", "--check"]).unwrap();
        assert_eq!(action, CommandSpec::new("cargo", ["fmt"]));
        let workspace_action =
            deterministic_preflight_remediation("cargo", &["fmt", "--all", "--", "--check"])
                .unwrap();
        assert_eq!(
            workspace_action,
            CommandSpec::new("cargo", ["fmt", "--all"])
        );
        assert!(deterministic_preflight_remediation("cargo", &["fmt"]).is_none());
        assert!(deterministic_preflight_remediation("cargo", &["check"]).is_none());
    }

    #[test]
    fn unknown_failure_retains_model_repair_budget_semantics() {
        let failure = QualityGateFailure {
            stage: QualityGateStage::Build,
            command: CommandSpec::new("cargo", ["build"]),
            exit_code: Some(101),
            stdout: String::new(),
            stderr: "compiler error".into(),
        };
        let plan = plan_quality_gate_remediation(&failure, &default_formatter_specs());
        assert_eq!(plan.kind, RemediationKind::ModelRepair);
        assert!(plan.consumes_model_attempt);
        assert!(plan.action.is_none());
    }

    #[test]
    fn compact_controls_are_natural_and_focus_aware() {
        assert_eq!(
            parse_chat_control("/compact"),
            Some(ChatControl::Compact { focus: None })
        );
        assert_eq!(
            parse_chat_control("/compact focus on current clock repair"),
            Some(ChatControl::Compact {
                focus: Some("current clock repair".into())
            })
        );
        assert_eq!(parse_chat_control("/context"), Some(ChatControl::Context));
        assert_eq!(parse_chat_control("/usage"), Some(ChatControl::Usage));
    }

    #[test]
    fn transcript_renders_safe_operational_evidence_not_hidden_reasoning() {
        let mut entry = ExecutionTranscriptEntry::new(
            ExecutionPhase::Build,
            "Building project",
            "Running the selected project's configured build command.",
        );
        entry.command = Some("cargo build".into());
        entry.snippet = Some(SafeSnippet::bounded(
            SnippetKind::Output,
            "text",
            "Finished dev profile",
            100,
        ));
        let rendered = entry.render_chat_markdown();
        assert!(rendered.contains("Building project"));
        assert!(rendered.contains("cargo build"));
        assert!(rendered.contains("Finished dev profile"));
        assert!(!rendered.to_ascii_lowercase().contains("chain-of-thought"));
    }

    #[test]
    fn provider_heartbeat_detects_stall_without_guessing_completion() {
        let heartbeat = ProviderHeartbeat {
            started_unix_ms: 1_000,
            last_event_unix_ms: 5_000,
            provider: "Native Models".into(),
            model: "test-model".into(),
            context_used: Some(8_000),
            context_limit: Some(16_384),
        };
        assert!(!heartbeat.appears_stalled(94_999, DEFAULT_STALL_WARNING_MS));
        assert!(heartbeat.appears_stalled(95_000, DEFAULT_STALL_WARNING_MS));
    }

    #[test]
    fn api_mismatch_snapshot_escalates_to_reconstruction() {
        let gate = serde_json::json!({
            "success": false,
            "stages": [{
                "capability": "validate",
                "success": false,
                "result": {
                    "source_revision": 7,
                    "cortex_candidate": {"quality_fingerprint": "abc"},
                    "cortex_quality": {"current": {"errors": 5, "warnings": 1}},
                    "diagnostics": [
                        {"level":"error","code":"E0432","file":"src/main.rs","line_start":5,"message":"unresolved import `wgpu::SurfaceOutputView`"},
                        {"level":"error","code":"E0433","file":"src/main.rs","line_start":6,"message":"cannot find `BackendFlags` in `wgpu`"},
                        {"level":"error","code":"E0599","file":"src/main.rs","line_start":7,"message":"no method named `create_render_pass` found"},
                        {"level":"error","code":"E0560","file":"src/main.rs","line_start":8,"message":"struct has no field named `color_state`"},
                        {"level":"error","code":"E0308","file":"src/main.rs","line_start":9,"message":"mismatched types"}
                    ]
                }
            }]
        });
        let snapshot = DiagnosticSnapshot::from_quality_gate(&gate);
        assert_eq!(snapshot.source_revision, 7);
        assert_eq!(
            snapshot.failure_class(),
            RepairFailureClass::DependencyApiMismatch
        );
        assert_eq!(
            snapshot.recommended_strategy(),
            RepairStrategy::Reconstruction
        );
    }

    #[test]
    fn checkpoint_log_is_preserved_and_missing_dependencies_are_extractable() {
        let gate = serde_json::json!({
            "success": false,
            "stages": [{
                "capability": "checkpoint",
                "success": false,
                "result": {
                    "source_revision": 9,
                    "success": false,
                    "checkpoint_log": "error[E0433]: use of unresolved module or unlinked crate `winit`"
                }
            }]
        });
        let snapshot = DiagnosticSnapshot::from_quality_gate(&gate);
        assert!(snapshot.raw_log.contains("winit"));
        assert_eq!(
            snapshot.missing_dependency_candidates(),
            vec!["winit".to_string()]
        );
        assert!(snapshot.fingerprint.starts_with("checkpoint-"));
        assert_ne!(snapshot.fingerprint, "unavailable");
    }

    #[test]
    fn checkpoint_raw_log_can_drive_structural_api_mismatch_reconstruction() {
        let gate = serde_json::json!({
            "success": false,
            "stages": [{
                "capability": "checkpoint",
                "success": false,
                "result": {
                    "source_revision": 4,
                    "success": false,
                    "checkpoint_log": concat!(
                        "error[E0432]: unresolved import `wgpu::SurfaceOutputView`\n",
                        "error[E0599]: no method named `create_render_pass` found\n",
                        "error[E0433]: could not find `BackendFlags` in `wgpu`\n",
                        "error[E0308]: mismatched types\n"
                    )
                }
            }]
        });
        let snapshot = DiagnosticSnapshot::from_quality_gate(&gate);
        assert_eq!(
            snapshot.failure_class(),
            RepairFailureClass::DependencyApiMismatch
        );
        assert_eq!(
            snapshot.recommended_strategy(),
            RepairStrategy::Reconstruction
        );
    }

    #[test]
    fn verification_delta_reports_real_improvement() {
        let previous = DiagnosticSnapshot {
            schema_version: 1,
            source_revision: 1,
            failed_stage: "validate".into(),
            errors: 3,
            warnings: 1,
            fingerprint: "before".into(),
            diagnostics: vec![
                RepairDiagnostic {
                    level: "error".into(),
                    code: "E1".into(),
                    file: "a.rs".into(),
                    line: 1,
                    message: "one".into(),
                },
                RepairDiagnostic {
                    level: "error".into(),
                    code: "E2".into(),
                    file: "a.rs".into(),
                    line: 2,
                    message: "two".into(),
                },
                RepairDiagnostic {
                    level: "error".into(),
                    code: "E3".into(),
                    file: "a.rs".into(),
                    line: 3,
                    message: "three".into(),
                },
            ],
            raw_log: String::new(),
        };
        let current = DiagnosticSnapshot {
            schema_version: 1,
            source_revision: 2,
            failed_stage: "validate".into(),
            errors: 1,
            warnings: 0,
            fingerprint: "after".into(),
            diagnostics: vec![RepairDiagnostic {
                level: "error".into(),
                code: "E3".into(),
                file: "a.rs".into(),
                line: 3,
                message: "three".into(),
            }],
            raw_log: String::new(),
        };
        let delta = VerificationDelta::between(Some(&previous), &current);
        assert!(delta.improved);
        assert!(!delta.regressed);
        assert_eq!(delta.resolved, 2);
        assert_eq!(delta.introduced, 0);
    }

    #[test]
    fn repair_progress_snapshot_is_human_readable() {
        let progress = ExecutionProgressSnapshot {
            stage: RepairProgressStage::GroundingDependencies,
            headline: "Repairing hello3d".into(),
            current_action: "Grounding wgpu 0.19.4".into(),
            next_action: "Prepare reconstruction".into(),
            attempt: 1,
            maximum_attempts: 5,
            errors: 15,
            warnings: 2,
        };
        let rendered = progress.render_human();
        assert!(rendered.contains("Grounding dependencies"));
        assert!(rendered.contains("15 error(s), 2 warning(s)"));
        assert!(rendered.contains("Prepare reconstruction"));
    }

    #[test]
    fn compaction_notice_explicitly_preserves_full_history() {
        let notice = CompactionNotice {
            created_unix_ms: 1,
            before_units: 14_900,
            after_units: 4_200,
            units_label: "tokens".into(),
            focus: Some("current repair".into()),
        };
        let rendered = notice.render_chat_markdown();
        assert!(rendered.contains("Full conversation history remains preserved"));
        assert!(rendered.contains("current repair"));
    }
}
