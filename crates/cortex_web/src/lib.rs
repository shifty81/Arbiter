//! Permission-gated Cortex web search/fetch tool extension.
//!
//! Search uses a configured SearXNG JSON endpoint. Direct fetch uses the OS curl
//! binary and is deliberately separate from Cortex's loopback-only provider HTTP client.

use cortex_protocol::{ToolCall, ToolDefinition};
use cortex_tools::ToolExtension;
use serde_json::{json, Value};
use std::process::Command;

const DEFAULT_MAX_FETCH_BYTES: usize = 1024 * 1024;

pub struct WebToolExtension {
    search_url: Option<String>,
}

impl WebToolExtension {
    pub fn from_env() -> Self {
        Self {
            search_url: std::env::var("CORTEX_WEB_SEARCH_URL")
                .ok()
                .map(|value| value.trim().trim_end_matches('/').to_string())
                .filter(|value| !value.is_empty()),
        }
    }

    fn search(&self, arguments: &Value) -> Result<Value, String> {
        let query = arguments
            .get("query")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| "web.search requires query".to_string())?;
        let endpoint = self.search_url.as_ref().ok_or_else(|| {
            "Cortex web search is enabled but no SearXNG endpoint is configured. Set CORTEX_WEB_SEARCH_URL or configure Web Search in Cortex Settings.".to_string()
        })?;
        validate_configured_search_endpoint(endpoint)?;
        let limit = arguments
            .get("limit")
            .and_then(Value::as_u64)
            .unwrap_or(8)
            .clamp(1, 20) as usize;
        let time_range = arguments
            .get("time_range")
            .and_then(Value::as_str)
            .filter(|value| matches!(*value, "day" | "week" | "month" | "year"));

        let mut url = format!(
            "{}/search?q={}&format=json&safesearch=1",
            endpoint,
            percent_encode(query)
        );
        if let Some(time_range) = time_range {
            url.push_str("&time_range=");
            url.push_str(time_range);
        }

        let bytes = curl_get(&url, 20, 4 * 1024 * 1024)?;
        let value: Value = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid SearXNG JSON: {error}"))?;
        let results = value
            .get("results")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .take(limit)
            .map(|item| {
                json!({
                    "title": item.get("title").and_then(Value::as_str).unwrap_or_default(),
                    "url": item.get("url").and_then(Value::as_str).unwrap_or_default(),
                    "snippet": item.get("content").and_then(Value::as_str).unwrap_or_default(),
                    "engine": item.get("engine").and_then(Value::as_str),
                    "published": item.get("publishedDate").or_else(|| item.get("published_date"))
                })
            })
            .collect::<Vec<_>>();
        Ok(json!({
            "provider": "searxng",
            "query": query,
            "count": results.len(),
            "results": results
        }))
    }

    fn fetch(&self, arguments: &Value) -> Result<Value, String> {
        let url = arguments
            .get("url")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| "web.fetch requires url".to_string())?;
        validate_external_http_url(url)?;
        let max_bytes = arguments
            .get("max_bytes")
            .and_then(Value::as_u64)
            .unwrap_or(DEFAULT_MAX_FETCH_BYTES as u64)
            .clamp(4 * 1024, 4 * 1024 * 1024) as usize;
        let bytes = curl_get(url, 25, max_bytes)?;
        let text = String::from_utf8_lossy(&bytes).to_string();
        Ok(json!({
            "url": url,
            "bytes": bytes.len(),
            "content": text
        }))
    }
}

impl ToolExtension for WebToolExtension {
    fn id(&self) -> &str {
        "cortex.web"
    }

    fn status(&self) -> Value {
        json!({
            "enabled": true,
            "search_provider": "searxng",
            "search_url": self.search_url,
            "fetch": true
        })
    }

    fn definitions(&self) -> Vec<ToolDefinition> {
        vec![
            ToolDefinition {
                name: "web.search".into(),
                description: "Search the public web through the configured Cortex SearXNG search provider.".into(),
                mutating: false,
                parameters: json!({
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]}
                    },
                    "required": ["query"]
                }),
            },
            ToolDefinition {
                name: "web.fetch".into(),
                description: "Fetch a public HTTP/HTTPS document for grounded Cortex research. Requires internet permission.".into(),
                mutating: false,
                parameters: json!({
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_bytes": {"type": "integer"}
                    },
                    "required": ["url"]
                }),
            },
        ]
    }

    fn execute(&mut self, call: &ToolCall) -> Option<Result<Value, String>> {
        match call.name.as_str() {
            "web.search" => Some(self.search(&call.arguments)),
            "web.fetch" => Some(self.fetch(&call.arguments)),
            _ => None,
        }
    }
}

fn curl_get(url: &str, timeout_seconds: u64, max_bytes: usize) -> Result<Vec<u8>, String> {
    let program = if cfg!(windows) { "curl.exe" } else { "curl" };
    let output = Command::new(program)
        .args([
            "--silent",
            "--show-error",
            "--fail",
            "--location",
            "--max-redirs",
            "5",
            "--connect-timeout",
            "5",
            "--max-time",
            &timeout_seconds.to_string(),
            "--proto",
            "=http,https",
            "--proto-redir",
            "=http,https",
            "--user-agent",
            "Open2D-Cortex/1",
            url,
        ])
        .output()
        .map_err(|error| format!("failed to start {program}: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "web request failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    if output.stdout.len() > max_bytes {
        return Err(format!(
            "web response exceeded Cortex limit: {} > {} bytes",
            output.stdout.len(),
            max_bytes
        ));
    }
    Ok(output.stdout)
}

fn validate_configured_search_endpoint(url: &str) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if !(lower.starts_with("https://") || lower.starts_with("http://")) {
        return Err("Cortex web search endpoint must use HTTP/HTTPS".into());
    }
    let host = lower
        .split_once("://")
        .map(|(_, rest)| rest)
        .unwrap_or_default()
        .split('/')
        .next()
        .unwrap_or_default();
    if host.is_empty() || host.starts_with('@') {
        return Err("Cortex web search endpoint has no valid host".into());
    }
    Ok(())
}

fn validate_external_http_url(url: &str) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if !(lower.starts_with("https://") || lower.starts_with("http://")) {
        return Err("Cortex web tools only allow HTTP/HTTPS URLs".into());
    }
    let host = lower
        .split_once("://")
        .map(|(_, rest)| rest)
        .unwrap_or_default()
        .split('/')
        .next()
        .unwrap_or_default()
        .split('@')
        .next_back()
        .unwrap_or_default()
        .split(':')
        .next()
        .unwrap_or_default();
    if host.is_empty()
        || host == "localhost"
        || host == "::1"
        || host.starts_with("127.")
        || host.starts_with("10.")
        || host.starts_with("192.168.")
        || host.ends_with(".local")
        || is_private_172(host)
    {
        return Err("Cortex web tools reject loopback/private-network destinations".into());
    }
    Ok(())
}

fn is_private_172(host: &str) -> bool {
    let mut parts = host.split('.');
    if parts.next() != Some("172") {
        return false;
    }
    parts
        .next()
        .and_then(|value| value.parse::<u8>().ok())
        .is_some_and(|octet| (16..=31).contains(&octet))
}

fn percent_encode(value: &str) -> String {
    let mut output = String::new();
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
            output.push(byte as char);
        } else {
            output.push_str(&format!("%{byte:02X}"));
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_private_web_targets() {
        assert!(validate_external_http_url("http://127.0.0.1:8080").is_err());
        assert!(validate_external_http_url("http://192.168.1.20").is_err());
        assert!(validate_external_http_url("https://example.com").is_ok());
    }

    #[test]
    fn configured_searxng_may_be_loopback() {
        assert!(validate_configured_search_endpoint("http://127.0.0.1:8080").is_ok());
        assert!(validate_configured_search_endpoint("https://search.example.com").is_ok());
    }

    #[test]
    fn search_query_encoding_is_stable() {
        assert_eq!(percent_encode("rust gui"), "rust%20gui");
    }
}
