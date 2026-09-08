//! Standalone Cortex settings persisted per attached workspace.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct CortexSettings {
    pub schema_version: u32,
    pub service_port: u16,
    pub auto_start_service: bool,
    pub provider: String,
    pub native_model_host_port: u16,
    pub native_auto_bootstrap: bool,
    pub native_models_max: u8,
    pub lmstudio_auto_start: bool,
    pub lmstudio_url: String,
    pub comfyui_url: String,
    pub web_search_enabled: bool,
    pub web_search_url: String,
    pub web_fetch_enabled: bool,
    pub image_provider: String,
    pub native_image_auto_bootstrap: bool,
    pub native_image_backend: String,
    pub native_image_model: Option<String>,
    pub chat_model: Option<String>,
    pub tool_model: Option<String>,
    pub vision_model: Option<String>,
    pub embedding_model: Option<String>,
    pub theme: String,
    pub compact_tool_cards: bool,
}

impl Default for CortexSettings {
    fn default() -> Self {
        Self {
            schema_version: 1,
            service_port: 7337,
            auto_start_service: true,
            provider: "native".into(),
            native_model_host_port: 12400,
            native_auto_bootstrap: true,
            native_models_max: 2,
            lmstudio_auto_start: true,
            lmstudio_url: "http://127.0.0.1:1234/v1".into(),
            comfyui_url: "http://127.0.0.1:8188".into(),
            web_search_enabled: true,
            web_search_url: String::new(),
            web_fetch_enabled: true,
            image_provider: "native".into(),
            native_image_auto_bootstrap: true,
            native_image_backend: "stable-diffusion.cpp".into(),
            native_image_model: None,
            chat_model: None,
            tool_model: None,
            vision_model: None,
            embedding_model: None,
            theme: "dark".into(),
            compact_tool_cards: false,
        }
    }
}

impl CortexSettings {
    pub fn load_or_default(state_root: &Path) -> Result<Self, String> {
        let path = state_root.join("settings.json");
        if !path.is_file() {
            let settings = Self::default();
            settings.save(state_root)?;
            return Ok(settings);
        }
        serde_json::from_slice(&fs::read(&path).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())
    }

    pub fn save(&self, state_root: &Path) -> Result<(), String> {
        fs::create_dir_all(state_root).map_err(|error| error.to_string())?;
        fs::write(
            state_root.join("settings.json"),
            serde_json::to_vec_pretty(self).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }

    pub fn set(&mut self, key: &str, value: &str) -> Result<(), String> {
        match key {
            "service_port" => {
                self.service_port = value.parse::<u16>().map_err(|error| error.to_string())?;
            }
            "auto_start_service" => {
                self.auto_start_service = parse_bool(value)?;
            }
            "provider" => {
                let normalized = value.trim().to_ascii_lowercase();
                if !matches!(normalized.as_str(), "native" | "lmstudio") {
                    return Err("provider must be native or lmstudio".into());
                }
                self.provider = normalized;
            }
            "native_model_host_port" => {
                self.native_model_host_port =
                    value.parse::<u16>().map_err(|error| error.to_string())?;
            }
            "native_auto_bootstrap" => self.native_auto_bootstrap = parse_bool(value)?,
            "native_models_max" => {
                self.native_models_max = value
                    .parse::<u8>()
                    .map_err(|error| error.to_string())?
                    .clamp(1, 8);
            }
            "lmstudio_auto_start" => self.lmstudio_auto_start = parse_bool(value)?,
            "lmstudio_url" => self.lmstudio_url = value.to_string(),
            "comfyui_url" => self.comfyui_url = value.to_string(),
            "web_search_enabled" => self.web_search_enabled = parse_bool(value)?,
            "web_search_url" => self.web_search_url = value.trim().to_string(),
            "web_fetch_enabled" => self.web_fetch_enabled = parse_bool(value)?,
            "image_provider" => {
                let normalized = value.trim().to_ascii_lowercase();
                if !matches!(normalized.as_str(), "native" | "comfyui") {
                    return Err("image_provider must be native or comfyui".into());
                }
                self.image_provider = normalized;
            }
            "native_image_auto_bootstrap" => {
                self.native_image_auto_bootstrap = parse_bool(value)?;
            }
            "native_image_backend" => {
                let normalized = value.trim().to_ascii_lowercase();
                if normalized != "stable-diffusion.cpp" {
                    return Err(
                        "native_image_backend currently supports stable-diffusion.cpp".into(),
                    );
                }
                self.native_image_backend = normalized;
            }
            "native_image_model" => self.native_image_model = optional(value),
            "chat_model" => self.chat_model = optional(value),
            "tool_model" => self.tool_model = optional(value),
            "vision_model" => self.vision_model = optional(value),
            "embedding_model" => self.embedding_model = optional(value),
            "theme" => {
                if !matches!(value, "dark" | "light" | "system") {
                    return Err("theme must be dark, light, or system".into());
                }
                self.theme = value.to_string();
            }
            "compact_tool_cards" => self.compact_tool_cards = parse_bool(value)?,
            _ => return Err(format!("unknown Cortex setting: {key}")),
        }
        Ok(())
    }
}

fn optional(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("automatic") {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn parse_bool(value: &str) -> Result<bool, String> {
    match value.to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(format!("invalid boolean value: {value}")),
    }
}
