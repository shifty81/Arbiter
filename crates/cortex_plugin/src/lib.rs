//! Cortex plugin manifests and user-controlled permission policy.
pub use cortex_permissions::{parse_permission, Permission, PermissionPolicy};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PluginManifest {
    pub schema_version: u32,
    pub id: String,
    pub name: String,
    pub version: String,
    pub description: String,
    #[serde(default)]
    pub permissions: Vec<Permission>,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default)]
    pub workspace_kinds: Vec<String>,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProtocolKind {
    McpStdio,
    LspStdio,
    DapStdio,
    BspStdio,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProtocolEndpoint {
    pub schema_version: u32,
    pub id: String,
    pub name: String,
    pub kind: ProtocolKind,
    pub executable: PathBuf,
    #[serde(default)]
    pub args: Vec<String>,
    pub working_directory: Option<PathBuf>,
    #[serde(default = "default_true")]
    pub local_only: bool,
    #[serde(default)]
    pub project_kinds: Vec<String>,
    #[serde(default)]
    pub permissions: Vec<Permission>,
}

impl ProtocolEndpoint {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty()
            || !self.id.chars().all(|character| {
                character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
            })
        {
            return Err("invalid Cortex protocol endpoint id".into());
        }
        if self.executable.as_os_str().is_empty() {
            return Err(format!("protocol endpoint `{}` has no executable", self.id));
        }
        if !self.local_only {
            return Err(format!(
                "protocol endpoint `{}` is not local-only; remote endpoints require a future explicit authorization profile",
                self.id
            ));
        }
        Ok(())
    }
}

fn default_true() -> bool {
    true
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SkillManifest {
    pub schema_version: u32,
    pub id: String,
    pub name: String,
    pub description: String,
    #[serde(default)]
    pub project_kinds: Vec<String>,
    #[serde(default)]
    pub required_permissions: Vec<Permission>,
    #[serde(default)]
    pub scripts: Vec<PathBuf>,
    #[serde(default)]
    pub templates: Vec<PathBuf>,
    #[serde(default)]
    pub validation_commands: Vec<String>,
    #[serde(default)]
    pub instructions: String,
}

impl SkillManifest {
    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty()
            || !self.id.chars().all(|character| {
                character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
            })
        {
            return Err("invalid Cortex skill id".into());
        }

        for path in self.scripts.iter().chain(self.templates.iter()) {
            if path.is_absolute()
                || path
                    .components()
                    .any(|component| matches!(component, std::path::Component::ParentDir))
            {
                return Err(format!(
                    "Cortex skill `{}` contains a path outside its skill package: {}",
                    self.id,
                    path.display()
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DiscoveredSkill {
    pub manifest: SkillManifest,
    pub source: String,
    pub path: Option<PathBuf>,
}

pub struct SkillRegistry;

impl SkillRegistry {
    pub fn discover(workspace: &Path, state: &Path) -> Result<Vec<DiscoveredSkill>, String> {
        let mut out = Vec::new();
        for (source, dir) in [
            (
                "workspace",
                workspace.join("config").join("cortex").join("skills"),
            ),
            ("user", state.join("skills")),
        ] {
            if !dir.is_dir() {
                continue;
            }
            for entry in fs::read_dir(&dir).map_err(|error| error.to_string())? {
                let path = entry.map_err(|error| error.to_string())?.path();
                if path.extension().and_then(|value| value.to_str()) != Some("json") {
                    continue;
                }
                let manifest: SkillManifest =
                    serde_json::from_slice(&fs::read(&path).map_err(|error| error.to_string())?)
                        .map_err(|error| {
                            format!("invalid Cortex skill {}: {error}", path.display())
                        })?;
                manifest.validate()?;
                out.push(DiscoveredSkill {
                    manifest,
                    source: source.into(),
                    path: Some(path),
                });
            }
        }
        out.sort_by(|left, right| left.manifest.id.cmp(&right.manifest.id));
        Ok(out)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DiscoveredPlugin {
    pub manifest: PluginManifest,
    pub source: String,
    pub path: Option<PathBuf>,
}
pub struct PluginRegistry;
impl PluginRegistry {
    pub fn discover(workspace: &Path, state: &Path) -> Result<Vec<DiscoveredPlugin>, String> {
        let mut out = builtins();
        for dir in [
            workspace.join("config").join("cortex").join("plugins"),
            state.join("plugins"),
        ] {
            if !dir.is_dir() {
                continue;
            }
            for e in fs::read_dir(&dir).map_err(|e| e.to_string())? {
                let p = e.map_err(|e| e.to_string())?.path();
                if p.extension().and_then(|x| x.to_str()) != Some("json") {
                    continue;
                }
                let m: PluginManifest =
                    serde_json::from_slice(&fs::read(&p).map_err(|e| e.to_string())?)
                        .map_err(|e| format!("invalid plugin manifest {}: {e}", p.display()))?;
                validate(&m)?;
                out.push(DiscoveredPlugin {
                    manifest: m,
                    source: "workspace".into(),
                    path: Some(p),
                });
            }
        }
        out.sort_by(|a, b| a.manifest.id.cmp(&b.manifest.id));
        Ok(out)
    }
}
fn validate(m: &PluginManifest) -> Result<(), String> {
    if m.id.is_empty()
        || !m
            .id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
    {
        Err("invalid Cortex plugin id".into())
    } else {
        Ok(())
    }
}
fn builtins() -> Vec<DiscoveredPlugin> {
    [
        ("cortex.core", "Cortex Core"),
        ("cortex.git", "Cortex Git Adapter"),
        ("cortex.open2d", "Open2D Adapter"),
    ]
    .into_iter()
    .map(|(id, name)| DiscoveredPlugin {
        manifest: PluginManifest {
            schema_version: 1,
            id: id.into(),
            name: name.into(),
            version: "0.1.0".into(),
            description: String::new(),
            permissions: Vec::new(),
            tools: Vec::new(),
            workspace_kinds: Vec::new(),
        },
        source: "builtin".into(),
        path: None,
    })
    .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn risky_denied_default() {
        let p = PermissionPolicy::default();
        assert!(!p.granted.contains(&Permission::GitWrite));
        assert!(!p.granted.contains(&Permission::Delete));
    }
}
