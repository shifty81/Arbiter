//! Cortex-owned GGUF model-host lifecycle built around a pinned llama.cpp router.
//!
//! The model host is deliberately process-isolated from the desktop. The desktop
//! owns the host lifetime; the host owns the llama-server child lifetime.

use cortex_execution::spine::provider_lease_active;
use cortex_http::HttpClient;
use cortex_service::{process_is_alive, terminate_owned_process};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const LLAMA_CPP_RELEASE: &str = "b10516";
pub const LLAMA_CPP_WINDOWS_VULKAN_ASSET: &str = "llama-b10516-bin-win-vulkan-x64.zip";
pub const LLAMA_CPP_WINDOWS_VULKAN_SHA256: &str =
    "530f57d2a874ce017827c1e5a926812b9d5de4667248575d1372b1c0acf94d83";
pub const LLAMA_CPP_WINDOWS_VULKAN_URL: &str =
    "https://github.com/ggml-org/llama.cpp/releases/download/b10516/llama-b10516-bin-win-vulkan-x64.zip";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ModelRoleHint {
    Chat,
    Coding,
    Reasoning,
    Vision,
    Embedding,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct NativeModelRecord {
    pub id: String,
    pub path: PathBuf,
    pub display_name: String,
    pub bytes: u64,
    pub role_hint: ModelRoleHint,
    pub mmproj: Option<PathBuf>,
    pub source: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NativeModelCatalog {
    pub schema_version: u32,
    pub models: Vec<NativeModelRecord>,
    pub roots: Vec<PathBuf>,
    pub generated_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ModelHostStatus {
    Starting,
    Ready,
    Failed,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelHostState {
    pub schema_version: u32,
    pub pid: u32,
    pub parent_pid: u32,
    pub llama_pid: u32,
    pub port: u16,
    pub endpoint: String,
    pub executable: PathBuf,
    pub llama_executable: PathBuf,
    pub models_preset: PathBuf,
    pub model_count: usize,
    pub started_unix_ms: u128,
    pub status: ModelHostStatus,
    pub error: Option<String>,
}

#[derive(Clone, Debug)]
pub struct ModelHostRegistry {
    state_path: PathBuf,
    log_path: PathBuf,
}

impl ModelHostRegistry {
    pub fn new(library_root: impl AsRef<Path>) -> Result<Self, String> {
        let internal = library_root.as_ref().join(".cortex").join("model-host");
        fs::create_dir_all(&internal).map_err(|error| error.to_string())?;
        Ok(Self {
            state_path: internal.join("state.json"),
            log_path: internal.join("launcher.log"),
        })
    }

    pub fn state_path(&self) -> &Path {
        &self.state_path
    }

    pub fn read(&self) -> Result<Option<ModelHostState>, String> {
        if !self.state_path.is_file() {
            return Ok(None);
        }
        serde_json::from_slice(&fs::read(&self.state_path).map_err(|error| error.to_string())?)
            .map(Some)
            .map_err(|error| error.to_string())
    }

    pub fn start(
        &self,
        host_executable: impl AsRef<Path>,
        library_root: impl AsRef<Path>,
        parent_pid: u32,
        port: u16,
        auto_bootstrap: bool,
        models_max: u8,
    ) -> Result<ModelHostState, String> {
        if let Some(state) = self.read()? {
            let reusable = state.status == ModelHostStatus::Ready
                && state.parent_pid == parent_pid
                && state.port == port
                && process_is_alive(state.pid)
                && process_is_alive(state.llama_pid)
                && HttpClient::with_timeout(Duration::from_secs(2))
                    .get(&format!("http://127.0.0.1:{}/health", state.port))
                    .and_then(|response| response.ensure_success())
                    .is_ok();
            if reusable {
                return Ok(state);
            }
            // Never replace stale state by deleting bookkeeping alone: terminate the
            // verified owned supervisor/inference processes first so a previous Desktop
            // session cannot leave a hidden native-model daemon behind.
            let _ = self.stop_force();
        }

        let executable = fs::canonicalize(host_executable.as_ref()).map_err(|error| {
            format!(
                "failed to resolve Cortex model-host executable {}: {error}",
                host_executable.as_ref().display()
            )
        })?;
        if let Some(parent) = self.log_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let stdout = File::create(&self.log_path).map_err(|error| error.to_string())?;
        let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
        let mut command = Command::new(&executable);
        command
            .arg("run")
            .arg("--library-root")
            .arg(library_root.as_ref())
            .arg("--parent-pid")
            .arg(parent_pid.to_string())
            .arg("--port")
            .arg(port.to_string())
            .arg("--models-max")
            .arg(models_max.clamp(1, 8).to_string())
            .arg(if auto_bootstrap {
                "--auto-bootstrap"
            } else {
                "--no-auto-bootstrap"
            })
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
        configure_background(&mut command);
        let mut child = command
            .spawn()
            .map_err(|error| format!("failed to start Cortex native model host: {error}"))?;
        let pid = child.id();
        let deadline = Instant::now() + Duration::from_secs(180);
        while Instant::now() < deadline {
            if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
                return Err(format!(
                    "Cortex model host PID {pid} exited during startup with {status}. Log: {}{}",
                    self.log_path.display(),
                    log_tail(&self.log_path)
                ));
            }
            if let Some(state) = self.read()? {
                match state.status {
                    ModelHostStatus::Ready => return Ok(state),
                    ModelHostStatus::Failed => {
                        return Err(state.error.unwrap_or_else(|| {
                            "Cortex native model host reported startup failure".into()
                        }))
                    }
                    ModelHostStatus::Starting => {}
                }
            }
            std::thread::sleep(Duration::from_millis(150));
        }
        let _ = child.kill();
        let _ = child.wait();
        Err(format!(
            "Cortex native model host did not become ready within 180 seconds. Log: {}{}",
            self.log_path.display(),
            log_tail(&self.log_path)
        ))
    }

    // O2D-R051N9M10_EXECUTION_SPINE
    pub fn stop(&self) -> Result<bool, String> {
        let library_root = self
            .state_path
            .parent()
            .and_then(Path::parent)
            .and_then(Path::parent);
        if library_root.map(provider_lease_active).unwrap_or(false) {
            return Ok(false);
        }
        self.stop_force()
    }

    pub fn stop_force(&self) -> Result<bool, String> {
        self.stop_m10_impl()
    }

    fn stop_m10_impl(&self) -> Result<bool, String> {
        let Some(state) = self.read()? else {
            return Ok(false);
        };
        // Stop the inference child first so a clean Desktop shutdown cannot orphan
        // llama-server even though the supervisor itself is process-isolated.
        let llama_stopped = terminate_owned_process(state.llama_pid, &state.llama_executable)?;
        let stopped = terminate_owned_process(state.pid, &state.executable)?;
        let deadline = Instant::now() + Duration::from_secs(6);
        while Instant::now() < deadline
            && (process_is_alive(state.pid) || process_is_alive(state.llama_pid))
        {
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = fs::remove_file(&self.state_path);
        Ok(stopped || llama_stopped)
    }
}

pub fn run_supervisor(
    library_root: impl AsRef<Path>,
    parent_pid: u32,
    port: u16,
    auto_bootstrap: bool,
    models_max: u8,
) -> Result<(), String> {
    if parent_pid == 0 || !process_is_alive(parent_pid) {
        return Err("Cortex model host requires a live Cortex Desktop owner PID".into());
    }
    let library_root = fs::canonicalize(library_root.as_ref()).map_err(|error| {
        format!(
            "failed to resolve Cortex library root {}: {error}",
            library_root.as_ref().display()
        )
    })?;
    let registry = ModelHostRegistry::new(&library_root)?;
    let models_root = library_root.join("Models");
    fs::create_dir_all(&models_root).map_err(|error| error.to_string())?;
    let catalog = discover_models(&models_root)?;
    if catalog.models.is_empty() {
        return Err(format!(
            "Cortex Native Models found no GGUF files. Add models under {} or keep existing GGUFs in the standard LM Studio model folder for automatic discovery.",
            models_root.display()
        ));
    }
    let startup_model = model_for_role(&catalog, ModelRoleHint::Chat)
        .map(|model| model.id.clone())
        .ok_or_else(|| "Cortex Native Models found no usable text model".to_string())?;
    let internal = library_root.join(".cortex").join("model-host");
    fs::create_dir_all(&internal).map_err(|error| error.to_string())?;
    let preset = internal.join("models.generated.ini");
    write_router_preset(&catalog, &preset)?;
    fs::write(
        internal.join("catalog.json"),
        serde_json::to_vec_pretty(&catalog).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;

    let runtime_root = library_root
        .join(".cortex")
        .join("runtime")
        .join("llama.cpp")
        .join(LLAMA_CPP_RELEASE);
    let llama = resolve_or_bootstrap_runtime(&runtime_root, auto_bootstrap)?;
    let log = File::create(internal.join("llama-server.log")).map_err(|error| error.to_string())?;
    let err = log.try_clone().map_err(|error| error.to_string())?;
    let mut command = Command::new(&llama);
    command
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("--models-preset")
        .arg(&preset)
        .arg("--models-max")
        .arg(models_max.clamp(1, 8).to_string())
        .arg("--jinja")
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(err));
    configure_background(&mut command);
    let mut llama_child = command
        .spawn()
        .map_err(|error| format!("failed to start bundled llama-server: {error}"))?;

    let executable = fs::canonicalize(std::env::current_exe().map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    let mut state = ModelHostState {
        schema_version: 1,
        pid: std::process::id(),
        parent_pid,
        llama_pid: llama_child.id(),
        port,
        endpoint: format!("http://127.0.0.1:{port}/v1"),
        executable,
        llama_executable: llama.clone(),
        models_preset: preset,
        model_count: catalog.models.len(),
        started_unix_ms: unix_ms(),
        status: ModelHostStatus::Starting,
        error: None,
    };
    write_state(registry.state_path(), &state)?;

    let http = HttpClient::with_timeout(Duration::from_secs(2));
    let deadline = Instant::now() + Duration::from_secs(120);
    let ready = loop {
        if let Some(status) = llama_child.try_wait().map_err(|error| error.to_string())? {
            break Err(format!("llama-server exited during startup with {status}"));
        }
        if http
            .get(&format!("http://127.0.0.1:{port}/health"))
            .and_then(|response| response.ensure_success())
            .is_ok()
        {
            break Ok(());
        }
        if Instant::now() >= deadline {
            break Err(
                "llama-server health endpoint did not become ready within 120 seconds".into(),
            );
        }
        if !process_is_alive(parent_pid) {
            break Err("Cortex Desktop owner exited during model-host startup".into());
        }
        std::thread::sleep(Duration::from_millis(200));
    };

    if let Err(error) = ready {
        state.status = ModelHostStatus::Failed;
        state.error = Some(error.clone());
        let _ = write_state(registry.state_path(), &state);
        let _ = llama_child.kill();
        let _ = llama_child.wait();
        return Err(error);
    }

    // Router mode exposes /health as soon as the router itself is ready, but the
    // first model can still be loading in a child process. Do not publish the
    // Cortex model host as Ready until the startup text model is truly loaded.
    let model_deadline = Instant::now() + Duration::from_secs(300);
    let model_ready = loop {
        if let Some(status) = llama_child.try_wait().map_err(|error| error.to_string())? {
            break Err(format!(
                "llama-server exited while loading startup model {startup_model} with {status}{}",
                log_tail(&internal.join("llama-server.log"))
            ));
        }
        if !process_is_alive(parent_pid) {
            break Err("Cortex Desktop owner exited while the startup model was loading".into());
        }

        if let Ok(response) = http.get(&format!("http://127.0.0.1:{port}/models")) {
            if let Ok(value) = response
                .ensure_success()
                .and_then(|response| response.json())
            {
                if let Some(model) =
                    value
                        .get("data")
                        .and_then(Value::as_array)
                        .and_then(|models| {
                            models.iter().find(|model| {
                                model.get("id").and_then(Value::as_str)
                                    == Some(startup_model.as_str())
                            })
                        })
                {
                    let status = model
                        .pointer("/status/value")
                        .and_then(Value::as_str)
                        .unwrap_or("unknown");
                    let failed = model
                        .pointer("/status/failed")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    if status == "loaded" || status == "sleeping" {
                        break Ok(());
                    }
                    if failed {
                        let exit_code = model
                            .pointer("/status/exit_code")
                            .and_then(Value::as_i64)
                            .unwrap_or(-1);
                        break Err(format!(
                            "startup model {startup_model} failed to load (exit code {exit_code}){}",
                            log_tail(&internal.join("llama-server.log"))
                        ));
                    }
                }
            }
        }

        if Instant::now() >= model_deadline {
            break Err(format!(
                "startup model {startup_model} did not become loaded within 300 seconds{}",
                log_tail(&internal.join("llama-server.log"))
            ));
        }
        std::thread::sleep(Duration::from_millis(250));
    };

    if let Err(error) = model_ready {
        state.status = ModelHostStatus::Failed;
        state.error = Some(error.clone());
        let _ = write_state(registry.state_path(), &state);
        let _ = llama_child.kill();
        let _ = llama_child.wait();
        return Err(error);
    }

    state.status = ModelHostStatus::Ready;
    write_state(registry.state_path(), &state)?;

    while process_is_alive(parent_pid) {
        if let Some(status) = llama_child.try_wait().map_err(|error| error.to_string())? {
            let _ = fs::remove_file(registry.state_path());
            return Err(format!("llama-server exited unexpectedly with {status}"));
        }
        std::thread::sleep(Duration::from_millis(500));
    }

    let _ = llama_child.kill();
    let _ = llama_child.wait();
    let _ = fs::remove_file(registry.state_path());
    Ok(())
}

pub fn discover_models(primary_root: impl AsRef<Path>) -> Result<NativeModelCatalog, String> {
    discover_models_with_external_roots(primary_root.as_ref(), true)
}

#[cfg(test)]
fn discover_models_local(primary_root: impl AsRef<Path>) -> Result<NativeModelCatalog, String> {
    discover_models_with_external_roots(primary_root.as_ref(), false)
}

fn discover_models_with_external_roots(
    primary_root: &Path,
    include_external_roots: bool,
) -> Result<NativeModelCatalog, String> {
    let mut roots = Vec::<(PathBuf, String)>::new();
    push_root(&mut roots, primary_root.to_path_buf(), "cortex_library");

    if include_external_roots {
        if let Some(user) = std::env::var_os("USERPROFILE").map(PathBuf::from) {
            push_root(
                &mut roots,
                user.join(".lmstudio").join("models"),
                "lm_studio",
            );
            push_root(
                &mut roots,
                user.join(".cache").join("lm-studio").join("models"),
                "lm_studio_legacy",
            );
            let settings = user.join(".lmstudio").join("settings.json");
            if let Ok(value) =
                serde_json::from_slice::<Value>(&fs::read(settings).unwrap_or_default())
            {
                if let Some(path) = value.get("downloadsFolder").and_then(Value::as_str) {
                    push_root(&mut roots, PathBuf::from(path), "lm_studio_configured");
                }
            }
        }
        if let Some(extra) = std::env::var_os("CORTEX_GGUF_ROOTS") {
            for root in std::env::split_paths(&extra) {
                push_root(&mut roots, root, "configured");
            }
        }
    }

    let mut models = Vec::new();
    let mut seen = BTreeSet::new();
    for (root, source) in &roots {
        if !root.is_dir() {
            continue;
        }
        let mut stack = vec![root.clone()];
        while let Some(directory) = stack.pop() {
            let Ok(entries) = fs::read_dir(&directory) else {
                continue;
            };
            for entry in entries.filter_map(Result::ok) {
                let path = entry.path();
                let Ok(file_type) = entry.file_type() else {
                    continue;
                };
                if file_type.is_dir() {
                    stack.push(path);
                    continue;
                }
                if !file_type.is_file() || !is_primary_gguf(&path) {
                    continue;
                }
                let canonical = fs::canonicalize(&path).unwrap_or(path.clone());
                if !seen.insert(canonical.clone()) {
                    continue;
                }
                let metadata = entry.metadata().map_err(|error| error.to_string())?;
                let mmproj = find_mmproj_for_model(&canonical);
                let display_name = canonical
                    .file_stem()
                    .and_then(|value| value.to_str())
                    .unwrap_or("GGUF model")
                    .to_string();
                let role_hint = role_hint_for(&display_name, mmproj.is_some());
                models.push(NativeModelRecord {
                    id: stable_model_id(&canonical),
                    path: canonical,
                    display_name,
                    bytes: metadata.len(),
                    role_hint,
                    mmproj,
                    source: source.clone(),
                });
            }
        }
    }
    models.sort_by(|left, right| left.display_name.cmp(&right.display_name));
    Ok(NativeModelCatalog {
        schema_version: 1,
        models,
        roots: roots.into_iter().map(|(root, _)| root).collect(),
        generated_unix_ms: unix_ms(),
    })
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelMirrorSource {
    pub source: PathBuf,
    pub destination: PathBuf,
    pub copied_files: u64,
    pub skipped_files: u64,
    pub bytes_copied: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelMirrorReport {
    pub schema_version: u32,
    pub label: String,
    pub destination_root: PathBuf,
    pub sources: Vec<ModelMirrorSource>,
    pub copied_files: u64,
    pub skipped_files: u64,
    pub bytes_copied: u64,
    pub generated_unix_ms: u128,
}

pub fn lmstudio_model_roots() -> Vec<PathBuf> {
    let mut roots = Vec::<PathBuf>::new();
    if let Some(user) = std::env::var_os("USERPROFILE").map(PathBuf::from) {
        push_unique_path(&mut roots, user.join(".lmstudio").join("models"));
        push_unique_path(
            &mut roots,
            user.join(".cache").join("lm-studio").join("models"),
        );
        let settings = user.join(".lmstudio").join("settings.json");
        if let Ok(value) = serde_json::from_slice::<Value>(&fs::read(settings).unwrap_or_default())
        {
            if let Some(path) = value.get("downloadsFolder").and_then(Value::as_str) {
                push_unique_path(&mut roots, PathBuf::from(path));
            }
        }
    }
    roots.retain(|root| root.is_dir());
    roots
}

pub fn mirror_lmstudio_models(
    destination_root: impl AsRef<Path>,
) -> Result<ModelMirrorReport, String> {
    let roots = lmstudio_model_roots();
    if roots.is_empty() {
        return Err("no LM Studio model directories were found".into());
    }
    mirror_model_roots("lm_studio", &roots, destination_root.as_ref())
}

pub fn mirror_model_tree(
    label: &str,
    source: impl AsRef<Path>,
    destination_root: impl AsRef<Path>,
) -> Result<ModelMirrorReport, String> {
    mirror_model_roots(
        label,
        &[source.as_ref().to_path_buf()],
        destination_root.as_ref(),
    )
}

fn mirror_model_roots(
    label: &str,
    roots: &[PathBuf],
    destination_root: &Path,
) -> Result<ModelMirrorReport, String> {
    fs::create_dir_all(destination_root).map_err(|error| error.to_string())?;
    let mut report = ModelMirrorReport {
        schema_version: 1,
        label: label.to_string(),
        destination_root: destination_root.to_path_buf(),
        sources: Vec::new(),
        copied_files: 0,
        skipped_files: 0,
        bytes_copied: 0,
        generated_unix_ms: unix_ms(),
    };

    for (index, source) in roots.iter().filter(|root| root.is_dir()).enumerate() {
        let namespace = format!(
            "{:02}-{}",
            index + 1,
            safe_path_component(
                source
                    .file_name()
                    .and_then(|value| value.to_str())
                    .unwrap_or(label)
            )
        );
        let destination = destination_root.join(namespace);
        let source_report = mirror_directory(source, &destination)?;
        report.copied_files += source_report.copied_files;
        report.skipped_files += source_report.skipped_files;
        report.bytes_copied += source_report.bytes_copied;
        report.sources.push(source_report);
    }

    let manifest = destination_root.join(format!("{label}-mirror.json"));
    fs::write(
        &manifest,
        serde_json::to_vec_pretty(&report).map_err(|error| error.to_string())?,
    )
    .map_err(|error| {
        format!(
            "failed to write model mirror manifest {}: {error}",
            manifest.display()
        )
    })?;

    Ok(report)
}

fn mirror_directory(source: &Path, destination: &Path) -> Result<ModelMirrorSource, String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    let mut copied_files = 0_u64;
    let mut skipped_files = 0_u64;
    let mut bytes_copied = 0_u64;
    let mut stack = vec![source.to_path_buf()];

    while let Some(directory) = stack.pop() {
        for entry in fs::read_dir(&directory).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            let path = entry.path();
            let file_type = entry.file_type().map_err(|error| error.to_string())?;
            if file_type.is_symlink() {
                continue;
            }
            if file_type.is_dir() {
                stack.push(path);
                continue;
            }
            if !file_type.is_file() {
                continue;
            }

            let relative = path
                .strip_prefix(source)
                .map_err(|error| error.to_string())?;
            let target = destination.join(relative);
            if let Some(parent) = target.parent() {
                fs::create_dir_all(parent).map_err(|error| error.to_string())?;
            }
            let metadata = entry.metadata().map_err(|error| error.to_string())?;
            if target
                .metadata()
                .ok()
                .is_some_and(|existing| existing.len() == metadata.len())
            {
                skipped_files += 1;
                continue;
            }

            let partial = target.with_extension(format!(
                "{}.cortex-partial",
                target
                    .extension()
                    .and_then(|value| value.to_str())
                    .unwrap_or("file")
            ));
            fs::copy(&path, &partial).map_err(|error| {
                format!(
                    "failed to mirror model file {} -> {}: {error}",
                    path.display(),
                    partial.display()
                )
            })?;
            if target.exists() {
                fs::remove_file(&target).map_err(|error| error.to_string())?;
            }
            fs::rename(&partial, &target).map_err(|error| error.to_string())?;
            copied_files += 1;
            bytes_copied += metadata.len();
        }
    }

    Ok(ModelMirrorSource {
        source: source.to_path_buf(),
        destination: destination.to_path_buf(),
        copied_files,
        skipped_files,
        bytes_copied,
    })
}

fn push_unique_path(paths: &mut Vec<PathBuf>, path: PathBuf) {
    if !paths.iter().any(|existing| existing == &path) {
        paths.push(path);
    }
}

fn safe_path_component(value: &str) -> String {
    let normalized = value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>();
    let trimmed = normalized.trim_matches('-');
    if trimmed.is_empty() {
        "models".into()
    } else {
        trimmed.to_string()
    }
}

pub fn write_router_preset(catalog: &NativeModelCatalog, path: &Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let startup_model = model_for_role(catalog, ModelRoleHint::Chat).map(|model| model.id.as_str());
    let mut output = String::from(
        "version = 1\n\n[*]\nc = 16384\nn-gpu-layers = 999\nload-on-startup = false\n\n",
    );
    for model in &catalog.models {
        output.push_str(&format!("[{}]\n", model.id));
        output.push_str(&format!("model = {}\n", ini_path(&model.path)));
        if startup_model == Some(model.id.as_str()) {
            // The router health endpoint can become available before an on-demand model
            // instance is actually ready. Preload one text model so Desktop certification
            // and the first real chat request never race the router's child startup.
            //
            // Do not emit the newer `default-model` preset option here. The Cortex-bundled
            // llama.cpp release predates that router extension, and Cortex already sends an
            // explicit model ID on every inference request.
            output.push_str("load-on-startup = true\n");
        }
        if let Some(mmproj) = &model.mmproj {
            output.push_str(&format!("mmproj = {}\n", ini_path(mmproj)));
        }
        if model.role_hint == ModelRoleHint::Embedding {
            output.push_str("embedding = true\npooling = mean\n");
        }
        output.push('\n');
    }
    fs::write(path, output).map_err(|error| error.to_string())
}

pub fn model_for_role(
    catalog: &NativeModelCatalog,
    role: ModelRoleHint,
) -> Option<&NativeModelRecord> {
    if let Some(exact) = catalog.models.iter().find(|model| model.role_hint == role) {
        return Some(exact);
    }

    if role == ModelRoleHint::Embedding {
        return None;
    }

    // Do not make a pure reasoning model the automatic interactive fallback
    // merely because it sorts first by filename.  Reasoning-first models can
    // consume the entire bounded output budget before emitting user-visible
    // text, which is a poor default for Desktop chat and short agent turns.
    // Prefer a general/coding/vision instruct model first; reasoning remains
    // available when explicitly selected or when it is the only text model.
    let fallback_order: &[ModelRoleHint] = match role {
        ModelRoleHint::Chat => &[
            ModelRoleHint::Coding,
            ModelRoleHint::Vision,
            ModelRoleHint::Reasoning,
        ],
        ModelRoleHint::Coding => &[
            ModelRoleHint::Chat,
            ModelRoleHint::Vision,
            ModelRoleHint::Reasoning,
        ],
        ModelRoleHint::Vision => &[
            ModelRoleHint::Chat,
            ModelRoleHint::Coding,
            ModelRoleHint::Reasoning,
        ],
        ModelRoleHint::Reasoning => &[
            ModelRoleHint::Coding,
            ModelRoleHint::Chat,
            ModelRoleHint::Vision,
        ],
        ModelRoleHint::Embedding => &[],
    };

    fallback_order
        .iter()
        .find_map(|fallback| {
            catalog
                .models
                .iter()
                .find(|model| model.role_hint == *fallback)
        })
        .or_else(|| {
            catalog
                .models
                .iter()
                .find(|model| model.role_hint != ModelRoleHint::Embedding)
        })
}

fn push_root(roots: &mut Vec<(PathBuf, String)>, root: PathBuf, source: &str) {
    if roots.iter().any(|(existing, _)| existing == &root) {
        return;
    }
    roots.push((root, source.to_string()));
}

fn is_primary_gguf(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return false;
    };
    let lower = name.to_ascii_lowercase();
    if !lower.ends_with(".gguf") || lower.contains("mmproj") {
        return false;
    }
    if lower.contains("-of-") && !lower.contains("-00001-of-") {
        return false;
    }
    true
}

fn find_mmproj_for_model(model: &Path) -> Option<PathBuf> {
    let directory = model.parent()?;
    let model_stem = model
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let model_family = model_family_key(&model_stem);

    let candidates = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|value| value.to_str())
                .map(|name| {
                    let lower = name.to_ascii_lowercase();
                    lower.starts_with("mmproj") && lower.ends_with(".gguf")
                })
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();

    if candidates.is_empty() {
        return None;
    }

    for candidate in &candidates {
        let stem = candidate
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let projector_family = model_family_key(
            stem.trim_start_matches("mmproj")
                .trim_start_matches(['-', '_', '.']),
        );
        if !model_family.is_empty()
            && !projector_family.is_empty()
            && (model_family.contains(&projector_family)
                || projector_family.contains(&model_family))
        {
            return Some(candidate.clone());
        }
    }

    // A generic mmproj is safe only when there is one primary model in the folder.
    let primary_count = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| is_primary_gguf(path))
        .count();
    (primary_count == 1 && candidates.len() == 1).then(|| candidates[0].clone())
}

fn model_family_key(value: &str) -> String {
    value
        .to_ascii_lowercase()
        .replace(".gguf", "")
        .replace("mmproj", "")
        .split(['-', '_', '.', ' '])
        .filter(|part| {
            !part.is_empty()
                && !part.starts_with('q')
                && !part.chars().all(|ch| ch.is_ascii_digit())
                && !matches!(
                    *part,
                    "f16"
                        | "f32"
                        | "bf16"
                        | "q4"
                        | "q5"
                        | "q6"
                        | "q8"
                        | "k"
                        | "m"
                        | "s"
                        | "xs"
                        | "xl"
                        | "model"
                        | "instruct"
                )
        })
        .take(5)
        .collect::<Vec<_>>()
        .join("-")
}

fn role_hint_for(name: &str, vision: bool) -> ModelRoleHint {
    let lower = name.to_ascii_lowercase();
    if lower.contains("embed") || lower.contains("embedding") {
        ModelRoleHint::Embedding
    } else if vision {
        ModelRoleHint::Vision
    } else if lower.contains("coder") || lower.contains("code-") || lower.contains("codestral") {
        ModelRoleHint::Coding
    } else if lower.contains("reason")
        || lower.contains("deepseek-r1")
        || lower.contains("qwen3")
        || lower.contains("gpt-oss")
    {
        ModelRoleHint::Reasoning
    } else {
        ModelRoleHint::Chat
    }
}

fn stable_model_id(path: &Path) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in path.to_string_lossy().as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("model")
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.') {
                ch
            } else {
                '-'
            }
        })
        .take(48)
        .collect::<String>();
    format!("{}-{hash:08x}", stem.trim_matches('-'))
}

fn ini_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn resolve_or_bootstrap_runtime(
    runtime_root: &Path,
    auto_bootstrap: bool,
) -> Result<PathBuf, String> {
    if let Some(explicit) = std::env::var_os("CORTEX_LLAMA_SERVER").map(PathBuf::from) {
        if explicit.is_file() {
            return fs::canonicalize(explicit).map_err(|error| error.to_string());
        }
    }
    let bundled = runtime_root.join("llama-server.exe");
    if bundled.is_file() {
        return fs::canonicalize(bundled).map_err(|error| error.to_string());
    }
    if let Some(path) = find_on_path("llama-server.exe") {
        return Ok(path);
    }
    if !auto_bootstrap {
        return Err(format!(
            "Cortex llama.cpp runtime is missing. Expected {} or CORTEX_LLAMA_SERVER.",
            bundled.display()
        ));
    }
    bootstrap_windows_vulkan(runtime_root)?;
    let resolved = runtime_root.join("llama-server.exe");
    if resolved.is_file() {
        fs::canonicalize(resolved).map_err(|error| error.to_string())
    } else {
        Err("Cortex llama.cpp bootstrap completed without llama-server.exe".into())
    }
}

fn find_on_path(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|directory| directory.join(name))
        .find(|candidate| candidate.is_file())
        .and_then(|candidate| fs::canonicalize(candidate).ok())
}

#[cfg(windows)]
fn powershell_filesystem_path(path: &Path) -> String {
    let value = path.to_string_lossy();
    if let Some(rest) = value.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = value.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        value.into_owned()
    }
}

#[cfg(windows)]
fn bootstrap_windows_vulkan(runtime_root: &Path) -> Result<(), String> {
    fs::create_dir_all(runtime_root).map_err(|error| error.to_string())?;
    let script = r#"
$ErrorActionPreference='Stop'
$root=$env:CORTEX_LLAMA_BOOTSTRAP_ROOT
$url=$env:CORTEX_LLAMA_BOOTSTRAP_URL
$expected=$env:CORTEX_LLAMA_BOOTSTRAP_SHA256
if ([string]::IsNullOrWhiteSpace($root)) { throw 'Cortex llama.cpp bootstrap root is empty' }
if ([string]::IsNullOrWhiteSpace($url)) { throw 'Cortex llama.cpp bootstrap URL is empty' }
if ([string]::IsNullOrWhiteSpace($expected)) { throw 'Cortex llama.cpp bootstrap SHA-256 is empty' }
$zip=Join-Path $env:TEMP ('cortex-llama-' + [guid]::NewGuid().ToString('N') + '.zip')
$extract=Join-Path $env:TEMP ('cortex-llama-' + [guid]::NewGuid().ToString('N'))
try {
  Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
  $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant()
  if ($actual -ne $expected.ToLowerInvariant()) { throw "llama.cpp runtime SHA-256 mismatch: $actual" }
  Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
  $server=Get-ChildItem -LiteralPath $extract -Recurse -File -Filter 'llama-server.exe' | Select-Object -First 1
  if ($null -eq $server) { throw 'llama-server.exe missing from verified release archive' }
  $sourceDir=$server.Directory.FullName
  Get-ChildItem -LiteralPath $sourceDir -File | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $root $_.Name) -Force }
} finally {
  Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $extract -Recurse -Force -ErrorAction SilentlyContinue
}
"#;
    let status = Command::new("powershell.exe")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ])
        .env(
            "CORTEX_LLAMA_BOOTSTRAP_ROOT",
            powershell_filesystem_path(runtime_root),
        )
        .env("CORTEX_LLAMA_BOOTSTRAP_URL", LLAMA_CPP_WINDOWS_VULKAN_URL)
        .env(
            "CORTEX_LLAMA_BOOTSTRAP_SHA256",
            LLAMA_CPP_WINDOWS_VULKAN_SHA256,
        )
        .status()
        .map_err(|error| format!("failed to launch Cortex llama.cpp bootstrap: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("Cortex llama.cpp bootstrap failed with {status}"))
    }
}

#[cfg(not(windows))]
fn bootstrap_windows_vulkan(_runtime_root: &Path) -> Result<(), String> {
    Err("automatic bundled llama.cpp bootstrap is currently Windows-only".into())
}

fn write_state(path: &Path, state: &ModelHostState) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    fs::write(
        path,
        serde_json::to_vec_pretty(state).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())
}

fn log_tail(path: &Path) -> String {
    let Ok(bytes) = fs::read(path) else {
        return String::new();
    };
    if bytes.is_empty() {
        return String::new();
    }
    let start = bytes.len().saturating_sub(4096);
    let text = String::from_utf8_lossy(&bytes[start..]);
    if text.trim().is_empty() {
        String::new()
    } else {
        format!("\nLast output:\n{}", text.trim())
    }
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[cfg(windows)]
fn configure_background(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x08000000 | 0x00000008);
}
#[cfg(not(windows))]
fn configure_background(_command: &mut Command) {}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(label: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "cortex-model-host-{label}-{}-{}",
            std::process::id(),
            unix_ms()
        ))
    }

    #[test]
    fn pinned_llama_bootstrap_contract_is_non_empty_and_https() {
        assert!(LLAMA_CPP_WINDOWS_VULKAN_URL.starts_with("https://"));
        assert!(!LLAMA_CPP_WINDOWS_VULKAN_URL.trim().is_empty());
        assert_eq!(LLAMA_CPP_WINDOWS_VULKAN_SHA256.len(), 64);
        assert!(LLAMA_CPP_WINDOWS_VULKAN_SHA256
            .chars()
            .all(|ch| ch.is_ascii_hexdigit()));
        assert!(LLAMA_CPP_WINDOWS_VULKAN_ASSET.ends_with(".zip"));
    }

    #[cfg(windows)]
    #[test]
    fn powershell_bootstrap_path_strips_extended_windows_prefixes() {
        assert_eq!(
            powershell_filesystem_path(Path::new(r"\\?\D:\Cortex\.cortex\runtime")),
            r"D:\Cortex\.cortex\runtime"
        );
        assert_eq!(
            powershell_filesystem_path(Path::new(r"\\?\UNC\server\share\Cortex")),
            r"\\server\share\Cortex"
        );
        assert_eq!(
            powershell_filesystem_path(Path::new(r"D:\Cortex\Models")),
            r"D:\Cortex\Models"
        );
    }

    #[test]
    fn gguf_catalog_skips_mmproj_and_later_shards() {
        let root = temp_root("catalog");
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("Qwen3-Coder-Q4.gguf"), b"x").unwrap();
        fs::write(root.join("mmproj-model.gguf"), b"x").unwrap();
        fs::write(root.join("big-00001-of-00002.gguf"), b"x").unwrap();
        fs::write(root.join("big-00002-of-00002.gguf"), b"x").unwrap();
        let catalog = discover_models_local(&root).unwrap();
        assert_eq!(catalog.models.len(), 2);
        assert!(catalog
            .models
            .iter()
            .any(|model| model.role_hint == ModelRoleHint::Coding));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn local_catalog_discovery_isolated_from_external_model_roots() {
        let root = temp_root("local-isolation");
        let external = temp_root("external-isolation");
        fs::create_dir_all(&root).unwrap();
        fs::create_dir_all(&external).unwrap();
        fs::write(root.join("local-chat.gguf"), b"x").unwrap();
        fs::write(external.join("external-chat.gguf"), b"x").unwrap();

        let previous = std::env::var_os("CORTEX_GGUF_ROOTS");
        std::env::set_var("CORTEX_GGUF_ROOTS", &external);
        let local = discover_models_local(&root).unwrap();
        if let Some(previous) = previous {
            std::env::set_var("CORTEX_GGUF_ROOTS", previous);
        } else {
            std::env::remove_var("CORTEX_GGUF_ROOTS");
        }

        assert_eq!(local.models.len(), 1);
        assert!(local.models[0].path.ends_with("local-chat.gguf"));

        fs::remove_dir_all(root).unwrap();
        fs::remove_dir_all(external).unwrap();
    }

    #[test]
    fn unrelated_mmproj_does_not_reclassify_coder_as_vision() {
        let root = temp_root("mmproj-association");
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("Qwen3-Coder-Q4.gguf"), b"x").unwrap();
        fs::write(root.join("mmproj-other-family.gguf"), b"x").unwrap();
        fs::write(root.join("other-family.gguf"), b"x").unwrap();

        let catalog = discover_models_local(&root).unwrap();
        let coder = catalog
            .models
            .iter()
            .find(|model| model.display_name.contains("Coder"))
            .unwrap();
        assert_eq!(coder.role_hint, ModelRoleHint::Coding);
        assert!(coder.mmproj.is_none());

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn embedded_mmproj_name_is_never_cataloged_as_a_primary_model() {
        let root = temp_root("embedded-mmproj-name");
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("gemma-chat-Q4_K_M.gguf"), b"x").unwrap();
        fs::write(root.join("gemma-chat-mmproj.q8_0.gguf"), b"x").unwrap();

        let catalog = discover_models_local(&root).unwrap();
        assert_eq!(catalog.models.len(), 1);
        assert_eq!(catalog.models[0].display_name, "gemma-chat-Q4_K_M");

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn chat_fallback_prefers_general_instruct_over_pure_reasoning() {
        let catalog = NativeModelCatalog {
            schema_version: 1,
            models: vec![
                NativeModelRecord {
                    id: "deepseek".into(),
                    path: PathBuf::from("DeepSeek-R1.gguf"),
                    display_name: "DeepSeek-R1".into(),
                    bytes: 1,
                    role_hint: ModelRoleHint::Reasoning,
                    mmproj: None,
                    source: "test".into(),
                },
                NativeModelRecord {
                    id: "qwen35".into(),
                    path: PathBuf::from("Qwen3.5.gguf"),
                    display_name: "Qwen3.5".into(),
                    bytes: 1,
                    role_hint: ModelRoleHint::Vision,
                    mmproj: Some(PathBuf::from("mmproj-Qwen3.5.gguf")),
                    source: "test".into(),
                },
            ],
            roots: Vec::new(),
            generated_unix_ms: 0,
        };

        let selected = model_for_role(&catalog, ModelRoleHint::Chat).unwrap();
        assert_eq!(selected.id, "qwen35");
    }

    #[test]
    fn model_tree_mirror_preserves_shards_projectors_and_structure() {
        let source = temp_root("mirror-source");
        let destination = temp_root("mirror-destination");
        let family = source.join("vendor").join("model");
        fs::create_dir_all(&family).unwrap();
        fs::write(family.join("model-00001-of-00002.gguf"), b"one").unwrap();
        fs::write(family.join("model-00002-of-00002.gguf"), b"two").unwrap();
        fs::write(family.join("mmproj-model.gguf"), b"projector").unwrap();
        fs::write(family.join("README.md"), b"license/provenance").unwrap();

        let report = mirror_model_tree("fixture", &source, &destination).unwrap();
        assert_eq!(report.copied_files, 4);
        let mirrored_root = &report.sources[0].destination;
        assert!(mirrored_root
            .join("vendor/model/model-00001-of-00002.gguf")
            .is_file());
        assert!(mirrored_root
            .join("vendor/model/model-00002-of-00002.gguf")
            .is_file());
        assert!(mirrored_root
            .join("vendor/model/mmproj-model.gguf")
            .is_file());
        assert!(destination.join("fixture-mirror.json").is_file());

        fs::remove_dir_all(source).unwrap();
        fs::remove_dir_all(destination).unwrap();
    }

    #[test]
    fn router_preset_contains_model_paths_and_roles() {
        let root = temp_root("preset");
        fs::create_dir_all(&root).unwrap();
        let embedding = root.join("embed-model.gguf");
        let chat = root.join("chat-model.gguf");
        fs::write(&embedding, b"x").unwrap();
        fs::write(&chat, b"x").unwrap();
        let catalog = discover_models_local(&root).unwrap();
        let preset = root.join("models.ini");
        write_router_preset(&catalog, &preset).unwrap();
        let text = fs::read_to_string(&preset).unwrap();
        assert!(text.contains("embedding = true"));
        assert!(text.contains("c = 16384"));
        assert!(text.contains("load-on-startup = false"));
        assert!(text.contains("load-on-startup = true"));
        assert!(!text.contains("default-model ="));
        fs::remove_dir_all(root).unwrap();
    }
}
