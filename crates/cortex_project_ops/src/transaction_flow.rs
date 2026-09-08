//! Typed Plan -> Validate -> Apply -> Verify -> Recover orchestration.
//!
//! Source mutations are delegated to `cortex_transactions::TransactionManager`.
//! Project concurrency is delegated to the project execution lease authority in
//! this crate.  This module coordinates the two; it does not implement a second
//! source backup/rollback engine.

use crate::{ProjectExecutionLeaseStore, ProjectLeaseMode};
use cortex_project::{
    OperationDiagnostic, OperationResult, ProjectOperation, ProjectOperationState,
    PROJECT_SPINE_SCHEMA_VERSION,
};
use cortex_transactions::TransactionManager;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub const PROJECT_TRANSACTION_FLOW_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ProjectMutation {
    Checkpoint {
        path: PathBuf,
    },
    WriteText {
        path: PathBuf,
        content: String,
    },
    ReplaceText {
        path: PathBuf,
        old: String,
        new: String,
        expected: usize,
    },
}

impl ProjectMutation {
    pub fn path(&self) -> &Path {
        match self {
            Self::Checkpoint { path }
            | Self::WriteText { path, .. }
            | Self::ReplaceText { path, .. } => path,
        }
    }

    pub fn kind_name(&self) -> &'static str {
        match self {
            Self::Checkpoint { .. } => "checkpoint",
            Self::WriteText { .. } => "write_text",
            Self::ReplaceText { .. } => "replace_text",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectTransactionPlan {
    pub schema_version: u32,
    pub id: String,
    pub operation: ProjectOperation,
    pub label: String,
    #[serde(default)]
    pub mutations: Vec<ProjectMutation>,
    #[serde(default)]
    pub required_paths: Vec<PathBuf>,
    #[serde(default)]
    pub forbidden_paths: Vec<PathBuf>,
    #[serde(default)]
    pub created_unix_ms: u128,
}

impl ProjectTransactionPlan {
    pub fn new(
        id: impl Into<String>,
        operation: ProjectOperation,
        label: impl Into<String>,
    ) -> Result<Self, String> {
        let id = id.into().trim().to_string();
        let label = label.into().trim().to_string();
        if id.is_empty() {
            return Err("project transaction plan id cannot be empty".into());
        }
        if label.is_empty() {
            return Err("project transaction plan label cannot be empty".into());
        }

        Ok(Self {
            schema_version: PROJECT_TRANSACTION_FLOW_SCHEMA_VERSION,
            id,
            operation,
            label,
            mutations: Vec::new(),
            required_paths: Vec::new(),
            forbidden_paths: Vec::new(),
            created_unix_ms: unix_millis(),
        })
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProjectTransactionPhase {
    Planned,
    Validating,
    Validated,
    Applying,
    Verifying,
    Recovering,
    Committed,
    RolledBack,
    Failed,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectTransactionJournalEntry {
    pub phase: ProjectTransactionPhase,
    pub message: String,
    pub created_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct MutationSummary {
    pub kind: String,
    pub path: PathBuf,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct VerificationCheck {
    pub key: String,
    pub passed: bool,
    #[serde(default)]
    pub detail: String,
}

impl VerificationCheck {
    pub fn pass(key: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            key: key.into(),
            passed: true,
            detail: detail.into(),
        }
    }

    pub fn fail(key: impl Into<String>, detail: impl Into<String>) -> Self {
        Self {
            key: key.into(),
            passed: false,
            detail: detail.into(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectTransactionJournal {
    pub schema_version: u32,
    pub plan_id: String,
    pub operation_id: String,
    pub project_id: String,
    #[serde(default)]
    pub source_transaction_id: Option<String>,
    #[serde(default)]
    pub mutations: Vec<MutationSummary>,
    #[serde(default)]
    pub verification: Vec<VerificationCheck>,
    #[serde(default)]
    pub entries: Vec<ProjectTransactionJournalEntry>,
    pub rollback_attempted: bool,
    pub rollback_succeeded: bool,
    #[serde(default)]
    pub result: Option<OperationResult>,
    pub updated_unix_ms: u128,
}

impl ProjectTransactionJournal {
    fn new(plan: &ProjectTransactionPlan) -> Self {
        let mut journal = Self {
            schema_version: PROJECT_TRANSACTION_FLOW_SCHEMA_VERSION,
            plan_id: plan.id.clone(),
            operation_id: plan.operation.id.clone(),
            project_id: plan.operation.project_id.to_string(),
            source_transaction_id: None,
            mutations: plan
                .mutations
                .iter()
                .map(|mutation| MutationSummary {
                    kind: mutation.kind_name().into(),
                    path: mutation.path().to_path_buf(),
                })
                .collect(),
            verification: Vec::new(),
            entries: Vec::new(),
            rollback_attempted: false,
            rollback_succeeded: false,
            result: None,
            updated_unix_ms: unix_millis(),
        };
        journal.push(
            ProjectTransactionPhase::Planned,
            "Project transaction plan accepted for validation",
        );
        journal
    }

    fn push(&mut self, phase: ProjectTransactionPhase, message: impl Into<String>) {
        let now = unix_millis();
        self.entries.push(ProjectTransactionJournalEntry {
            phase,
            message: message.into(),
            created_unix_ms: now,
        });
        self.updated_unix_ms = now;
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectTransactionOutcome {
    pub plan_id: String,
    #[serde(default)]
    pub source_transaction_id: Option<String>,
    pub committed: bool,
    pub rolled_back: bool,
    #[serde(default)]
    pub verification: Vec<VerificationCheck>,
    pub operation_result: OperationResult,
    pub journal_path: PathBuf,
}

pub struct ProjectTransactionEngine {
    project_root: PathBuf,
    state_root: PathBuf,
    lease_store: ProjectExecutionLeaseStore,
}

impl ProjectTransactionEngine {
    pub fn new(
        project_root: impl AsRef<Path>,
        state_root: impl AsRef<Path>,
    ) -> Result<Self, String> {
        let project_root = fs::canonicalize(project_root.as_ref()).map_err(|error| {
            format!(
                "failed to resolve project transaction root {}: {error}",
                project_root.as_ref().display()
            )
        })?;
        if !project_root.is_dir() {
            return Err(format!(
                "project transaction root is not a directory: {}",
                project_root.display()
            ));
        }

        let state_root = state_root.as_ref().to_path_buf();
        fs::create_dir_all(&state_root).map_err(|error| {
            format!(
                "failed to create project transaction state root {}: {error}",
                state_root.display()
            )
        })?;

        Ok(Self {
            project_root,
            lease_store: ProjectExecutionLeaseStore::new(&state_root),
            state_root,
        })
    }

    pub fn project_root(&self) -> &Path {
        &self.project_root
    }

    pub fn state_root(&self) -> &Path {
        &self.state_root
    }

    pub fn validate_plan(&self, plan: &ProjectTransactionPlan) -> Result<(), Vec<String>> {
        let mut errors = Vec::new();

        if plan.schema_version != PROJECT_TRANSACTION_FLOW_SCHEMA_VERSION {
            errors.push(format!(
                "unsupported project transaction plan schema {}",
                plan.schema_version
            ));
        }
        if plan.id.trim().is_empty() {
            errors.push("project transaction plan id cannot be empty".into());
        }
        if plan.operation.id.trim().is_empty() {
            errors.push("project operation id cannot be empty".into());
        }
        if plan.operation.command_key.trim().is_empty() {
            errors.push("project operation command key cannot be empty".into());
        }
        if plan.label.trim().is_empty() {
            errors.push("project transaction plan label cannot be empty".into());
        }
        if plan.mutations.is_empty() {
            errors.push("project transaction plan contains no mutations".into());
        }

        let mut seen_paths = BTreeSet::<PathBuf>::new();
        for mutation in &plan.mutations {
            let path = mutation.path();
            if let Err(error) = validate_relative_project_path(path) {
                errors.push(error);
            }
            if !seen_paths.insert(path.to_path_buf()) {
                errors.push(format!(
                    "project transaction plan mutates the same path more than once: {}",
                    path.display()
                ));
            }
            if let ProjectMutation::ReplaceText { old, expected, .. } = mutation {
                if old.is_empty() {
                    errors.push(format!(
                        "replace mutation has an empty match string: {}",
                        path.display()
                    ));
                }
                if *expected == 0 {
                    errors.push(format!(
                        "replace mutation expected count must be at least 1: {}",
                        path.display()
                    ));
                }
            }
        }

        for path in plan
            .required_paths
            .iter()
            .chain(plan.forbidden_paths.iter())
        {
            if let Err(error) = validate_relative_project_path(path) {
                errors.push(error);
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }

    pub fn execute<V>(
        &self,
        plan: &ProjectTransactionPlan,
        mut verifier: V,
    ) -> Result<ProjectTransactionOutcome, String>
    where
        V: FnMut(&Path) -> Result<Vec<VerificationCheck>, String>,
    {
        let started = Instant::now();
        let mut journal = ProjectTransactionJournal::new(plan);
        let journal_path = self.journal_path(&plan.id);

        journal.push(
            ProjectTransactionPhase::Validating,
            "Validating project transaction invariants",
        );
        self.persist_journal(&journal_path, &journal)?;

        if let Err(errors) = self.validate_plan(plan) {
            let message = errors.join("; ");
            journal.push(ProjectTransactionPhase::Failed, message.clone());
            let result = OperationResult::failed(
                &plan.operation,
                None,
                format!("project transaction validation failed: {message}"),
                elapsed_ms(started),
            );
            journal.result = Some(result.clone());
            self.persist_journal(&journal_path, &journal)?;
            return Ok(ProjectTransactionOutcome {
                plan_id: plan.id.clone(),
                source_transaction_id: None,
                committed: false,
                rolled_back: false,
                verification: Vec::new(),
                operation_result: result,
                journal_path,
            });
        }

        self.validate_preconditions(plan)?;
        journal.push(
            ProjectTransactionPhase::Validated,
            "Project transaction validation passed",
        );
        self.persist_journal(&journal_path, &journal)?;

        let _lease = self.lease_store.acquire(
            Some(plan.operation.project_id.clone()),
            &self.project_root,
            &plan.operation.id,
            ProjectLeaseMode::ExclusiveWrite,
        )?;

        let mut manager = TransactionManager::new(&self.project_root, &self.state_root)?;
        if let Some(active) = manager.active_id() {
            return Err(format!(
                "project contains an active source transaction {active}; recover it before starting {}",
                plan.id
            ));
        }

        let source_transaction_id = manager.begin(&plan.label)?;
        journal.source_transaction_id = Some(source_transaction_id.clone());
        journal.push(
            ProjectTransactionPhase::Applying,
            format!(
                "Applying {} mutation(s) under reversible source transaction {}",
                plan.mutations.len(),
                source_transaction_id
            ),
        );
        self.persist_journal(&journal_path, &journal)?;

        for mutation in &plan.mutations {
            if let Err(error) = apply_mutation(&mut manager, mutation) {
                journal.push(
                    ProjectTransactionPhase::Recovering,
                    format!(
                        "Mutation {} failed for {}; rolling back: {error}",
                        mutation.kind_name(),
                        mutation.path().display()
                    ),
                );
                return self.rollback_after_failure(
                    plan,
                    manager,
                    journal,
                    journal_path,
                    source_transaction_id,
                    "apply_failed",
                    error,
                    Vec::new(),
                    started,
                );
            }
        }

        journal.push(
            ProjectTransactionPhase::Verifying,
            "All planned mutations applied; running verification",
        );
        self.persist_journal(&journal_path, &journal)?;

        let verification = match verifier(&self.project_root) {
            Ok(checks) => checks,
            Err(error) => {
                journal.push(
                    ProjectTransactionPhase::Recovering,
                    format!("Verification execution failed; rolling back: {error}"),
                );
                return self.rollback_after_failure(
                    plan,
                    manager,
                    journal,
                    journal_path,
                    source_transaction_id,
                    "verification_error",
                    error,
                    Vec::new(),
                    started,
                );
            }
        };

        journal.verification = verification.clone();
        let failed_checks = verification
            .iter()
            .filter(|check| !check.passed)
            .cloned()
            .collect::<Vec<_>>();

        if !failed_checks.is_empty() {
            journal.push(
                ProjectTransactionPhase::Recovering,
                format!(
                    "{} verification check(s) failed; rolling back",
                    failed_checks.len()
                ),
            );
            let detail = failed_checks
                .iter()
                .map(|check| format!("{}: {}", check.key, check.detail))
                .collect::<Vec<_>>()
                .join("; ");
            return self.rollback_after_failure(
                plan,
                manager,
                journal,
                journal_path,
                source_transaction_id,
                "verification_failed",
                detail,
                verification,
                started,
            );
        }

        let committed_id = manager
            .commit()?
            .ok_or_else(|| "source transaction disappeared before commit".to_string())?;

        journal.push(
            ProjectTransactionPhase::Committed,
            format!("Source transaction {committed_id} committed after verification"),
        );
        let mut result = OperationResult::succeeded(&plan.operation, elapsed_ms(started));
        result.artifacts.push(journal_path.clone());
        journal.result = Some(result.clone());
        self.persist_journal(&journal_path, &journal)?;

        Ok(ProjectTransactionOutcome {
            plan_id: plan.id.clone(),
            source_transaction_id: Some(committed_id),
            committed: true,
            rolled_back: false,
            verification,
            operation_result: result,
            journal_path,
        })
    }

    pub fn recover_active(
        &self,
        operation: &ProjectOperation,
    ) -> Result<Option<ProjectTransactionOutcome>, String> {
        let started = Instant::now();
        let _lease = self.lease_store.acquire(
            Some(operation.project_id.clone()),
            &self.project_root,
            &operation.id,
            ProjectLeaseMode::ExclusiveWrite,
        )?;

        let mut manager = TransactionManager::new(&self.project_root, &self.state_root)?;
        let Some(active_id) = manager.active_id().map(str::to_string) else {
            return Ok(None);
        };

        let recovery_plan_id = format!("recover-{active_id}");
        let journal_path = self.journal_path(&recovery_plan_id);
        let mut journal = ProjectTransactionJournal {
            schema_version: PROJECT_TRANSACTION_FLOW_SCHEMA_VERSION,
            plan_id: recovery_plan_id.clone(),
            operation_id: operation.id.clone(),
            project_id: operation.project_id.to_string(),
            source_transaction_id: Some(active_id.clone()),
            mutations: Vec::new(),
            verification: Vec::new(),
            entries: Vec::new(),
            rollback_attempted: true,
            rollback_succeeded: false,
            result: None,
            updated_unix_ms: unix_millis(),
        };
        journal.push(
            ProjectTransactionPhase::Recovering,
            format!("Recovering abandoned active source transaction {active_id}"),
        );

        let rolled_back_id = manager
            .rollback()?
            .ok_or_else(|| "active source transaction disappeared during recovery".to_string())?;
        journal.rollback_succeeded = true;
        journal.push(
            ProjectTransactionPhase::RolledBack,
            format!("Abandoned source transaction {rolled_back_id} rolled back"),
        );

        let result = OperationResult {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            operation_id: operation.id.clone(),
            project_id: operation.project_id.clone(),
            command_key: operation.command_key.clone(),
            state: ProjectOperationState::RolledBack,
            exit_code: None,
            elapsed_ms: elapsed_ms(started),
            artifacts: vec![journal_path.clone()],
            diagnostics: vec![OperationDiagnostic {
                code: "abandoned_transaction_recovered".into(),
                message: format!(
                    "Recovered and rolled back abandoned source transaction {rolled_back_id}"
                ),
                path: None,
            }],
        };
        journal.result = Some(result.clone());
        self.persist_journal(&journal_path, &journal)?;

        Ok(Some(ProjectTransactionOutcome {
            plan_id: recovery_plan_id,
            source_transaction_id: Some(rolled_back_id),
            committed: false,
            rolled_back: true,
            verification: Vec::new(),
            operation_result: result,
            journal_path,
        }))
    }

    fn validate_preconditions(&self, plan: &ProjectTransactionPlan) -> Result<(), String> {
        for relative in &plan.required_paths {
            let path = self.project_root.join(relative);
            if !path.exists() {
                return Err(format!(
                    "required project path does not exist: {}",
                    relative.display()
                ));
            }
        }
        for relative in &plan.forbidden_paths {
            let path = self.project_root.join(relative);
            if path.exists() {
                return Err(format!(
                    "forbidden project path already exists: {}",
                    relative.display()
                ));
            }
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn rollback_after_failure(
        &self,
        plan: &ProjectTransactionPlan,
        mut manager: TransactionManager,
        mut journal: ProjectTransactionJournal,
        journal_path: PathBuf,
        source_transaction_id: String,
        code: &str,
        message: String,
        verification: Vec<VerificationCheck>,
        started: Instant,
    ) -> Result<ProjectTransactionOutcome, String> {
        journal.rollback_attempted = true;
        self.persist_journal(&journal_path, &journal)?;

        let rollback = manager.rollback();
        journal.rollback_succeeded = rollback.is_ok();
        match &rollback {
            Ok(Some(transaction)) => journal.push(
                ProjectTransactionPhase::RolledBack,
                format!("Source transaction {transaction} rolled back"),
            ),
            Ok(None) => journal.push(
                ProjectTransactionPhase::Failed,
                "Rollback was requested but no active source transaction remained",
            ),
            Err(error) => journal.push(
                ProjectTransactionPhase::Failed,
                format!("Source rollback failed: {error}"),
            ),
        }

        let rollback_message = match rollback {
            Ok(Some(transaction)) => {
                format!("{message}; source transaction {transaction} was rolled back")
            }
            Ok(None) => format!("{message}; no active source transaction remained to roll back"),
            Err(error) => format!("{message}; rollback also failed: {error}"),
        };

        let result = OperationResult {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            operation_id: plan.operation.id.clone(),
            project_id: plan.operation.project_id.clone(),
            command_key: plan.operation.command_key.clone(),
            state: if journal.rollback_succeeded {
                ProjectOperationState::RolledBack
            } else {
                ProjectOperationState::Failed
            },
            exit_code: None,
            elapsed_ms: elapsed_ms(started),
            artifacts: vec![journal_path.clone()],
            diagnostics: vec![OperationDiagnostic {
                code: code.into(),
                message: rollback_message,
                path: None,
            }],
        };
        journal.result = Some(result.clone());
        journal.verification = verification.clone();
        self.persist_journal(&journal_path, &journal)?;

        Ok(ProjectTransactionOutcome {
            plan_id: plan.id.clone(),
            source_transaction_id: Some(source_transaction_id),
            committed: false,
            rolled_back: journal.rollback_succeeded,
            verification,
            operation_result: result,
            journal_path,
        })
    }

    fn journal_path(&self, plan_id: &str) -> PathBuf {
        self.state_root
            .join("project-operations")
            .join(safe_component(plan_id))
            .join("journal.json")
    }

    fn persist_journal(
        &self,
        path: &Path,
        journal: &ProjectTransactionJournal,
    ) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                format!(
                    "failed to create project transaction journal directory {}: {error}",
                    parent.display()
                )
            })?;
        }
        let bytes = serde_json::to_vec_pretty(journal)
            .map_err(|error| format!("failed to encode project transaction journal: {error}"))?;
        let temp = path.with_extension(format!("json.tmp.{}", std::process::id()));
        fs::write(&temp, bytes)
            .map_err(|error| format!("failed to write {}: {error}", temp.display()))?;
        if path.exists() {
            fs::remove_file(path)
                .map_err(|error| format!("failed to replace {}: {error}", path.display()))?;
        }
        fs::rename(&temp, path)
            .map_err(|error| format!("failed to publish {}: {error}", path.display()))
    }
}

fn apply_mutation(
    manager: &mut TransactionManager,
    mutation: &ProjectMutation,
) -> Result<(), String> {
    match mutation {
        ProjectMutation::Checkpoint { path } => manager.checkpoint_path(path),
        ProjectMutation::WriteText { path, content } => manager.write_text(path, content),
        ProjectMutation::ReplaceText {
            path,
            old,
            new,
            expected,
        } => manager
            .replace_text(path, old, new, *expected)
            .map(|_| ()),
    }
}

fn validate_relative_project_path(path: &Path) -> Result<(), String> {
    if path.as_os_str().is_empty() {
        return Err("project transaction path cannot be empty".into());
    }
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(format!(
            "project transaction path must be workspace-relative: {}",
            path.display()
        ));
    }
    Ok(())
}

fn safe_component(value: &str) -> String {
    let value = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.') {
                character
            } else {
                '-'
            }
        })
        .collect::<String>();
    let trimmed = value.trim_matches('-');
    if trimmed.is_empty() {
        "operation".into()
    } else {
        trimmed.chars().take(100).collect()
    }
}

fn elapsed_ms(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX)
}

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use cortex_project::{ProjectId, PROJECT_SPINE_SCHEMA_VERSION};

    fn temp_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "cortex-project-flow-{label}-{}-{}",
            std::process::id(),
            unix_millis()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn operation(id: &str) -> ProjectOperation {
        let mut operation =
            ProjectOperation::new(id, ProjectId::new("cortex").unwrap(), "source.update").unwrap();
        operation.schema_version = PROJECT_SPINE_SCHEMA_VERSION;
        operation
    }

    #[test]
    fn successful_verification_commits_transaction() {
        let project = temp_root("commit-project");
        let state = temp_root("commit-state");
        fs::write(project.join("file.txt"), "before").unwrap();

        let mut plan =
            ProjectTransactionPlan::new("plan-commit", operation("op-commit"), "commit-test")
                .unwrap();
        plan.mutations.push(ProjectMutation::WriteText {
            path: PathBuf::from("file.txt"),
            content: "after".into(),
        });

        let engine = ProjectTransactionEngine::new(&project, &state).unwrap();
        let outcome = engine
            .execute(&plan, |root| {
                let text = fs::read_to_string(root.join("file.txt")).unwrap();
                Ok(vec![VerificationCheck {
                    key: "file-content".into(),
                    passed: text == "after",
                    detail: text,
                }])
            })
            .unwrap();

        assert!(outcome.committed);
        assert!(!outcome.rolled_back);
        assert_eq!(outcome.operation_result.state, ProjectOperationState::Succeeded);
        assert_eq!(fs::read_to_string(project.join("file.txt")).unwrap(), "after");

        let _ = fs::remove_dir_all(project);
        let _ = fs::remove_dir_all(state);
    }

    #[test]
    fn failed_verification_rolls_back_original_bytes() {
        let project = temp_root("rollback-project");
        let state = temp_root("rollback-state");
        fs::write(project.join("file.txt"), "before").unwrap();

        let mut plan =
            ProjectTransactionPlan::new("plan-rollback", operation("op-rollback"), "rollback-test")
                .unwrap();
        plan.mutations.push(ProjectMutation::WriteText {
            path: PathBuf::from("file.txt"),
            content: "after".into(),
        });

        let engine = ProjectTransactionEngine::new(&project, &state).unwrap();
        let outcome = engine
            .execute(&plan, |_| {
                Ok(vec![VerificationCheck::fail(
                    "forced-failure",
                    "verification intentionally failed",
                )])
            })
            .unwrap();

        assert!(!outcome.committed);
        assert!(outcome.rolled_back);
        assert_eq!(
            outcome.operation_result.state,
            ProjectOperationState::RolledBack
        );
        assert_eq!(
            fs::read_to_string(project.join("file.txt")).unwrap(),
            "before"
        );

        let _ = fs::remove_dir_all(project);
        let _ = fs::remove_dir_all(state);
    }

    #[test]
    fn invalid_parent_path_fails_before_mutation() {
        let project = temp_root("unsafe-project");
        let state = temp_root("unsafe-state");

        let mut plan =
            ProjectTransactionPlan::new("plan-unsafe", operation("op-unsafe"), "unsafe-test")
                .unwrap();
        plan.mutations.push(ProjectMutation::WriteText {
            path: PathBuf::from("../escape.txt"),
            content: "bad".into(),
        });

        let engine = ProjectTransactionEngine::new(&project, &state).unwrap();
        let outcome = engine
            .execute(&plan, |_| Ok(vec![VerificationCheck::pass("unused", "unused")]))
            .unwrap();

        assert_eq!(outcome.operation_result.state, ProjectOperationState::Failed);
        assert!(!outcome.committed);
        assert!(!outcome.rolled_back);

        let _ = fs::remove_dir_all(project);
        let _ = fs::remove_dir_all(state);
    }

    #[test]
    fn abandoned_source_transaction_can_be_recovered() {
        let project = temp_root("recover-project");
        let state = temp_root("recover-state");
        fs::write(project.join("file.txt"), "before").unwrap();

        {
            let mut manager = TransactionManager::new(&project, &state).unwrap();
            manager.begin("abandoned").unwrap();
            manager.write_text("file.txt", "after").unwrap();
        }

        assert_eq!(fs::read_to_string(project.join("file.txt")).unwrap(), "after");

        let engine = ProjectTransactionEngine::new(&project, &state).unwrap();
        let outcome = engine
            .recover_active(&operation("op-recover"))
            .unwrap()
            .expect("active transaction should be recovered");

        assert!(outcome.rolled_back);
        assert_eq!(
            fs::read_to_string(project.join("file.txt")).unwrap(),
            "before"
        );

        let _ = fs::remove_dir_all(project);
        let _ = fs::remove_dir_all(state);
    }

    #[test]
    fn duplicate_mutation_target_is_rejected() {
        let project = temp_root("duplicate-project");
        let state = temp_root("duplicate-state");

        let mut plan =
            ProjectTransactionPlan::new("plan-duplicate", operation("op-duplicate"), "duplicate")
                .unwrap();
        plan.mutations.push(ProjectMutation::Checkpoint {
            path: PathBuf::from("same.txt"),
        });
        plan.mutations.push(ProjectMutation::WriteText {
            path: PathBuf::from("same.txt"),
            content: "value".into(),
        });

        let engine = ProjectTransactionEngine::new(&project, &state).unwrap();
        let errors = engine.validate_plan(&plan).unwrap_err();
        assert!(errors
            .iter()
            .any(|error| error.contains("same path more than once")));

        let _ = fs::remove_dir_all(project);
        let _ = fs::remove_dir_all(state);
    }
}
