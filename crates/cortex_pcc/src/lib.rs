//! Typed bridge from Cortex into the universal Python Project Control Center.
//!
//! PCC owns cross-project build/test/gate operations. Cortex remains the reasoning,
//! permissions and agent surface and consumes PCC through this narrow JSON contract.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PccInvocation {
    pub program: PathBuf,
    pub prefix_args: Vec<String>,
    pub source_root: PathBuf,
}

#[derive(Clone, Debug)]
pub struct PccClient {
    project_root: PathBuf,
    invocation: PccInvocation,
}

impl PccClient {
    pub fn discover(project_root: impl AsRef<Path>) -> Result<Self, String> {
        let project_root = project_root
            .as_ref()
            .canonicalize()
            .map_err(|error| format!("failed to resolve PCC project root: {error}"))?;
        let source_root = project_root.join("tools").join("pcc").join("src");
        if !source_root.join("pcc").join("__main__.py").is_file() {
            return Err(format!(
                "Universal Python PCC is not installed in this project: {}",
                source_root.display()
            ));
        }
        let invocation = discover_python(source_root)?;
        Ok(Self {
            project_root,
            invocation,
        })
    }

    pub fn project_root(&self) -> &Path {
        &self.project_root
    }

    pub fn invocation(&self) -> &PccInvocation {
        &self.invocation
    }

    pub fn status(&self) -> Result<Value, String> {
        self.invoke(&["status"], false)
    }

    pub fn catalog(&self) -> Result<Value, String> {
        self.invoke(&["catalog"], false)
    }

    pub fn command_descriptor(&self, key: &str) -> Result<Value, String> {
        let catalog = self.catalog()?;
        catalog
            .get("commands")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .find(|command| command.get("key").and_then(Value::as_str) == Some(key))
            .cloned()
            .ok_or_else(|| format!("Universal Python PCC command is not registered: {key}"))
    }

    pub fn doctor(&self) -> Result<Value, String> {
        self.invoke(&["doctor"], false)
    }

    pub fn archive_audit(&self, archive: &str, prefix: Option<&str>) -> Result<Value, String> {
        let mut args = vec!["archive-audit", archive];
        if let Some(prefix) = prefix.filter(|value| !value.trim().is_empty()) {
            args.extend(["--prefix", prefix]);
        }
        self.invoke(&args, false)
    }

    pub fn gate(&self, key: &str) -> Result<Value, String> {
        self.invoke(&["gate", key], false)
    }

    /// Run the exact argv registered in project.control.json for a read-only command.
    ///
    /// Cortex deliberately does not expose raw trailing argv here. Parameterized PCC
    /// commands must use typed schemas in a later contract revision so model-supplied
    /// arguments cannot silently invalidate command risk metadata.
    pub fn run_read_only(&self, key: &str) -> Result<Value, String> {
        self.invoke(&["run", key], false)
    }

    /// Run the exact argv registered in project.control.json with explicit mutation authority.
    ///
    /// See `run_read_only`: arbitrary model-provided trailing argv is intentionally forbidden.
    pub fn run_mutating(&self, key: &str) -> Result<Value, String> {
        self.invoke(&["run", "--allow-mutation", key], false)
    }

    fn invoke(&self, args: &[&str], _interactive: bool) -> Result<Value, String> {
        let mut command = Command::new(&self.invocation.program);
        command.args(&self.invocation.prefix_args);
        command
            .arg("-m")
            .arg("pcc")
            .arg("--project-root")
            .arg(&self.project_root)
            .arg("--json")
            .args(args)
            .current_dir(&self.project_root);

        let python_path = std::env::var_os("PYTHONPATH")
            .map(|existing| {
                let mut paths = vec![self.invocation.source_root.clone()];
                paths.extend(std::env::split_paths(&existing));
                std::env::join_paths(paths).unwrap_or(existing)
            })
            .unwrap_or_else(|| self.invocation.source_root.clone().into_os_string());
        command.env("PYTHONPATH", python_path);

        let output = command
            .output()
            .map_err(|error| format!("failed to launch Universal Python PCC: {error}"))?;
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let value = serde_json::from_str::<Value>(&stdout).map_err(|error| {
            format!(
                "Universal Python PCC returned non-JSON output (exit={:?}): {error}; stdout={stdout}; stderr={stderr}",
                output.status.code()
            )
        })?;
        if output.status.success() {
            Ok(value)
        } else {
            Err(format!(
                "Universal Python PCC failed (exit={:?}): {}",
                output.status.code(),
                value
                    .get("error")
                    .and_then(Value::as_str)
                    .unwrap_or(stdout.as_str())
            ))
        }
    }
}

fn parse_python_version(text: &str) -> Option<(u32, u32)> {
    let version = text.split_whitespace().find(|part| {
        part.chars().next().is_some_and(|ch| ch.is_ascii_digit()) && part.contains('.')
    })?;
    let mut numbers = version.split('.').map(|part| {
        part.chars()
            .take_while(|ch| ch.is_ascii_digit())
            .collect::<String>()
    });
    let major = numbers.next()?.parse::<u32>().ok()?;
    let minor = numbers.next()?.parse::<u32>().ok()?;
    Some((major, minor))
}

fn python_version_ok(program: &str, prefix: &[String]) -> bool {
    let Ok(output) = Command::new(program).args(prefix).arg("--version").output() else {
        return false;
    };
    if !output.status.success() {
        return false;
    }
    let text = if output.stdout.is_empty() {
        String::from_utf8_lossy(&output.stderr).to_string()
    } else {
        String::from_utf8_lossy(&output.stdout).to_string()
    };
    matches!(parse_python_version(&text), Some((major, minor)) if major > 3 || (major == 3 && minor >= 11))
}

fn discover_python(source_root: PathBuf) -> Result<PccInvocation, String> {
    if let Some(explicit) = std::env::var_os("CORTEX_PCC_PYTHON").map(PathBuf::from) {
        let program = explicit.to_string_lossy().to_string();
        if !python_version_ok(&program, &[]) {
            return Err(format!(
                "CORTEX_PCC_PYTHON does not resolve to Python 3.11+: {}",
                explicit.display()
            ));
        }
        return Ok(PccInvocation {
            program: explicit,
            prefix_args: Vec::new(),
            source_root,
        });
    }
    for (program, prefix) in [
        ("python", Vec::<String>::new()),
        ("python3", Vec::<String>::new()),
        ("py", vec!["-3".to_string()]),
    ] {
        if python_version_ok(program, &prefix) {
            return Ok(PccInvocation {
                program: PathBuf::from(program),
                prefix_args: prefix,
                source_root,
            });
        }
    }
    Err("Universal Python PCC requires Python 3.11+ (python, python3, or py -3).".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_version_parser_is_deterministic() {
        assert_eq!(parse_python_version("Python 3.11.9"), Some((3, 11)));
        assert_eq!(parse_python_version("Python 3.13.5\r\n"), Some((3, 13)));
        assert_eq!(parse_python_version("Python 4.0.0"), Some((4, 0)));
        assert_eq!(parse_python_version("Python 3.10.14"), Some((3, 10)));
        assert_eq!(parse_python_version("not python"), None);
    }
}
