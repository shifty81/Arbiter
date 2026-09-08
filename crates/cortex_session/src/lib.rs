//! Canonical project-agnostic Cortex development-session evidence layout.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DevSession {
    pub schema_version: u32,
    pub id: String,
    pub project_root: PathBuf,
    pub directory: PathBuf,
    pub created_unix_ms: u128,
    pub captures: Vec<CaptureEvidence>,
    pub events: Vec<SessionEvent>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CaptureEvidence {
    pub path: PathBuf,
    pub source: String,
    pub created_unix_ms: u128,
    pub metadata: serde_json::Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SessionEvent {
    pub created_unix_ms: u128,
    pub kind: String,
    pub message: String,
    pub data: serde_json::Value,
}

impl DevSession {
    pub fn create(project_root: impl AsRef<Path>, label: &str) -> Result<Self, String> {
        let project_root = project_root.as_ref().to_path_buf();
        let sessions_root = project_root.join(".cortex").join("sessions");
        Self::create_in(project_root, sessions_root, label)
    }

    pub fn create_in(
        project_root: impl AsRef<Path>,
        sessions_root: impl AsRef<Path>,
        label: &str,
    ) -> Result<Self, String> {
        let project_root = project_root.as_ref().to_path_buf();
        let now = unix_ms();
        let id = format!("{now}-{}-{}", std::process::id(), sanitize(label));
        let directory = sessions_root.as_ref().join(&id);
        fs::create_dir_all(directory.join("captures")).map_err(|e| e.to_string())?;
        fs::create_dir_all(directory.join("logs")).map_err(|e| e.to_string())?;
        fs::create_dir_all(directory.join("artifacts")).map_err(|e| e.to_string())?;
        let session = Self {
            schema_version: 1,
            id,
            project_root,
            directory,
            created_unix_ms: now,
            captures: Vec::new(),
            events: Vec::new(),
        };
        session.save()?;
        Ok(session)
    }

    pub fn log(
        &mut self,
        kind: impl Into<String>,
        message: impl Into<String>,
        data: serde_json::Value,
    ) -> Result<(), String> {
        self.events.push(SessionEvent {
            created_unix_ms: unix_ms(),
            kind: kind.into(),
            message: message.into(),
            data,
        });
        self.save()
    }

    pub fn add_capture(&mut self, capture: CaptureEvidence) -> Result<(), String> {
        self.captures.push(capture);
        self.save()
    }

    pub fn save(&self) -> Result<(), String> {
        let bytes = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        fs::write(self.directory.join("session.json"), bytes).map_err(|e| e.to_string())
    }
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}
fn sanitize(value: &str) -> String {
    let s: String = value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '-' | '_') {
                c
            } else {
                '-'
            }
        })
        .collect();
    if s.is_empty() {
        "session".into()
    } else {
        s
    }
}
