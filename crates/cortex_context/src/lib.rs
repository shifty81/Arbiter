//! Canonical project context/incremental-file-index authority.

use cortex_workspace::{Workspace, WorkspaceError};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceInventory {
    pub schema_version: u32,
    pub root: PathBuf,
    pub name: String,
    pub scanned_unix_ms: u128,
    pub file_count: usize,
    pub total_bytes: u64,
    pub textual_files: usize,
    pub extension_counts: BTreeMap<String, usize>,
    pub manifests: Vec<PathBuf>,
    pub top_level_entries: Vec<PathBuf>,
    pub truncated: bool,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CodeIntelligenceSource {
    SyntaxTree,
    LanguageServer,
    Compiler,
    TextIndex,
    SemanticMemory,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CodeSymbolRecord {
    pub path: PathBuf,
    pub name: String,
    pub kind: String,
    pub line: u32,
    pub column: u32,
    pub source: CodeIntelligenceSource,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CodeIntelligenceManifest {
    pub schema_version: u32,
    pub symbols: Vec<CodeSymbolRecord>,
    pub language_servers: Vec<String>,
    pub syntax_languages: Vec<String>,
    pub generated_unix_ms: u128,
}

impl CodeIntelligenceManifest {
    pub fn save(&self, state_root: &Path) -> Result<(), String> {
        let path = state_root.join("context").join("code_intelligence.json");
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::write(
            path,
            serde_json::to_vec_pretty(self).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContextFileRecord {
    pub path: PathBuf,
    pub size: u64,
    pub modified_unix_ms: u128,
    pub textual: bool,
    pub language: Option<String>,
    pub content_hash: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContextIndex {
    pub schema_version: u32,
    pub root: PathBuf,
    pub scanned_unix_ms: u128,
    pub max_files: usize,
    pub max_hash_bytes: usize,
    pub total_bytes: u64,
    pub language_counts: BTreeMap<String, usize>,
    pub manifests: Vec<PathBuf>,
    pub files: Vec<ContextFileRecord>,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContextDelta {
    pub previous_index_present: bool,
    pub new_files: Vec<PathBuf>,
    pub modified_files: Vec<PathBuf>,
    pub deleted_files: Vec<PathBuf>,
    pub unchanged_files: usize,
    #[serde(default)]
    pub hashed_files: usize,
    #[serde(default)]
    pub reused_hashes: usize,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct IndexScanStats {
    hashed_files: usize,
    reused_hashes: usize,
}

#[derive(Clone)]
pub struct ContextStore {
    workspace: Workspace,
}

impl ContextStore {
    pub fn new(workspace: Workspace) -> Self {
        Self { workspace }
    }

    pub fn workspace(&self) -> &Workspace {
        &self.workspace
    }

    pub fn root(&self) -> PathBuf {
        self.workspace.cortex_state_dir().join("context")
    }

    pub fn inventory_path(&self) -> PathBuf {
        self.root().join("workspace_inventory.json")
    }

    pub fn index_path(&self) -> PathBuf {
        self.root().join("file_index.json")
    }

    pub fn scan_inventory(&self, max_files: usize) -> Result<WorkspaceInventory, String> {
        let max_files = max_files.clamp(1, 250_000);
        let requested = max_files.saturating_add(1);
        let mut files = self.workspace.list_files("", requested).map_err(err)?;
        let truncated = files.len() > max_files;
        if truncated {
            files.truncate(max_files);
        }

        let mut total_bytes = 0_u64;
        let mut textual_files = 0_usize;
        let mut extension_counts = BTreeMap::<String, usize>::new();
        let mut manifests = Vec::<PathBuf>::new();
        for relative in &files {
            let absolute = self.workspace.resolve(relative).map_err(err)?;
            if let Ok(metadata) = fs::metadata(&absolute) {
                total_bytes = total_bytes.saturating_add(metadata.len());
            }
            if looks_textual(relative) {
                textual_files += 1;
            }
            let extension = relative
                .extension()
                .and_then(|value| value.to_str())
                .map(|value| value.to_ascii_lowercase())
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| "<none>".into());
            *extension_counts.entry(extension).or_default() += 1;
            if is_manifest(relative) {
                manifests.push(relative.clone());
            }
        }
        manifests.sort();

        let mut top_level_entries = fs::read_dir(self.workspace.root())
            .map_err(|error| error.to_string())?
            .filter_map(Result::ok)
            .filter_map(|entry| {
                let path = entry.path();
                let name = path.file_name()?.to_str()?;
                if path.is_dir() && is_ignored_dir(name) {
                    return None;
                }
                path.strip_prefix(self.workspace.root())
                    .ok()
                    .map(Path::to_path_buf)
            })
            .collect::<Vec<_>>();
        top_level_entries.sort();
        top_level_entries.truncate(256);

        Ok(WorkspaceInventory {
            schema_version: 2,
            root: self.workspace.root().to_path_buf(),
            name: self.workspace.profile().name.clone(),
            scanned_unix_ms: unix_ms(),
            file_count: files.len(),
            total_bytes,
            textual_files,
            extension_counts,
            manifests,
            top_level_entries,
            truncated,
        })
    }

    pub fn save_inventory(&self, inventory: &WorkspaceInventory) -> Result<PathBuf, String> {
        fs::create_dir_all(self.root()).map_err(|error| error.to_string())?;
        let path = self.inventory_path();
        fs::write(
            &path,
            serde_json::to_vec_pretty(inventory).map_err(|e| e.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        Ok(path)
    }

    pub fn load_inventory(&self) -> Result<Option<WorkspaceInventory>, String> {
        let path = self.inventory_path();
        if !path.is_file() {
            return Ok(None);
        }
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map(Some)
            .map_err(|e| e.to_string())
    }

    pub fn rebuild_inventory(&self, max_files: usize) -> Result<WorkspaceInventory, String> {
        let inventory = self.scan_inventory(max_files)?;
        self.save_inventory(&inventory)?;
        Ok(inventory)
    }

    pub fn scan_index(
        &self,
        max_files: usize,
        max_hash_bytes: usize,
    ) -> Result<ContextIndex, String> {
        self.scan_index_incremental(None, max_files, max_hash_bytes)
            .map(|(index, _)| index)
    }

    fn scan_index_incremental(
        &self,
        previous: Option<&ContextIndex>,
        max_files: usize,
        max_hash_bytes: usize,
    ) -> Result<(ContextIndex, IndexScanStats), String> {
        let max_files = max_files.clamp(1, 250_000);
        let max_hash_bytes = max_hash_bytes.clamp(4 * 1024, 8 * 1024 * 1024);
        let mut paths = self
            .workspace
            .list_files("", max_files.saturating_add(1))
            .map_err(err)?;
        let truncated = paths.len() > max_files;
        if truncated {
            paths.truncate(max_files);
        }

        let previous_files = previous
            .map(|index| {
                index
                    .files
                    .iter()
                    .map(|record| (record.path.clone(), record))
                    .collect::<BTreeMap<_, _>>()
            })
            .unwrap_or_default();

        let mut files = Vec::with_capacity(paths.len());
        let mut total_bytes = 0_u64;
        let mut language_counts = BTreeMap::new();
        let mut manifests = Vec::new();
        let mut stats = IndexScanStats::default();

        for relative in paths {
            let absolute = self.workspace.resolve(&relative).map_err(err)?;
            let metadata = match fs::metadata(&absolute) {
                Ok(value) => value,
                Err(_) => continue,
            };
            let size = metadata.len();
            let modified_unix_ms = modified_ms(&metadata);
            total_bytes = total_bytes.saturating_add(size);

            let language = language_for_path(&relative).map(str::to_string);
            if let Some(value) = language.as_ref() {
                *language_counts.entry(value.clone()).or_insert(0_usize) += 1;
            }
            if is_manifest(&relative) {
                manifests.push(relative.clone());
            }

            let content_hash = if size <= max_hash_bytes as u64 {
                let reusable = previous_files.get(&relative).and_then(|before| {
                    if before.size == size
                        && before.modified_unix_ms == modified_unix_ms
                        && before.content_hash.is_some()
                    {
                        before.content_hash.clone()
                    } else {
                        None
                    }
                });

                match reusable {
                    Some(hash) => {
                        stats.reused_hashes += 1;
                        Some(hash)
                    }
                    None => {
                        stats.hashed_files += 1;
                        Some(hash_file(&absolute)?)
                    }
                }
            } else {
                None
            };

            files.push(ContextFileRecord {
                path: relative,
                size,
                modified_unix_ms,
                textual: looks_textual(&absolute),
                language,
                content_hash,
            });
        }

        files.sort_by(|left, right| left.path.cmp(&right.path));
        manifests.sort();

        Ok((
            ContextIndex {
                schema_version: 1,
                root: self.workspace.root().to_path_buf(),
                scanned_unix_ms: unix_ms(),
                max_files,
                max_hash_bytes,
                total_bytes,
                language_counts,
                manifests,
                files,
                truncated,
            },
            stats,
        ))
    }

    pub fn load_index(&self) -> Result<Option<ContextIndex>, String> {
        let path = self.index_path();
        if !path.is_file() {
            return Ok(None);
        }
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map(Some)
            .map_err(|e| e.to_string())
    }

    pub fn rebuild_index(
        &self,
        max_files: usize,
        max_hash_bytes: usize,
    ) -> Result<(ContextIndex, ContextDelta), String> {
        let previous = self.load_index()?;
        let (current, stats) =
            self.scan_index_incremental(previous.as_ref(), max_files, max_hash_bytes)?;
        let mut delta = compare(previous.as_ref(), &current);
        delta.hashed_files = stats.hashed_files;
        delta.reused_hashes = stats.reused_hashes;

        fs::create_dir_all(self.root()).map_err(|error| error.to_string())?;
        fs::write(
            self.index_path(),
            serde_json::to_vec_pretty(&current).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;

        Ok((current, delta))
    }
}

fn compare(previous: Option<&ContextIndex>, current: &ContextIndex) -> ContextDelta {
    let mut delta = ContextDelta {
        previous_index_present: previous.is_some(),
        ..ContextDelta::default()
    };
    let old = previous
        .map(|index| {
            index
                .files
                .iter()
                .map(|r| (r.path.clone(), r))
                .collect::<BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let new = current
        .files
        .iter()
        .map(|r| (r.path.clone(), r))
        .collect::<BTreeMap<_, _>>();
    for (path, record) in &new {
        match old.get(path) {
            None => delta.new_files.push(path.clone()),
            Some(before) if changed(before, record) => delta.modified_files.push(path.clone()),
            Some(_) => delta.unchanged_files += 1,
        }
    }
    for path in old.keys() {
        if !new.contains_key(path) {
            delta.deleted_files.push(path.clone());
        }
    }
    delta
}

fn changed(a: &ContextFileRecord, b: &ContextFileRecord) -> bool {
    a.size != b.size || a.modified_unix_ms != b.modified_unix_ms || a.content_hash != b.content_hash
}

fn hash_file(path: &Path) -> Result<String, String> {
    let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
    let mut buffer = [0_u8; 32 * 1024];
    let mut hash = 0xcbf29ce484222325_u64;
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        for byte in &buffer[..count] {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x100000001b3);
        }
    }
    Ok(format!("{hash:016x}"))
}

fn modified_ms(metadata: &fs::Metadata) -> u128 {
    metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|value| value.as_millis())
        .unwrap_or_default()
}

fn is_manifest(path: &Path) -> bool {
    matches!(
        path.file_name()
            .and_then(|v| v.to_str())
            .unwrap_or_default(),
        "Cargo.toml"
            | "package.json"
            | "pyproject.toml"
            | "CMakeLists.txt"
            | "Makefile"
            | "go.mod"
            | "pom.xml"
            | "build.gradle"
            | "build.gradle.kts"
    )
}

fn looks_textual(path: &Path) -> bool {
    matches!(
        path.extension()
            .and_then(|v| v.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "rs" | "toml"
            | "json"
            | "md"
            | "txt"
            | "ron"
            | "yaml"
            | "yml"
            | "xml"
            | "html"
            | "css"
            | "scss"
            | "js"
            | "jsx"
            | "ts"
            | "tsx"
            | "py"
            | "c"
            | "cc"
            | "cpp"
            | "cxx"
            | "h"
            | "hpp"
            | "cs"
            | "java"
            | "kt"
            | "go"
            | "sh"
            | "cmd"
            | "bat"
            | "ps1"
    )
}

fn language_for_path(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()?.to_ascii_lowercase().as_str() {
        "rs" => Some("rust"),
        "toml" => Some("toml"),
        "json" => Some("json"),
        "md" => Some("markdown"),
        "ts" | "tsx" => Some("typescript"),
        "js" | "jsx" => Some("javascript"),
        "py" => Some("python"),
        "c" => Some("c"),
        "cc" | "cpp" | "cxx" => Some("cpp"),
        "h" | "hpp" => Some("cpp_header"),
        "cs" => Some("csharp"),
        "java" => Some("java"),
        "kt" => Some("kotlin"),
        "go" => Some("go"),
        "yaml" | "yml" => Some("yaml"),
        "ron" => Some("ron"),
        "ps1" => Some("powershell"),
        "cmd" | "bat" => Some("windows_batch"),
        "sh" => Some("shell"),
        _ => None,
    }
}

fn is_ignored_dir(name: &str) -> bool {
    matches!(
        name,
        ".git"
            | ".cortex"
            | ".open2d"
            | "target"
            | "node_modules"
            | "logs"
            | "build"
            | "builds"
            | "dist"
    )
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn err(error: WorkspaceError) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn index_delta_detects_changes() {
        let base = std::env::temp_dir().join(format!(
            "cortex-context-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        let root = base.join("workspace");
        let state_root = base.join("state");

        let _ = fs::remove_dir_all(&base);
        fs::create_dir_all(root.join("src")).unwrap();
        fs::create_dir_all(&state_root).unwrap();
        fs::write(root.join("Cargo.toml"), "[workspace]\n").unwrap();
        fs::write(root.join("src/lib.rs"), "pub fn a() {}\n").unwrap();

        // Tests must never depend on the user's durable Cortex workspace cache.
        // Give this temporary workspace an equally temporary, explicit state root.
        let workspace = Workspace::open_with_state_root(&root, &state_root).unwrap();
        let store = ContextStore::new(workspace);

        let (_, first) = store.rebuild_index(100, 1024 * 1024).unwrap();
        assert_eq!(first.new_files.len(), 2);
        assert!(first.hashed_files >= 2);

        let (_, unchanged) = store.rebuild_index(100, 1024 * 1024).unwrap();
        assert_eq!(unchanged.unchanged_files, 2);
        assert!(unchanged.reused_hashes >= 2);

        fs::write(root.join("src/lib.rs"), "pub fn changed_name() {}\n").unwrap();
        let (_, second) = store.rebuild_index(100, 1024 * 1024).unwrap();
        assert!(second
            .modified_files
            .iter()
            .any(|path| path == Path::new("src/lib.rs")));
        assert!(second.hashed_files >= 1);

        let _ = fs::remove_dir_all(base);
    }
}
