//! Cortex image-artifact catalog and promotion lifecycle.

use cortex_protocol::{ImageArtifact, ImageArtifactStatus};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ImageArtifactCatalog {
    pub schema_version: u32,
    pub artifacts: Vec<ImageArtifact>,
}

impl ImageArtifactCatalog {
    pub fn load(path: &Path) -> Result<Self, String> {
        if !path.exists() {
            return Ok(Self {
                schema_version: 1,
                artifacts: Vec::new(),
            });
        }
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }

    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::write(
            path,
            serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }

    pub fn register(
        &mut self,
        mut artifact: ImageArtifact,
        metadata_root: &Path,
    ) -> Result<ImageArtifact, String> {
        fs::create_dir_all(metadata_root).map_err(|e| e.to_string())?;
        let metadata_path = metadata_root.join(format!("{}.json", safe_name(&artifact.id)));
        artifact.metadata_path = Some(metadata_path.clone());
        fs::write(
            &metadata_path,
            serde_json::to_vec_pretty(&artifact).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        self.artifacts.retain(|existing| existing.id != artifact.id);
        self.artifacts.push(artifact.clone());
        Ok(artifact)
    }

    pub fn set_status(&mut self, id: &str, status: ImageArtifactStatus) -> Result<(), String> {
        let artifact = self
            .artifacts
            .iter_mut()
            .find(|artifact| artifact.id == id)
            .ok_or_else(|| format!("image artifact not found: {id}"))?;
        artifact.status = status;
        if let Some(path) = &artifact.metadata_path {
            fs::write(
                path,
                serde_json::to_vec_pretty(&*artifact).map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    pub fn promote(
        &mut self,
        id: &str,
        content_root: &Path,
        relative_destination: &Path,
    ) -> Result<PathBuf, String> {
        if relative_destination.is_absolute()
            || relative_destination
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err("unsafe generated-image promotion path".into());
        }
        let artifact = self
            .artifacts
            .iter_mut()
            .find(|artifact| artifact.id == id)
            .ok_or_else(|| format!("image artifact not found: {id}"))?;
        let destination = content_root.join(relative_destination);
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::copy(&artifact.path, &destination).map_err(|e| e.to_string())?;
        artifact.status = ImageArtifactStatus::Promoted;
        if let Some(path) = &artifact.metadata_path {
            fs::write(
                path,
                serde_json::to_vec_pretty(&*artifact).map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
        }
        Ok(destination)
    }
}

pub fn catalog_path(project_root: &Path) -> PathBuf {
    catalog_path_from_state(&project_root.join(".open2d").join("cortex"))
}

pub fn metadata_root(project_root: &Path) -> PathBuf {
    metadata_root_from_state(&project_root.join(".open2d").join("cortex"))
}

pub fn generated_output_root(project_root: &Path) -> PathBuf {
    generated_output_root_from_state(&project_root.join(".open2d").join("cortex"))
}

pub fn catalog_path_from_state(state_root: &Path) -> PathBuf {
    state_root.join("image_artifacts").join("catalog.json")
}

pub fn metadata_root_from_state(state_root: &Path) -> PathBuf {
    state_root.join("image_artifacts").join("metadata")
}

pub fn generated_output_root_from_state(state_root: &Path) -> PathBuf {
    state_root.join("image_artifacts").join("generated")
}

fn safe_name(value: &str) -> String {
    value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.') {
                c
            } else {
                '_'
            }
        })
        .collect()
}
