//! Native project-operation coordination for Cortex.
//!
//! This crate does not replace `cortex_adapter_git` or `cortex_execution`.
//! It composes the existing Git adapter with project-scoped coordination state:
//! rich read-only repository/worktree inspection and cross-process execution
//! leases that prevent conflicting project operations.

use cortex_adapter_git::GitAdapter;
use cortex_project::ProjectId;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{self, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const PROJECT_OPS_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_LEASE_TTL_MS: u128 = 15 * 60 * 1000;
const COORDINATION_LOCK_TIMEOUT: Duration = Duration::from_secs(3);
const COORDINATION_LOCK_RETRY: Duration = Duration::from_millis(25);
static LEASE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct RepositoryIdentity {
    pub root: PathBuf,
    pub git_dir: PathBuf,
    #[serde(default)]
    pub branch: Option<String>,
    #[serde(default)]
    pub head: Option<String>,
    #[serde(default)]
    pub upstream: Option<String>,
    #[serde(default)]
    pub origin: Option<String>,
    #[serde(default)]
    pub ahead: Option<u64>,
    #[serde(default)]
    pub behind: Option<u64>,
    #[serde(default)]
    pub detached: bool,
    #[serde(default)]
    pub bare: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct GitWorktreeState {
    pub path: PathBuf,
    #[serde(default)]
    pub head: Option<String>,
    #[serde(default)]
    pub branch: Option<String>,
    #[serde(default)]
    pub bare: bool,
    #[serde(default)]
    pub detached: bool,
    #[serde(default)]
    pub locked: bool,
    #[serde(default)]
    pub lock_reason: Option<String>,
    #[serde(default)]
    pub prunable: bool,
    #[serde(default)]
    pub prune_reason: Option<String>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectGitState {
    pub schema_version: u32,
    pub repository: RepositoryIdentity,
    #[serde(default)]
    pub clean: bool,
    #[serde(default)]
    pub porcelain: Vec<String>,
    #[serde(default)]
    pub worktrees: Vec<GitWorktreeState>,
    pub observed_unix_ms: u128,
}

impl ProjectGitState {
    pub fn synchronized_with_upstream(&self) -> bool {
        self.repository.ahead == Some(0) && self.repository.behind == Some(0)
    }

    pub fn has_multiple_worktrees(&self) -> bool {
        self.worktrees.len() > 1
    }
}

pub struct ProjectGitInspector;

impl ProjectGitInspector {
    pub fn inspect(root: impl AsRef<Path>) -> Result<ProjectGitState, String> {
        let root = root.as_ref();
        let adapter = GitAdapter::detect(root)
            .ok_or_else(|| format!("not a Git working tree: {}", root.display()))?;
        let status = adapter.status()?;

        let repository_root = git_required(root, &["rev-parse", "--show-toplevel"])?;
        let repository_root = canonical_or_original(Path::new(repository_root.trim()));

        let git_dir = git_required(root, &["rev-parse", "--absolute-git-dir"])?;
        let git_dir = canonical_or_original(Path::new(git_dir.trim()));

        let head = git_optional(root, &["rev-parse", "HEAD"]);
        let branch = status.branch.clone();
        let detached = branch.is_none() && head.is_some();
        let bare = git_optional(root, &["rev-parse", "--is-bare-repository"])
            .is_some_and(|value| value.trim().eq_ignore_ascii_case("true"));

        let upstream = git_optional(
            root,
            &[
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{upstream}",
            ],
        );
        let upstream = upstream
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());

        let origin = git_optional(root, &["remote", "get-url", "origin"])
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());

        let (ahead, behind) = upstream
            .as_deref()
            .and_then(|value| {
                git_optional(
                    root,
                    &[
                        "rev-list",
                        "--left-right",
                        "--count",
                        &format!("HEAD...{value}"),
                    ],
                )
            })
            .and_then(|value| parse_ahead_behind(&value))
            .map(|(ahead, behind)| (Some(ahead), Some(behind)))
            .unwrap_or((None, None));

        let worktree_porcelain = git_required(root, &["worktree", "list", "--porcelain"])?;
        let mut worktrees = parse_worktree_porcelain(&worktree_porcelain);
        worktrees.sort_by(|left, right| left.path.cmp(&right.path));

        Ok(ProjectGitState {
            schema_version: PROJECT_OPS_SCHEMA_VERSION,
            repository: RepositoryIdentity {
                root: repository_root,
                git_dir,
                branch,
                head: head.map(|value| value.trim().to_string()),
                upstream,
                origin,
                ahead,
                behind,
                detached,
                bare,
            },
            clean: status.clean,
            porcelain: status.porcelain,
            worktrees,
            observed_unix_ms: unix_millis(),
        })
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProjectLeaseMode {
    SharedRead,
    #[default]
    ExclusiveWrite,
}

impl ProjectLeaseMode {
    fn conflicts_with(self, other: Self) -> bool {
        !matches!((self, other), (Self::SharedRead, Self::SharedRead))
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectExecutionLease {
    pub schema_version: u32,
    pub lease_id: String,
    #[serde(default)]
    pub project_id: Option<ProjectId>,
    pub project_root: PathBuf,
    pub operation_id: String,
    pub mode: ProjectLeaseMode,
    pub owner_pid: u32,
    pub acquired_unix_ms: u128,
    pub heartbeat_unix_ms: u128,
    pub ttl_ms: u128,
}

impl ProjectExecutionLease {
    pub fn stale_at(&self, now_unix_ms: u128) -> bool {
        now_unix_ms.saturating_sub(self.heartbeat_unix_ms) > self.ttl_ms.max(1)
    }
}

#[derive(Clone, Debug)]
pub struct ProjectExecutionLeaseStore {
    root: PathBuf,
    ttl_ms: u128,
}

impl ProjectExecutionLeaseStore {
    pub fn new(state_root: impl Into<PathBuf>) -> Self {
        Self::with_ttl(state_root, DEFAULT_LEASE_TTL_MS)
    }

    pub fn with_ttl(state_root: impl Into<PathBuf>, ttl_ms: u128) -> Self {
        Self {
            root: state_root.into().join("execution-leases"),
            ttl_ms: ttl_ms.max(1),
        }
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn active(&self) -> Result<Vec<ProjectExecutionLease>, String> {
        fs::create_dir_all(&self.root).map_err(|error| error.to_string())?;
        let now = unix_millis();
        let mut leases = Vec::new();

        for entry in fs::read_dir(&self.root).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let lease = read_lease(&path)?;
            if !lease.stale_at(now) {
                leases.push(lease);
            }
        }

        leases.sort_by(|left, right| left.lease_id.cmp(&right.lease_id));
        Ok(leases)
    }

    pub fn acquire(
        &self,
        project_id: Option<ProjectId>,
        project_root: impl AsRef<Path>,
        operation_id: impl Into<String>,
        mode: ProjectLeaseMode,
    ) -> Result<ProjectExecutionLeaseGuard, String> {
        let operation_id = operation_id.into().trim().to_string();
        if operation_id.is_empty() {
            return Err("project execution lease operation id cannot be empty".into());
        }

        let project_root = fs::canonicalize(project_root.as_ref()).map_err(|error| {
            format!(
                "failed to resolve project lease root {}: {error}",
                project_root.as_ref().display()
            )
        })?;

        fs::create_dir_all(&self.root).map_err(|error| error.to_string())?;
        let _lock = CoordinationLock::acquire(&self.root)?;

        self.reap_stale_locked()?;

        let existing = self.read_all_locked()?;
        if let Some(conflict) = existing.iter().find(|lease| {
            lease.project_root == project_root && mode.conflicts_with(lease.mode)
        }) {
            return Err(format!(
                "project operation is already leased: project={} operation={} mode={:?} owner_pid={} lease={}",
                project_root.display(),
                conflict.operation_id,
                conflict.mode,
                conflict.owner_pid,
                conflict.lease_id
            ));
        }

        let now = unix_millis();
        let lease_id = new_lease_id(&operation_id);
        let lease = ProjectExecutionLease {
            schema_version: PROJECT_OPS_SCHEMA_VERSION,
            lease_id: lease_id.clone(),
            project_id,
            project_root,
            operation_id,
            mode,
            owner_pid: process::id(),
            acquired_unix_ms: now,
            heartbeat_unix_ms: now,
            ttl_ms: self.ttl_ms,
        };

        write_lease_atomic(&self.lease_path(&lease_id), &lease)?;

        Ok(ProjectExecutionLeaseGuard {
            store: self.clone(),
            lease,
            released: false,
        })
    }

    pub fn heartbeat(&self, lease_id: &str) -> Result<ProjectExecutionLease, String> {
        let _lock = CoordinationLock::acquire(&self.root)?;
        let path = self.lease_path(lease_id);
        let mut lease = read_lease(&path)?;
        if lease.owner_pid != process::id() {
            return Err(format!(
                "lease {} is owned by pid {}, not current pid {}",
                lease.lease_id,
                lease.owner_pid,
                process::id()
            ));
        }
        lease.heartbeat_unix_ms = unix_millis();
        write_lease_atomic(&path, &lease)?;
        Ok(lease)
    }

    pub fn release(&self, lease_id: &str) -> Result<bool, String> {
        let _lock = CoordinationLock::acquire(&self.root)?;
        let path = self.lease_path(lease_id);
        if !path.exists() {
            return Ok(false);
        }
        let lease = read_lease(&path)?;
        if lease.owner_pid != process::id() {
            return Err(format!(
                "refusing to release lease {} owned by pid {}",
                lease.lease_id, lease.owner_pid
            ));
        }
        fs::remove_file(&path).map_err(|error| {
            format!("failed to release project execution lease {}: {error}", path.display())
        })?;
        Ok(true)
    }

    pub fn reap_stale(&self) -> Result<usize, String> {
        fs::create_dir_all(&self.root).map_err(|error| error.to_string())?;
        let _lock = CoordinationLock::acquire(&self.root)?;
        self.reap_stale_locked()
    }

    fn lease_path(&self, lease_id: &str) -> PathBuf {
        self.root.join(format!("{}.json", sanitize_id(lease_id)))
    }

    fn read_all_locked(&self) -> Result<Vec<ProjectExecutionLease>, String> {
        let mut leases = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            leases.push(read_lease(&path)?);
        }
        Ok(leases)
    }

    fn reap_stale_locked(&self) -> Result<usize, String> {
        let now = unix_millis();
        let mut removed = 0usize;
        for entry in fs::read_dir(&self.root).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let lease = read_lease(&path)?;
            if lease.stale_at(now) {
                fs::remove_file(&path).map_err(|error| {
                    format!("failed to reap stale lease {}: {error}", path.display())
                })?;
                removed = removed.saturating_add(1);
            }
        }
        Ok(removed)
    }
}

pub struct ProjectExecutionLeaseGuard {
    store: ProjectExecutionLeaseStore,
    lease: ProjectExecutionLease,
    released: bool,
}

impl ProjectExecutionLeaseGuard {
    pub fn lease(&self) -> &ProjectExecutionLease {
        &self.lease
    }

    pub fn heartbeat(&mut self) -> Result<(), String> {
        self.lease = self.store.heartbeat(&self.lease.lease_id)?;
        Ok(())
    }

    pub fn release(&mut self) -> Result<(), String> {
        if self.released {
            return Ok(());
        }
        let _ = self.store.release(&self.lease.lease_id)?;
        self.released = true;
        Ok(())
    }
}

impl Drop for ProjectExecutionLeaseGuard {
    fn drop(&mut self) {
        let _ = self.release();
    }
}

struct CoordinationLock {
    path: PathBuf,
}

impl CoordinationLock {
    fn acquire(root: &Path) -> Result<Self, String> {
        fs::create_dir_all(root).map_err(|error| error.to_string())?;
        let path = root.join(".coordination.lock");
        let deadline = std::time::Instant::now() + COORDINATION_LOCK_TIMEOUT;

        loop {
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(mut file) => {
                    let _ = writeln!(
                        file,
                        "pid={} acquired_unix_ms={}",
                        process::id(),
                        unix_millis()
                    );
                    return Ok(Self { path });
                }
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    if std::time::Instant::now() >= deadline {
                        return Err(format!(
                            "timed out acquiring project-operation coordination lock: {}",
                            path.display()
                        ));
                    }
                    thread::sleep(COORDINATION_LOCK_RETRY);
                }
                Err(error) => {
                    return Err(format!(
                        "failed to acquire project-operation coordination lock {}: {error}",
                        path.display()
                    ));
                }
            }
        }
    }
}

impl Drop for CoordinationLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

fn git_required(root: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("git")
        .args(args)
        .current_dir(root)
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

fn git_optional(root: &Path, args: &[&str]) -> Option<String> {
    git_required(root, args).ok()
}

fn parse_ahead_behind(value: &str) -> Option<(u64, u64)> {
    let mut parts = value.split_whitespace();
    let ahead = parts.next()?.parse::<u64>().ok()?;
    let behind = parts.next()?.parse::<u64>().ok()?;
    Some((ahead, behind))
}

fn parse_worktree_porcelain(value: &str) -> Vec<GitWorktreeState> {
    let mut worktrees = Vec::new();
    let mut current: Option<GitWorktreeState> = None;

    for line in value.lines().chain(std::iter::once("")) {
        if line.trim().is_empty() {
            if let Some(worktree) = current.take() {
                worktrees.push(worktree);
            }
            continue;
        }

        if let Some(path) = line.strip_prefix("worktree ") {
            if let Some(worktree) = current.take() {
                worktrees.push(worktree);
            }
            current = Some(GitWorktreeState {
                path: PathBuf::from(path),
                ..GitWorktreeState::default()
            });
            continue;
        }

        let Some(worktree) = current.as_mut() else {
            continue;
        };

        if let Some(head) = line.strip_prefix("HEAD ") {
            worktree.head = Some(head.to_string());
        } else if let Some(branch) = line.strip_prefix("branch ") {
            worktree.branch = Some(
                branch
                    .strip_prefix("refs/heads/")
                    .unwrap_or(branch)
                    .to_string(),
            );
        } else if line == "bare" {
            worktree.bare = true;
        } else if line == "detached" {
            worktree.detached = true;
        } else if let Some(reason) = line.strip_prefix("locked") {
            worktree.locked = true;
            let reason = reason.trim();
            if !reason.is_empty() {
                worktree.lock_reason = Some(reason.to_string());
            }
        } else if let Some(reason) = line.strip_prefix("prunable") {
            worktree.prunable = true;
            let reason = reason.trim();
            if !reason.is_empty() {
                worktree.prune_reason = Some(reason.to_string());
            }
        }
    }

    worktrees
}

fn canonical_or_original(path: &Path) -> PathBuf {
    fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
}

fn read_lease(path: &Path) -> Result<ProjectExecutionLease, String> {
    let lease: ProjectExecutionLease = serde_json::from_slice(
        &fs::read(path)
            .map_err(|error| format!("failed to read lease {}: {error}", path.display()))?,
    )
    .map_err(|error| format!("invalid lease {}: {error}", path.display()))?;
    if lease.schema_version != PROJECT_OPS_SCHEMA_VERSION {
        return Err(format!(
            "unsupported project execution lease schema {} in {}",
            lease.schema_version,
            path.display()
        ));
    }
    Ok(lease)
}

fn write_lease_atomic(path: &Path, lease: &ProjectExecutionLease) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = path.with_extension(format!("json.tmp.{}", process::id()));
    let bytes = serde_json::to_vec_pretty(lease)
        .map_err(|error| format!("failed to encode project execution lease: {error}"))?;
    fs::write(&temp, bytes)
        .map_err(|error| format!("failed to write lease {}: {error}", temp.display()))?;
    if path.exists() {
        fs::remove_file(path)
            .map_err(|error| format!("failed to replace lease {}: {error}", path.display()))?;
    }
    fs::rename(&temp, path)
        .map_err(|error| format!("failed to publish lease {}: {error}", path.display()))
}

fn new_lease_id(operation_id: &str) -> String {
    let sequence = LEASE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!(
        "lease-{}-{}-{}-{}",
        unix_millis(),
        process::id(),
        sequence,
        sanitize_id(operation_id)
    )
}

fn sanitize_id(value: &str) -> String {
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
        trimmed.chars().take(80).collect()
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

    fn temp_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "cortex-project-ops-{label}-{}-{}",
            process::id(),
            unix_millis()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn worktree_porcelain_parser_preserves_lock_and_detached_state() {
        let input = "\
worktree C:/repo
HEAD aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/main

worktree C:/repo-task
HEAD bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
detached
locked task active

";
        let worktrees = parse_worktree_porcelain(input);
        assert_eq!(worktrees.len(), 2);
        assert_eq!(worktrees[0].branch.as_deref(), Some("main"));
        assert!(worktrees[1].detached);
        assert!(worktrees[1].locked);
        assert_eq!(worktrees[1].lock_reason.as_deref(), Some("task active"));
    }

    #[test]
    fn ahead_behind_parser_is_stable() {
        assert_eq!(parse_ahead_behind("3\t2\n"), Some((3, 2)));
        assert_eq!(parse_ahead_behind("bad"), None);
    }

    #[test]
    fn shared_read_leases_can_coexist_but_write_conflicts() {
        let state = temp_root("shared");
        let project = temp_root("project-shared");
        let store = ProjectExecutionLeaseStore::new(&state);

        let read_a = store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "read-a",
                ProjectLeaseMode::SharedRead,
            )
            .unwrap();
        let read_b = store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "read-b",
                ProjectLeaseMode::SharedRead,
            )
            .unwrap();

        assert_eq!(store.active().unwrap().len(), 2);
        assert!(store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "write",
                ProjectLeaseMode::ExclusiveWrite,
            )
            .is_err());

        drop(read_b);
        drop(read_a);
        let _ = fs::remove_dir_all(state);
        let _ = fs::remove_dir_all(project);
    }

    #[test]
    fn exclusive_write_blocks_second_operation() {
        let state = temp_root("exclusive");
        let project = temp_root("project-exclusive");
        let store = ProjectExecutionLeaseStore::new(&state);

        let write = store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "write-a",
                ProjectLeaseMode::ExclusiveWrite,
            )
            .unwrap();

        assert!(store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "read",
                ProjectLeaseMode::SharedRead,
            )
            .is_err());

        drop(write);
        assert!(store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "read",
                ProjectLeaseMode::SharedRead,
            )
            .is_ok());

        let _ = fs::remove_dir_all(state);
        let _ = fs::remove_dir_all(project);
    }

    #[test]
    fn stale_lease_is_reaped_before_acquire() {
        let state = temp_root("stale");
        let project = temp_root("project-stale");
        let store = ProjectExecutionLeaseStore::with_ttl(&state, 1);
        fs::create_dir_all(store.root()).unwrap();

        let stale = ProjectExecutionLease {
            schema_version: PROJECT_OPS_SCHEMA_VERSION,
            lease_id: "lease-stale".into(),
            project_id: Some(ProjectId::new("cortex").unwrap()),
            project_root: fs::canonicalize(&project).unwrap(),
            operation_id: "old".into(),
            mode: ProjectLeaseMode::ExclusiveWrite,
            owner_pid: 999_999,
            acquired_unix_ms: 1,
            heartbeat_unix_ms: 1,
            ttl_ms: 1,
        };
        write_lease_atomic(&store.lease_path(&stale.lease_id), &stale).unwrap();

        let lease = store
            .acquire(
                Some(ProjectId::new("cortex").unwrap()),
                &project,
                "new",
                ProjectLeaseMode::ExclusiveWrite,
            )
            .unwrap();
        assert_eq!(lease.lease().operation_id, "new");

        drop(lease);
        let _ = fs::remove_dir_all(state);
        let _ = fs::remove_dir_all(project);
    }

    #[test]
    fn lease_ids_are_filesystem_safe() {
        let id = new_lease_id("build / dangerous:value");
        assert!(!id.contains('/'));
        assert!(!id.contains(':'));
    }
}
