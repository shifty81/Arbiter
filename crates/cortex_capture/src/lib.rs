//! Project-agnostic Windows development capture helpers.

use cortex_protocol::ImageInput;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CaptureResult {
    pub path: PathBuf,
    pub process_id: u32,
    pub bytes: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WindowInspection {
    pub schema_version: u32,
    pub pid: u32,
    pub process_name: String,
    pub title: String,
    pub has_window: bool,
    pub visible: bool,
    pub responsive: bool,
    pub bounds: Option<WindowBounds>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WindowBounds {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

pub struct CaptureService {
    project_root: PathBuf,
}

impl CaptureService {
    pub fn new(project_root: impl Into<PathBuf>) -> Self {
        Self {
            project_root: project_root.into(),
        }
    }

    pub fn inspect_process_window(&self, process_id: u32) -> Result<WindowInspection, String> {
        let helper = materialize_helper(
            "Inspect-CortexWindow.ps1",
            include_str!("../../../scripts/Inspect-CortexWindow.ps1"),
        )?;
        let output = Command::new("powershell.exe")
            .arg("-NoProfile")
            .arg("-ExecutionPolicy")
            .arg("Bypass")
            .arg("-File")
            .arg(&helper)
            .arg("-ProcessId")
            .arg(process_id.to_string())
            .output()
            .map_err(|error| format!("failed to start window inspection helper: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "window inspection helper failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        let text = String::from_utf8_lossy(&output.stdout);
        let json_line = text
            .lines()
            .rev()
            .find(|line| line.trim_start().starts_with('{'))
            .ok_or_else(|| "window inspection helper returned no JSON result".to_string())?;
        serde_json::from_str(json_line)
            .map_err(|error| format!("invalid window inspection JSON: {error}"))
    }

    pub fn capture_process_window(
        &self,
        process_id: u32,
        relative_output: &Path,
    ) -> Result<CaptureResult, String> {
        if relative_output.is_absolute()
            || relative_output
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return Err("unsafe capture output path".into());
        }
        let output = self.project_root.join(relative_output);
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let helper = materialize_helper(
            "Capture-CortexWindow.ps1",
            include_str!("../../../scripts/Capture-CortexWindow.ps1"),
        )?;
        let status = Command::new("powershell.exe")
            .arg("-NoProfile")
            .arg("-ExecutionPolicy")
            .arg("Bypass")
            .arg("-File")
            .arg(&helper)
            .arg("-ProcessId")
            .arg(process_id.to_string())
            .arg("-OutputPath")
            .arg(&output)
            .status()
            .map_err(|e| format!("failed to start capture helper: {e}"))?;
        if !status.success() {
            return Err(format!(
                "capture helper failed with status {:?}",
                status.code()
            ));
        }
        let bytes = fs::metadata(&output).map_err(|e| e.to_string())?.len();
        Ok(CaptureResult {
            path: output,
            process_id,
            bytes,
        })
    }

    pub fn load_png_input(&self, path: &Path) -> Result<ImageInput, String> {
        self.load_image_input(path)
    }

    pub fn load_image_input(&self, path: &Path) -> Result<ImageInput, String> {
        let bytes = fs::read(path).map_err(|e| e.to_string())?;
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let mime_type = match extension.as_str() {
            "png" => "image/png",
            "jpg" | "jpeg" => "image/jpeg",
            "webp" => "image/webp",
            _ => {
                return Err(format!(
                    "unsupported Cortex vision image type: .{extension}"
                ))
            }
        };
        Ok(ImageInput {
            mime_type: mime_type.into(),
            data_base64: encode_base64(&bytes),
        })
    }
}

fn materialize_helper(name: &str, source: &str) -> Result<PathBuf, String> {
    let root = std::env::temp_dir().join("Open2D-Cortex").join("helpers");
    fs::create_dir_all(&root).map_err(|error| {
        format!(
            "failed to create Cortex helper directory {}: {error}",
            root.display()
        )
    })?;
    let path = root.join(name);
    let current = fs::read_to_string(&path).ok();
    if current.as_deref() != Some(source) {
        fs::write(&path, source).map_err(|error| {
            format!(
                "failed to materialize Cortex helper {}: {error}",
                path.display()
            )
        })?;
    }
    Ok(path)
}

pub fn encode_base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    let mut i = 0;
    while i < bytes.len() {
        let a = bytes[i] as u32;
        let b = bytes.get(i + 1).copied().unwrap_or(0) as u32;
        let c = bytes.get(i + 2).copied().unwrap_or(0) as u32;
        let triple = (a << 16) | (b << 8) | c;
        out.push(TABLE[((triple >> 18) & 63) as usize] as char);
        out.push(TABLE[((triple >> 12) & 63) as usize] as char);
        if i + 1 < bytes.len() {
            out.push(TABLE[((triple >> 6) & 63) as usize] as char);
        } else {
            out.push('=');
        }
        if i + 2 < bytes.len() {
            out.push(TABLE[(triple & 63) as usize] as char);
        } else {
            out.push('=');
        }
        i += 3;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn base64_smoke() {
        assert_eq!(encode_base64(b"Cortex"), "Q29ydGV4");
    }
}
