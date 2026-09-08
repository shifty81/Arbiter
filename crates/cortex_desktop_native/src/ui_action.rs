//! Platform-neutral Cortex desktop UI actions.
//!
//! Native window procedures translate HWND/control events into these actions.
//! One dispatcher consumes the action, which prevents Win32 match arms from
//! leaking heterogeneous domain return types such as `bool` or `Result`.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UiPanel {
    Files,
    Changes,
    Memory,
    Artifacts,
    Tasks,
    Settings,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UiAction {
    ActivateWorkspace(usize),
    SelectConversation(usize),
    NewChat,
    ArchiveConversation,
    RefreshProject,
    RebuildContextIndex,
    CopyText(String),
    CopyPath(String),
    RateMessage { message_id: String, score: i8 },
    Regenerate { message_id: String },
    OpenWorkbenchFile(String),
    FocusAddProject,
    OpenSettings,
    OpenCommandPalette,
    ShowPanel(UiPanel),
    ShowChat,
    ShowWorkbench,
    ShowVault,
    ToggleProjectSidebar,
    ToggleContextPanel,
    RunBuild,
    ProviderStatus,
    ScanLibrary,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ui_actions_are_typed_and_payload_preserving() {
        assert_eq!(UiAction::NewChat, UiAction::NewChat);
        assert_eq!(UiAction::ShowVault, UiAction::ShowVault);
        assert_eq!(
            UiAction::RateMessage {
                message_id: "message-1".into(),
                score: 1,
            },
            UiAction::RateMessage {
                message_id: "message-1".into(),
                score: 1,
            }
        );
        assert_ne!(
            UiAction::ShowPanel(UiPanel::Files),
            UiAction::ShowPanel(UiPanel::Changes)
        );
    }
}
