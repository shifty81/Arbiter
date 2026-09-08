//! Unified discovery of Cortex screenshots, generated images and evidence artifacts.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ArtifactKind {
    Image,
    Screenshot,
    Evidence,
    Log,
    Other,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ArtifactEntry {
    pub path: PathBuf,
    pub kind: ArtifactKind,
    pub bytes: u64,
    #[serde(default)]
    pub workspace_id: Option<String>,
    #[serde(default)]
    pub job_id: Option<String>,
    #[serde(default)]
    pub producer: Option<String>,
}

pub fn discover(
    workspace_root: &Path,
    state_root: &Path,
    sessions_root: &Path,
    limit: usize,
) -> Result<Vec<ArtifactEntry>, String> {
    let mut result = Vec::new();
    let roots = [
        state_root.join("image_artifacts"),
        sessions_root.to_path_buf(),
        state_root.join("activity"),
        state_root.join("tasks"),
    ];
    for root in roots {
        collect(workspace_root, &root, limit, &mut result)?;
        if result.len() >= limit {
            break;
        }
    }
    result.sort_by(|left, right| left.path.cmp(&right.path));
    result.truncate(limit);
    Ok(result)
}

fn collect(
    workspace_root: &Path,
    root: &Path,
    limit: usize,
    result: &mut Vec<ArtifactEntry>,
) -> Result<(), String> {
    if result.len() >= limit || !root.exists() {
        return Ok(());
    }
    if root.is_file() {
        push(workspace_root, root, result)?;
        return Ok(());
    }
    for entry in fs::read_dir(root).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        if path.is_dir() {
            collect(workspace_root, &path, limit, result)?;
        } else if path.is_file() {
            push(workspace_root, &path, result)?;
        }
        if result.len() >= limit {
            break;
        }
    }
    Ok(())
}

fn push(workspace_root: &Path, path: &Path, result: &mut Vec<ArtifactEntry>) -> Result<(), String> {
    let metadata = fs::metadata(path).map_err(|error| error.to_string())?;
    let relative = path
        .strip_prefix(workspace_root)
        .unwrap_or(path)
        .to_path_buf();
    result.push(ArtifactEntry {
        kind: classify(path),
        path: relative,
        bytes: metadata.len(),
        workspace_id: None,
        job_id: None,
        producer: Some("cortex_artifacts.discover".into()),
    });
    Ok(())
}

fn classify(path: &Path) -> ArtifactKind {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(extension.as_str(), "png" | "jpg" | "jpeg" | "webp") {
        if path
            .to_string_lossy()
            .to_ascii_lowercase()
            .contains("capture")
        {
            ArtifactKind::Screenshot
        } else {
            ArtifactKind::Image
        }
    } else if path
        .file_name()
        .and_then(|value| value.to_str())
        .map(|value| value.contains("evidence"))
        .unwrap_or(false)
    {
        ArtifactKind::Evidence
    } else if matches!(extension.as_str(), "log" | "jsonl") {
        ArtifactKind::Log
    } else {
        ArtifactKind::Other
    }
}
