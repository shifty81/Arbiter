//! Native Cortex project-operation contracts.
//!
//! These types are the first native authority absorbed from the historical
//! Universal Project Control Center donor.  They deliberately describe
//! projects, capabilities, commands, gates and artifacts without owning any
//! project-specific implementation.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

pub const PROJECT_CONTROL_SCHEMA_VERSION: u32 = 1;

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

    pub fn capabilities(&self) -> BTreeSet<CapabilityId> {
        let mut capabilities = BTreeSet::new();
        for command in &self.commands {
            let key = command.key.to_ascii_lowercase();
            for (needle, capability) in [
                ("fmt", "format"),
                ("format", "format"),
                ("check", "validate"),
                ("validate", "validate"),
                ("test", "test"),
                ("clippy", "lint"),
                ("lint", "lint"),
                ("build", "build"),
                ("run", "run"),
                ("package", "package"),
                ("release", "package"),
            ] {
                if key.contains(needle) {
                    capabilities.insert(CapabilityId::new(capability));
                }
            }
        }
        if !self.quality_gates.is_empty() {
            capabilities.insert(CapabilityId::new("quality_gate"));
        }
        if self.project.id.is_cortex() {
            capabilities.insert(CapabilityId::new("cortex_system"));
        }
        capabilities
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_id_validation_is_stable() {
        assert!(ProjectId::new("cortex").unwrap().is_cortex());
        assert!(ProjectId::new("havenwild.dev").is_ok());
        assert!(ProjectId::new("bad/id").is_err());
    }

    #[test]
    fn capabilities_are_derived_from_commands() {
        let contract = ProjectContract {
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
        };
        let capabilities = contract.capabilities();
        assert!(capabilities.contains(&CapabilityId::new("build")));
        assert!(capabilities.contains(&CapabilityId::new("quality_gate")));
        assert!(capabilities.contains(&CapabilityId::new("cortex_system")));
    }
}
