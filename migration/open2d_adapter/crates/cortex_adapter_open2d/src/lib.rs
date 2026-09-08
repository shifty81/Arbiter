//! Optional Open2D integration for standalone Cortex.
//!
//! Cortex core/workspace code does not require this adapter. When an Open2D
//! repository is attached, the adapter exposes Foundry/Ember-specific metadata
//! and launch contracts.

use cortex_process::ProcessService;
use cortex_protocol::{ToolCall, ToolDefinition};
use cortex_session::DevSession;
use cortex_tools::ToolExtension;
use cortex_workspace::Workspace;
use open2d_runtime_bridge::read_snapshot;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Open2DAdapter {
    pub root: PathBuf,
    pub foundry_package: String,
    pub ember_package: String,
}

impl Open2DAdapter {
    pub fn detect(root: impl AsRef<Path>) -> Option<Self> {
        let root = root.as_ref();
        let detected = root
            .join("config")
            .join("architecture")
            .join("foundry_dependency_policy.json")
            .is_file()
            || root.join("apps").join("open2d_foundry").is_dir();
        detected.then(|| Self {
            root: root.to_path_buf(),
            foundry_package: "open2d_foundry".into(),
            ember_package: "open2d_ember".into(),
        })
    }

    pub fn status(&self) -> serde_json::Value {
        let foundry_executable = self.foundry_executable();
        let ember_executable = self.ember_executable();
        serde_json::json!({
            "id": "open2d",
            "root": self.root,
            "foundry_package": self.foundry_package,
            "ember_package": self.ember_package,
            "foundry_executable": foundry_executable,
            "foundry_executable_ready": foundry_executable.is_file(),
            "ember_executable": ember_executable,
            "ember_executable_ready": ember_executable.is_file(),
            "launch_authority": "certified_project_executable"
        })
    }

    pub fn foundry_executable(&self) -> PathBuf {
        self.root
            .join("target")
            .join("debug")
            .join(if cfg!(windows) {
                "open2d_foundry.exe"
            } else {
                "open2d_foundry"
            })
    }

    pub fn ember_executable(&self) -> PathBuf {
        self.root
            .join("target")
            .join("debug")
            .join(if cfg!(windows) {
                "open2d_ember.exe"
            } else {
                "open2d_ember"
            })
    }

    pub fn foundry_args(&self, project: Option<&str>) -> Vec<String> {
        project.map(str::to_string).into_iter().collect()
    }

    pub fn ember_args(&self, session_dir: &Path, level: Option<&str>) -> Vec<String> {
        let mut args = vec![
            "--session-dir".into(),
            session_dir.to_string_lossy().to_string(),
        ];
        if let Some(level) = level {
            args.push("--level".into());
            args.push(level.to_string());
        }
        args
    }
}

pub struct Open2DToolExtension {
    adapter: Open2DAdapter,
    processes: ProcessService,
    session: DevSession,
}

impl Open2DToolExtension {
    pub fn detect(root: impl AsRef<Path>) -> Result<Option<Self>, String> {
        let root = root.as_ref();
        let Some(adapter) = Open2DAdapter::detect(root) else {
            return Ok(None);
        };
        let workspace = Workspace::open(root).map_err(|error| error.to_string())?;
        let session =
            DevSession::create_in(workspace.root(), workspace.sessions_dir(), "cortex-open2d")?;
        Ok(Some(Self {
            adapter,
            processes: ProcessService::default(),
            session,
        }))
    }
}

impl ToolExtension for Open2DToolExtension {
    fn id(&self) -> &str {
        "open2d"
    }

    fn status(&self) -> Value {
        self.adapter.status()
    }

    fn definitions(&self) -> Vec<ToolDefinition> {
        definitions()
    }

    fn execute(&mut self, call: &ToolCall) -> Option<Result<Value, String>> {
        let result = match call.name.as_str() {
            "runtime.launch_foundry" => {
                let project = call.arguments.get("project").and_then(Value::as_str);
                let args = self.adapter.foundry_args(project);
                let executable = self.adapter.foundry_executable();
                if !executable.is_file() {
                    return Some(Err(format!(
                        "certified Open2D Foundry executable is missing at {}; run the project quality/checkpoint build before launch",
                        executable.display()
                    )));
                }
                self.processes
                    .spawn_project_executable(
                        &self.adapter.root,
                        "Open2D Foundry",
                        Some("open2d_foundry".into()),
                        &executable,
                        &args,
                    )
                    .map(|pid| {
                        let _ = self.session.log(
                            "process",
                            "launched certified Foundry executable",
                            json!({"pid": pid, "executable": executable, "args": args}),
                        );
                        json!({"pid": pid, "executable": executable, "args": args})
                    })
            }
            "runtime.launch_ember" => {
                let level = call.arguments.get("level").and_then(Value::as_str);
                let args = self.adapter.ember_args(&self.session.directory, level);
                let executable = self.adapter.ember_executable();
                if !executable.is_file() {
                    return Some(Err(format!(
                        "certified Open2D Ember executable is missing at {}; run the project quality/checkpoint build before launch",
                        executable.display()
                    )));
                }
                self.processes
                    .spawn_project_executable(
                        &self.adapter.root,
                        "Open2D Ember",
                        Some("open2d_ember".into()),
                        &executable,
                        &args,
                    )
                    .map(|pid| {
                        let _ = self.session.log(
                            "process",
                            "launched certified Ember executable",
                            json!({"pid": pid, "executable": executable, "args": args}),
                        );
                        json!({
                            "pid": pid,
                            "executable": executable,
                            "args": args,
                            "session_dir": self.session.directory.clone()
                        })
                    })
            }
            "runtime.status" => {
                let statuses = self.processes.statuses();
                let snapshot = read_snapshot(&self.session.directory).ok();
                Ok(json!({"processes": statuses, "runtime": snapshot}))
            }
            "runtime.stop" => {
                let Some(pid) = call.arguments.get("pid").and_then(Value::as_u64) else {
                    return Some(Err("missing integer argument: pid".into()));
                };
                self.processes
                    .stop(pid as u32)
                    .map(|stopped| json!({"stopped": stopped}))
            }
            _ => return None,
        };
        Some(result)
    }
}

pub fn definitions() -> Vec<ToolDefinition> {
    vec![
        tool(
            "runtime.launch_foundry",
            "Launch the certified Open2D Foundry project executable directly under Cortex ownership; does not use cargo run.",
            true,
            json!({"type":"object","properties":{"project":{"type":"string"}}}),
        ),
        tool(
            "runtime.launch_ember",
            "Launch the certified Open2D Ember editor executable directly under Cortex ownership; does not use cargo run.",
            true,
            json!({"type":"object","properties":{"level":{"type":"string"}}}),
        ),
        tool(
            "runtime.status",
            "Read Open2D adapter-owned process and Ember runtime state.",
            false,
            json!({"type":"object","properties":{}}),
        ),
        tool(
            "runtime.stop",
            "Stop a process owned by the active Open2D adapter session.",
            true,
            json!({"type":"object","properties":{"pid":{"type":"integer"}},"required":["pid"]}),
        ),
    ]
}

fn tool(name: &str, description: &str, mutating: bool, parameters: Value) -> ToolDefinition {
    ToolDefinition {
        name: name.into(),
        description: description.into(),
        parameters,
        mutating,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_args_target_certified_executables_without_cargo_run() {
        let root = PathBuf::from("project");
        let adapter = Open2DAdapter {
            root: root.clone(),
            foundry_package: "open2d_foundry".into(),
            ember_package: "open2d_ember".into(),
        };
        let foundry = adapter.foundry_args(Some("demo.open2d"));
        assert_eq!(foundry, vec!["demo.open2d".to_string()]);
        let ember = adapter.ember_args(Path::new("session"), Some("main"));
        assert_eq!(
            ember,
            vec![
                "--session-dir".to_string(),
                "session".to_string(),
                "--level".to_string(),
                "main".to_string(),
            ]
        );
        assert!(!foundry.iter().any(|arg| arg == "run" || arg == "cargo"));
        assert!(!ember.iter().any(|arg| arg == "run" || arg == "cargo"));
    }

    #[test]
    fn generic_directory_is_not_open2d() {
        let root =
            std::env::temp_dir().join(format!("cortex-open2d-adapter-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        assert!(Open2DAdapter::detect(&root).is_none());
        std::fs::remove_dir_all(root).unwrap();
    }
}
