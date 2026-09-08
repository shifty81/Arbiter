//! Read-only Git integration for Cortex review workflows.
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TaskWorktreePlan {
    pub task_id: String,
    pub source_root: PathBuf,
    pub worktree_root: PathBuf,
    pub branch_name: String,
}

impl TaskWorktreePlan {
    pub fn add_args(&self) -> Vec<String> {
        vec![
            "worktree".into(),
            "add".into(),
            "-b".into(),
            self.branch_name.clone(),
            git_cli_path(&self.worktree_root),
        ]
    }

    pub fn remove_args(&self) -> Vec<String> {
        vec![
            "worktree".into(),
            "remove".into(),
            "--force".into(),
            git_cli_path(&self.worktree_root),
        ]
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct GitRecoveryPlan {
    pub repository_root: PathBuf,
    pub bundle_path: PathBuf,
    pub enable_rerere: bool,
}

impl GitRecoveryPlan {
    pub fn bundle_create_args(&self) -> Vec<String> {
        vec![
            "bundle".into(),
            "create".into(),
            git_cli_path(&self.bundle_path),
            "--all".into(),
        ]
    }

    pub fn rerere_config_args(&self) -> Vec<String> {
        vec!["config".into(), "rerere.enabled".into(), "true".into()]
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GitStatus {
    pub root: PathBuf,
    pub branch: Option<String>,
    pub porcelain: Vec<String>,
    pub clean: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GitCommit {
    pub hash: String,
    pub author: String,
    pub subject: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ShadowGitSnapshot {
    pub project_root: PathBuf,
    pub git_dir: PathBuf,
    pub commit: String,
    pub changed: bool,
    pub label: String,
}

fn git_cli_path(path: &Path) -> String {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = text.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        text.into_owned()
    }
}

pub struct ShadowGitStore;

impl ShadowGitStore {
    pub fn snapshot(
        project_root: &Path,
        git_dir: &Path,
        label: &str,
    ) -> Result<ShadowGitSnapshot, String> {
        if !project_root.is_dir() {
            return Err(format!(
                "project root does not exist: {}",
                project_root.display()
            ));
        }
        fs::create_dir_all(git_dir).map_err(|error| error.to_string())?;
        let git_dir_text = git_cli_path(git_dir);
        let work_tree_text = git_cli_path(project_root);
        let base = [
            format!("--git-dir={git_dir_text}"),
            format!("--work-tree={work_tree_text}"),
        ];
        if !git_dir.join("HEAD").is_file() {
            run_git_owned(
                project_root,
                &[base[0].clone(), base[1].clone(), "init".into()],
            )?;
            run_git_owned(
                project_root,
                &[
                    base[0].clone(),
                    "config".into(),
                    "user.name".into(),
                    "Cortex Local Recovery".into(),
                ],
            )?;
            run_git_owned(
                project_root,
                &[
                    base[0].clone(),
                    "config".into(),
                    "user.email".into(),
                    "cortex@local.invalid".into(),
                ],
            )?;
            let info = git_dir.join("info");
            fs::create_dir_all(&info).map_err(|error| error.to_string())?;
            fs::write(
                info.join("exclude"),
                "target/\nnode_modules/\nbuild/\nbuilds/\nbin/\nobj/\n.cache/\n.idea/\n.vs/\nDerivedDataCache/\nIntermediate/\nSaved/\ndist/\nout/\n.cortex/\n",
            )
            .map_err(|error| error.to_string())?;
        }
        run_git_owned(
            project_root,
            &[base[0].clone(), base[1].clone(), "add".into(), "-A".into()],
        )?;
        let changed = !Command::new("git")
            .args([
                base[0].as_str(),
                base[1].as_str(),
                "diff",
                "--cached",
                "--quiet",
            ])
            .current_dir(project_root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| format!("failed to inspect Cortex shadow Git state: {error}"))?
            .success();
        if changed {
            run_git_owned(
                project_root,
                &[
                    base[0].clone(),
                    base[1].clone(),
                    "commit".into(),
                    "-m".into(),
                    label.to_string(),
                ],
            )?;
        }
        let commit = run_git_owned(
            project_root,
            &[
                base[0].clone(),
                base[1].clone(),
                "rev-parse".into(),
                "HEAD".into(),
            ],
        )?
        .trim()
        .to_string();
        Ok(ShadowGitSnapshot {
            project_root: project_root.to_path_buf(),
            git_dir: git_dir.to_path_buf(),
            commit,
            changed,
            label: label.to_string(),
        })
    }

    pub fn log(
        project_root: &Path,
        git_dir: &Path,
        limit: usize,
    ) -> Result<Vec<GitCommit>, String> {
        if !git_dir.join("HEAD").is_file() {
            return Ok(Vec::new());
        }
        let args = vec![
            format!("--git-dir={}", git_cli_path(git_dir)),
            format!("--work-tree={}", git_cli_path(project_root)),
            "log".into(),
            "-n".into(),
            limit.clamp(1, 200).to_string(),
            "--pretty=format:%H%x1f%an%x1f%s".into(),
        ];
        let out = run_git_owned(project_root, &args)?;
        Ok(out
            .lines()
            .filter_map(|line| {
                let mut parts = line.split('\x1f');
                Some(GitCommit {
                    hash: parts.next()?.into(),
                    author: parts.next()?.into(),
                    subject: parts.next()?.into(),
                })
            })
            .collect())
    }
}

#[derive(Clone, Debug)]
pub struct GitAdapter {
    root: PathBuf,
}
impl GitAdapter {
    pub fn detect(root: impl AsRef<Path>) -> Option<Self> {
        let root = root.as_ref();
        if !root.is_dir() {
            return None;
        }

        let output = Command::new("git")
            .args(["rev-parse", "--is-inside-work-tree"])
            .current_dir(root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .ok()?;

        (output.status.success() && String::from_utf8_lossy(&output.stdout).trim() == "true").then(
            || Self {
                root: root.to_path_buf(),
            },
        )
    }
    pub fn status(&self) -> Result<GitStatus, String> {
        let p = self.run(&["status", "--porcelain=v1"])?;
        let branch = self
            .run(&["branch", "--show-current"])
            .ok()
            .map(|x| x.trim().to_string())
            .filter(|x| !x.is_empty());
        let lines = p
            .lines()
            .filter(|l| !l.trim().is_empty())
            .map(str::to_string)
            .collect::<Vec<_>>();
        Ok(GitStatus {
            root: self.root.clone(),
            branch,
            clean: lines.is_empty(),
            porcelain: lines,
        })
    }
    pub fn diff(&self, paths: &[PathBuf], staged: bool) -> Result<String, String> {
        let mut a = vec!["diff".to_string(), "--no-ext-diff".to_string()];
        if staged {
            a.push("--cached".into());
        }
        if !paths.is_empty() {
            a.push("--".into());
            a.extend(paths.iter().map(|p| p.to_string_lossy().to_string()));
        }
        self.run_owned(&a)
    }
    pub fn log(&self, limit: usize) -> Result<Vec<GitCommit>, String> {
        let n = limit.clamp(1, 200).to_string();
        let out = self.run(&["log", "-n", &n, "--pretty=format:%H%x1f%an%x1f%s"])?;
        Ok(out
            .lines()
            .filter_map(|l| {
                let mut p = l.split('\x1f');
                Some(GitCommit {
                    hash: p.next()?.into(),
                    author: p.next()?.into(),
                    subject: p.next()?.into(),
                })
            })
            .collect())
    }
    pub fn show(&self, rev: &str) -> Result<String, String> {
        validate_revision(rev)?;
        self.run(&["show", "--stat", "--oneline", "--decorate", rev])
    }
    fn run(&self, args: &[&str]) -> Result<String, String> {
        self.run_owned(&args.iter().map(|x| (*x).to_string()).collect::<Vec<_>>())
    }
    fn run_owned(&self, args: &[String]) -> Result<String, String> {
        let out = Command::new("git")
            .args(args)
            .current_dir(&self.root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|e| format!("failed to run git: {e}"))?;
        if !out.status.success() {
            return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
        }
        Ok(String::from_utf8_lossy(&out.stdout).to_string())
    }
}
fn run_git_owned(cwd: &Path, args: &[String]) -> Result<String, String> {
    let output = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|error| format!("failed to run git: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn validate_revision(v: &str) -> Result<(), String> {
    if v.is_empty()
        || !v
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '/' | '.' | '~' | '^'))
    {
        Err("invalid Git revision".into())
    } else {
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unsafe_revision_rejected() {
        assert!(validate_revision("HEAD;bad").is_err());
        assert!(validate_revision("HEAD~1").is_ok());
    }

    #[test]
    fn git_cli_path_strips_extended_windows_drive_prefix() {
        assert_eq!(
            git_cli_path(Path::new(r"\\?\D:\Git\Recovery\projects\fixture.git")),
            r"D:\Git\Recovery\projects\fixture.git"
        );
    }

    #[test]
    fn git_cli_path_strips_extended_windows_unc_prefix() {
        assert_eq!(
            git_cli_path(Path::new(r"\\?\UNC\server\share\fixture.git")),
            r"\\server\share\fixture.git"
        );
    }

    #[test]
    fn git_cli_path_preserves_normal_paths() {
        assert_eq!(
            git_cli_path(Path::new(r"D:\Git\Recovery\projects\fixture.git")),
            r"D:\Git\Recovery\projects\fixture.git"
        );
    }
}
