//! Canonical durable Cortex jobs and event-stream authority.

pub use cortex_execution::{
    DiagnosticSnapshot, ExecutionPhase, ExecutionProgressSnapshot, ExecutionTranscriptEntry,
    RepairDossier, RepairFailureClass, RepairProgressStage, RepairStrategy, TranscriptVisibility,
    VerificationDelta,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AutomationTrigger {
    Manual,
    Startup,
    IntervalMinutes(u32),
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AutomationDefinition {
    pub schema_version: u32,
    pub id: String,
    pub name: String,
    pub skill_id: String,
    pub project_id: Option<String>,
    pub enabled: bool,
    pub trigger: AutomationTrigger,
    #[serde(default)]
    pub arguments: Value,
    pub created_unix_ms: u128,
    pub updated_unix_ms: u128,
    pub last_run_unix_ms: Option<u128>,
}

pub struct AutomationStore {
    path: PathBuf,
}

impl AutomationStore {
    pub fn open(state_root: impl AsRef<Path>) -> Result<Self, String> {
        let root = state_root.as_ref().join("automations");
        fs::create_dir_all(&root).map_err(|error| error.to_string())?;
        Ok(Self {
            path: root.join("automations.json"),
        })
    }

    pub fn list(&self) -> Result<Vec<AutomationDefinition>, String> {
        if !self.path.is_file() {
            return Ok(Vec::new());
        }
        serde_json::from_slice(&fs::read(&self.path).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())
    }

    pub fn upsert(&self, mut definition: AutomationDefinition) -> Result<(), String> {
        validate_automation_id(&definition.id)?;
        let mut definitions = self.list()?;
        definition.updated_unix_ms = unix_ms();
        if let Some(existing) = definitions
            .iter_mut()
            .find(|existing| existing.id == definition.id)
        {
            *existing = definition;
        } else {
            definitions.push(definition);
        }
        definitions.sort_by(|left, right| left.id.cmp(&right.id));
        fs::write(
            &self.path,
            serde_json::to_vec_pretty(&definitions).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }

    pub fn due_at_startup(&self) -> Result<Vec<AutomationDefinition>, String> {
        Ok(self
            .list()?
            .into_iter()
            .filter(|automation| {
                automation.enabled && matches!(automation.trigger, AutomationTrigger::Startup)
            })
            .collect())
    }
}

fn validate_automation_id(id: &str) -> Result<(), String> {
    if id.is_empty()
        || !id.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
    {
        Err("invalid Cortex automation id".into())
    } else {
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Queued,
    Running,
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct JobProgress {
    pub current: u64,
    pub total: Option<u64>,
    pub message: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CortexJob {
    pub schema_version: u32,
    pub id: String,
    pub kind: String,
    pub title: String,
    pub status: JobStatus,
    pub created_unix_ms: u128,
    pub updated_unix_ms: u128,
    pub progress: JobProgress,
    pub detail: String,
    #[serde(default)]
    pub result: Value,
    pub cancellation_requested: bool,
}

pub struct JobStore {
    root: PathBuf,
}

impl JobStore {
    pub fn open(state_root: impl AsRef<Path>) -> Result<Self, String> {
        let root = state_root.as_ref().join("jobs");
        fs::create_dir_all(&root).map_err(|error| error.to_string())?;
        Ok(Self { root })
    }

    pub fn create(&self, kind: &str, title: &str) -> Result<CortexJob, String> {
        let now = unix_ms();
        let job = CortexJob {
            schema_version: 1,
            id: format!("{now}-{}-job", std::process::id()),
            kind: kind.to_string(),
            title: title.to_string(),
            status: JobStatus::Queued,
            created_unix_ms: now,
            updated_unix_ms: now,
            progress: JobProgress::default(),
            detail: String::new(),
            result: Value::Null,
            cancellation_requested: false,
        };
        self.save(&job)?;
        Ok(job)
    }

    pub fn update(
        &self,
        job: &mut CortexJob,
        status: JobStatus,
        detail: impl Into<String>,
        result: Value,
    ) -> Result<(), String> {
        job.status = status;
        job.detail = detail.into();
        job.result = result;
        job.updated_unix_ms = unix_ms();
        self.save(job)
    }

    pub fn progress(
        &self,
        job: &mut CortexJob,
        current: u64,
        total: Option<u64>,
        message: impl Into<String>,
    ) -> Result<(), String> {
        job.status = JobStatus::Running;
        job.progress = JobProgress {
            current,
            total,
            message: message.into(),
        };
        job.updated_unix_ms = unix_ms();
        self.save(job)
    }

    pub fn request_cancel(&self, id: &str) -> Result<bool, String> {
        let Some(mut job) = self.get(id)? else {
            return Ok(false);
        };
        if matches!(
            job.status,
            JobStatus::Succeeded | JobStatus::Failed | JobStatus::Cancelled
        ) {
            return Ok(false);
        }
        job.cancellation_requested = true;
        job.updated_unix_ms = unix_ms();
        self.save(&job)?;
        Ok(true)
    }

    pub fn cancellation_requested(&self, id: &str) -> Result<bool, String> {
        Ok(self
            .get(id)?
            .map(|job| job.cancellation_requested)
            .unwrap_or(false))
    }

    pub fn get(&self, id: &str) -> Result<Option<CortexJob>, String> {
        let path = self.root.join(format!("{id}.json"));
        if !path.is_file() {
            return Ok(None);
        }
        serde_json::from_slice(&fs::read(path).map_err(|error| error.to_string())?)
            .map(Some)
            .map_err(|error| error.to_string())
    }

    pub fn list(&self, limit: usize) -> Result<Vec<CortexJob>, String> {
        let mut jobs = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|error| error.to_string())? {
            let path = entry.map_err(|error| error.to_string())?.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let Ok(job) = serde_json::from_slice::<CortexJob>(
                &fs::read(path).map_err(|error| error.to_string())?,
            ) else {
                continue;
            };
            jobs.push(job);
        }
        jobs.sort_by_key(|job| std::cmp::Reverse(job.updated_unix_ms));
        jobs.truncate(limit.clamp(1, 500));
        Ok(jobs)
    }

    fn save(&self, job: &CortexJob) -> Result<(), String> {
        fs::write(
            self.root.join(format!("{}.json", job.id)),
            serde_json::to_vec_pretty(job).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EventKind {
    Chat,
    Agent,
    Tool,
    Build,
    Review,
    Vault,
    Context,
    Workspace,
    Artifact,
    Service,
    Job,
    Approval,
    Error,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CortexEvent {
    pub schema_version: u32,
    pub id: String,
    pub created_unix_ms: u128,
    pub kind: EventKind,
    pub title: String,
    pub detail: String,
    pub success: Option<bool>,
    #[serde(default)]
    pub metadata: Value,
}

pub struct EventStore {
    path: PathBuf,
}

impl EventStore {
    pub fn open(state_root: impl AsRef<Path>) -> Result<Self, String> {
        let root = state_root.as_ref().join("events");
        fs::create_dir_all(&root).map_err(|error| error.to_string())?;
        Ok(Self {
            path: root.join("events.jsonl"),
        })
    }

    pub fn append(
        &self,
        kind: EventKind,
        title: impl Into<String>,
        detail: impl Into<String>,
        success: Option<bool>,
        metadata: Value,
    ) -> Result<CortexEvent, String> {
        self.append_at(unix_ms(), kind, title, detail, success, metadata)
    }

    pub fn append_execution(
        &self,
        entry: &ExecutionTranscriptEntry,
    ) -> Result<CortexEvent, String> {
        let kind = match entry.phase {
            ExecutionPhase::Tool | ExecutionPhase::Mutation => EventKind::Tool,
            ExecutionPhase::Format
            | ExecutionPhase::Check
            | ExecutionPhase::Test
            | ExecutionPhase::Lint
            | ExecutionPhase::Build
            | ExecutionPhase::Launch
            | ExecutionPhase::Verify => EventKind::Build,
            ExecutionPhase::Context | ExecutionPhase::Compact => EventKind::Context,
            ExecutionPhase::Failed | ExecutionPhase::Cancelled => EventKind::Error,
            _ => EventKind::Agent,
        };
        let metadata = serde_json::to_value(entry).map_err(|error| error.to_string())?;
        self.append_at(
            entry.created_unix_ms,
            kind,
            &entry.title,
            entry.render_activity_detail(),
            entry.success,
            metadata,
        )
    }

    fn append_at(
        &self,
        created_unix_ms: u128,
        kind: EventKind,
        title: impl Into<String>,
        detail: impl Into<String>,
        success: Option<bool>,
        metadata: Value,
    ) -> Result<CortexEvent, String> {
        let event = CortexEvent {
            schema_version: 1,
            id: format!("{created_unix_ms}-{}-event", std::process::id()),
            created_unix_ms,
            kind,
            title: title.into(),
            detail: detail.into(),
            success,
            metadata,
        };
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .map_err(|error| error.to_string())?;
        serde_json::to_writer(&mut file, &event).map_err(|error| error.to_string())?;
        file.write_all(b"\n").map_err(|error| error.to_string())?;
        Ok(event)
    }

    pub fn recent(&self, limit: usize) -> Result<Vec<CortexEvent>, String> {
        if !self.path.is_file() {
            return Ok(Vec::new());
        }
        let file = fs::File::open(&self.path).map_err(|error| error.to_string())?;
        let mut events = BufReader::new(file)
            .lines()
            .map_while(Result::ok)
            .filter_map(|line| serde_json::from_str::<CortexEvent>(&line).ok())
            .collect::<Vec<_>>();
        events.sort_by_key(|event| std::cmp::Reverse(event.created_unix_ms));
        events.truncate(limit.clamp(1, 500));
        Ok(events)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

// Compatibility names used by pre-R051N4 callers.
pub type TaskStatus = JobStatus;
pub type CortexTask = CortexJob;
pub struct TaskStore(JobStore);

impl TaskStore {
    pub fn open(state_root: impl AsRef<Path>) -> Result<Self, String> {
        JobStore::open(state_root).map(Self)
    }
    pub fn create(&self, title: &str) -> Result<CortexTask, String> {
        self.0.create("task", title)
    }
    pub fn update(
        &self,
        task: &mut CortexTask,
        status: TaskStatus,
        detail: impl Into<String>,
        result: Value,
    ) -> Result<(), String> {
        self.0.update(task, status, detail, result)
    }
    pub fn list(&self, limit: usize) -> Result<Vec<CortexTask>, String> {
        self.0.list(limit)
    }
}

pub type ActivityKind = EventKind;
pub type ActivityEvent = CortexEvent;
pub struct ActivityStore(EventStore);

impl ActivityStore {
    pub fn open(state_root: impl AsRef<Path>) -> Result<Self, String> {
        EventStore::open(state_root).map(Self)
    }
    pub fn append(
        &self,
        kind: ActivityKind,
        title: impl Into<String>,
        detail: impl Into<String>,
        success: Option<bool>,
        metadata: Value,
    ) -> Result<ActivityEvent, String> {
        self.0.append(kind, title, detail, success, metadata)
    }
    pub fn append_execution(
        &self,
        entry: &ExecutionTranscriptEntry,
    ) -> Result<ActivityEvent, String> {
        self.0.append_execution(entry)
    }
    pub fn recent(&self, limit: usize) -> Result<Vec<ActivityEvent>, String> {
        self.0.recent(limit)
    }
    pub fn path(&self) -> &Path {
        self.0.path()
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
    fn cancellation_is_durable() {
        let root = std::env::temp_dir().join(format!("cortex-jobs-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        let store = JobStore::open(&root).unwrap();
        let job = store.create("test", "test job").unwrap();
        assert!(store.request_cancel(&job.id).unwrap());
        assert!(store.cancellation_requested(&job.id).unwrap());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn execution_entries_keep_authoritative_timestamp_and_metadata() {
        let root = std::env::temp_dir().join(format!(
            "cortex-jobs-execution-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        let _ = fs::remove_dir_all(&root);
        let store = EventStore::open(&root).unwrap();
        let mut entry = ExecutionTranscriptEntry::new(
            ExecutionPhase::Build,
            "Building",
            "cargo build is running",
        );
        entry.command = Some("cargo build".into());
        let expected_timestamp = entry.created_unix_ms;
        let event = store.append_execution(&entry).unwrap();
        assert_eq!(event.created_unix_ms, expected_timestamp);
        assert_eq!(event.kind, EventKind::Build);
        assert_eq!(event.metadata["phase"], "build");
        assert_eq!(event.metadata["command"], "cargo build");
        let _ = fs::remove_dir_all(root);
    }
}
