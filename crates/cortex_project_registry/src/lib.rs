//! Native projection layer from the existing Cortex workspace registry into the
//! typed project spine.
//!
//! `cortex_registry` remains the canonical workspace attachment authority.
//! This crate adds project-centric persistence and indexes without creating a
//! competing workspace registry or changing the existing registry file format.

use cortex_project::{
    CapabilityId, ProjectAuthority, ProjectHealth, ProjectId, ProjectRelationship,
    ProjectSpineSnapshot,
};
use cortex_registry::{RegisteredWorkspace, WorkspaceRegistry};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectRegistryProjection {
    pub workspace_id: String,
    #[serde(default)]
    pub project_id: Option<ProjectId>,
    #[serde(default)]
    pub family: Option<String>,
    #[serde(default)]
    pub authority: ProjectAuthority,
    pub root: PathBuf,
    #[serde(default)]
    pub known_paths: Vec<PathBuf>,
    #[serde(default)]
    pub capabilities: BTreeSet<CapabilityId>,
    #[serde(default)]
    pub command_keys: BTreeSet<String>,
    #[serde(default)]
    pub contract_path: Option<PathBuf>,
    #[serde(default)]
    pub spine: Option<ProjectSpineSnapshot>,
    #[serde(default)]
    pub health: ProjectHealth,
    #[serde(default)]
    pub relationships: Vec<ProjectRelationship>,
    #[serde(default)]
    pub updated_unix_ms: u128,
}

impl ProjectRegistryProjection {
    pub fn from_workspace(
        workspace: &RegisteredWorkspace,
        existing: Option<&Self>,
    ) -> Result<Self, String> {
        let contract = cortex_project::ProjectContract::load_optional(&workspace.root)?;
        let family = contract
            .as_ref()
            .and_then(|contract| contract.project.family.clone());
        let command_keys = contract
            .as_ref()
            .map(|contract| {
                contract
                    .commands
                    .iter()
                    .map(|command| command.key.clone())
                    .collect::<BTreeSet<_>>()
            })
            .unwrap_or_default();

        let capabilities = contract
            .as_ref()
            .map(cortex_project::ProjectContract::capabilities)
            .unwrap_or_else(|| workspace.capabilities.clone());

        let project_id = contract
            .as_ref()
            .map(|contract| contract.project.id.clone())
            .or_else(|| workspace.project_id.clone());

        if let (Some(workspace_id), Some(contract_id)) = (
            workspace.project_id.as_ref(),
            contract.as_ref().map(|value| &value.project.id),
        ) {
            if workspace_id != contract_id {
                return Err(format!(
                    "workspace {} project id {} disagrees with contract id {}",
                    workspace.id, workspace_id, contract_id
                ));
            }
        }

        let authority = contract
            .as_ref()
            .map(|contract| contract.project.authority)
            .unwrap_or(workspace.authority);

        let health = existing
            .map(|projection| projection.health.clone())
            .unwrap_or_default();
        let relationships = existing
            .map(|projection| projection.relationships.clone())
            .unwrap_or_default();

        let spine = contract.as_ref().map(|contract| {
            let mut snapshot = contract.spine_snapshot();
            snapshot.health = health.clone();
            snapshot.relationships = relationships.clone();
            snapshot
        });

        Ok(Self {
            workspace_id: workspace.id.clone(),
            project_id,
            family,
            authority,
            root: workspace.root.clone(),
            known_paths: workspace.known_paths.clone(),
            capabilities,
            command_keys,
            contract_path: contract
                .as_ref()
                .map(|_| workspace.root.join("project.control.json"))
                .or_else(|| workspace.contract_path.clone()),
            spine,
            health,
            relationships,
            updated_unix_ms: unix_millis(),
        })
    }

    pub fn refresh_spine_auxiliary_state(&mut self) {
        if let Some(spine) = &mut self.spine {
            spine.health = self.health.clone();
            spine.relationships = self.relationships.clone();
        }
    }
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectRegistryProjectionState {
    pub schema_version: u32,
    #[serde(default)]
    pub projects: BTreeMap<String, ProjectRegistryProjection>,
    #[serde(default)]
    pub generated_unix_ms: u128,
}

impl ProjectRegistryProjectionState {
    pub fn workspace(&self, workspace_id: &str) -> Option<&ProjectRegistryProjection> {
        self.projects.get(workspace_id)
    }

    pub fn project(&self, project_id: &ProjectId) -> Vec<&ProjectRegistryProjection> {
        self.projects
            .values()
            .filter(|projection| projection.project_id.as_ref() == Some(project_id))
            .collect()
    }

    pub fn family_index(&self) -> BTreeMap<String, BTreeSet<String>> {
        let mut index = BTreeMap::<String, BTreeSet<String>>::new();
        for projection in self.projects.values() {
            let Some(family) = projection
                .family
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty())
            else {
                continue;
            };
            index
                .entry(family.to_string())
                .or_default()
                .insert(projection.workspace_id.clone());
        }
        index
    }

    pub fn capability_index(&self) -> BTreeMap<CapabilityId, BTreeSet<String>> {
        let mut index = BTreeMap::<CapabilityId, BTreeSet<String>>::new();
        for projection in self.projects.values() {
            for capability in &projection.capabilities {
                index
                    .entry(capability.clone())
                    .or_default()
                    .insert(projection.workspace_id.clone());
            }
        }
        index
    }

    pub fn command_index(&self) -> BTreeMap<String, BTreeSet<String>> {
        let mut index = BTreeMap::<String, BTreeSet<String>>::new();
        for projection in self.projects.values() {
            for command in &projection.command_keys {
                index
                    .entry(command.clone())
                    .or_default()
                    .insert(projection.workspace_id.clone());
            }
        }
        index
    }

    pub fn relationships_for_project(&self, project_id: &ProjectId) -> Vec<ProjectRelationship> {
        let mut relationships = Vec::new();
        for projection in self.projects.values() {
            for relationship in &projection.relationships {
                if &relationship.from == project_id || &relationship.to == project_id {
                    relationships.push(relationship.clone());
                }
            }
        }
        relationships.sort_by(|left, right| {
            left.from
                .cmp(&right.from)
                .then_with(|| left.to.cmp(&right.to))
                .then_with(|| left.kind.cmp(&right.kind))
                .then_with(|| left.reason.cmp(&right.reason))
        });
        relationships.dedup();
        relationships
    }
}

#[derive(Clone, Debug)]
pub struct ProjectRegistryProjectionStore {
    path: PathBuf,
}

impl ProjectRegistryProjectionStore {
    pub fn open_for(registry: &WorkspaceRegistry) -> Self {
        Self {
            path: registry.home().join("registry").join("project_spines.json"),
        }
    }

    pub fn open(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn load(&self) -> Result<ProjectRegistryProjectionState, String> {
        if !self.path.is_file() {
            return Ok(ProjectRegistryProjectionState {
                schema_version: PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION,
                projects: BTreeMap::new(),
                generated_unix_ms: unix_millis(),
            });
        }

        let state: ProjectRegistryProjectionState = serde_json::from_slice(
            &fs::read(&self.path)
                .map_err(|error| format!("failed to read {}: {error}", self.path.display()))?,
        )
        .map_err(|error| {
            format!(
                "invalid Cortex project registry projection {}: {error}",
                self.path.display()
            )
        })?;

        if state.schema_version != PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION {
            return Err(format!(
                "unsupported Cortex project registry projection schema {} (expected {})",
                state.schema_version, PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION
            ));
        }

        Ok(state)
    }

    pub fn refresh_all(
        &self,
        registry: &WorkspaceRegistry,
    ) -> Result<ProjectRegistryProjectionState, String> {
        let registry_state = registry.state()?;
        let previous = self.load()?;
        let mut projects = BTreeMap::new();

        for workspace in &registry_state.workspaces {
            let existing = previous.projects.get(&workspace.id);
            let projection = ProjectRegistryProjection::from_workspace(workspace, existing)?;
            projects.insert(workspace.id.clone(), projection);
        }

        let state = ProjectRegistryProjectionState {
            schema_version: PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION,
            projects,
            generated_unix_ms: unix_millis(),
        };
        self.save(&state)?;
        Ok(state)
    }

    pub fn refresh_workspace(
        &self,
        registry: &WorkspaceRegistry,
        workspace_id: &str,
    ) -> Result<ProjectRegistryProjection, String> {
        let registry_state = registry.state()?;
        let workspace = registry_state
            .workspaces
            .iter()
            .find(|workspace| workspace.id == workspace_id)
            .ok_or_else(|| format!("registered Cortex workspace not found: {workspace_id}"))?;

        let mut state = self.load()?;
        let existing = state.projects.get(workspace_id);
        let projection = ProjectRegistryProjection::from_workspace(workspace, existing)?;
        state
            .projects
            .insert(workspace_id.to_string(), projection.clone());
        state.generated_unix_ms = unix_millis();
        self.save(&state)?;
        Ok(projection)
    }

    pub fn set_health(
        &self,
        workspace_id: &str,
        health: ProjectHealth,
    ) -> Result<ProjectRegistryProjection, String> {
        let mut state = self.load()?;
        let projection = state
            .projects
            .get_mut(workspace_id)
            .ok_or_else(|| format!("project registry projection not found: {workspace_id}"))?;
        projection.health = health;
        projection.updated_unix_ms = unix_millis();
        projection.refresh_spine_auxiliary_state();
        let result = projection.clone();
        state.generated_unix_ms = unix_millis();
        self.save(&state)?;
        Ok(result)
    }

    pub fn replace_relationships(
        &self,
        workspace_id: &str,
        relationships: Vec<ProjectRelationship>,
    ) -> Result<ProjectRegistryProjection, String> {
        let mut state = self.load()?;
        let projection = state
            .projects
            .get_mut(workspace_id)
            .ok_or_else(|| format!("project registry projection not found: {workspace_id}"))?;
        let project_id = projection.project_id.as_ref().ok_or_else(|| {
            format!(
                "workspace {workspace_id} has no governed project id; relationships require one"
            )
        })?;

        for relationship in &relationships {
            relationship.validate()?;
            if &relationship.from != project_id && &relationship.to != project_id {
                return Err(format!(
                    "relationship {} -> {} is not connected to project {}",
                    relationship.from, relationship.to, project_id
                ));
            }
        }

        let mut normalized = relationships;
        normalized.sort_by(|left, right| {
            left.from
                .cmp(&right.from)
                .then_with(|| left.to.cmp(&right.to))
                .then_with(|| left.kind.cmp(&right.kind))
                .then_with(|| left.reason.cmp(&right.reason))
        });
        normalized.dedup();

        projection.relationships = normalized;
        projection.updated_unix_ms = unix_millis();
        projection.refresh_spine_auxiliary_state();
        let result = projection.clone();
        state.generated_unix_ms = unix_millis();
        self.save(&state)?;
        Ok(result)
    }

    pub fn remove_workspace(&self, workspace_id: &str) -> Result<bool, String> {
        let mut state = self.load()?;
        let removed = state.projects.remove(workspace_id).is_some();
        if removed {
            state.generated_unix_ms = unix_millis();
            self.save(&state)?;
        }
        Ok(removed)
    }

    pub fn spine_for_workspace(
        &self,
        workspace_id: &str,
    ) -> Result<Option<ProjectSpineSnapshot>, String> {
        Ok(self
            .load()?
            .projects
            .get(workspace_id)
            .and_then(|projection| projection.spine.clone()))
    }

    fn save(&self, state: &ProjectRegistryProjectionState) -> Result<(), String> {
        let mut normalized = state.clone();
        normalized.schema_version = PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION;
        normalized.generated_unix_ms = unix_millis();

        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                format!(
                    "failed to create project registry directory {}: {error}",
                    parent.display()
                )
            })?;
        }

        let bytes = serde_json::to_vec_pretty(&normalized)
            .map_err(|error| format!("failed to encode project registry projection: {error}"))?;
        let temp = self.path.with_extension("json.tmp");
        fs::write(&temp, bytes)
            .map_err(|error| format!("failed to write {}: {error}", temp.display()))?;

        if self.path.exists() {
            fs::remove_file(&self.path).map_err(|error| {
                format!(
                    "failed to replace project registry projection {}: {error}",
                    self.path.display()
                )
            })?;
        }

        fs::rename(&temp, &self.path).map_err(|error| {
            format!(
                "failed to publish project registry projection {}: {error}",
                self.path.display()
            )
        })
    }
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
    use cortex_project::{ProjectHealthCheck, ProjectHealthState, ProjectRelationshipKind};

    fn projection(
        workspace_id: &str,
        project_id: &str,
        family: Option<&str>,
        capabilities: &[&str],
        commands: &[&str],
    ) -> ProjectRegistryProjection {
        ProjectRegistryProjection {
            workspace_id: workspace_id.into(),
            project_id: Some(ProjectId::new(project_id).unwrap()),
            family: family.map(str::to_string),
            capabilities: capabilities
                .iter()
                .map(|value| CapabilityId::new(*value))
                .collect(),
            command_keys: commands.iter().map(|value| (*value).to_string()).collect(),
            ..ProjectRegistryProjection::default()
        }
    }

    #[test]
    fn indexes_are_deterministic() {
        let mut state = ProjectRegistryProjectionState {
            schema_version: PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION,
            ..ProjectRegistryProjectionState::default()
        };
        state.projects.insert(
            "ws-1".into(),
            projection(
                "ws-1",
                "cortex",
                Some("cortex"),
                &["build", "test"],
                &["build", "test"],
            ),
        );
        state.projects.insert(
            "ws-2".into(),
            projection("ws-2", "havenwild", Some("games"), &["build"], &["build"]),
        );

        assert_eq!(
            state.capability_index()[&CapabilityId::new("build")],
            BTreeSet::from(["ws-1".to_string(), "ws-2".to_string()])
        );
        assert_eq!(
            state.command_index()["test"],
            BTreeSet::from(["ws-1".to_string()])
        );
        assert_eq!(
            state.family_index()["games"],
            BTreeSet::from(["ws-2".to_string()])
        );
    }

    #[test]
    fn relationships_must_touch_the_project() {
        let root = std::env::temp_dir().join(format!(
            "cortex-project-registry-test-{}-{}",
            std::process::id(),
            unix_millis()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ProjectRegistryProjectionStore::open(root.join("projection.json"));

        let mut state = ProjectRegistryProjectionState {
            schema_version: PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION,
            ..ProjectRegistryProjectionState::default()
        };
        state
            .projects
            .insert("ws-1".into(), projection("ws-1", "cortex", None, &[], &[]));
        store.save(&state).unwrap();

        let good = ProjectRelationship {
            from: ProjectId::new("cortex").unwrap(),
            to: ProjectId::new("havenwild").unwrap(),
            kind: ProjectRelationshipKind::IntegratesWith,
            confidence: 90,
            reason: "adapter".into(),
        };
        assert!(store.replace_relationships("ws-1", vec![good]).is_ok());

        let bad = ProjectRelationship {
            from: ProjectId::new("alpha").unwrap(),
            to: ProjectId::new("beta").unwrap(),
            kind: ProjectRelationshipKind::Related,
            confidence: 50,
            reason: "unrelated".into(),
        };
        assert!(store.replace_relationships("ws-1", vec![bad]).is_err());

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn health_persists_and_round_trips() {
        let root = std::env::temp_dir().join(format!(
            "cortex-project-health-test-{}-{}",
            std::process::id(),
            unix_millis()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ProjectRegistryProjectionStore::open(root.join("projection.json"));

        let mut state = ProjectRegistryProjectionState {
            schema_version: PROJECT_REGISTRY_PROJECTION_SCHEMA_VERSION,
            ..ProjectRegistryProjectionState::default()
        };
        state
            .projects
            .insert("ws-1".into(), projection("ws-1", "cortex", None, &[], &[]));
        store.save(&state).unwrap();

        let health = ProjectHealth::from_checks(vec![ProjectHealthCheck {
            key: "cargo".into(),
            state: ProjectHealthState::Healthy,
            required: true,
            ..ProjectHealthCheck::default()
        }]);
        store.set_health("ws-1", health.clone()).unwrap();

        let loaded = store.load().unwrap();
        assert_eq!(loaded.projects["ws-1"].health, health);

        let _ = fs::remove_dir_all(root);
    }
}
