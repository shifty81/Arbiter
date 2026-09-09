//! Canonical Cortex capability and permission policy.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    WorkspaceRead,
    WorkspaceWrite,
    ProcessExecute,
    GitRead,
    GitWrite,
    NetworkLocal,
    NetworkInternet,
    Vision,
    ImageGeneration,
    ExternalPath,
    Delete,
    Credentials,
    SystemChange,
    UiAutomation,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum TrustLevel {
    System,
    User,
    ProjectPolicy,
    TrustedTool,
    UntrustedContent,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalLevel {
    Automatic,
    UserApproval,
    StrongApproval,
    PrivilegedBroker,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CapabilityRequest {
    pub permission: Permission,
    pub operation: String,
    pub trust: TrustLevel,
    #[serde(default)]
    pub destructive: bool,
    #[serde(default)]
    pub privileged: bool,
}

impl CapabilityRequest {
    pub fn approval_level(&self) -> ApprovalLevel {
        if self.privileged {
            ApprovalLevel::PrivilegedBroker
        } else if self.destructive
            || matches!(
                self.permission,
                Permission::Delete
                    | Permission::Credentials
                    | Permission::SystemChange
                    | Permission::UiAutomation
            )
        {
            ApprovalLevel::StrongApproval
        } else if matches!(
            self.permission,
            Permission::WorkspaceWrite
                | Permission::ProcessExecute
                | Permission::GitWrite
                | Permission::ExternalPath
                | Permission::NetworkInternet
        ) {
            ApprovalLevel::UserApproval
        } else {
            ApprovalLevel::Automatic
        }
    }

    pub fn content_may_authorize(&self) -> bool {
        !matches!(self.trust, TrustLevel::UntrustedContent)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PermissionPolicy {
    pub schema_version: u32,
    pub granted: BTreeSet<Permission>,
}

impl Default for PermissionPolicy {
    fn default() -> Self {
        Self {
            schema_version: 2,
            granted: [
                Permission::WorkspaceRead,
                Permission::WorkspaceWrite,
                Permission::ProcessExecute,
                Permission::GitRead,
                Permission::NetworkLocal,
                Permission::Vision,
                Permission::ImageGeneration,
            ]
            .into_iter()
            .collect(),
        }
    }
}

impl PermissionPolicy {
    pub fn load_or_default(path: &Path) -> Result<Self, String> {
        if !path.is_file() {
            return Ok(Self::default());
        }
        let mut policy: Self = serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        if policy.schema_version < 2 {
            policy.schema_version = 2;
        }
        Ok(policy)
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
    pub fn grant(&mut self, permission: Permission) {
        self.granted.insert(permission);
    }
    pub fn revoke(&mut self, permission: Permission) {
        self.granted.remove(&permission);
    }
    pub fn require(&self, permission: Permission, operation: &str) -> Result<(), String> {
        if self.granted.contains(&permission) {
            Ok(())
        } else {
            Err(format!(
                "Cortex permission denied for `{operation}`: {permission:?}"
            ))
        }
    }

    pub fn authorize(&self, request: &CapabilityRequest) -> Result<ApprovalLevel, String> {
        self.require(request.permission, &request.operation)?;
        let approval = request.approval_level();
        if !request.content_may_authorize() && !matches!(approval, ApprovalLevel::Automatic) {
            return Err(format!(
                "untrusted content cannot authorize Cortex capability `{}`",
                request.operation
            ));
        }
        Ok(approval)
    }
}

pub fn permission_for_tool(name: &str) -> Permission {
    if name.starts_with("source.") {
        if matches!(
            name,
            "source.list"
                | "source.read"
                | "source.search"
                | "source.transaction_status"
                | "source.transaction_files"
        ) {
            Permission::WorkspaceRead
        } else {
            Permission::WorkspaceWrite
        }
    } else if name.starts_with("workspace.") {
        match name {
            "workspace.storage_set" => Permission::SystemChange,
            "workspace.offsite_backup_set"
            | "workspace.scan_storage"
            | "workspace.scan_machine"
            | "workspace.migration_apply" => Permission::ExternalPath,
            _ => Permission::WorkspaceRead,
        }
    } else if name.starts_with("build.") || name.starts_with("runtime.") {
        Permission::ProcessExecute
    } else if name.starts_with("git.") {
        match name {
            "git.host.bootstrap" => Permission::SystemChange,
            "git.host.ensure_ssh_key" => Permission::Credentials,
            "git.host.ensure_identity" => Permission::Credentials,
            "git.host.backup" => Permission::ExternalPath,
            "git.vault.ingest" => Permission::ExternalPath,
            "git.vault.materialize" => Permission::WorkspaceWrite,
            "git.release.snapshot" => Permission::WorkspaceWrite,
            "git.issue.create" => Permission::GitWrite,
            "git.stage" | "git.unstage" | "git.commit" | "git.branch.create"
            | "git.branch.switch" | "git.safety.create" | "git.fetch.local" | "git.push.local" => {
                Permission::GitWrite
            }
            "git.project.attach_local" => Permission::GitWrite,
            _ if name.contains("write") || name.contains("commit") || name.contains("reset") => {
                Permission::GitWrite
            }
            _ => Permission::GitRead,
        }
    } else if name.starts_with("pcc.") {
        match name {
            "pcc.status" | "pcc.catalog" | "pcc.doctor" | "pcc.archive_audit" => {
                Permission::WorkspaceRead
            }
            _ => Permission::ProcessExecute,
        }
    } else if name.starts_with("web.") {
        Permission::NetworkInternet
    } else if name.starts_with("vision.") || name.starts_with("capture.") {
        Permission::Vision
    } else if name.starts_with("image.") {
        Permission::ImageGeneration
    } else if name.starts_with("vscode.") {
        if matches!(name, "vscode.apply_workspace_edit" | "vscode.save_all") {
            Permission::WorkspaceWrite
        } else {
            Permission::WorkspaceRead
        }
    } else {
        Permission::WorkspaceRead
    }
}

pub fn parse_permission(value: &str) -> Option<Permission> {
    match value.to_ascii_lowercase().as_str() {
        "workspace_read" | "read" => Some(Permission::WorkspaceRead),
        "workspace_write" | "write" => Some(Permission::WorkspaceWrite),
        "process_execute" | "execute" => Some(Permission::ProcessExecute),
        "git_read" => Some(Permission::GitRead),
        "git_write" => Some(Permission::GitWrite),
        "network_local" => Some(Permission::NetworkLocal),
        "network_internet" | "internet" => Some(Permission::NetworkInternet),
        "vision" => Some(Permission::Vision),
        "image_generation" | "image" => Some(Permission::ImageGeneration),
        "external_path" => Some(Permission::ExternalPath),
        "delete" => Some(Permission::Delete),
        "credentials" => Some(Permission::Credentials),
        "system_change" | "system" => Some(Permission::SystemChange),
        "ui_automation" | "desktop_automation" => Some(Permission::UiAutomation),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn local_git_host_mutations_require_governed_permissions() {
        assert_eq!(
            permission_for_tool("git.host.bootstrap"),
            Permission::SystemChange
        );
        assert_eq!(
            permission_for_tool("git.host.ensure_ssh_key"),
            Permission::Credentials
        );
        assert_eq!(
            permission_for_tool("git.host.ensure_identity"),
            Permission::Credentials
        );
        assert_eq!(
            permission_for_tool("git.issue.create"),
            Permission::GitWrite
        );
        assert_eq!(
            permission_for_tool("git.project.attach_local"),
            Permission::GitWrite
        );
        assert_eq!(
            permission_for_tool("git.provider.refresh"),
            Permission::GitRead
        );
        assert_eq!(permission_for_tool("git.host.status"), Permission::GitRead);
        assert_eq!(permission_for_tool("git.sync.status"), Permission::GitRead);
        assert_eq!(permission_for_tool("git.fetch.local"), Permission::GitWrite);
        assert_eq!(
            permission_for_tool("git.host.backup"),
            Permission::ExternalPath
        );
    }

    #[test]
    fn universal_pcc_tools_preserve_execution_authority() {
        assert_eq!(permission_for_tool("pcc.status"), Permission::WorkspaceRead);
        assert_eq!(
            permission_for_tool("pcc.catalog"),
            Permission::WorkspaceRead
        );
        assert_eq!(permission_for_tool("pcc.doctor"), Permission::WorkspaceRead);
        assert_eq!(
            permission_for_tool("pcc.archive_audit"),
            Permission::WorkspaceRead
        );
        assert_eq!(permission_for_tool("pcc.gate"), Permission::ProcessExecute);
        assert_eq!(
            permission_for_tool("pcc.run_readonly"),
            Permission::ProcessExecute
        );
        assert_eq!(permission_for_tool("pcc.run"), Permission::ProcessExecute);
    }

    #[test]
    fn risky_permissions_default_denied() {
        let p = PermissionPolicy::default();
        assert!(!p.granted.contains(&Permission::GitWrite));
        assert!(!p.granted.contains(&Permission::Delete));
        assert!(!p.granted.contains(&Permission::Credentials));
        assert!(!p.granted.contains(&Permission::SystemChange));
        assert!(!p.granted.contains(&Permission::UiAutomation));
    }
    #[test]
    fn portable_storage_operations_require_external_or_system_authority() {
        assert_eq!(
            permission_for_tool("workspace.storage_status"),
            Permission::WorkspaceRead
        );
        assert_eq!(
            permission_for_tool("workspace.storage_set"),
            Permission::SystemChange
        );
        assert_eq!(
            permission_for_tool("workspace.scan_machine"),
            Permission::ExternalPath
        );
        assert_eq!(
            permission_for_tool("workspace.migration_apply"),
            Permission::ExternalPath
        );
        assert_eq!(
            permission_for_tool("workspace.offsite_backup_set"),
            Permission::ExternalPath
        );
    }
}
