//! Persistent standalone Cortex service lifecycle and PID ownership.
use serde::{Deserialize, Serialize};
use std::fs;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ServiceStatus {
    Running,
    Stale,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ServiceState {
    pub schema_version: u32,
    pub pid: u32,
    pub port: u16,
    pub workspace_root: PathBuf,
    pub executable: PathBuf,
    pub started_unix_ms: u128,
    pub status: ServiceStatus,
}

pub struct ServiceRegistry {
    state_path: PathBuf,
    workspace_root: PathBuf,
}
pub struct ServiceClaim {
    registry: ServiceRegistry,
    pid: u32,
}

impl ServiceRegistry {
    pub fn new(
        state_root: impl AsRef<Path>,
        workspace_root: impl AsRef<Path>,
    ) -> Result<Self, String> {
        fs::create_dir_all(state_root.as_ref()).map_err(|e| e.to_string())?;
        Ok(Self {
            state_path: state_root.as_ref().join("service.json"),
            workspace_root: workspace_root.as_ref().to_path_buf(),
        })
    }
    pub fn read(&self) -> Result<Option<ServiceState>, String> {
        if !self.state_path.is_file() {
            return Ok(None);
        }
        let mut state: ServiceState =
            serde_json::from_slice(&fs::read(&self.state_path).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        state.status = if process_matches_executable(state.pid, &state.executable) {
            ServiceStatus::Running
        } else {
            ServiceStatus::Stale
        };
        Ok(Some(state))
    }
    pub fn spawn(&self, port: u16) -> Result<ServiceState, String> {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        self.spawn_executable(exe, port)
    }

    pub fn spawn_executable(
        &self,
        executable: impl AsRef<Path>,
        port: u16,
    ) -> Result<ServiceState, String> {
        self.spawn_executable_with_env(executable, port, &[])
    }

    pub fn spawn_executable_with_env(
        &self,
        executable: impl AsRef<Path>,
        port: u16,
        environment: &[(String, String)],
    ) -> Result<ServiceState, String> {
        let exe = fs::canonicalize(executable).map_err(|e| e.to_string())?;
        if let Some(state) = self.read()? {
            if state.status == ServiceStatus::Running {
                if process_matches_executable(state.pid, &exe) {
                    return Ok(state);
                }
                self.stop().map_err(|error| {
                    format!(
                        "failed to replace Cortex service {} with {}: {error}",
                        state.executable.display(),
                        exe.display()
                    )
                })?;
            } else {
                let _ = fs::remove_file(&self.state_path);
            }
        }
        let startup_log = self.startup_log_path();
        if let Some(parent) = startup_log.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let stdout_log = File::create(&startup_log).map_err(|e| {
            format!(
                "failed to create Cortex service startup log {}: {e}",
                startup_log.display()
            )
        })?;
        let stderr_log = stdout_log.try_clone().map_err(|e| e.to_string())?;

        let mut cmd = Command::new(&exe);
        cmd.arg("--workspace")
            .arg(&self.workspace_root)
            .arg("service")
            .arg("run")
            .arg("--port")
            .arg(port.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout_log))
            .stderr(Stdio::from(stderr_log));
        for (key, value) in environment {
            cmd.env(key, value);
        }
        configure_background(&mut cmd);
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("failed to launch Cortex service: {e}"))?;
        let pid = child.id();
        let deadline = Instant::now() + Duration::from_secs(45);
        while Instant::now() < deadline {
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                let _ = fs::remove_file(&self.state_path);
                return Err(format!(
                    "Cortex service PID {pid} exited during startup with {status}. Startup log: {}{}",
                    startup_log.display(),
                    startup_log_suffix(&startup_log)
                ));
            }
            if let Some(state) = self.read_published_state()? {
                if state.pid == pid && state.status == ServiceStatus::Running {
                    return Ok(state);
                }
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        let _ = child.kill();
        let _ = child.wait();
        let _ = fs::remove_file(&self.state_path);
        Err(format!(
            "Cortex service PID {pid} did not publish ready state within 45 seconds. Workspace: {}. Startup log: {}{}",
            self.workspace_root.display(),
            startup_log.display(),
            startup_log_suffix(&startup_log)
        ))
    }
    fn read_published_state(&self) -> Result<Option<ServiceState>, String> {
        if !self.state_path.is_file() {
            return Ok(None);
        }
        let bytes = fs::read(&self.state_path).map_err(|e| e.to_string())?;
        match serde_json::from_slice(&bytes) {
            Ok(state) => Ok(Some(state)),
            Err(_) => Ok(None),
        }
    }

    fn startup_log_path(&self) -> PathBuf {
        self.state_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("logs")
            .join("cortex-service-startup.log")
    }

    pub fn claim_current_process(&self, port: u16) -> Result<ServiceClaim, String> {
        let exe = fs::canonicalize(std::env::current_exe().map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let state = ServiceState {
            schema_version: 1,
            pid: std::process::id(),
            port,
            workspace_root: self.workspace_root.clone(),
            executable: exe,
            started_unix_ms: unix_ms(),
            status: ServiceStatus::Running,
        };
        fs::write(
            &self.state_path,
            serde_json::to_vec_pretty(&state).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        Ok(ServiceClaim {
            registry: Self {
                state_path: self.state_path.clone(),
                workspace_root: self.workspace_root.clone(),
            },
            pid: state.pid,
        })
    }
    pub fn stop(&self) -> Result<bool, String> {
        let Some(state) = self.read()? else {
            return Ok(false);
        };
        if state.status != ServiceStatus::Running {
            let _ = fs::remove_file(&self.state_path);
            return Ok(false);
        }
        if !process_matches_executable(state.pid, &state.executable) {
            return Err(format!(
                "refusing to stop PID {}: executable ownership not verified",
                state.pid
            ));
        }
        terminate_process(state.pid)?;
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if !process_matches_executable(state.pid, &state.executable) {
                let _ = fs::remove_file(&self.state_path);
                return Ok(true);
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        Err(format!("Cortex service PID {} did not stop", state.pid))
    }
    pub fn clear_stale(&self) -> Result<bool, String> {
        match self.read()? {
            Some(s) if s.status == ServiceStatus::Stale => {
                fs::remove_file(&self.state_path).map_err(|e| e.to_string())?;
                Ok(true)
            }
            _ => Ok(false),
        }
    }
}
impl Drop for ServiceClaim {
    fn drop(&mut self) {
        if let Ok(Some(state)) = self.registry.read() {
            if state.pid == self.pid {
                let _ = fs::remove_file(&self.registry.state_path);
            }
        }
    }
}
pub fn process_is_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    process_exists(pid)
}

pub fn terminate_owned_process(pid: u32, expected: &Path) -> Result<bool, String> {
    if !process_matches_executable(pid, expected) {
        return Ok(false);
    }
    terminate_process(pid)?;
    Ok(true)
}

fn startup_log_suffix(path: &Path) -> String {
    let Ok(bytes) = fs::read(path) else {
        return String::new();
    };
    if bytes.is_empty() {
        return String::new();
    }
    let start = bytes.len().saturating_sub(4096);
    let tail = String::from_utf8_lossy(&bytes[start..]);
    let compact = tail.trim();
    if compact.is_empty() {
        String::new()
    } else {
        format!("\nLast startup output:\n{compact}")
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
#[cfg(windows)]
fn process_exists(pid: u32) -> bool {
    use std::ffi::c_void;
    type WinHandle = *mut c_void;
    const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    #[link(name = "kernel32")]
    extern "system" {
        #[link_name = "OpenProcess"]
        fn open_process_alive(
            desired_access: u32,
            inherit_handle: i32,
            process_id: u32,
        ) -> WinHandle;
        #[link_name = "CloseHandle"]
        fn close_handle_alive(object: WinHandle) -> i32;
    }
    unsafe {
        let handle = open_process_alive(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            false
        } else {
            let _ = close_handle_alive(handle);
            true
        }
    }
}

#[cfg(not(windows))]
fn process_exists(pid: u32) -> bool {
    Path::new("/proc").join(pid.to_string()).exists()
}

#[cfg(windows)]
fn process_matches_executable(pid: u32, expected: &Path) -> bool {
    use std::ffi::{c_void, OsString};
    use std::os::windows::ffi::OsStringExt;

    type WinHandle = *mut c_void;
    const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;

    #[link(name = "kernel32")]
    extern "system" {
        #[link_name = "OpenProcess"]
        fn open_process(desired_access: u32, inherit_handle: i32, process_id: u32) -> WinHandle;
        #[link_name = "QueryFullProcessImageNameW"]
        fn query_full_process_image_name_w(
            process: WinHandle,
            flags: u32,
            image_name: *mut u16,
            size: *mut u32,
        ) -> i32;
        #[link_name = "CloseHandle"]
        fn close_handle(object: WinHandle) -> i32;
    }

    let actual = unsafe {
        let process = open_process(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if process.is_null() {
            return false;
        }

        let mut buffer = vec![0_u16; 32_768];
        let mut size = buffer.len() as u32;
        let ok = query_full_process_image_name_w(process, 0, buffer.as_mut_ptr(), &mut size);
        let _ = close_handle(process);
        if ok == 0 || size == 0 {
            return false;
        }
        PathBuf::from(OsString::from_wide(&buffer[..size as usize]))
    };

    let Ok(actual) = fs::canonicalize(actual) else {
        return false;
    };
    let Ok(expected) = fs::canonicalize(expected) else {
        return false;
    };
    actual == expected
}
#[cfg(target_os = "linux")]
fn process_matches_executable(pid: u32, expected: &Path) -> bool {
    let Ok(actual) = fs::canonicalize(format!("/proc/{pid}/exe")) else {
        return false;
    };
    let Ok(expected) = fs::canonicalize(expected) else {
        return false;
    };
    actual == expected
}
#[cfg(all(not(windows), not(target_os = "linux")))]
fn process_matches_executable(pid: u32, _expected: &Path) -> bool {
    Command::new("kill")
        .args(["-0", &pid.to_string()])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}
#[cfg(windows)]
fn terminate_process(pid: u32) -> Result<(), String> {
    use std::os::windows::process::CommandExt;
    let mut command = Command::new("taskkill");
    command
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        // CREATE_NO_WINDOW: lifecycle cleanup must never flash/attach a console
        // while the native Cortex Desktop changes project context.
        .creation_flags(0x08000000);
    let s = command.status().map_err(|e| e.to_string())?;
    if s.success() {
        Ok(())
    } else if !process_exists(pid) {
        // taskkill can race a process that exits on its own between ownership
        // verification and termination. That is already the desired end state.
        Ok(())
    } else {
        Err(format!("taskkill failed for PID {pid}"))
    }
}
#[cfg(not(windows))]
fn terminate_process(pid: u32) -> Result<(), String> {
    let s = Command::new("kill")
        .args(["-TERM", &pid.to_string()])
        .status()
        .map_err(|e| e.to_string())?;
    if s.success() {
        Ok(())
    } else {
        Err(format!("kill failed for PID {pid}"))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn missing_service_is_stopped() {
        let root = std::env::temp_dir().join(format!(
            "cortex-service-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        let registry = ServiceRegistry::new(&root, &root).unwrap();
        assert!(registry.read().unwrap().is_none());
        assert!(!registry.stop().unwrap());
        fs::remove_dir_all(root).unwrap();
    }
}
