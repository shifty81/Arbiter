//! Native Cortex project-operation contracts.
//!
//! These types are the first native authority absorbed from the historical
//! Universal Project Control Center donor.  They deliberately describe
//! projects, capabilities, commands, gates and artifacts without owning any
//! project-specific implementation.

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

pub const PROJECT_CONTROL_SCHEMA_VERSION: u32 = 1;
pub const PROJECT_SPINE_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(transparent)]
pub struct ProjectId(pub String);

impl ProjectId {
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into().trim().to_string();
        if value.is_empty() {
            return Err("project id cannot be empty".into());
        }
        if !value
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.'))
        {
            return Err(format!("project id contains unsupported characters: {value}"));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn is_cortex(&self) -> bool {
        self.0.eq_ignore_ascii_case("cortex")
    }
}

impl fmt::Display for ProjectId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(transparent)]
pub struct ProjectKind(pub String);

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(transparent)]
pub struct CapabilityId(pub String);

impl CapabilityId {
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProjectAuthority {
    CortexSystem,
    Managed,
    Adapter,
    External,
    #[default]
    Unknown,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CommandRisk {
    #[default]
    ReadOnly,
    LocalMutation,
    ExternalMutation,
    Destructive,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CancellationPolicy {
    #[default]
    Cooperative,
    BoundedKill,
    NotSupported,
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RollbackPolicy {
    #[default]
    None,
    Snapshot,
    Transactional,
    ProviderOwned,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectIdentity {
    pub id: ProjectId,
    pub name: String,
    pub kind: ProjectKind,
    #[serde(default)]
    pub family: Option<String>,
    #[serde(default)]
    pub authority: ProjectAuthority,
}

#[derive(
    Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash,
)]
#[serde(rename_all = "snake_case")]
pub enum CapabilitySource {
    Declared,
    CommandDerived,
    GateDerived,
    CortexSystem,
    Adapter,
    #[default]
    Unknown,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectCapability {
    pub id: CapabilityId,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub source: CapabilitySource,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ToolRequirement {
    pub tool: String,
    #[serde(default)]
    pub required: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct CommandDescriptor {
    pub key: String,
    pub label: String,
    pub program: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub risk: CommandRisk,
    #[serde(default)]
    pub side_effects: Vec<String>,
    #[serde(default)]
    pub permissions: Vec<String>,
    #[serde(default)]
    pub network_required: bool,
    #[serde(default)]
    pub cancellation: CancellationPolicy,
    #[serde(default)]
    pub rollback: RollbackPolicy,
    #[serde(default)]
    pub artifacts: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectCommand {
    pub project_id: ProjectId,
    pub descriptor: CommandDescriptor,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct QualityGateDescriptor {
    pub key: String,
    pub label: String,
    #[serde(default)]
    pub stages: Vec<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactDeclaration {
    pub key: String,
    pub path: PathBuf,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct RootControlDescriptor {
    #[serde(default)]
    pub mode: String,
    #[serde(default)]
    pub entrypoint: String,
    #[serde(default)]
    pub runtime: String,
    #[serde(default)]
    pub adapter: String,
    #[serde(default)]
    pub upstream: String,
    #[serde(default)]
    pub external_runtime_required: bool,
}

#[derive(
    Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash,
)]
#[serde(rename_all = "snake_case")]
pub enum ProjectHealthState {
    Healthy,
    Degraded,
    Unhealthy,
    Blocked,
    #[default]
    Unknown,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectHealthCheck {
    pub key: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub state: ProjectHealthState,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub observed_unix_ms: Option<u128>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectHealth {
    #[serde(default)]
    pub state: ProjectHealthState,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub checks: Vec<ProjectHealthCheck>,
}

impl ProjectHealth {
    pub fn from_checks(checks: Vec<ProjectHealthCheck>) -> Self {
        let state = aggregate_health(&checks);
        let summary = match state {
            ProjectHealthState::Healthy => "all required project health checks are healthy",
            ProjectHealthState::Degraded => "project health is degraded",
            ProjectHealthState::Unhealthy => "one or more required project health checks are unhealthy",
            ProjectHealthState::Blocked => "project operations are blocked",
            ProjectHealthState::Unknown => "project health is not yet known",
        }
        .to_string();
        Self {
            state,
            summary,
            checks,
        }
    }

    pub fn operational(&self) -> bool {
        matches!(
            self.state,
            ProjectHealthState::Healthy | ProjectHealthState::Degraded
        )
    }
}

fn aggregate_health(checks: &[ProjectHealthCheck]) -> ProjectHealthState {
    if checks.is_empty() {
        return ProjectHealthState::Unknown;
    }
    if checks
        .iter()
        .any(|check| check.required && check.state == ProjectHealthState::Blocked)
    {
        return ProjectHealthState::Blocked;
    }
    if checks
        .iter()
        .any(|check| check.required && check.state == ProjectHealthState::Unhealthy)
    {
        return ProjectHealthState::Unhealthy;
    }
    if checks.iter().any(|check| {
        matches!(
            check.state,
            ProjectHealthState::Blocked
                | ProjectHealthState::Unhealthy
                | ProjectHealthState::Degraded
                | ProjectHealthState::Unknown
        )
    }) {
        return ProjectHealthState::Degraded;
    }
    ProjectHealthState::Healthy
}

#[derive(
    Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash,
)]
#[serde(rename_all = "snake_case")]
pub enum ProjectRelationshipKind {
    Contains,
    DependsOn,
    IntegratesWith,
    AdapterFor,
    DerivedFrom,
    RelatedCopy,
    SharedRepository,
    Supersedes,
    #[default]
    Related,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectRelationship {
    pub from: ProjectId,
    pub to: ProjectId,
    #[serde(default)]
    pub kind: ProjectRelationshipKind,
    #[serde(default)]
    pub confidence: u8,
    #[serde(default)]
    pub reason: String,
}

impl ProjectRelationship {
    pub fn validate(&self) -> Result<(), String> {
        if self.from.0.trim().is_empty() || self.to.0.trim().is_empty() {
            return Err("project relationship endpoints cannot be empty".into());
        }
        if self.from == self.to && !matches!(self.kind, ProjectRelationshipKind::RelatedCopy) {
            return Err("project relationship cannot target itself".into());
        }
        if self.confidence > 100 {
            return Err(format!(
                "project relationship confidence must be 0..=100, got {}",
                self.confidence
            ));
        }
        Ok(())
    }
}

#[derive(
    Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash,
)]
#[serde(rename_all = "snake_case")]
pub enum ProjectOperationState {
    Planned,
    Validated,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    RolledBack,
    #[default]
    Unknown,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectOperation {
    pub schema_version: u32,
    pub id: String,
    pub project_id: ProjectId,
    pub command_key: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub working_directory: Option<PathBuf>,
    #[serde(default)]
    pub requested_by: Option<String>,
    #[serde(default)]
    pub created_unix_ms: u128,
}

impl ProjectOperation {
    pub fn new(
        id: impl Into<String>,
        project_id: ProjectId,
        command_key: impl Into<String>,
    ) -> Result<Self, String> {
        let id = id.into().trim().to_string();
        let command_key = command_key.into().trim().to_string();
        if id.is_empty() {
            return Err("project operation id cannot be empty".into());
        }
        if command_key.is_empty() {
            return Err("project operation command key cannot be empty".into());
        }
        Ok(Self {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            id,
            project_id,
            command_key,
            ..Self::default()
        })
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct OperationDiagnostic {
    #[serde(default)]
    pub code: String,
    pub message: String,
    #[serde(default)]
    pub path: Option<PathBuf>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct OperationResult {
    pub schema_version: u32,
    pub operation_id: String,
    pub project_id: ProjectId,
    pub command_key: String,
    #[serde(default)]
    pub state: ProjectOperationState,
    #[serde(default)]
    pub exit_code: Option<i32>,
    #[serde(default)]
    pub elapsed_ms: u64,
    #[serde(default)]
    pub artifacts: Vec<PathBuf>,
    #[serde(default)]
    pub diagnostics: Vec<OperationDiagnostic>,
}

impl OperationResult {
    pub fn succeeded(operation: &ProjectOperation, elapsed_ms: u64) -> Self {
        Self {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            operation_id: operation.id.clone(),
            project_id: operation.project_id.clone(),
            command_key: operation.command_key.clone(),
            state: ProjectOperationState::Succeeded,
            exit_code: Some(0),
            elapsed_ms,
            artifacts: Vec::new(),
            diagnostics: Vec::new(),
        }
    }

    pub fn failed(
        operation: &ProjectOperation,
        exit_code: Option<i32>,
        message: impl Into<String>,
        elapsed_ms: u64,
    ) -> Self {
        Self {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            operation_id: operation.id.clone(),
            project_id: operation.project_id.clone(),
            command_key: operation.command_key.clone(),
            state: ProjectOperationState::Failed,
            exit_code,
            elapsed_ms,
            artifacts: Vec::new(),
            diagnostics: vec![OperationDiagnostic {
                code: "command_failed".into(),
                message: message.into(),
                path: None,
            }],
        }
    }

    pub fn succeeded_cleanly(&self) -> bool {
        self.state == ProjectOperationState::Succeeded && self.exit_code == Some(0)
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectAdapterDescriptor {
    pub id: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub project_kinds: BTreeSet<ProjectKind>,
    #[serde(default)]
    pub capabilities: BTreeSet<CapabilityId>,
    #[serde(default)]
    pub command_keys: BTreeSet<String>,
}

#[derive(
    Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash,
)]
#[serde(rename_all = "snake_case")]
pub enum ContractIssueSeverity {
    Info,
    Warning,
    Error,
    #[default]
    Unknown,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContractValidationIssue {
    #[serde(default)]
    pub severity: ContractIssueSeverity,
    pub code: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectContract {
    pub schema_version: u32,
    pub project: ProjectIdentity,
    #[serde(default)]
    pub requirements: Vec<ToolRequirement>,
    #[serde(default)]
    pub commands: Vec<CommandDescriptor>,
    #[serde(default)]
    pub quality_gates: Vec<QualityGateDescriptor>,
    #[serde(default)]
    pub artifacts: Vec<ArtifactDeclaration>,
    #[serde(default)]
    pub root_control_center: Option<RootControlDescriptor>,
}

impl ProjectContract {
    pub fn load_optional(root: &Path) -> Result<Option<Self>, String> {
        let path = root.join("project.control.json");
        if !path.is_file() {
            return Ok(None);
        }
        let bytes = fs::read(&path)
            .map_err(|error| format!("failed to read {}: {error}", path.display()))?;
        let mut contract: Self = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid project contract {}: {error}", path.display()))?;
        if contract.schema_version != PROJECT_CONTROL_SCHEMA_VERSION {
            return Err(format!(
                "unsupported project.control schema {} in {}",
                contract.schema_version,
                path.display()
            ));
        }
        contract.project.id = ProjectId::new(contract.project.id.0)?;
        if contract.project.name.trim().is_empty() {
            contract.project.name = contract.project.id.0.clone();
        }
        if contract.project.id.is_cortex() {
            contract.project.authority = ProjectAuthority::CortexSystem;
        } else if matches!(contract.project.authority, ProjectAuthority::Unknown) {
            contract.project.authority = ProjectAuthority::Managed;
        }
        let errors = contract
            .validate()
            .into_iter()
            .filter(|issue| issue.severity == ContractIssueSeverity::Error)
            .collect::<Vec<_>>();
        if !errors.is_empty() {
            return Err(format!(
                "invalid project contract {}: {}",
                path.display(),
                errors
                    .iter()
                    .map(|issue| format!("{}: {}", issue.code, issue.message))
                    .collect::<Vec<_>>()
                    .join("; ")
            ));
        }
        Ok(Some(contract))
    }

    pub fn load_required(root: &Path) -> Result<Self, String> {
        Self::load_optional(root)?.ok_or_else(|| {
            format!(
                "project.control.json is required for governed Cortex project operations: {}",
                root.display()
            )
        })
    }

    pub fn command(&self, key: &str) -> Option<&CommandDescriptor> {
        self.commands.iter().find(|command| command.key == key)
    }

    pub fn quality_gate(&self, key: &str) -> Option<&QualityGateDescriptor> {
        self.quality_gates.iter().find(|gate| gate.key == key)
    }

    pub fn commands_typed(&self) -> Vec<ProjectCommand> {
        self.commands
            .iter()
            .cloned()
            .map(|descriptor| ProjectCommand {
                project_id: self.project.id.clone(),
                descriptor,
            })
            .collect()
    }

    pub fn capabilities(&self) -> BTreeSet<CapabilityId> {
        self.capability_descriptors()
            .into_iter()
            .map(|capability| capability.id)
            .collect()
    }

    pub fn capability_descriptors(&self) -> Vec<ProjectCapability> {
        let mut capabilities = BTreeMap::<CapabilityId, ProjectCapability>::new();

        let mut add = |id: &str, label: &str, source: CapabilitySource| {
            let key = CapabilityId::new(id);
            capabilities.entry(key.clone()).or_insert(ProjectCapability {
                id: key,
                label: label.into(),
                description: String::new(),
                source,
            });
        };

        for command in &self.commands {
            let key = command.key.to_ascii_lowercase();
            for (needle, capability, label) in [
                ("fmt", "format", "Format"),
                ("format", "format", "Format"),
                ("check", "validate", "Validate"),
                ("validate", "validate", "Validate"),
                ("test", "test", "Test"),
                ("clippy", "lint", "Lint"),
                ("lint", "lint", "Lint"),
                ("build", "build", "Build"),
                ("run", "run", "Run"),
                ("package", "package", "Package"),
                ("release", "package", "Package"),
            ] {
                if key.contains(needle) {
                    add(capability, label, CapabilitySource::CommandDerived);
                }
            }
        }

        if !self.quality_gates.is_empty() {
            add(
                "quality_gate",
                "Quality Gate",
                CapabilitySource::GateDerived,
            );
        }
        if self.root_control_center.is_some() {
            add(
                "project_operations",
                "Project Operations",
                CapabilitySource::Declared,
            );
        }
        if self.project.id.is_cortex() {
            add(
                "cortex_system",
                "Cortex System",
                CapabilitySource::CortexSystem,
            );
        }

        capabilities.into_values().collect()
    }

    pub fn validate(&self) -> Vec<ContractValidationIssue> {
        let mut issues = Vec::new();

        if self.schema_version != PROJECT_CONTROL_SCHEMA_VERSION {
            issues.push(ContractValidationIssue {
                severity: ContractIssueSeverity::Error,
                code: "schema_version".into(),
                message: format!(
                    "expected schema version {}, got {}",
                    PROJECT_CONTROL_SCHEMA_VERSION, self.schema_version
                ),
            });
        }

        if self.project.id.0.trim().is_empty() {
            issues.push(ContractValidationIssue {
                severity: ContractIssueSeverity::Error,
                code: "project_id.empty".into(),
                message: "project id cannot be empty".into(),
            });
        }

        if self.project.name.trim().is_empty() {
            issues.push(ContractValidationIssue {
                severity: ContractIssueSeverity::Warning,
                code: "project_name.empty".into(),
                message: "project name is empty".into(),
            });
        }

        let mut command_keys = BTreeSet::new();
        for command in &self.commands {
            if command.key.trim().is_empty() {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "command.key.empty".into(),
                    message: "command key cannot be empty".into(),
                });
            } else if !command_keys.insert(command.key.clone()) {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "command.key.duplicate".into(),
                    message: format!("duplicate command key: {}", command.key),
                });
            }
            if command.program.trim().is_empty() {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "command.program.empty".into(),
                    message: format!("command {} has no program", command.key),
                });
            }
        }

        let mut gate_keys = BTreeSet::new();
        for gate in &self.quality_gates {
            if gate.key.trim().is_empty() {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "gate.key.empty".into(),
                    message: "quality gate key cannot be empty".into(),
                });
            } else if !gate_keys.insert(gate.key.clone()) {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "gate.key.duplicate".into(),
                    message: format!("duplicate quality gate key: {}", gate.key),
                });
            }
            for stage in &gate.stages {
                if !command_keys.contains(stage) {
                    issues.push(ContractValidationIssue {
                        severity: ContractIssueSeverity::Error,
                        code: "gate.stage.missing_command".into(),
                        message: format!(
                            "quality gate {} references missing command {}",
                            gate.key, stage
                        ),
                    });
                }
            }
        }

        let mut artifact_keys = BTreeSet::new();
        for artifact in &self.artifacts {
            if artifact.key.trim().is_empty() {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "artifact.key.empty".into(),
                    message: "artifact key cannot be empty".into(),
                });
            } else if !artifact_keys.insert(artifact.key.clone()) {
                issues.push(ContractValidationIssue {
                    severity: ContractIssueSeverity::Error,
                    code: "artifact.key.duplicate".into(),
                    message: format!("duplicate artifact key: {}", artifact.key),
                });
            }
        }

        issues
    }

    pub fn spine_snapshot(&self) -> ProjectSpineSnapshot {
        ProjectSpineSnapshot {
            schema_version: PROJECT_SPINE_SCHEMA_VERSION,
            identity: self.project.clone(),
            capabilities: self.capability_descriptors(),
            commands: self.commands_typed(),
            quality_gates: self.quality_gates.clone(),
            artifacts: self.artifacts.clone(),
            health: ProjectHealth::default(),
            relationships: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectSpineSnapshot {
    pub schema_version: u32,
    pub identity: ProjectIdentity,
    #[serde(default)]
    pub capabilities: Vec<ProjectCapability>,
    #[serde(default)]
    pub commands: Vec<ProjectCommand>,
    #[serde(default)]
    pub quality_gates: Vec<QualityGateDescriptor>,
    #[serde(default)]
    pub artifacts: Vec<ArtifactDeclaration>,
    #[serde(default)]
    pub health: ProjectHealth,
    #[serde(default)]
    pub relationships: Vec<ProjectRelationship>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

impl ProjectSpineSnapshot {
    pub fn capability_ids(&self) -> BTreeSet<CapabilityId> {
        self.capabilities
            .iter()
            .map(|capability| capability.id.clone())
            .collect()
    }

    pub fn command(&self, key: &str) -> Option<&ProjectCommand> {
        self.commands
            .iter()
            .find(|command| command.descriptor.key == key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_contract() -> ProjectContract {
        ProjectContract {
            schema_version: PROJECT_CONTROL_SCHEMA_VERSION,
            project: ProjectIdentity {
                id: ProjectId("cortex".into()),
                name: "Cortex".into(),
                kind: ProjectKind("rust-workspace".into()),
                authority: ProjectAuthority::CortexSystem,
                family: None,
            },
            commands: vec![CommandDescriptor {
                key: "build".into(),
                label: "Build".into(),
                program: "cargo".into(),
                args: vec!["build".into()],
                ..CommandDescriptor::default()
            }],
            quality_gates: vec![QualityGateDescriptor {
                key: "fast".into(),
                label: "Fast".into(),
                stages: vec!["build".into()],
            }],
            ..ProjectContract::default()
        }
    }

    #[test]
    fn project_id_validation_is_stable() {
        assert!(ProjectId::new("cortex").unwrap().is_cortex());
        assert!(ProjectId::new("havenwild.dev").is_ok());
        assert!(ProjectId::new("bad/id").is_err());
    }

    #[test]
    fn capabilities_are_derived_from_commands() {
        let contract = sample_contract();
        let capabilities = contract.capabilities();
        assert!(capabilities.contains(&CapabilityId::new("build")));
        assert!(capabilities.contains(&CapabilityId::new("quality_gate")));
        assert!(capabilities.contains(&CapabilityId::new("cortex_system")));
    }

    #[test]
    fn contract_validation_detects_missing_gate_stage() {
        let mut contract = sample_contract();
        contract.quality_gates[0].stages.push("missing".into());
        let issues = contract.validate();
        assert!(issues.iter().any(|issue| {
            issue.severity == ContractIssueSeverity::Error
                && issue.code == "gate.stage.missing_command"
        }));
    }

    #[test]
    fn health_rollup_prioritizes_required_failures() {
        let health = ProjectHealth::from_checks(vec![
            ProjectHealthCheck {
                key: "cargo".into(),
                state: ProjectHealthState::Healthy,
                required: true,
                ..ProjectHealthCheck::default()
            },
            ProjectHealthCheck {
                key: "git".into(),
                state: ProjectHealthState::Unhealthy,
                required: true,
                ..ProjectHealthCheck::default()
            },
        ]);
        assert_eq!(health.state, ProjectHealthState::Unhealthy);
        assert!(!health.operational());
    }

    #[test]
    fn operation_result_is_bound_to_operation_identity() {
        let operation = ProjectOperation::new(
            "op-1",
            ProjectId::new("cortex").unwrap(),
            "build",
        )
        .unwrap();
        let result = OperationResult::succeeded(&operation, 42);
        assert_eq!(result.operation_id, "op-1");
        assert_eq!(result.command_key, "build");
        assert!(result.succeeded_cleanly());
    }

    #[test]
    fn relationship_validation_rejects_bad_confidence() {
        let relationship = ProjectRelationship {
            from: ProjectId::new("cortex").unwrap(),
            to: ProjectId::new("havenwild").unwrap(),
            kind: ProjectRelationshipKind::IntegratesWith,
            confidence: 101,
            reason: "test".into(),
        };
        assert!(relationship.validate().is_err());
    }

    #[test]
    fn spine_snapshot_round_trips() {
        let snapshot = sample_contract().spine_snapshot();
        let encoded = serde_json::to_string(&snapshot).unwrap();
        let decoded: ProjectSpineSnapshot = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded.identity.id.as_str(), "cortex");
        assert!(decoded.capability_ids().contains(&CapabilityId::new("build")));
        assert!(decoded.command("build").is_some());
    }
}
