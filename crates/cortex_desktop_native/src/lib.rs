//! Dependency-light native desktop shell for Cortex.
//!
//! Windows uses Win32 controls directly. Other targets provide a small
//! headless fallback so the shared workspace can still be checked elsewhere.

pub use cortex_protocol::{CortexStreamEvent, CortexStreamKind};

mod ui;
mod ui_action;
pub use ui::{
    chat_scroll_policy, code_language_label, code_lines, parse_unified_diff,
    validate_shell_profiles, validate_sidebar_context_profiles, Axis, CommandMatch, CommandPalette,
    ContextPanelLayout, DiffRowKind, DiffView, FocusRing, Insets, KeyIntent, LayoutConstraints,
    LayoutNode, LayoutRect, LayoutSize, ScrollAnchor, ScrollStickiness, ShellLayout,
    ShellLayoutInput, SidebarLayout, SmoothScrollController, UiAcceptanceIssue,
    UiAcceptanceProfile, UiAcceptanceReport, UiCommand, UiDensity, UiScale, UiTheme, VirtualList,
    VirtualListItem, VirtualListWindow, WidgetId, WidgetKind, WidgetState, WorkbenchDocument,
    WorkbenchState,
};
pub use ui_action::{UiAction, UiPanel};

#[derive(Clone, Debug, Default)]
pub struct DesktopChatBlock {
    pub message_id: String,
    pub role: String,
    pub label: String,
    pub text: String,
    pub kind: String,
    pub path: String,
    pub language: String,
    pub status: String,
    pub created_unix_ms: u128,
    pub feedback_score: i8,
    pub revision: u32,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopWorkbenchDocument {
    pub path: String,
    pub language: String,
    pub content: String,
    pub bytes: u64,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopFileEntry {
    pub name: String,
    pub relative_path: String,
    pub is_directory: bool,
    pub bytes: u64,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopFileListing {
    pub scope: String,
    pub root: String,
    pub current: String,
    pub entries: Vec<DesktopFileEntry>,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopLibraryView {
    pub summary: String,
    pub projects: Vec<String>,
    pub lineage: Vec<String>,
    pub storage: Vec<String>,
    pub inbox: Vec<String>,
    pub plans: Vec<String>,
    pub recovery: Vec<String>,
    pub scan_ready: bool,
    pub truncated: bool,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopConfigSnapshot {
    pub library_root: String,
    pub offsite_backup_root: String,
    pub storage_identity: String,
    pub service_port: u16,
    pub auto_start_service: bool,
    pub provider: String,
    pub native_model_host_port: u16,
    pub native_auto_bootstrap: bool,
    pub native_models_max: u8,
    pub lmstudio_auto_start: bool,
    pub lmstudio_url: String,
    pub comfyui_url: String,
    pub chat_model: String,
    pub tool_model: String,
    pub vision_model: String,
    pub embedding_model: String,
    pub theme: String,
    pub compact_tool_cards: bool,
}

#[derive(Clone, Debug, Default)]
pub struct DesktopSnapshot {
    pub workspace_title: String,
    pub workspaces: Vec<String>,
    pub active_workspace: Option<usize>,
    pub conversations: Vec<String>,
    pub active_conversation: Option<usize>,
    pub conversation_title: String,
    pub transcript: String,
    pub chat_blocks: Vec<DesktopChatBlock>,
    pub library: DesktopLibraryView,
    pub info: String,
    pub activity: String,
    pub jobs: String,
    pub build: String,
    pub git: String,
    pub vault_activity: String,
    pub system_activity: String,
    pub native_model_log_root: String,
    pub notifications: String,
    pub status: String,
    pub provider_recovery_pending: bool,
}

// O2D-R051N9STOR1J_NATIVE_ADAPTER_CONTRACT_REBASE
pub trait DesktopWorker: Send {
    fn send_message_stream(
        &mut self,
        text: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<(), String>;
    fn run_agent(&mut self, mode: &str, prompt: &str) -> Result<(), String>;
    fn run_agent_stream(
        &mut self,
        mode: &str,
        prompt: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<(), String>;
    fn show_provider_status(&mut self) -> Result<(), String>;
    fn refresh_repository_provider(&mut self) -> Result<(), String>;
    fn refresh_repository_vault_audit(&mut self) -> Result<(), String>;
    fn create_repository_safety_checkpoint(&mut self) -> Result<(), String>;
    fn push_repository_local(&mut self) -> Result<(), String>;
    fn run_build_check(&mut self) -> Result<(), String>;
    fn rebuild_context_index(&mut self) -> Result<(), String>;
    fn ingest_paths(&mut self, paths: &[String]) -> Result<(), String>;
    fn scan_library(&mut self) -> Result<(), String>;
    fn scan_storage_catalog_preview(
        &mut self,
        should_cancel: &mut dyn FnMut() -> bool,
    ) -> Result<(), String>;
    fn scan_machine_catalog_preview(
        &mut self,
        include_removable: bool,
        should_cancel: &mut dyn FnMut() -> bool,
    ) -> Result<(), String>;
    fn redo_message(&mut self, message_id: &str, instructions: &str) -> Result<(), String>;
    fn persist_state(&mut self) -> Result<(), String>;
}

pub trait DesktopHost {
    fn snapshot(&mut self) -> DesktopSnapshot;
    fn attach_workspace(&mut self, path: &str) -> Result<(), String>;
    fn set_library_root(&mut self, path: &str) -> Result<(), String>;
    fn config_snapshot(&mut self) -> Result<DesktopConfigSnapshot, String>;
    fn set_config_value(&mut self, key: &str, value: &str) -> Result<(), String>;
    fn scan_library(&mut self) -> Result<(), String>;
    fn rate_message(&mut self, message_id: &str, score: i8) -> Result<(), String>;
    fn record_error_message(&mut self, context: &str, error: &str) -> Result<(), String>;
    fn switch_workspace(&mut self, index: usize) -> Result<(), String>;
    fn new_conversation(&mut self) -> Result<(), String>;
    fn archive_conversation(&mut self) -> Result<(), String>;
    fn select_conversation(&mut self, index: usize) -> Result<(), String>;
    fn export_conversation(&mut self, index: usize, format: &str) -> Result<String, String>;
    fn export_project_conversations(&mut self, format: &str) -> Result<String, String>;
    fn cancel_pending_request(&mut self) -> Result<bool, String>;
    fn cancel_active_request(&mut self) -> Result<bool, String>;
    fn send_message(&mut self, text: &str) -> Result<(), String>;
    fn send_message_stream(
        &mut self,
        text: &str,
        on_event: &mut dyn FnMut(CortexStreamEvent),
    ) -> Result<(), String>;
    fn show_files(&mut self, query: &str) -> Result<(), String>;
    fn browse_files(
        &mut self,
        library_scope: bool,
        relative_directory: &str,
    ) -> Result<DesktopFileListing, String>;
    fn open_workbench_file(
        &mut self,
        relative_path: &str,
    ) -> Result<DesktopWorkbenchDocument, String>;
    fn show_changes(&mut self) -> Result<(), String>;
    fn search_vault(&mut self, query: &str) -> Result<(), String>;
    fn show_artifacts(&mut self) -> Result<(), String>;
    fn show_tasks(&mut self) -> Result<(), String>;
    fn show_settings(&mut self) -> Result<(), String>;
    fn show_provider_status(&mut self) -> Result<(), String>;
    fn probe_provider(&mut self) -> Result<(), String>;
    fn run_build_check(&mut self) -> Result<(), String>;
    fn rebuild_context_index(&mut self) -> Result<(), String>;
    fn show_context_index(&mut self) -> Result<(), String>;
    fn run_agent(&mut self, mode: &str, prompt: &str) -> Result<(), String>;
    fn spawn_worker(&mut self) -> Result<Box<dyn DesktopWorker>, String>;
    fn refresh(&mut self) -> Result<(), String>;
}

#[cfg(windows)]
pub fn run(host: impl DesktopHost + Send + 'static) -> Result<(), String> {
    windows::run(Box::new(host))
}

#[cfg(not(windows))]
pub fn run(mut host: impl DesktopHost + Send + 'static) -> Result<(), String> {
    let snapshot = host.snapshot();
    println!("Cortex Desktop native shell is available on Windows.");
    println!("Workspace: {}", snapshot.workspace_title);
    println!("Conversations: {}", snapshot.conversations.len());
    Ok(())
}

#[cfg(windows)]
mod windows {
    use super::{
        chat_scroll_policy, code_language_label, code_lines, parse_unified_diff, CommandPalette,
        ContextPanelLayout, CortexStreamEvent, CortexStreamKind, DesktopChatBlock,
        DesktopFileListing, DesktopHost, DesktopSnapshot, DesktopWorkbenchDocument, DesktopWorker,
        DiffRowKind, DiffView, LayoutSize, ScrollStickiness, ShellLayout, ShellLayoutInput,
        SidebarLayout, SmoothScrollController, UiAction, UiCommand, UiPanel, UiTheme, VirtualList,
        VirtualListItem,
    };
    use std::collections::{hash_map::DefaultHasher, VecDeque};
    use std::env;
    use std::ffi::c_void;
    use std::hash::{Hash, Hasher};
    use std::fs::OpenOptions;
    use std::io::{BufRead, BufReader, Write};
    use std::path::PathBuf;
    use std::process::{Child, Command, Stdio};
    use std::ptr::{null, null_mut};
    use std::sync::atomic::{AtomicBool, AtomicI32, AtomicU64, AtomicUsize, Ordering};
    use std::sync::{Mutex, OnceLock};
    use std::thread;
    use std::time::{Duration, Instant};

    type Hwnd = *mut c_void;
    type Hinstance = *mut c_void;
    type Hmenu = *mut c_void;
    type Hcursor = *mut c_void;
    type Hbrush = *mut c_void;
    type Hicon = *mut c_void;
    type Hdrop = *mut c_void;
    type Hdc = *mut c_void;
    type Lresult = isize;
    type Wparam = usize;
    type Lparam = isize;

    const WS_OVERLAPPEDWINDOW: u32 = 0x00CF0000;
    const WS_CLIPCHILDREN: u32 = 0x02000000;
    const WS_CLIPSIBLINGS: u32 = 0x04000000;
    const WS_VISIBLE: u32 = 0x10000000;
    const WS_CHILD: u32 = 0x40000000;
    const WS_BORDER: u32 = 0x00800000;
    const WS_VSCROLL: u32 = 0x00200000;
    const SS_NOTIFY: u32 = 0x00000100;
    const WS_TABSTOP: u32 = 0x00010000;
    const ES_MULTILINE: u32 = 0x0004;
    const ES_AUTOVSCROLL: u32 = 0x0040;
    const ES_AUTOHSCROLL: u32 = 0x0080;
    const ES_READONLY: u32 = 0x0800;
    const ES_WANTRETURN: u32 = 0x1000;
    const LBS_NOTIFY: u32 = 0x0001;
    const LBS_OWNERDRAWVARIABLE: u32 = 0x0020;
    const LBS_HASSTRINGS: u32 = 0x0040;
    const LBS_NOINTEGRALHEIGHT: u32 = 0x0100;
    const BS_PUSHBUTTON: u32 = 0;
    const BS_OWNERDRAW: u32 = 0x0000000B;
    const SW_HIDE: i32 = 0;
    const SW_SHOW: i32 = 5;
    const CW_USEDEFAULT: i32 = 0x80000000_u32 as i32;

    const WM_CREATE: u32 = 0x0001;
    const WM_DESTROY: u32 = 0x0002;
    const WM_SIZE: u32 = 0x0005;
    const WM_CLOSE: u32 = 0x0010;
    const WM_ERASEBKGND: u32 = 0x0014;
    const WM_PAINT: u32 = 0x000F;
    const WM_MOUSEWHEEL: u32 = 0x020A;
    const WM_LBUTTONDOWN: u32 = 0x0201;
    const WM_LBUTTONUP: u32 = 0x0202;
    const WM_CONTEXTMENU: u32 = 0x007B;
    const WM_DRAWITEM: u32 = 0x002B;
    const WM_COMMAND: u32 = 0x0111;
    const WM_VSCROLL: u32 = 0x0115;
    const WM_DROPFILES: u32 = 0x0233;
    const SB_LINEUP: usize = 0;
    const SB_LINEDOWN: usize = 1;
    const SB_PAGEUP: usize = 2;
    const SB_PAGEDOWN: usize = 3;
    const SB_THUMBPOSITION: usize = 4;
    const SB_THUMBTRACK: usize = 5;
    const SB_TOP: usize = 6;
    const SB_BOTTOM: usize = 7;
    const SB_VERT: i32 = 1;
    const WM_CTLCOLOREDIT: u32 = 0x0133;
    const WM_CTLCOLORLISTBOX: u32 = 0x0134;
    const WM_CTLCOLORBTN: u32 = 0x0135;
    const WM_CTLCOLORSCROLLBAR: u32 = 0x0137;
    const WM_CTLCOLORSTATIC: u32 = 0x0138;
    const WM_KEYDOWN: u32 = 0x0100;
    const EM_SETCUEBANNER: u32 = 0x1501;
    const EM_REPLACESEL: u32 = 0x00C2;
    const WM_SETFONT: u32 = 0x0030;
    const WM_ASYNC_COMPLETE: u32 = 0x8001;
    const WM_ASYNC_PROGRESS: u32 = 0x8002;
    const WM_LMSTUDIO_LOG: u32 = 0x8004;
    const WM_THINKING_TICK: u32 = 0x8005;
    const WM_SCROLL_TICK: u32 = 0x8006;

    const LB_ADDSTRING: u32 = 0x0180;
    const LB_RESETCONTENT: u32 = 0x0184;
    const LB_SETCURSEL: u32 = 0x0186;
    const LB_GETCURSEL: u32 = 0x0188;
    const LB_GETTEXT: u32 = 0x0189;
    const LB_GETTEXTLEN: u32 = 0x018A;
    const LB_SETITEMHEIGHT: u32 = 0x01A0;
    const LB_ITEMFROMPOINT: u32 = 0x01A9;
    const LBN_SELCHANGE: u16 = 1;
    const LBN_DBLCLK: u16 = 2;
    const EN_CHANGE: u16 = 0x0300;
    const EM_SETSEL: u32 = 0x00B1;
    const EM_SCROLLCARET: u32 = 0x00B7;

    const GWLP_WNDPROC: i32 = -4;
    const VK_RETURN: usize = 0x0D;
    const VK_ESCAPE: usize = 0x1B;
    const VK_UP: usize = 0x26;
    const VK_DOWN: usize = 0x28;
    const VK_SHIFT: i32 = 0x10;
    const VK_CONTROL: i32 = 0x11;
    const VK_K: usize = 0x4B;
    const VK_P: usize = 0x50;
    const VK_F10: usize = 0x79;
    const VK_APPS: usize = 0x5D;

    const IDC_ARROW: *const u16 = 32512usize as *const u16;

    // COLORREF uses 0x00BBGGRR. These neutral values are symmetrical enough
    // to remain readable regardless of channel ordering.
    const DARK_BACKGROUND: u32 = 0x001E1E1E;
    const DARK_SURFACE: u32 = 0x002B2B2B;
    const DARK_SURFACE_PRESSED: u32 = 0x00373737;
    const DARK_FIELD: u32 = 0x00181818;
    const DARK_BORDER: u32 = 0x004A4A4A;
    const DARK_TEXT: u32 = 0x00E8E8E8;
    const DARK_TEXT_DISABLED: u32 = 0x00808080;
    const DARK_ACCENT: u32 = 0x00D58B5A;
    const DARK_ACCENT_SOFT: u32 = 0x004B352A;
    const DIFF_ADD_BG: u32 = 0x00253A29;
    const DIFF_REMOVE_BG: u32 = 0x003A2529;
    const ODS_SELECTED: u32 = 0x0001;
    const ODS_DISABLED: u32 = 0x0004;
    const DT_CENTER: u32 = 0x0001;
    const DT_VCENTER: u32 = 0x0004;
    const DT_SINGLELINE: u32 = 0x0020;
    const DT_WORDBREAK: u32 = 0x0010;
    const DT_EXPANDTABS: u32 = 0x0040;
    const DT_CALCRECT: u32 = 0x0400;
    const DT_NOPREFIX: u32 = 0x0800;
    const TRANSPARENT: i32 = 1;
    const SRCCOPY: u32 = 0x00CC0020;
    const MF_STRING: u32 = 0x0000;
    const MF_GRAYED: u32 = 0x0001;
    const MF_SEPARATOR: u32 = 0x0800;
    const TPM_RIGHTBUTTON: u32 = 0x0002;
    const TPM_RETURNCMD: u32 = 0x0100;
    const CF_UNICODETEXT: u32 = 13;
    const GMEM_MOVEABLE: u32 = 0x0002;

    const ID_CONVERSATIONS: i32 = 200;
    const ID_NEW_CHAT: i32 = 201;
    const ID_TRANSCRIPT: i32 = 202;
    const ID_INPUT: i32 = 203;
    const ID_SEND: i32 = 204;
    const ID_INFO: i32 = 205;
    const ID_FILES: i32 = 206;
    const ID_CHANGES: i32 = 207;
    const ID_VAULT: i32 = 208;
    const ID_ARTIFACTS: i32 = 209;
    const ID_QUERY: i32 = 210;
    const ID_ACTIVITY: i32 = 211;
    const ID_BUILD: i32 = 212;
    const ID_REFRESH: i32 = 213;
    const ID_STATUS: i32 = 214;
    const ID_INSPECT: i32 = 215;
    const ID_PLAN: i32 = 216;
    const ID_APPLY: i32 = 217;
    const ID_REPAIR: i32 = 218;
    const ID_SETTINGS: i32 = 219;
    const ID_CONTEXT_INDEX: i32 = 220;
    const ID_CONTEXT_INDEX_STATUS: i32 = 221;
    const ID_PROVIDER: i32 = 222;
    const ID_CANCEL: i32 = 223;
    const ID_WORKSPACES: i32 = 224;
    const ID_WORKSPACE_PATH: i32 = 225;
    const ID_ATTACH_WORKSPACE: i32 = 226;
    const ID_TASKS: i32 = 227;
    const ID_ARCHIVE_CHAT: i32 = 228;
    const ID_TOGGLE_LEFT: i32 = 229;
    const ID_TOGGLE_RIGHT: i32 = 230;
    const ID_TOGGLE_ACTIVITY: i32 = 231;
    const ID_RIGHT_TITLE: i32 = 232;
    const ID_ACTIVITY_CORTEX_TAB: i32 = 233;
    const ID_ACTIVITY_LMSTUDIO_TAB: i32 = 234;
    const ID_THINKING_BUBBLE: i32 = 235;
    const ID_LIBRARY_ROOT: i32 = 236;
    const ID_LIBRARY_SCAN: i32 = 237;
    const ID_CONFIG_TAB_GENERAL: i32 = 238;
    const ID_CONFIG_TAB_LIBRARY: i32 = 239;
    const ID_CONFIG_TAB_PROVIDERS: i32 = 240;
    const ID_CONFIG_TAB_MODELS: i32 = 241;
    const ID_CONFIG_TAB_APPEARANCE: i32 = 242;
    const ID_CONFIG_LABEL_1: i32 = 243;
    const ID_CONFIG_LABEL_2: i32 = 244;
    const ID_CONFIG_LABEL_3: i32 = 245;
    const ID_CONFIG_LABEL_4: i32 = 246;
    const ID_CONFIG_EDIT_1: i32 = 247;
    const ID_CONFIG_EDIT_2: i32 = 248;
    const ID_CONFIG_EDIT_3: i32 = 249;
    const ID_CONFIG_EDIT_4: i32 = 250;
    const ID_CONFIG_APPLY: i32 = 251;
    const ID_CONFIG_SECONDARY: i32 = 252;
    const ID_REDO_INPUT: i32 = 253;
    const ID_REDO_APPLY: i32 = 254;
    const ID_REDO_CANCEL: i32 = 255;
    const ID_RAIL_PROJECTS: i32 = 256;
    const ID_RAIL_CHATS: i32 = 257;
    const ID_RAIL_FILES: i32 = 258;
    const ID_RAIL_ADD: i32 = 259;
    const ID_RAIL_CONFIG: i32 = 260;
    const ID_ACTIVITY_JOBS_TAB: i32 = 261;
    const ID_ACTIVITY_BUILD_TAB: i32 = 262;
    const ID_ACTIVITY_GIT_TAB: i32 = 263;
    const ID_ACTIVITY_NOTIFICATIONS_TAB: i32 = 264;
    const ID_FILE_SCOPE_PROJECT: i32 = 265;
    const ID_FILE_SCOPE_LIBRARY: i32 = 266;
    const ID_FILE_HOME: i32 = 267;
    const ID_FILE_UP: i32 = 268;
    const ID_FILE_PATH: i32 = 269;
    const ID_FILE_LIST: i32 = 270;
    const ID_LEFT_TITLE: i32 = 271;
    const ID_RIGHT_HEADER: i32 = 272;
    const ID_MODE_CHAT: i32 = 273;
    const ID_MODE_WORKBENCH: i32 = 274;
    const ID_WORKBENCH_TABS: i32 = 275;
    const ID_WORKBENCH_PATH: i32 = 276;
    const ID_WORKBENCH_EDITOR: i32 = 277;
    const ID_COMMAND_QUERY: i32 = 278;
    const ID_COMMAND_LIST: i32 = 279;
    const ID_COMMAND_HINT: i32 = 280;

    const CMD_CTX_OPEN: u32 = 700;
    const CMD_CTX_NEW_CHAT: u32 = 701;
    const CMD_CTX_REFRESH: u32 = 702;
    const CMD_CTX_INDEX: u32 = 703;
    const CMD_CTX_COPY: u32 = 704;
    const CMD_CTX_ARCHIVE: u32 = 705;
    const CMD_CTX_UPVOTE: u32 = 706;
    const CMD_CTX_DOWNVOTE: u32 = 707;
    const CMD_CTX_REGENERATE: u32 = 708;
    const CMD_CTX_OPEN_WORKBENCH: u32 = 709;
    const CMD_CTX_COPY_PATH: u32 = 710;
    const CMD_CTX_NEW_PROJECT: u32 = 711;
    const CMD_CTX_SETTINGS: u32 = 712;
    const CMD_CTX_COMMANDS: u32 = 713;
    const CMD_CTX_EXPORT_CHAT_TXT: u32 = 714;
    const CMD_CTX_EXPORT_CHAT_MARKDOWN: u32 = 715;
    const CMD_CTX_EXPORT_CHAT_JSON: u32 = 716;
    const CMD_CTX_EXPORT_PROJECT_MARKDOWN: u32 = 717;

    static HOST: OnceLock<Mutex<Box<dyn DesktopHost + Send>>> = OnceLock::new();
    static ASYNC_RESULT: OnceLock<Mutex<Option<AsyncCompletion>>> = OnceLock::new();
    static ASYNC_PROGRESS: OnceLock<Mutex<Vec<CortexStreamEvent>>> = OnceLock::new();
    static ASYNC_STREAM_TEXT: OnceLock<Mutex<String>> = OnceLock::new();
    static ASYNC_BUSY: AtomicBool = AtomicBool::new(false);
    static ASYNC_CANCEL_REQUESTED: AtomicBool = AtomicBool::new(false);
    static CLOSE_WHEN_IDLE: AtomicBool = AtomicBool::new(false);
    static ACTIVE_RIGHT_PANE: AtomicUsize = AtomicUsize::new(ID_FILES as usize);
    static ACTIVE_ACTIVITY_PANE: AtomicUsize = AtomicUsize::new(ID_ACTIVITY_CORTEX_TAB as usize);
    static LEFT_COLLAPSED: AtomicBool = AtomicBool::new(false);
    static RIGHT_COLLAPSED: AtomicBool = AtomicBool::new(true);
    static ACTIVITY_EXPANDED: AtomicBool = AtomicBool::new(false);
    static EXPANDED_WORKSPACE: AtomicUsize = AtomicUsize::new(usize::MAX);
    static LAST_ACTIVE_WORKSPACE: AtomicUsize = AtomicUsize::new(usize::MAX);
    static LAST_CHAT_SIGNATURE: AtomicU64 = AtomicU64::new(0);
    static CORTEX_ACTIVITY_TEXT: OnceLock<Mutex<String>> = OnceLock::new();
    static LMSTUDIO_LOG_LINES: OnceLock<Mutex<VecDeque<String>>> = OnceLock::new();
    static LMSTUDIO_LOG_PENDING: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
    static LMSTUDIO_LOG_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
    static LMSTUDIO_LOG_RUNNING: AtomicBool = AtomicBool::new(false);
    static WORK_QUEUE: OnceLock<Mutex<VecDeque<QueuedWork>>> = OnceLock::new();
    static ACTIVE_WORK_LABEL: OnceLock<Mutex<String>> = OnceLock::new();
    // O2D-R051N9STOR1J_H33_DUPLICATE_REQUEST_GUARD
    // The semantic work key lets the native shell reject accidental duplicate
    // submissions without disabling intentional queueing of distinct requests.
    static ACTIVE_WORK_KEY: OnceLock<Mutex<String>> = OnceLock::new();
    static UI_TICKER_RUNNING: AtomicBool = AtomicBool::new(false);
    static THINKING_FRAME: AtomicUsize = AtomicUsize::new(0);
    static CONFIG_TAB: AtomicUsize = AtomicUsize::new(0);
    static NAV_ROWS: OnceLock<Mutex<Vec<NavRow>>> = OnceLock::new();
    static CHAT_CARD_BLOCKS: OnceLock<Mutex<Vec<DesktopChatBlock>>> = OnceLock::new();
    static CHAT_LAYOUT_CACHE: OnceLock<Mutex<ChatLayoutCache>> = OnceLock::new();
    static CHAT_LAYOUT_DIRTY: AtomicBool = AtomicBool::new(true);
    static CHAT_BACKBUFFER: OnceLock<Mutex<ChatBackBuffer>> = OnceLock::new();
    static CHAT_NORMAL_FONT: OnceLock<usize> = OnceLock::new();
    static CHAT_LABEL_FONT: OnceLock<usize> = OnceLock::new();
    static CHAT_CODE_FONT: OnceLock<usize> = OnceLock::new();
    static FLUENT_ICON_FONT: OnceLock<usize> = OnceLock::new();
    static CHAT_SCROLL: OnceLock<Mutex<SmoothScrollController>> = OnceLock::new();
    static CHAT_FOLLOW_END: AtomicBool = AtomicBool::new(true);
    static CHAT_SCROLL_TICKER_RUNNING: AtomicBool = AtomicBool::new(false);
    static CHAT_CONTENT_HEIGHT: AtomicI32 = AtomicI32::new(0);
    static CHAT_ACTION_REGIONS: OnceLock<Mutex<Vec<ChatActionRegion>>> = OnceLock::new();
    static REDO_TARGET: OnceLock<Mutex<String>> = OnceLock::new();
    static REDO_ACTIVE: AtomicBool = AtomicBool::new(false);
    static FILE_BROWSER_LIBRARY_SCOPE: AtomicBool = AtomicBool::new(false);
    static FILE_BROWSER_LISTING: OnceLock<Mutex<DesktopFileListing>> = OnceLock::new();
    static WORKBENCH_ACTIVE: AtomicBool = AtomicBool::new(false);
    static WORKBENCH_DOCUMENTS: OnceLock<Mutex<Vec<DesktopWorkbenchDocument>>> = OnceLock::new();
    static WORKBENCH_ACTIVE_DOCUMENT: AtomicUsize = AtomicUsize::new(usize::MAX);
    static INPUT_PREV_PROC: OnceLock<isize> = OnceLock::new();
    static TRANSCRIPT_PREV_PROC: OnceLock<isize> = OnceLock::new();
    static COMMAND_PALETTE_VISIBLE: AtomicBool = AtomicBool::new(false);
    static COMMAND_PALETTE_RESULTS: OnceLock<Mutex<Vec<UiCommand>>> = OnceLock::new();
    static UI_FONT: OnceLock<usize> = OnceLock::new();
    static DARK_BACKGROUND_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_SURFACE_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_SURFACE_PRESSED_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_FIELD_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_BORDER_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_ACCENT_BRUSH: OnceLock<usize> = OnceLock::new();
    static DARK_ACCENT_SOFT_BRUSH: OnceLock<usize> = OnceLock::new();
    static DIFF_ADD_BRUSH: OnceLock<usize> = OnceLock::new();
    static DIFF_REMOVE_BRUSH: OnceLock<usize> = OnceLock::new();

    struct AsyncCompletion {
        result: Result<(), String>,
        clear_input: bool,
        cancel_requested: bool,
    }

    enum BackgroundAction {
        Chat(String),
        Agent {
            mode: String,
            prompt: String,
        },
        Provider,
        Build,
        Index,
        Ingest(Vec<String>),
        LibraryScan,
        Redo {
            message_id: String,
            instructions: String,
        },
    }

    #[derive(Clone, Copy)]
    enum ChatActionKind {
        Copy,
        Up,
        Down,
        Redo,
        CopyCode,
    }

    #[derive(Clone)]
    struct ChatActionRegion {
        rect: Rect,
        message_id: String,
        payload: String,
        current_score: i8,
        kind: ChatActionKind,
    }

    #[derive(Clone)]
    struct CachedChatCard {
        block: DesktopChatBlock,
        segments: Vec<MarkdownSegment>,
        segment_heights: Vec<i32>,
        file_header: String,
        label_height: i32,
        file_header_height: i32,
        diff: Option<DiffView>,
        top: i32,
        height: i32,
        x: i32,
        width: i32,
    }

    #[derive(Default)]
    struct ChatLayoutCache {
        viewport_width: i32,
        cards: Vec<CachedChatCard>,
        virtual_items: Vec<VirtualListItem>,
        content_height: i32,
    }

    #[derive(Default)]
    struct ChatBackBuffer {
        dc: usize,
        bitmap: usize,
        previous_bitmap: usize,
        width: i32,
        height: i32,
    }

    struct QueuedWork {
        worker: Box<dyn DesktopWorker>,
        action: BackgroundAction,
        label: String,
        target: String,
    }

    #[derive(Clone, Copy)]
    enum NavRow {
        Spacer,
        Workspace(usize),
        Conversation(usize),
    }

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Point {
        x: i32,
        y: i32,
    }

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Rect {
        left: i32,
        top: i32,
        right: i32,
        bottom: i32,
    }

    #[repr(C)]
    struct Msg {
        hwnd: Hwnd,
        message: u32,
        w_param: Wparam,
        l_param: Lparam,
        time: u32,
        pt: Point,
        l_private: u32,
    }

    #[repr(C)]
    struct WndClassW {
        style: u32,
        wnd_proc: Option<unsafe extern "system" fn(Hwnd, u32, Wparam, Lparam) -> Lresult>,
        cls_extra: i32,
        wnd_extra: i32,
        instance: Hinstance,
        icon: Hicon,
        cursor: Hcursor,
        background: Hbrush,
        menu_name: *const u16,
        class_name: *const u16,
    }

    #[repr(C)]
    struct PaintStruct {
        hdc: Hdc,
        erase: i32,
        paint: Rect,
        restore: i32,
        inc_update: i32,
        reserved: [u8; 32],
    }

    #[repr(C)]
    struct DrawItemStruct {
        _ctl_type: u32,
        ctl_id: u32,
        item_id: u32,
        _item_action: u32,
        item_state: u32,
        hwnd_item: Hwnd,
        hdc: Hdc,
        rc_item: Rect,
        _item_data: usize,
    }

    #[link(name = "shell32")]
    extern "system" {
        fn DragAcceptFiles(hwnd: Hwnd, accept: i32);
        fn DragQueryFileW(drop: Hdrop, file: u32, buffer: *mut u16, length: u32) -> u32;
        fn DragFinish(drop: Hdrop);
    }

    #[link(name = "user32")]
    extern "system" {
        fn RegisterClassW(class: *const WndClassW) -> u16;
        fn CreateWindowExW(
            ex_style: u32,
            class_name: *const u16,
            window_name: *const u16,
            style: u32,
            x: i32,
            y: i32,
            width: i32,
            height: i32,
            parent: Hwnd,
            menu: Hmenu,
            instance: Hinstance,
            param: *mut c_void,
        ) -> Hwnd;
        fn DefWindowProcW(hwnd: Hwnd, message: u32, w_param: Wparam, l_param: Lparam) -> Lresult;
        fn ShowWindow(hwnd: Hwnd, command: i32) -> i32;
        fn UpdateWindow(hwnd: Hwnd) -> i32;
        fn GetMessageW(message: *mut Msg, hwnd: Hwnd, min: u32, max: u32) -> i32;
        fn TranslateMessage(message: *const Msg) -> i32;
        fn DispatchMessageW(message: *const Msg) -> Lresult;
        fn PostQuitMessage(exit_code: i32);
        fn GetClientRect(hwnd: Hwnd, rect: *mut Rect) -> i32;
        fn MoveWindow(hwnd: Hwnd, x: i32, y: i32, width: i32, height: i32, repaint: i32) -> i32;
        fn InvalidateRect(hwnd: Hwnd, rect: *const Rect, erase: i32) -> i32;
        fn GetDlgItem(hwnd: Hwnd, id: i32) -> Hwnd;
        fn GetDlgCtrlID(hwnd: Hwnd) -> i32;
        fn SendMessageW(hwnd: Hwnd, message: u32, w_param: Wparam, l_param: Lparam) -> Lresult;
        fn SetWindowTextW(hwnd: Hwnd, text: *const u16) -> i32;
        fn GetWindowTextLengthW(hwnd: Hwnd) -> i32;
        fn GetWindowTextW(hwnd: Hwnd, buffer: *mut u16, max_count: i32) -> i32;
        fn LoadCursorW(instance: Hinstance, cursor_name: *const u16) -> Hcursor;
        fn MessageBoxW(hwnd: Hwnd, text: *const u16, caption: *const u16, kind: u32) -> i32;
        fn PostMessageW(hwnd: Hwnd, message: u32, w_param: Wparam, l_param: Lparam) -> i32;
        fn EnableWindow(hwnd: Hwnd, enable: i32) -> i32;
        fn SetFocus(hwnd: Hwnd) -> Hwnd;
        fn GetParent(hwnd: Hwnd) -> Hwnd;
        fn GetKeyState(virtual_key: i32) -> i16;
        fn GetCursorPos(point: *mut Point) -> i32;
        fn ScreenToClient(hwnd: Hwnd, point: *mut Point) -> i32;
        fn CreatePopupMenu() -> Hmenu;
        fn AppendMenuW(menu: Hmenu, flags: u32, item: usize, text: *const u16) -> i32;
        fn TrackPopupMenuEx(
            menu: Hmenu,
            flags: u32,
            x: i32,
            y: i32,
            hwnd: Hwnd,
            params: *const c_void,
        ) -> u32;
        fn DestroyMenu(menu: Hmenu) -> i32;
        fn OpenClipboard(hwnd: Hwnd) -> i32;
        fn EmptyClipboard() -> i32;
        fn SetClipboardData(format: u32, memory: *mut c_void) -> *mut c_void;
        fn CloseClipboard() -> i32;
        fn DestroyWindow(hwnd: Hwnd) -> i32;
        fn FillRect(hdc: Hdc, rect: *const Rect, brush: Hbrush) -> i32;
        fn FrameRect(hdc: Hdc, rect: *const Rect, brush: Hbrush) -> i32;
        fn DrawTextW(hdc: Hdc, text: *const u16, count: i32, rect: *mut Rect, format: u32) -> i32;
        fn BeginPaint(hwnd: Hwnd, paint: *mut PaintStruct) -> Hdc;
        fn EndPaint(hwnd: Hwnd, paint: *const PaintStruct) -> i32;
        fn SetScrollRange(hwnd: Hwnd, bar: i32, min: i32, max: i32, redraw: i32) -> i32;
        fn SetScrollPos(hwnd: Hwnd, bar: i32, pos: i32, redraw: i32) -> i32;
        fn SetWindowLongPtrW(hwnd: Hwnd, index: i32, new_long: isize) -> isize;
        fn CallWindowProcW(
            previous: isize,
            hwnd: Hwnd,
            message: u32,
            w_param: Wparam,
            l_param: Lparam,
        ) -> Lresult;
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleW(module_name: *const u16) -> Hinstance;
        fn LoadLibraryW(module_name: *const u16) -> Hinstance;
        fn GlobalAlloc(flags: u32, bytes: usize) -> *mut c_void;
        fn GlobalLock(memory: *mut c_void) -> *mut c_void;
        fn GlobalUnlock(memory: *mut c_void) -> i32;
        fn GlobalFree(memory: *mut c_void) -> *mut c_void;
    }

    #[link(name = "gdi32")]
    extern "system" {
        fn CreateSolidBrush(color: u32) -> Hbrush;
        fn CreateCompatibleDC(hdc: Hdc) -> Hdc;
        fn DeleteDC(hdc: Hdc) -> i32;
        fn CreateCompatibleBitmap(hdc: Hdc, width: i32, height: i32) -> *mut c_void;
        fn BitBlt(
            destination: Hdc,
            x: i32,
            y: i32,
            width: i32,
            height: i32,
            source: Hdc,
            source_x: i32,
            source_y: i32,
            raster_operation: u32,
        ) -> i32;
        fn SetTextColor(hdc: Hdc, color: u32) -> u32;
        fn SetBkColor(hdc: Hdc, color: u32) -> u32;
        fn SetBkMode(hdc: Hdc, mode: i32) -> i32;
        fn CreateFontW(
            height: i32,
            width: i32,
            escapement: i32,
            orientation: i32,
            weight: i32,
            italic: u32,
            underline: u32,
            strike_out: u32,
            char_set: u32,
            out_precision: u32,
            clip_precision: u32,
            quality: u32,
            pitch_and_family: u32,
            face: *const u16,
        ) -> *mut c_void;
        fn SelectObject(hdc: Hdc, object: *mut c_void) -> *mut c_void;
        fn DeleteObject(object: *mut c_void) -> i32;
        fn CreateRoundRectRgn(
            left: i32,
            top: i32,
            right: i32,
            bottom: i32,
            width: i32,
            height: i32,
        ) -> *mut c_void;
        fn FillRgn(hdc: Hdc, region: *mut c_void, brush: Hbrush) -> i32;
        fn FrameRgn(hdc: Hdc, region: *mut c_void, brush: Hbrush, width: i32, height: i32) -> i32;
        fn Polygon(hdc: Hdc, points: *const Point, count: i32) -> i32;
    }

    #[link(name = "dwmapi")]
    extern "system" {
        fn DwmSetWindowAttribute(
            hwnd: Hwnd,
            attribute: u32,
            value: *const c_void,
            value_size: u32,
        ) -> i32;
    }

    #[link(name = "uxtheme")]
    extern "system" {
        fn SetWindowTheme(hwnd: Hwnd, app_name: *const u16, id_list: *const u16) -> i32;
    }

    fn solid_brush(slot: &OnceLock<usize>, color: u32) -> Hbrush {
        *slot.get_or_init(|| unsafe { CreateSolidBrush(color) as usize }) as Hbrush
    }

    fn background_brush() -> Hbrush {
        solid_brush(&DARK_BACKGROUND_BRUSH, DARK_BACKGROUND)
    }

    fn surface_brush() -> Hbrush {
        solid_brush(&DARK_SURFACE_BRUSH, DARK_SURFACE)
    }

    fn pressed_surface_brush() -> Hbrush {
        solid_brush(&DARK_SURFACE_PRESSED_BRUSH, DARK_SURFACE_PRESSED)
    }

    fn border_brush() -> Hbrush {
        solid_brush(&DARK_BORDER_BRUSH, DARK_BORDER)
    }

    fn accent_brush() -> Hbrush {
        solid_brush(&DARK_ACCENT_BRUSH, DARK_ACCENT)
    }

    fn accent_soft_brush() -> Hbrush {
        solid_brush(&DARK_ACCENT_SOFT_BRUSH, DARK_ACCENT_SOFT)
    }

    fn field_brush() -> Hbrush {
        solid_brush(&DARK_FIELD_BRUSH, DARK_FIELD)
    }

    fn diff_add_brush() -> Hbrush {
        solid_brush(&DIFF_ADD_BRUSH, DIFF_ADD_BG)
    }

    fn diff_remove_brush() -> Hbrush {
        solid_brush(&DIFF_REMOVE_BRUSH, DIFF_REMOVE_BG)
    }

    unsafe fn apply_dark_title_bar(hwnd: Hwnd) {
        let enabled: i32 = 1;
        let value = &enabled as *const i32 as *const c_void;
        let size = std::mem::size_of::<i32>() as u32;
        // Windows 11/current Windows 10 use attribute 20. Some older Windows 10
        // builds expose the same setting as 19. Failure is harmless.
        if DwmSetWindowAttribute(hwnd, 20, value, size) != 0 {
            let _ = DwmSetWindowAttribute(hwnd, 19, value, size);
        }
    }

    pub fn run(host: Box<dyn DesktopHost + Send>) -> Result<(), String> {
        HOST.set(Mutex::new(host))
            .map_err(|_| "Cortex desktop host already initialized".to_string())?;

        unsafe {
            let rich_edit = wide("Msftedit.dll");
            let _ = LoadLibraryW(rich_edit.as_ptr());

            let instance = GetModuleHandleW(null());
            if instance.is_null() {
                return Err("GetModuleHandleW failed".into());
            }
            let class_name = wide("CortexDesktopWindow");
            let title = wide("Cortex");
            let class = WndClassW {
                style: 0,
                wnd_proc: Some(window_proc),
                cls_extra: 0,
                wnd_extra: 0,
                instance,
                icon: null_mut(),
                cursor: LoadCursorW(null_mut(), IDC_ARROW),
                background: background_brush(),
                menu_name: null(),
                class_name: class_name.as_ptr(),
            };
            if RegisterClassW(&class) == 0 {
                return Err("RegisterClassW failed".into());
            }
            let hwnd = CreateWindowExW(
                0,
                class_name.as_ptr(),
                title.as_ptr(),
                WS_OVERLAPPEDWINDOW | WS_VISIBLE | WS_CLIPCHILDREN,
                CW_USEDEFAULT,
                CW_USEDEFAULT,
                1440,
                900,
                null_mut(),
                null_mut(),
                instance,
                null_mut(),
            );
            if hwnd.is_null() {
                return Err("CreateWindowExW failed".into());
            }
            apply_dark_title_bar(hwnd);
            ShowWindow(hwnd, SW_SHOW);
            UpdateWindow(hwnd);

            let mut message = std::mem::zeroed::<Msg>();
            loop {
                let result = GetMessageW(&mut message, null_mut(), 0, 0);
                if result == -1 {
                    return Err("GetMessageW failed".into());
                }
                if result == 0 {
                    break;
                }
                if handle_global_shortcut(hwnd, &message) {
                    continue;
                }
                TranslateMessage(&message);
                let dispatch_started = Instant::now();
                DispatchMessageW(&message);
                let dispatch_elapsed = dispatch_started.elapsed();
                if dispatch_elapsed >= Duration::from_millis(100) {
                    record_ui_blocking_boundary(
                        "DispatchMessageW",
                        dispatch_elapsed,
                        &format!(
                            "message=0x{:04X} w_param={} l_param={}",
                            message.message, message.w_param, message.l_param
                        ),
                    );
                }
            }
        }
        Ok(())
    }

    unsafe extern "system" fn window_proc(
        hwnd: Hwnd,
        message: u32,
        w_param: Wparam,
        l_param: Lparam,
    ) -> Lresult {
        match message {
            WM_CREATE => {
                create_controls(hwnd);
                layout(hwnd);
                refresh(hwnd);
                DragAcceptFiles(hwnd, 1);
                start_ui_ticker(hwnd);
                0
            }
            WM_SIZE => {
                layout(hwnd);
                0
            }
            WM_MOUSEWHEEL => {
                let transcript = GetDlgItem(hwnd, ID_TRANSCRIPT);
                if !transcript.is_null() {
                    SendMessageW(transcript, WM_MOUSEWHEEL, w_param, l_param);
                    0
                } else {
                    DefWindowProcW(hwnd, message, w_param, l_param)
                }
            }
            WM_ASYNC_COMPLETE => {
                complete_async(hwnd);
                0
            }
            WM_ASYNC_PROGRESS => {
                apply_async_progress(hwnd);
                0
            }
            WM_LMSTUDIO_LOG => {
                append_pending_lmstudio_activity(hwnd);
                0
            }
            WM_THINKING_TICK => {
                update_thinking_bubble(hwnd);
                0
            }
            WM_DROPFILES => {
                let drop = w_param as Hdrop;
                let count = DragQueryFileW(drop, u32::MAX, null_mut(), 0);
                let mut paths = Vec::new();
                for index in 0..count.min(32) {
                    let length = DragQueryFileW(drop, index, null_mut(), 0);
                    if length == 0 {
                        continue;
                    }
                    let mut buffer = vec![0_u16; length as usize + 1];
                    if DragQueryFileW(drop, index, buffer.as_mut_ptr(), buffer.len() as u32) > 0 {
                        paths.push(String::from_utf16_lossy(&buffer[..length as usize]));
                    }
                }
                DragFinish(drop);
                if !paths.is_empty() {
                    queue_simple_work(hwnd, BackgroundAction::Ingest(paths), "Attachment intake");
                }
                0
            }
            WM_CONTEXTMENU => {
                let source = w_param as Hwnd;
                let packed = l_param as u32;
                let x = (packed & 0xffff) as u16 as i16 as i32;
                let y = ((packed >> 16) & 0xffff) as u16 as i16 as i32;
                show_native_context_menu(hwnd, source, x, y);
                0
            }
            WM_DRAWITEM => {
                let draw = l_param as *const DrawItemStruct;
                if draw.is_null() {
                    return 0;
                }
                let draw = &*draw;
                if draw.hdc.is_null() || draw.hwnd_item.is_null() {
                    return 0;
                }
                if draw_navigation_row(draw) || draw_right_tab(draw) {
                    return 1;
                }
                let selected = draw.item_state & ODS_SELECTED != 0;
                let disabled = draw.item_state & ODS_DISABLED != 0;
                let active_right = matches!(
                    draw.ctl_id as i32,
                    ID_FILES | ID_CHANGES | ID_VAULT | ID_ARTIFACTS | ID_TASKS | ID_SETTINGS
                ) && ACTIVE_RIGHT_PANE.load(Ordering::SeqCst)
                    == draw.ctl_id as usize;
                let active_activity = matches!(
                    draw.ctl_id as i32,
                    ID_ACTIVITY_CORTEX_TAB
                        | ID_ACTIVITY_LMSTUDIO_TAB
                        | ID_ACTIVITY_JOBS_TAB
                        | ID_ACTIVITY_BUILD_TAB
                        | ID_ACTIVITY_GIT_TAB
                        | ID_ACTIVITY_NOTIFICATIONS_TAB
                ) && ACTIVE_ACTIVITY_PANE.load(Ordering::SeqCst)
                    == draw.ctl_id as usize;
                let active_config = matches!(
                    draw.ctl_id as i32,
                    ID_CONFIG_TAB_GENERAL
                        | ID_CONFIG_TAB_LIBRARY
                        | ID_CONFIG_TAB_PROVIDERS
                        | ID_CONFIG_TAB_MODELS
                        | ID_CONFIG_TAB_APPEARANCE
                ) && CONFIG_TAB.load(Ordering::SeqCst)
                    == match draw.ctl_id as i32 {
                        ID_CONFIG_TAB_GENERAL => 0,
                        ID_CONFIG_TAB_LIBRARY => 1,
                        ID_CONFIG_TAB_PROVIDERS => 2,
                        ID_CONFIG_TAB_MODELS => 3,
                        _ => 4,
                    };
                let active_mode = match draw.ctl_id as i32 {
                    ID_MODE_CHAT => !WORKBENCH_ACTIVE.load(Ordering::SeqCst),
                    ID_MODE_WORKBENCH => WORKBENCH_ACTIVE.load(Ordering::SeqCst),
                    _ => false,
                };
                let brush = if selected
                    || active_right
                    || active_activity
                    || active_config
                    || active_mode
                {
                    pressed_surface_brush()
                } else {
                    surface_brush()
                };
                FillRect(draw.hdc, &draw.rc_item, background_brush());
                let mut button_rect = draw.rc_item;
                button_rect.left += 1;
                button_rect.top += 1;
                button_rect.right -= 1;
                button_rect.bottom -= 1;
                paint_rounded_surface(draw.hdc, &button_rect, brush, border_brush(), 8);
                SetBkMode(draw.hdc, TRANSPARENT);
                SetTextColor(
                    draw.hdc,
                    if disabled {
                        DARK_TEXT_DISABLED
                    } else {
                        DARK_TEXT
                    },
                );
                let old_font = SelectObject(draw.hdc, ui_font());
                let text = wide(&get_text(draw.hwnd_item));
                let mut text_rect = draw.rc_item;
                DrawTextW(
                    draw.hdc,
                    text.as_ptr(),
                    -1,
                    &mut text_rect,
                    DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                );
                SelectObject(draw.hdc, old_font);
                1
            }
            WM_ERASEBKGND => {
                let hdc = w_param as Hdc;
                let mut rect = Rect {
                    left: 0,
                    top: 0,
                    right: 0,
                    bottom: 0,
                };
                if !hdc.is_null() && GetClientRect(hwnd, &mut rect) != 0 {
                    FillRect(hdc, &rect, background_brush());
                    1
                } else {
                    0
                }
            }
            WM_PAINT => {
                paint_shell_borders(hwnd);
                0
            }
            WM_CTLCOLOREDIT | WM_CTLCOLORLISTBOX => {
                let hdc = w_param as Hdc;
                if !hdc.is_null() {
                    SetTextColor(hdc, DARK_TEXT);
                    SetBkColor(hdc, DARK_FIELD);
                }
                field_brush() as Lresult
            }
            WM_CTLCOLORBTN | WM_CTLCOLORSCROLLBAR => {
                let hdc = w_param as Hdc;
                if !hdc.is_null() {
                    SetTextColor(hdc, DARK_TEXT);
                    SetBkColor(hdc, DARK_SURFACE);
                }
                surface_brush() as Lresult
            }
            WM_CTLCOLORSTATIC => {
                let hdc = w_param as Hdc;
                if !hdc.is_null() {
                    SetTextColor(hdc, DARK_TEXT);
                    SetBkColor(hdc, DARK_BACKGROUND);
                }
                background_brush() as Lresult
            }
            WM_COMMAND => {
                let id = (w_param & 0xffff) as i32;
                let notification = ((w_param >> 16) & 0xffff) as u16;
                if id == ID_COMMAND_QUERY && notification == EN_CHANGE {
                    refresh_command_palette(hwnd);
                    return 0;
                }
                if id == ID_COMMAND_LIST && notification == LBN_DBLCLK {
                    execute_command_palette(hwnd);
                    return 0;
                }
                if let Some(action) = control_ui_action(id) {
                    dispatch_ui_action(hwnd, action);
                    return 0;
                }
                match id {
                    ID_ATTACH_WORKSPACE => {
                        let path = get_text(GetDlgItem(hwnd, ID_WORKSPACE_PATH));
                        if path.trim().is_empty() {
                            show_error(hwnd, "Enter a workspace folder path first.");
                        } else {
                            let path = path.trim().to_string();
                            invoke(hwnd, move |host| host.attach_workspace(&path));
                        }
                    }
                    ID_WORKSPACES if notification == LBN_SELCHANGE => {
                        let selected =
                            SendMessageW(GetDlgItem(hwnd, ID_WORKSPACES), LB_GETCURSEL, 0, 0);
                        if selected >= 0 {
                            let row = NAV_ROWS
                                .get_or_init(|| Mutex::new(Vec::new()))
                                .lock()
                                .ok()
                                .and_then(|rows| rows.get(selected as usize).copied());
                            match row {
                                Some(NavRow::Workspace(index)) => {
                                    let expanded = EXPANDED_WORKSPACE.load(Ordering::SeqCst);
                                    if expanded == index {
                                        EXPANDED_WORKSPACE.store(usize::MAX, Ordering::SeqCst);
                                        refresh(hwnd);
                                    } else {
                                        EXPANDED_WORKSPACE.store(index, Ordering::SeqCst);
                                        let current = LAST_ACTIVE_WORKSPACE.load(Ordering::SeqCst);
                                        if current == index {
                                            refresh(hwnd);
                                        } else {
                                            invoke(hwnd, move |host| host.switch_workspace(index));
                                        }
                                    }
                                }
                                Some(NavRow::Conversation(index)) => {
                                    invoke(hwnd, |host| host.select_conversation(index));
                                }
                                Some(NavRow::Spacer) | None => {}
                            }
                        }
                    }
                    ID_LIBRARY_ROOT => {
                        let path = get_text(GetDlgItem(hwnd, ID_WORKSPACE_PATH));
                        if path.trim().is_empty() {
                            show_error(
                                hwnd,
                                "Enter the drive/folder to use as the Cortex Library first.",
                            );
                        } else {
                            invoke(hwnd, |host| host.set_library_root(path.trim()));
                        }
                    }
                    ID_LIBRARY_SCAN => {
                        queue_simple_work(hwnd, BackgroundAction::LibraryScan, "Scan library");
                    }
                    ID_TOGGLE_LEFT => {
                        LEFT_COLLAPSED.fetch_xor(true, Ordering::SeqCst);
                        layout(hwnd);
                    }
                    ID_RAIL_PROJECTS | ID_RAIL_CHATS => {
                        LEFT_COLLAPSED.store(false, Ordering::SeqCst);
                        layout(hwnd);
                    }
                    ID_RAIL_FILES => {
                        RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                        set_right_pane(
                            hwnd,
                            ID_FILES,
                            "Files",
                            "Browse project or Cortex Library...",
                        );
                        layout(hwnd);
                        invoke(hwnd, |host| host.show_files(""));
                    }
                    ID_RAIL_ADD => {
                        LEFT_COLLAPSED.store(false, Ordering::SeqCst);
                        layout(hwnd);
                        SetFocus(GetDlgItem(hwnd, ID_WORKSPACE_PATH));
                    }
                    ID_RAIL_CONFIG => open_config_panel(hwnd),
                    ID_TOGGLE_RIGHT => {
                        RIGHT_COLLAPSED.fetch_xor(true, Ordering::SeqCst);
                        layout(hwnd);
                    }
                    ID_MODE_CHAT => {
                        WORKBENCH_ACTIVE.store(false, Ordering::SeqCst);
                        layout(hwnd);
                    }
                    ID_MODE_WORKBENCH => {
                        WORKBENCH_ACTIVE.store(true, Ordering::SeqCst);
                        refresh_workbench_document_list(hwnd);
                        show_active_workbench_document(hwnd);
                        layout(hwnd);
                    }
                    ID_WORKBENCH_TABS if notification == LBN_SELCHANGE => {
                        let selected =
                            SendMessageW(GetDlgItem(hwnd, ID_WORKBENCH_TABS), LB_GETCURSEL, 0, 0);
                        if selected >= 0 {
                            WORKBENCH_ACTIVE_DOCUMENT.store(selected as usize, Ordering::SeqCst);
                            show_active_workbench_document(hwnd);
                        }
                    }
                    ID_TOGGLE_ACTIVITY => {
                        ACTIVITY_EXPANDED.fetch_xor(true, Ordering::SeqCst);
                        layout(hwnd);
                        render_active_activity(hwnd);
                    }
                    ID_ACTIVITY_CORTEX_TAB => {
                        ACTIVE_ACTIVITY_PANE
                            .store(ID_ACTIVITY_CORTEX_TAB as usize, Ordering::SeqCst);
                        invalidate_activity_tabs(hwnd);
                        render_active_activity(hwnd);
                    }
                    ID_ACTIVITY_LMSTUDIO_TAB => {
                        ACTIVE_ACTIVITY_PANE
                            .store(ID_ACTIVITY_LMSTUDIO_TAB as usize, Ordering::SeqCst);
                        start_lmstudio_log_stream(hwnd);
                        invalidate_activity_tabs(hwnd);
                        render_active_activity(hwnd);
                    }
                    ID_ACTIVITY_JOBS_TAB
                    | ID_ACTIVITY_BUILD_TAB
                    | ID_ACTIVITY_GIT_TAB
                    | ID_ACTIVITY_NOTIFICATIONS_TAB => {
                        ACTIVE_ACTIVITY_PANE.store(id as usize, Ordering::SeqCst);
                        invalidate_activity_tabs(hwnd);
                        render_active_activity(hwnd);
                    }
                    ID_NEW_CHAT => {
                        invoke(hwnd, |host| host.new_conversation());
                    }
                    ID_ARCHIVE_CHAT => {
                        invoke(hwnd, |host| host.archive_conversation());
                    }
                    ID_SEND => {
                        let text = get_text(GetDlgItem(hwnd, ID_INPUT));
                        let prompt = text.trim().to_string();
                        if !prompt.is_empty() {
                            queue_chat_work(hwnd, prompt);
                        }
                    }
                    ID_FILES => {
                        RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                        set_right_pane(hwnd, ID_FILES, "Files", "");
                        layout(hwnd);
                        load_file_browser(hwnd, false, "");
                    }
                    ID_FILE_SCOPE_PROJECT => load_file_browser(hwnd, false, ""),
                    ID_FILE_SCOPE_LIBRARY => load_file_browser(hwnd, true, ""),
                    ID_FILE_HOME => load_file_browser(
                        hwnd,
                        FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst),
                        "",
                    ),
                    ID_FILE_UP => file_browser_up(hwnd),
                    ID_FILE_LIST if notification == LBN_DBLCLK => {
                        let selected =
                            SendMessageW(GetDlgItem(hwnd, ID_FILE_LIST), LB_GETCURSEL, 0, 0);
                        if selected >= 0 {
                            let entry = FILE_BROWSER_LISTING
                                .get_or_init(|| Mutex::new(DesktopFileListing::default()))
                                .lock()
                                .ok()
                                .and_then(|listing| {
                                    listing.entries.get(selected as usize).cloned()
                                });
                            if let Some(entry) = entry {
                                if entry.is_directory {
                                    load_file_browser(
                                        hwnd,
                                        FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst),
                                        &entry.relative_path,
                                    );
                                } else if !FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst) {
                                    open_file_in_workbench(hwnd, &entry.relative_path);
                                } else {
                                    set_text(
                                        GetDlgItem(hwnd, ID_INFO),
                                        &format!(
                                            "Library file selected:\r\n{}\r\n\r\nRegister its project or drag/drop it into chat to give the active conversation explicit intake context.",
                                            entry.relative_path
                                        ),
                                    );
                                }
                            }
                        }
                    }
                    ID_CHANGES => {
                        set_right_pane(
                            hwnd,
                            ID_CHANGES,
                            "Changes",
                            "Git diff + Cortex transaction review",
                        );
                        invoke(hwnd, |host| host.show_changes());
                    }
                    ID_VAULT => {
                        set_right_pane(hwnd, ID_VAULT, "Memory", "Search project memory...");
                        let query = get_text(GetDlgItem(hwnd, ID_QUERY));
                        invoke(hwnd, |host| host.search_vault(query.trim()));
                    }
                    ID_ARTIFACTS => {
                        set_right_pane(
                            hwnd,
                            ID_ARTIFACTS,
                            "Artifacts",
                            "Recent artifacts and visual evidence",
                        );
                        invoke(hwnd, |host| host.show_artifacts());
                    }
                    ID_TASKS => {
                        set_right_pane(hwnd, ID_TASKS, "Tasks", "Recent Cortex jobs and progress");
                        invoke(hwnd, |host| host.show_tasks());
                    }
                    ID_SETTINGS => {
                        open_config_panel(hwnd);
                    }
                    ID_CONFIG_TAB_GENERAL
                    | ID_CONFIG_TAB_LIBRARY
                    | ID_CONFIG_TAB_PROVIDERS
                    | ID_CONFIG_TAB_MODELS
                    | ID_CONFIG_TAB_APPEARANCE => {
                        CONFIG_TAB.store(
                            match id {
                                ID_CONFIG_TAB_GENERAL => 0,
                                ID_CONFIG_TAB_LIBRARY => 1,
                                ID_CONFIG_TAB_PROVIDERS => 2,
                                ID_CONFIG_TAB_MODELS => 3,
                                _ => 4,
                            },
                            Ordering::SeqCst,
                        );
                        load_config_tab(hwnd);
                    }
                    ID_REDO_APPLY => {
                        let instructions = get_text(GetDlgItem(hwnd, ID_REDO_INPUT));
                        let message_id = REDO_TARGET
                            .get_or_init(|| Mutex::new(String::new()))
                            .lock()
                            .map(|value| value.clone())
                            .unwrap_or_default();
                        if !message_id.is_empty() {
                            let (worker, target) = match capture_worker(hwnd) {
                                Ok(value) => value,
                                Err(error) => {
                                    show_error(hwnd, &error);
                                    return 0;
                                }
                            };
                            cancel_redo(hwnd);
                            enqueue_work(
                                hwnd,
                                QueuedWork {
                                    worker,
                                    action: BackgroundAction::Redo {
                                        message_id,
                                        instructions,
                                    },
                                    label: "Redo response".into(),
                                    target,
                                },
                            );
                        }
                    }
                    ID_REDO_CANCEL => cancel_redo(hwnd),
                    ID_CONFIG_APPLY => apply_config_tab(hwnd),
                    ID_CONFIG_SECONDARY if CONFIG_TAB.load(Ordering::SeqCst) == 1 => {
                        queue_simple_work(hwnd, BackgroundAction::LibraryScan, "Library scan");
                    }
                    ID_CONFIG_SECONDARY => {}
                    ID_PROVIDER => {
                        queue_simple_work(hwnd, BackgroundAction::Provider, "Provider probe");
                    }
                    ID_BUILD => {
                        queue_simple_work(hwnd, BackgroundAction::Build, "Build check");
                    }
                    ID_CONTEXT_INDEX => {
                        queue_simple_work(hwnd, BackgroundAction::Index, "Context index");
                    }
                    ID_CONTEXT_INDEX_STATUS => {
                        invoke(hwnd, |host| host.show_context_index());
                    }
                    ID_INSPECT | ID_PLAN | ID_APPLY | ID_REPAIR => {
                        let prompt = get_text(GetDlgItem(hwnd, ID_INPUT));
                        if prompt.trim().is_empty() {
                            show_error(hwnd, "Enter an agent instruction in the chat input first.");
                        } else {
                            let mode = match id {
                                ID_INSPECT => "inspect",
                                ID_PLAN => "plan",
                                ID_APPLY => "apply",
                                _ => "repair",
                            };
                            let prompt = prompt.trim().to_string();
                            let mode_label = match mode {
                                "inspect" => "Inspect",
                                "plan" => "Plan",
                                "apply" => "Code",
                                _ => "Repair",
                            };
                            if queue_agent_work(hwnd, mode.to_string(), prompt.clone()) {
                                render_agent_preview(hwnd, &prompt, mode_label);
                            }
                        }
                    }
                    ID_CANCEL => {
                        if ASYNC_BUSY.load(Ordering::SeqCst) {
                            request_active_cancel(hwnd, false);
                        } else {
                            invoke_bool_result(
                                hwnd,
                                "Pending provider request cancelled",
                                "No pending provider request to cancel",
                                |host| host.cancel_pending_request(),
                            );
                        }
                    }
                    ID_REFRESH => {
                        invoke(hwnd, |host| host.refresh());
                    }
                    _ => {}
                }
                0
            }
            WM_CLOSE => {
                clear_work_queue();
                if ASYNC_BUSY.load(Ordering::SeqCst) {
                    request_active_cancel(hwnd, true);
                    0
                } else {
                    DestroyWindow(hwnd);
                    0
                }
            }
            WM_DESTROY => {
                UI_TICKER_RUNNING.store(false, Ordering::SeqCst);
                stop_lmstudio_log_stream();
                PostQuitMessage(0);
                0
            }
            _ => DefWindowProcW(hwnd, message, w_param, l_param),
        }
    }

    unsafe fn create_controls(hwnd: Hwnd) {
        let instance = GetModuleHandleW(null());
        control(
            hwnd,
            instance,
            "BUTTON",
            "<<",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_TOGGLE_LEFT,
        );
        for (label, id) in [
            ("▦", ID_RAIL_PROJECTS),
            ("◌", ID_RAIL_CHATS),
            ("▤", ID_RAIL_FILES),
            ("+", ID_RAIL_ADD),
            ("⚙", ID_RAIL_CONFIG),
        ] {
            control(
                hwnd,
                instance,
                "BUTTON",
                label,
                WS_CHILD | BS_PUSHBUTTON,
                id,
            );
        }
        control(
            hwnd,
            instance,
            "BUTTON",
            ">>",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_TOGGLE_RIGHT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Activity",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_TOGGLE_ACTIVITY,
        );
        control(
            hwnd,
            instance,
            "STATIC",
            "Projects",
            WS_CHILD | WS_VISIBLE,
            ID_LEFT_TITLE,
        );
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
            ID_WORKSPACE_PATH,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Add Project",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_ATTACH_WORKSPACE,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Library",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_LIBRARY_ROOT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Scan",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_LIBRARY_SCAN,
        );
        control(
            hwnd,
            instance,
            "LISTBOX",
            "",
            WS_CHILD
                | WS_VISIBLE
                | WS_VSCROLL
                | LBS_NOTIFY
                | LBS_OWNERDRAWVARIABLE
                | LBS_HASSTRINGS
                | LBS_NOINTEGRALHEIGHT,
            ID_WORKSPACES,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "New Chat",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            ID_NEW_CHAT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Archive",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_ARCHIVE_CHAT,
        );
        control(
            hwnd,
            instance,
            "LISTBOX",
            "",
            WS_CHILD | WS_VISIBLE | WS_BORDER | WS_VSCROLL | LBS_NOTIFY,
            ID_CONVERSATIONS,
        );
        let transcript = control(
            hwnd,
            instance,
            "STATIC",
            "",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | SS_NOTIFY,
            ID_TRANSCRIPT,
        );
        subclass_transcript(transcript);
        control(
            hwnd,
            instance,
            "BUTTON",
            "Chat",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_MODE_CHAT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Workbench",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_MODE_WORKBENCH,
        );
        control(
            hwnd,
            instance,
            "LISTBOX",
            "",
            WS_CHILD | WS_BORDER | WS_VSCROLL | LBS_NOTIFY,
            ID_WORKBENCH_TABS,
        );
        control(
            hwnd,
            instance,
            "STATIC",
            "No document open",
            WS_CHILD,
            ID_WORKBENCH_PATH,
        );
        let workbench_editor = control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD
                | WS_BORDER
                | WS_VSCROLL
                | ES_MULTILINE
                | ES_AUTOVSCROLL
                | ES_AUTOHSCROLL
                | ES_READONLY,
            ID_WORKBENCH_EDITOR,
        );
        SendMessageW(workbench_editor, WM_SETFONT, chat_code_font() as Wparam, 1);
        control(
            hwnd,
            instance,
            "STATIC",
            "",
            WS_CHILD | WS_VISIBLE,
            ID_THINKING_BUBBLE,
        );
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD
                | WS_VISIBLE
                | WS_VSCROLL
                | WS_TABSTOP
                | ES_MULTILINE
                | ES_AUTOVSCROLL
                | ES_WANTRETURN,
            ID_INPUT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Send",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            ID_SEND,
        );
        let redo_input = control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
            ID_REDO_INPUT,
        );
        let redo_cue = wide("What should Cortex change in this response?");
        SendMessageW(redo_input, EM_SETCUEBANNER, 1, redo_cue.as_ptr() as Lparam);
        control(
            hwnd,
            instance,
            "BUTTON",
            "Regenerate",
            WS_CHILD | BS_PUSHBUTTON,
            ID_REDO_APPLY,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Cancel",
            WS_CHILD | BS_PUSHBUTTON,
            ID_REDO_CANCEL,
        );
        control(
            hwnd,
            instance,
            "STATIC",
            "Context",
            WS_CHILD | WS_VISIBLE,
            ID_RIGHT_HEADER,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Files",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_FILES,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Changes",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_CHANGES,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Memory",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_VAULT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Artifacts",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_ARTIFACTS,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Tasks",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_TASKS,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Settings",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_SETTINGS,
        );
        for (label, id) in [
            ("General", ID_CONFIG_TAB_GENERAL),
            ("Library", ID_CONFIG_TAB_LIBRARY),
            ("Providers", ID_CONFIG_TAB_PROVIDERS),
            ("Models", ID_CONFIG_TAB_MODELS),
            ("UI", ID_CONFIG_TAB_APPEARANCE),
        ] {
            control(
                hwnd,
                instance,
                "BUTTON",
                label,
                WS_CHILD | BS_PUSHBUTTON,
                id,
            );
        }
        for id in CONFIG_LABELS {
            control(hwnd, instance, "STATIC", "", WS_CHILD, id);
        }
        for id in CONFIG_EDITS {
            control(
                hwnd,
                instance,
                "EDIT",
                "",
                WS_CHILD | WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
                id,
            );
        }
        control(
            hwnd,
            instance,
            "BUTTON",
            "Apply",
            WS_CHILD | BS_PUSHBUTTON,
            ID_CONFIG_APPLY,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "",
            WS_CHILD | BS_PUSHBUTTON,
            ID_CONFIG_SECONDARY,
        );

        for (label, id) in [
            ("Project", ID_FILE_SCOPE_PROJECT),
            ("Library", ID_FILE_SCOPE_LIBRARY),
            ("Home", ID_FILE_HOME),
            ("Up", ID_FILE_UP),
        ] {
            control(
                hwnd,
                instance,
                "BUTTON",
                label,
                WS_CHILD | BS_PUSHBUTTON,
                id,
            );
        }
        control(hwnd, instance, "STATIC", "", WS_CHILD, ID_FILE_PATH);
        control(
            hwnd,
            instance,
            "LISTBOX",
            "",
            WS_CHILD | WS_VSCROLL | LBS_NOTIFY | WS_BORDER,
            ID_FILE_LIST,
        );

        control(
            hwnd,
            instance,
            "STATIC",
            "Files",
            WS_CHILD | WS_VISIBLE,
            ID_RIGHT_TITLE,
        );
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_BORDER | ES_AUTOHSCROLL,
            ID_QUERY,
        );
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
            ID_INFO,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Build Check",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_BUILD,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Refresh",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_REFRESH,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Index",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_CONTEXT_INDEX,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Index Status",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_CONTEXT_INDEX_STATUS,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Provider",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_PROVIDER,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            // O2D-R051N9STOR1I_H33_STOP_CONTROL
            "Stop",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_CANCEL,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Inspect",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_INSPECT,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Plan",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_PLAN,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Code",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_APPLY,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Repair",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_REPAIR,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "Cortex Activity",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_ACTIVITY_CORTEX_TAB,
        );
        control(
            hwnd,
            instance,
            "BUTTON",
            "LM Studio Logs",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            ID_ACTIVITY_LMSTUDIO_TAB,
        );
        for (label, id) in [
            ("Jobs", ID_ACTIVITY_JOBS_TAB),
            ("Build", ID_ACTIVITY_BUILD_TAB),
            ("Git", ID_ACTIVITY_GIT_TAB),
            ("Notifications", ID_ACTIVITY_NOTIFICATIONS_TAB),
        ] {
            control(
                hwnd,
                instance,
                "BUTTON",
                label,
                WS_CHILD | BS_PUSHBUTTON,
                id,
            );
        }
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY,
            ID_ACTIVITY,
        );
        control(
            hwnd,
            instance,
            "STATIC",
            "Command Palette  ·  Ctrl+K",
            WS_CHILD,
            ID_COMMAND_HINT,
        );
        control(
            hwnd,
            instance,
            "EDIT",
            "",
            WS_CHILD | WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
            ID_COMMAND_QUERY,
        );
        control(
            hwnd,
            instance,
            "LISTBOX",
            "",
            WS_CHILD | WS_BORDER | WS_VSCROLL | LBS_NOTIFY,
            ID_COMMAND_LIST,
        );
        control(
            hwnd,
            instance,
            "STATIC",
            "Cortex",
            WS_CHILD | WS_VISIBLE,
            ID_STATUS,
        );
        let query = GetDlgItem(hwnd, ID_QUERY);
        let query_cue = wide("Filter files or search project Memory...");
        SendMessageW(query, EM_SETCUEBANNER, 1, query_cue.as_ptr() as Lparam);
        let command_query = GetDlgItem(hwnd, ID_COMMAND_QUERY);
        let command_cue = wide("Type a command, panel, project action, or tool...");
        SendMessageW(
            command_query,
            EM_SETCUEBANNER,
            1,
            command_cue.as_ptr() as Lparam,
        );
        EnableWindow(GetDlgItem(hwnd, ID_CANCEL), 0);
        let input = GetDlgItem(hwnd, ID_INPUT);
        subclass_input(input);
        let cue = wide("Message Cortex...   Enter to send   |   Shift+Enter for a new line");
        SendMessageW(input, EM_SETCUEBANNER, 1, cue.as_ptr() as Lparam);
        SetFocus(input);
    }

    unsafe fn begin_redo(parent: Hwnd, message_id: &str) {
        if let Ok(mut target) = REDO_TARGET.get_or_init(|| Mutex::new(String::new())).lock() {
            *target = message_id.to_string();
        }
        REDO_ACTIVE.store(true, Ordering::SeqCst);
        set_text(GetDlgItem(parent, ID_REDO_INPUT), "");
        layout(parent);
        SetFocus(GetDlgItem(parent, ID_REDO_INPUT));
    }

    unsafe fn cancel_redo(parent: Hwnd) {
        REDO_ACTIVE.store(false, Ordering::SeqCst);
        if let Ok(mut target) = REDO_TARGET.get_or_init(|| Mutex::new(String::new())).lock() {
            target.clear();
        }
        set_text(GetDlgItem(parent, ID_REDO_INPUT), "");
        layout(parent);
    }

    unsafe fn rate_card(parent: Hwnd, message_id: &str, score: i8) {
        let Some(host) = HOST.get() else {
            return;
        };
        let Ok(mut host) = host.try_lock() else {
            return;
        };
        if host.rate_message(message_id, score).is_ok() {
            drop(host);
            refresh(parent);
        }
    }

    unsafe fn subclass_transcript(transcript: Hwnd) {
        if transcript.is_null() || TRANSCRIPT_PREV_PROC.get().is_some() {
            return;
        }
        let previous = SetWindowLongPtrW(
            transcript,
            GWLP_WNDPROC,
            transcript_proc as *const () as usize as isize,
        );
        if previous != 0 {
            let _ = TRANSCRIPT_PREV_PROC.set(previous);
        }
    }

    unsafe fn chat_viewport_height(hwnd: Hwnd) -> i32 {
        let mut rect = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        if GetClientRect(hwnd, &mut rect) != 0 {
            (rect.bottom - rect.top).max(1)
        } else {
            1
        }
    }

    unsafe fn chat_max_scroll(hwnd: Hwnd) -> f32 {
        (CHAT_CONTENT_HEIGHT.load(Ordering::SeqCst) - chat_viewport_height(hwnd)).max(0) as f32
    }

    fn chat_scroll_current() -> f32 {
        CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|scroll| scroll.current())
            .unwrap_or(0.0)
    }

    unsafe fn sync_chat_scrollbar(hwnd: Hwnd) {
        let (current, max_offset) = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|scroll| (scroll.current(), scroll.max_offset()))
            .unwrap_or((0.0, 0.0));
        SetScrollRange(hwnd, SB_VERT, 0, max_offset.round() as i32, 0);
        SetScrollPos(hwnd, SB_VERT, current.round() as i32, 1);
    }

    unsafe fn update_chat_follow_mode(hwnd: Hwnd) {
        let viewport = chat_viewport_height(hwnd) as f32;
        let total = CHAT_CONTENT_HEIGHT.load(Ordering::SeqCst).max(0) as f32;
        let target = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|scroll| scroll.target())
            .unwrap_or(0.0);
        CHAT_FOLLOW_END.store(
            matches!(
                chat_scroll_policy(target, total, viewport),
                ScrollStickiness::StickToEnd
            ),
            Ordering::SeqCst,
        );
    }

    unsafe fn start_chat_scroll_ticker(hwnd: Hwnd) {
        if CHAT_SCROLL_TICKER_RUNNING
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return;
        }
        let hwnd_value = hwnd as usize;
        thread::spawn(move || {
            while CHAT_SCROLL_TICKER_RUNNING.load(Ordering::SeqCst) {
                thread::sleep(Duration::from_millis(16));
                unsafe {
                    if PostMessageW(hwnd_value as Hwnd, WM_SCROLL_TICK, 0, 0) == 0 {
                        CHAT_SCROLL_TICKER_RUNNING.store(false, Ordering::SeqCst);
                    }
                }
            }
        });
    }

    unsafe fn set_chat_scroll_target(hwnd: Hwnd, target: f32, follow_input: bool) {
        let max_scroll = chat_max_scroll(hwnd);
        let animating = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|mut scroll| {
                scroll.set_max_offset(max_scroll);
                scroll.set_target(target);
                scroll.is_animating()
            })
            .unwrap_or(false);
        if follow_input {
            update_chat_follow_mode(hwnd);
        }
        if animating {
            start_chat_scroll_ticker(hwnd);
        } else {
            sync_chat_scrollbar(hwnd);
            InvalidateRect(hwnd, null(), 0);
        }
    }

    unsafe fn nudge_chat_scroll(hwnd: Hwnd, delta: f32) {
        let max_scroll = chat_max_scroll(hwnd);
        let animating = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|mut scroll| {
                scroll.set_max_offset(max_scroll);
                scroll.nudge(delta);
                scroll.is_animating()
            })
            .unwrap_or(false);
        update_chat_follow_mode(hwnd);
        if animating {
            start_chat_scroll_ticker(hwnd);
        }
    }

    unsafe fn jump_chat_scroll(hwnd: Hwnd, target: f32, follow_input: bool) {
        let max_scroll = chat_max_scroll(hwnd);
        if let Ok(mut scroll) = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
        {
            scroll.set_max_offset(max_scroll);
            scroll.jump_to(target);
        }
        if follow_input {
            update_chat_follow_mode(hwnd);
        }
        sync_chat_scrollbar(hwnd);
        InvalidateRect(hwnd, null(), 0);
    }

    unsafe fn animate_chat_scroll(hwnd: Hwnd) {
        let animating = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|mut scroll| scroll.step())
            .unwrap_or(false);
        sync_chat_scrollbar(hwnd);
        InvalidateRect(hwnd, null(), 0);
        if !animating {
            CHAT_SCROLL_TICKER_RUNNING.store(false, Ordering::SeqCst);
        }
    }

    unsafe extern "system" fn transcript_proc(
        hwnd: Hwnd,
        message: u32,
        w_param: Wparam,
        l_param: Lparam,
    ) -> Lresult {
        match message {
            WM_ERASEBKGND => return 1,
            WM_LBUTTONDOWN => {
                SetFocus(hwnd);
                return 0;
            }
            WM_PAINT => {
                paint_chat_cards(hwnd);
                return 0;
            }
            WM_MOUSEWHEEL => {
                let delta = ((w_param >> 16) & 0xffff) as u16 as i16 as i32;
                nudge_chat_scroll(hwnd, -(delta as f32 / 120.0) * 72.0);
                return 0;
            }
            WM_LBUTTONUP => {
                let x = (l_param as u32 & 0xffff) as u16 as i16 as i32;
                let y = ((l_param as u32 >> 16) & 0xffff) as u16 as i16 as i32;
                let region = CHAT_ACTION_REGIONS
                    .get_or_init(|| Mutex::new(Vec::new()))
                    .lock()
                    .ok()
                    .and_then(|regions| {
                        regions
                            .iter()
                            .find(|region| {
                                x >= region.rect.left
                                    && x <= region.rect.right
                                    && y >= region.rect.top
                                    && y <= region.rect.bottom
                            })
                            .cloned()
                    });
                if let Some(region) = region {
                    let parent = GetParent(hwnd);
                    match region.kind {
                        ChatActionKind::Copy | ChatActionKind::CopyCode => {
                            if let Err(error) = set_clipboard_text(parent, &region.payload) {
                                show_error(parent, &error);
                            } else {
                                set_text(
                                    GetDlgItem(parent, ID_STATUS),
                                    "Cortex | Copied to clipboard",
                                );
                            }
                        }
                        ChatActionKind::Up => rate_card(
                            parent,
                            &region.message_id,
                            if region.current_score > 0 { 0 } else { 1 },
                        ),
                        ChatActionKind::Down => rate_card(
                            parent,
                            &region.message_id,
                            if region.current_score < 0 { 0 } else { -1 },
                        ),
                        ChatActionKind::Redo => begin_redo(parent, &region.message_id),
                    }
                    return 0;
                }
            }
            WM_VSCROLL => {
                let command = w_param & 0xffff;
                match command {
                    SB_LINEUP => nudge_chat_scroll(hwnd, -42.0),
                    SB_LINEDOWN => nudge_chat_scroll(hwnd, 42.0),
                    SB_PAGEUP => nudge_chat_scroll(hwnd, -320.0),
                    SB_PAGEDOWN => nudge_chat_scroll(hwnd, 320.0),
                    SB_TOP => set_chat_scroll_target(hwnd, 0.0, true),
                    SB_BOTTOM => {
                        CHAT_FOLLOW_END.store(true, Ordering::SeqCst);
                        set_chat_scroll_target(hwnd, chat_max_scroll(hwnd), false);
                    }
                    SB_THUMBPOSITION | SB_THUMBTRACK => {
                        jump_chat_scroll(hwnd, ((w_param >> 16) & 0xffff) as f32, true);
                    }
                    _ => {}
                }
                return 0;
            }
            WM_SCROLL_TICK => {
                animate_chat_scroll(hwnd);
                return 0;
            }
            WM_SIZE => {
                CHAT_LAYOUT_DIRTY.store(true, Ordering::SeqCst);
                if let Ok(mut regions) = CHAT_ACTION_REGIONS
                    .get_or_init(|| Mutex::new(Vec::new()))
                    .lock()
                {
                    regions.clear();
                }
                if let Ok(mut scroll) = CHAT_SCROLL
                    .get_or_init(|| Mutex::new(SmoothScrollController::default()))
                    .lock()
                {
                    scroll.set_max_offset(chat_max_scroll(hwnd));
                }
                sync_chat_scrollbar(hwnd);
                InvalidateRect(hwnd, null(), 0);
            }
            _ => {}
        }

        if let Some(previous) = TRANSCRIPT_PREV_PROC.get().copied() {
            return CallWindowProcW(previous, hwnd, message, w_param, l_param);
        }
        DefWindowProcW(hwnd, message, w_param, l_param)
    }

    unsafe fn create_chat_font(points: i32, monospace: bool, bold: bool) -> *mut c_void {
        let face = wide(if monospace { "Consolas" } else { "Segoe UI" });
        CreateFontW(
            -points,
            0,
            0,
            0,
            if bold { 600 } else { 400 },
            0,
            0,
            0,
            1,
            0,
            0,
            5,
            0,
            face.as_ptr(),
        )
    }

    unsafe fn measure_draw_text(hdc: Hdc, font: *mut c_void, text: &str, width: i32) -> i32 {
        let old = SelectObject(hdc, font);
        let wide_text = wide(text);
        let mut rect = Rect {
            left: 0,
            top: 0,
            right: width.max(40),
            bottom: 0,
        };
        DrawTextW(
            hdc,
            wide_text.as_ptr(),
            text.encode_utf16().count() as i32,
            &mut rect,
            DT_WORDBREAK | DT_CALCRECT | DT_NOPREFIX,
        );
        SelectObject(hdc, old);
        (rect.bottom - rect.top).max(18)
    }

    unsafe fn draw_card_text(hdc: Hdc, font: *mut c_void, text: &str, mut rect: Rect, color: u32) {
        let old = SelectObject(hdc, font);
        SetBkMode(hdc, TRANSPARENT);
        SetTextColor(hdc, color);
        let wide_text = wide(text);
        DrawTextW(
            hdc,
            wide_text.as_ptr(),
            text.encode_utf16().count() as i32,
            &mut rect,
            DT_WORDBREAK | DT_NOPREFIX,
        );
        SelectObject(hdc, old);
    }

    unsafe fn paint_rounded_surface(
        hdc: Hdc,
        rect: &Rect,
        fill: Hbrush,
        border: Hbrush,
        radius: i32,
    ) {
        let region = CreateRoundRectRgn(
            rect.left,
            rect.top,
            rect.right + 1,
            rect.bottom + 1,
            radius,
            radius,
        );
        if region.is_null() {
            FillRect(hdc, rect, fill);
            FrameRect(hdc, rect, border);
            return;
        }
        FillRgn(hdc, region, fill);
        FrameRgn(hdc, region, border, 1, 1);
        DeleteObject(region);
    }

    unsafe fn chat_normal_font() -> *mut c_void {
        *CHAT_NORMAL_FONT.get_or_init(|| create_chat_font(21, false, false) as usize) as *mut c_void
    }

    unsafe fn chat_label_font() -> *mut c_void {
        *CHAT_LABEL_FONT.get_or_init(|| create_chat_font(23, false, true) as usize) as *mut c_void
    }

    unsafe fn chat_code_font() -> *mut c_void {
        *CHAT_CODE_FONT.get_or_init(|| create_chat_font(19, true, false) as usize) as *mut c_void
    }

    unsafe fn reset_chat_backbuffer(buffer: &mut ChatBackBuffer) {
        if buffer.dc != 0 && buffer.previous_bitmap != 0 {
            SelectObject(buffer.dc as Hdc, buffer.previous_bitmap as *mut c_void);
        }
        if buffer.bitmap != 0 {
            DeleteObject(buffer.bitmap as *mut c_void);
        }
        if buffer.dc != 0 {
            DeleteDC(buffer.dc as Hdc);
        }
        *buffer = ChatBackBuffer::default();
    }

    unsafe fn ensure_chat_backbuffer(paint_hdc: Hdc, width: i32, height: i32) -> Hdc {
        let Ok(mut buffer) = CHAT_BACKBUFFER
            .get_or_init(|| Mutex::new(ChatBackBuffer::default()))
            .lock()
        else {
            return paint_hdc;
        };

        if buffer.dc != 0 && buffer.width == width && buffer.height == height {
            return buffer.dc as Hdc;
        }

        reset_chat_backbuffer(&mut buffer);

        let dc = CreateCompatibleDC(paint_hdc);
        if dc.is_null() {
            return paint_hdc;
        }

        let bitmap = CreateCompatibleBitmap(paint_hdc, width, height);
        if bitmap.is_null() {
            DeleteDC(dc);
            return paint_hdc;
        }

        let previous = SelectObject(dc, bitmap);
        buffer.dc = dc as usize;
        buffer.bitmap = bitmap as usize;
        buffer.previous_bitmap = previous as usize;
        buffer.width = width;
        buffer.height = height;
        dc
    }

    unsafe fn present_chat_backbuffer(paint_hdc: Hdc, render_hdc: Hdc, width: i32, height: i32) {
        if render_hdc != paint_hdc {
            BitBlt(paint_hdc, 0, 0, width, height, render_hdc, 0, 0, SRCCOPY);
        }
    }

    fn code_block_height(text: &str) -> i32 {
        code_lines(text).len().max(1) as i32 * 22
    }

    unsafe fn draw_code_block_lines(hdc: Hdc, font: *mut c_void, text: &str, rect: Rect) {
        let lines = code_lines(text);
        let digits = lines.len().max(1).to_string().len() as i32;
        let gutter_width = (digits * 10 + 24).max(44);
        let old = SelectObject(hdc, font);
        SetBkMode(hdc, TRANSPARENT);

        for line in lines {
            let top = rect.top + (line.number.saturating_sub(1) as i32) * 22;
            if top >= rect.bottom {
                break;
            }

            let mut number_rect = Rect {
                left: rect.left,
                top,
                right: (rect.left + gutter_width).min(rect.right),
                bottom: (top + 22).min(rect.bottom),
            };
            let number = wide(&line.number.to_string());
            SetTextColor(hdc, DARK_TEXT_DISABLED);
            DrawTextW(
                hdc,
                number.as_ptr(),
                -1,
                &mut number_rect,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
            );

            let mut code_rect = Rect {
                left: rect.left + gutter_width + 8,
                top,
                right: rect.right,
                bottom: (top + 22).min(rect.bottom),
            };
            let code = wide(&line.text);
            SetTextColor(hdc, DARK_TEXT);
            DrawTextW(
                hdc,
                code.as_ptr(),
                -1,
                &mut code_rect,
                DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | DT_EXPANDTABS,
            );
        }
        SelectObject(hdc, old);
    }

    unsafe fn rebuild_chat_layout(hdc: Hdc, viewport_width: i32) {
        let blocks = CHAT_CARD_BLOCKS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
            .map(|blocks| blocks.clone())
            .unwrap_or_default();

        let normal_font = chat_normal_font();
        let label_font = chat_label_font();

        let gap = 16;
        let mut top = 18;
        let mut cards = Vec::with_capacity(blocks.len());
        let mut virtual_items = Vec::with_capacity(blocks.len());

        for (index, block) in blocks.into_iter().enumerate() {
            let user = block.role == "user";
            let file = block.kind == "file";
            let max_width = if user {
                (viewport_width * 68 / 100).max(280)
            } else {
                (viewport_width * 84 / 100).max(320)
            };
            let card_width = max_width.min(viewport_width - 36).max(240);
            let x = if user {
                viewport_width - card_width - 18
            } else {
                18
            };
            let inner_width = card_width - 32;

            let diff = if block.kind == "diff" {
                Some(parse_unified_diff(&block.text, 160))
            } else {
                None
            };
            let segments = if diff.is_some() {
                Vec::new()
            } else if file {
                vec![MarkdownSegment {
                    code: true,
                    language: block.language.clone(),
                    text: block.text.clone(),
                }]
            } else {
                split_markdown_segments(&block.text)
            };

            let label_height = if block.label.is_empty() {
                0
            } else {
                measure_draw_text(hdc, label_font, &block.label, inner_width)
            };

            let file_header = if file {
                format!(
                    "{}  ·  {}",
                    if block.status.is_empty() {
                        "Saved"
                    } else {
                        block.status.as_str()
                    },
                    if block.language.is_empty() {
                        "Text"
                    } else {
                        block.language.as_str()
                    }
                )
            } else {
                String::new()
            };
            let file_header_height = if file {
                measure_draw_text(hdc, label_font, &file_header, inner_width)
            } else {
                0
            };

            let segment_heights = segments
                .iter()
                .map(|segment| {
                    if segment.code {
                        code_block_height(&segment.text)
                    } else {
                        measure_draw_text(hdc, normal_font, &segment.text, inner_width)
                    }
                })
                .collect::<Vec<_>>();

            let mut card_height = 22;
            if label_height > 0 {
                card_height += label_height + 8;
            }
            if file {
                card_height += 30;
            }
            if let Some(diff_view) = diff.as_ref() {
                card_height += 48 + diff_view.rows.len() as i32 * 22;
                if diff_view.truncated {
                    card_height += 24;
                }
            } else {
                for (segment, height) in segments.iter().zip(segment_heights.iter()) {
                    card_height += if segment.code {
                        *height + 34
                    } else {
                        *height + 10
                    };
                }
            }
            if !user && !block.message_id.is_empty() {
                card_height += 30;
            }
            card_height += 12;

            cards.push(CachedChatCard {
                block,
                segments,
                segment_heights,
                file_header,
                label_height,
                file_header_height,
                diff,
                top,
                height: card_height,
                x,
                width: card_width,
            });
            virtual_items.push(
                VirtualListItem::new(format!("chat.card.{index}"), (card_height + gap) as f32)
                    .expect("generated chat card widget id is valid"),
            );
            top += card_height + gap;
        }

        let content_height = top + 18;
        if let Ok(mut cache) = CHAT_LAYOUT_CACHE
            .get_or_init(|| Mutex::new(ChatLayoutCache::default()))
            .lock()
        {
            cache.viewport_width = viewport_width;
            cache.cards = cards;
            cache.virtual_items = virtual_items;
            cache.content_height = content_height;
        }
        CHAT_CONTENT_HEIGHT.store(content_height, Ordering::SeqCst);
        CHAT_LAYOUT_DIRTY.store(false, Ordering::SeqCst);
    }

    unsafe fn ensure_chat_layout(hdc: Hdc, viewport_width: i32) {
        let width_changed = CHAT_LAYOUT_CACHE
            .get_or_init(|| Mutex::new(ChatLayoutCache::default()))
            .lock()
            .map(|cache| cache.viewport_width != viewport_width)
            .unwrap_or(true);

        if CHAT_LAYOUT_DIRTY.load(Ordering::SeqCst) || width_changed {
            rebuild_chat_layout(hdc, viewport_width);
        }
    }

    unsafe fn draw_diff_view(hdc: Hdc, font: *mut c_void, diff: &DiffView, rect: Rect) {
        let mid = rect.left + (rect.right - rect.left) / 2;
        let old = SelectObject(hdc, font);
        SetBkMode(hdc, TRANSPARENT);

        for (index, row) in diff.rows.iter().enumerate() {
            let top = rect.top + index as i32 * 22;
            if top + 22 > rect.bottom {
                break;
            }
            let left = Rect {
                left: rect.left,
                top,
                right: mid - 2,
                bottom: top + 22,
            };
            let right = Rect {
                left: mid + 2,
                top,
                right: rect.right,
                bottom: top + 22,
            };

            match row.kind {
                DiffRowKind::Removed => {
                    FillRect(hdc, &left, diff_remove_brush());
                }
                DiffRowKind::Added => {
                    FillRect(hdc, &right, diff_add_brush());
                }
                DiffRowKind::Modified => {
                    FillRect(hdc, &left, diff_remove_brush());
                    FillRect(hdc, &right, diff_add_brush());
                }
                DiffRowKind::Context => {}
            }

            let before = row
                .before_line
                .map(|line| format!("{line:>4}  {}", row.before))
                .unwrap_or_default();
            let after = row
                .after_line
                .map(|line| format!("{line:>4}  {}", row.after))
                .unwrap_or_default();

            SetTextColor(hdc, DARK_TEXT);
            let mut before_rect = Rect {
                left: left.left + 6,
                top,
                right: left.right - 4,
                bottom: top + 22,
            };
            let before_wide = wide(&before);
            DrawTextW(
                hdc,
                before_wide.as_ptr(),
                -1,
                &mut before_rect,
                DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | DT_EXPANDTABS,
            );

            let mut after_rect = Rect {
                left: right.left + 6,
                top,
                right: right.right - 4,
                bottom: top + 22,
            };
            let after_wide = wide(&after);
            DrawTextW(
                hdc,
                after_wide.as_ptr(),
                -1,
                &mut after_rect,
                DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | DT_EXPANDTABS,
            );
        }
        SelectObject(hdc, old);
    }

    unsafe fn paint_chat_cards(hwnd: Hwnd) {
        let mut paint = PaintStruct {
            hdc: null_mut(),
            erase: 0,
            paint: Rect {
                left: 0,
                top: 0,
                right: 0,
                bottom: 0,
            },
            restore: 0,
            inc_update: 0,
            reserved: [0; 32],
        };
        let paint_hdc = BeginPaint(hwnd, &mut paint);
        if paint_hdc.is_null() {
            return;
        }

        let mut client = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        GetClientRect(hwnd, &mut client);

        let width = (client.right - client.left).max(1);
        let height = (client.bottom - client.top).max(1);
        let hdc = ensure_chat_backbuffer(paint_hdc, width, height);
        FillRect(hdc, &client, background_brush());

        let normal_font = chat_normal_font();
        let label_font = chat_label_font();
        let code_font = chat_code_font();

        let viewport_width = width.max(320);
        ensure_chat_layout(hdc, viewport_width);

        let scroll = chat_scroll_current();
        let mut action_regions = Vec::<ChatActionRegion>::new();

        if let Ok(cache) = CHAT_LAYOUT_CACHE
            .get_or_init(|| Mutex::new(ChatLayoutCache::default()))
            .lock()
        {
            if cache.cards.is_empty() {
                let center_x = client.right / 2;
                let icon_rect = Rect {
                    left: center_x - 28,
                    top: 92,
                    right: center_x + 28,
                    bottom: 142,
                };
                draw_fluent_icon(hdc, '\u{E8BD}', icon_rect, DARK_TEXT_DISABLED);
                draw_card_text(
                    hdc,
                    label_font,
                    "Start a Cortex conversation",
                    Rect {
                        left: 36,
                        top: 150,
                        right: client.right - 36,
                        bottom: 184,
                    },
                    DARK_TEXT,
                );
                draw_card_text(
                    hdc,
                    normal_font,
                    "Ask about the active project, inspect files, plan work, or drop reference files into the window.",
                    Rect {
                        left: 54,
                        top: 190,
                        right: client.right - 54,
                        bottom: 260,
                    },
                    DARK_TEXT_DISABLED,
                );
            }
            let window = VirtualList::window(
                &cache.virtual_items,
                (scroll - 18.0).max(0.0),
                height as f32,
                240.0,
            );

            for cached in cache.cards.iter().skip(window.first).take(window.len()) {
                let block = &cached.block;
                let user = block.role == "user";
                let file = block.kind == "file";
                let card = Rect {
                    left: cached.x,
                    top: cached.top - scroll.round() as i32,
                    right: cached.x + cached.width,
                    bottom: cached.top - scroll.round() as i32 + cached.height,
                };

                if card.bottom < 0 || card.top > client.bottom {
                    continue;
                }

                paint_rounded_surface(
                    hdc,
                    &card,
                    if user {
                        pressed_surface_brush()
                    } else {
                        surface_brush()
                    },
                    border_brush(),
                    18,
                );

                let mut cy = card.top + 14;
                if cached.label_height > 0 {
                    let identity_height = cached.label_height.max(22);
                    let icon_rect = Rect {
                        left: card.left + 16,
                        top: cy,
                        right: card.left + 38,
                        bottom: cy + identity_height + 2,
                    };
                    draw_fluent_icon(
                        hdc,
                        message_identity_icon(block),
                        icon_rect,
                        if user { DARK_TEXT_DISABLED } else { DARK_TEXT },
                    );
                    draw_card_text(
                        hdc,
                        label_font,
                        &block.label,
                        Rect {
                            left: card.left + 44,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + identity_height + 4,
                        },
                        if user { DARK_TEXT_DISABLED } else { DARK_TEXT },
                    );
                    cy += identity_height + 8;
                }

                if file {
                    draw_card_text(
                        hdc,
                        label_font,
                        &cached.file_header,
                        Rect {
                            left: card.left + 16,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + cached.file_header_height + 4,
                        },
                        DARK_TEXT_DISABLED,
                    );
                    cy += cached.file_header_height + 8;
                }

                if let Some(diff) = cached.diff.as_ref() {
                    let title = if block.path.is_empty() {
                        if diff.path.is_empty() {
                            "Code changes"
                        } else {
                            diff.path.as_str()
                        }
                    } else {
                        block.path.as_str()
                    };
                    draw_card_text(
                        hdc,
                        label_font,
                        title,
                        Rect {
                            left: card.left + 16,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + 24,
                        },
                        DARK_TEXT,
                    );
                    cy += 28;
                    draw_card_text(
                        hdc,
                        label_font,
                        "BEFORE",
                        Rect {
                            left: card.left + 16,
                            top: cy,
                            right: card.left + cached.width / 2,
                            bottom: cy + 20,
                        },
                        DARK_TEXT_DISABLED,
                    );
                    draw_card_text(
                        hdc,
                        label_font,
                        "AFTER",
                        Rect {
                            left: card.left + cached.width / 2,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + 20,
                        },
                        DARK_TEXT_DISABLED,
                    );
                    cy += 22;
                    draw_diff_view(
                        hdc,
                        code_font,
                        diff,
                        Rect {
                            left: card.left + 16,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + diff.rows.len() as i32 * 22,
                        },
                    );
                    cy += diff.rows.len() as i32 * 22 + 6;
                    if diff.truncated {
                        draw_card_text(
                            hdc,
                            label_font,
                            "Diff truncated in chat · open full diff in Workbench",
                            Rect {
                                left: card.left + 16,
                                top: cy,
                                right: card.right - 16,
                                bottom: cy + 22,
                            },
                            DARK_TEXT_DISABLED,
                        );
                    }
                }

                for (segment, text_h) in cached.segments.iter().zip(cached.segment_heights.iter()) {
                    let font = if segment.code { code_font } else { normal_font };
                    if segment.code {
                        let code_rect = Rect {
                            left: card.left + 16,
                            top: cy,
                            right: card.right - 16,
                            bottom: cy + *text_h + 24,
                        };
                        paint_rounded_surface(hdc, &code_rect, field_brush(), border_brush(), 12);
                        if !segment.language.is_empty() {
                            draw_card_text(
                                hdc,
                                label_font,
                                &code_language_label(&segment.language),
                                Rect {
                                    left: code_rect.left + 12,
                                    top: code_rect.top + 6,
                                    right: code_rect.right - 48,
                                    bottom: code_rect.top + 24,
                                },
                                DARK_TEXT_DISABLED,
                            );
                        }
                        let copy_code = Rect {
                            left: code_rect.right - 38,
                            top: code_rect.top + 4,
                            right: code_rect.right - 10,
                            bottom: code_rect.top + 28,
                        };
                        draw_action_icon_button(hdc, copy_code, '\u{E8C8}', false);
                        action_regions.push(ChatActionRegion {
                            rect: copy_code,
                            message_id: block.message_id.clone(),
                            payload: segment.text.clone(),
                            current_score: block.feedback_score,
                            kind: ChatActionKind::CopyCode,
                        });
                        draw_code_block_lines(
                            hdc,
                            font,
                            &segment.text,
                            Rect {
                                left: code_rect.left + 8,
                                top: code_rect.top + 24,
                                right: code_rect.right - 12,
                                bottom: code_rect.bottom - 8,
                            },
                        );
                        cy = code_rect.bottom + 10;
                    } else {
                        draw_card_text(
                            hdc,
                            font,
                            &segment.text,
                            Rect {
                                left: card.left + 16,
                                top: cy,
                                right: card.right - 16,
                                bottom: cy + *text_h + 6,
                            },
                            DARK_TEXT,
                        );
                        cy += *text_h + 10;
                    }
                }

                if !user && !block.message_id.is_empty() {
                    let action_y = card.bottom - 34;
                    let copy = Rect {
                        left: card.left + 16,
                        top: action_y,
                        right: card.left + 44,
                        bottom: action_y + 24,
                    };
                    let up = Rect {
                        left: card.left + 50,
                        top: action_y,
                        right: card.left + 78,
                        bottom: action_y + 24,
                    };
                    let down = Rect {
                        left: card.left + 84,
                        top: action_y,
                        right: card.left + 112,
                        bottom: action_y + 24,
                    };
                    let redo = Rect {
                        left: card.left + 118,
                        top: action_y,
                        right: card.left + 146,
                        bottom: action_y + 24,
                    };

                    draw_action_icon_button(hdc, copy, '\u{E8C8}', false);
                    draw_vote_arrow(hdc, up, true, block.feedback_score > 0);
                    draw_vote_arrow(hdc, down, false, block.feedback_score < 0);
                    draw_action_icon_button(hdc, redo, '\u{E72C}', false);

                    action_regions.push(ChatActionRegion {
                        rect: copy,
                        message_id: block.message_id.clone(),
                        payload: block.text.clone(),
                        current_score: block.feedback_score,
                        kind: ChatActionKind::Copy,
                    });
                    action_regions.push(ChatActionRegion {
                        rect: up,
                        message_id: block.message_id.clone(),
                        payload: String::new(),
                        current_score: block.feedback_score,
                        kind: ChatActionKind::Up,
                    });
                    action_regions.push(ChatActionRegion {
                        rect: down,
                        message_id: block.message_id.clone(),
                        payload: String::new(),
                        current_score: block.feedback_score,
                        kind: ChatActionKind::Down,
                    });
                    action_regions.push(ChatActionRegion {
                        rect: redo,
                        message_id: block.message_id.clone(),
                        payload: String::new(),
                        current_score: block.feedback_score,
                        kind: ChatActionKind::Redo,
                    });
                }
            }

            CHAT_CONTENT_HEIGHT.store(cache.content_height, Ordering::SeqCst);
        }

        if let Ok(mut stored) = CHAT_ACTION_REGIONS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        {
            *stored = action_regions;
        }

        let max_scroll = (CHAT_CONTENT_HEIGHT.load(Ordering::SeqCst) - height).max(0) as f32;
        let follow_end = CHAT_FOLLOW_END.load(Ordering::SeqCst);
        let should_animate = CHAT_SCROLL
            .get_or_init(|| Mutex::new(SmoothScrollController::default()))
            .lock()
            .map(|mut scroll_state| {
                scroll_state.set_max_offset(max_scroll);
                if follow_end {
                    scroll_state.set_target(max_scroll);
                }
                scroll_state.is_animating()
            })
            .unwrap_or(false);

        sync_chat_scrollbar(hwnd);
        if should_animate {
            start_chat_scroll_ticker(hwnd);
        }

        present_chat_backbuffer(paint_hdc, hdc, width, height);
        EndPaint(hwnd, &paint);
    }

    unsafe fn subclass_input(input: Hwnd) {
        if input.is_null() || INPUT_PREV_PROC.get().is_some() {
            return;
        }
        let previous = SetWindowLongPtrW(
            input,
            GWLP_WNDPROC,
            input_proc as *const () as usize as isize,
        );
        if previous != 0 {
            let _ = INPUT_PREV_PROC.set(previous);
        }
    }

    unsafe extern "system" fn input_proc(
        hwnd: Hwnd,
        message: u32,
        w_param: Wparam,
        l_param: Lparam,
    ) -> Lresult {
        if message == WM_KEYDOWN && w_param == VK_RETURN {
            let shift_down = (GetKeyState(VK_SHIFT) as u16 & 0x8000) != 0;
            if !shift_down {
                let parent = GetParent(hwnd);
                if !parent.is_null() {
                    PostMessageW(parent, WM_COMMAND, ID_SEND as Wparam, hwnd as Lparam);
                    return 0;
                }
            }
        }
        if let Some(previous) = INPUT_PREV_PROC.get() {
            return CallWindowProcW(*previous, hwnd, message, w_param, l_param);
        }
        DefWindowProcW(hwnd, message, w_param, l_param)
    }

    unsafe fn ui_font() -> *mut c_void {
        let handle = *UI_FONT.get_or_init(|| {
            let face = wide("Segoe UI");
            CreateFontW(-19, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face.as_ptr()) as usize
        });
        handle as *mut c_void
    }

    unsafe fn fluent_icon_font() -> *mut c_void {
        let handle = *FLUENT_ICON_FONT.get_or_init(|| {
            let face = wide("Segoe Fluent Icons");
            CreateFontW(-18, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face.as_ptr()) as usize
        });
        handle as *mut c_void
    }

    unsafe fn draw_fluent_icon(hdc: Hdc, glyph: char, mut rect: Rect, color: u32) {
        SetBkMode(hdc, TRANSPARENT);
        SetTextColor(hdc, color);
        let old_font = SelectObject(hdc, fluent_icon_font());
        let text = wide(&glyph.to_string());
        DrawTextW(
            hdc,
            text.as_ptr(),
            -1,
            &mut rect,
            DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
        );
        SelectObject(hdc, old_font);
    }

    unsafe fn draw_vote_arrow(hdc: Hdc, rect: Rect, up: bool, selected: bool) {
        let cx = (rect.left + rect.right) / 2;
        let top = rect.top + 4;
        let bottom = rect.bottom - 4;
        let points = if up {
            [
                Point { x: cx, y: top },
                Point {
                    x: rect.right - 5,
                    y: top + 8,
                },
                Point {
                    x: cx + 4,
                    y: top + 8,
                },
                Point {
                    x: cx + 4,
                    y: bottom,
                },
                Point {
                    x: cx - 4,
                    y: bottom,
                },
                Point {
                    x: cx - 4,
                    y: top + 8,
                },
                Point {
                    x: rect.left + 5,
                    y: top + 8,
                },
            ]
        } else {
            [
                Point {
                    x: rect.left + 5,
                    y: bottom - 8,
                },
                Point {
                    x: cx - 4,
                    y: bottom - 8,
                },
                Point { x: cx - 4, y: top },
                Point { x: cx + 4, y: top },
                Point {
                    x: cx + 4,
                    y: bottom - 8,
                },
                Point {
                    x: rect.right - 5,
                    y: bottom - 8,
                },
                Point { x: cx, y: bottom },
            ]
        };
        let brush = if selected {
            accent_brush()
        } else {
            border_brush()
        };
        let previous = SelectObject(hdc, brush);
        Polygon(hdc, points.as_ptr(), points.len() as i32);
        SelectObject(hdc, previous);
    }

    unsafe fn draw_action_icon_button(hdc: Hdc, rect: Rect, glyph: char, active: bool) {
        paint_rounded_surface(
            hdc,
            &rect,
            if active {
                accent_soft_brush()
            } else {
                background_brush()
            },
            if active {
                accent_brush()
            } else {
                border_brush()
            },
            8,
        );
        let mut icon = rect;
        icon.left += 2;
        icon.right -= 2;
        icon.top += 1;
        icon.bottom -= 1;
        draw_fluent_icon(
            hdc,
            glyph,
            icon,
            if active {
                DARK_TEXT
            } else {
                DARK_TEXT_DISABLED
            },
        );
    }

    fn message_identity_icon(block: &DesktopChatBlock) -> char {
        if block.role == "user" {
            '\u{E77B}'
        } else if block.kind == "error" || block.status.eq_ignore_ascii_case("error") {
            '\u{E7BA}'
        } else if block.kind == "tool" || block.kind == "file" || block.kind == "diff" {
            '\u{E90F}'
        } else if block.role == "system" {
            '\u{E946}'
        } else {
            '\u{E8BD}'
        }
    }

    unsafe fn set_clipboard_text(owner: Hwnd, text: &str) -> Result<(), String> {
        let utf16 = text
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect::<Vec<_>>();
        let bytes = utf16.len() * std::mem::size_of::<u16>();
        if OpenClipboard(owner) == 0 {
            return Err("Windows clipboard is currently unavailable.".into());
        }
        let mut memory: *mut c_void = null_mut();
        let result = (|| {
            if EmptyClipboard() == 0 {
                return Err("Unable to clear the Windows clipboard.".to_string());
            }
            memory = GlobalAlloc(GMEM_MOVEABLE, bytes);
            if memory.is_null() {
                return Err("Unable to allocate Windows clipboard memory.".to_string());
            }
            let target = GlobalLock(memory) as *mut u16;
            if target.is_null() {
                return Err("Unable to lock Windows clipboard memory.".to_string());
            }
            std::ptr::copy_nonoverlapping(utf16.as_ptr(), target, utf16.len());
            GlobalUnlock(memory);
            if SetClipboardData(CF_UNICODETEXT, memory).is_null() {
                return Err("Unable to publish text to the Windows clipboard.".to_string());
            }
            memory = null_mut(); // Windows owns it after SetClipboardData succeeds.
            Ok(())
        })();
        CloseClipboard();
        if !memory.is_null() {
            GlobalFree(memory);
        }
        result
    }

    unsafe fn listbox_item_text(list: Hwnd, index: usize) -> String {
        let len = SendMessageW(list, LB_GETTEXTLEN, index, 0);
        if len <= 0 {
            return String::new();
        }
        let mut buffer = vec![0_u16; len as usize + 1];
        let copied = SendMessageW(list, LB_GETTEXT, index, buffer.as_mut_ptr() as Lparam);
        if copied <= 0 {
            String::new()
        } else {
            String::from_utf16_lossy(&buffer[..copied as usize])
        }
    }

    unsafe fn draw_navigation_row(draw: &DrawItemStruct) -> bool {
        if draw.ctl_id as i32 != ID_WORKSPACES || draw.item_id == u32::MAX {
            return false;
        }
        let index = draw.item_id as usize;
        let row = NAV_ROWS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
            .ok()
            .and_then(|rows| rows.get(index).copied());
        let Some(row) = row else {
            return false;
        };

        FillRect(draw.hdc, &draw.rc_item, background_brush());
        if matches!(row, NavRow::Spacer) {
            return true;
        }

        let selected = draw.item_state & ODS_SELECTED != 0;
        let mut surface = draw.rc_item;
        surface.left += 3;
        surface.right -= 3;
        surface.top += 2;
        surface.bottom -= 2;
        if selected {
            paint_rounded_surface(draw.hdc, &surface, accent_soft_brush(), border_brush(), 9);
        }

        let text = listbox_item_text(draw.hwnd_item, index);
        let (icon, indent, font, color) = match row {
            NavRow::Workspace(workspace_index) => {
                let expanded = EXPANDED_WORKSPACE.load(Ordering::SeqCst) == workspace_index;
                (
                    if expanded { '\u{E70D}' } else { '\u{E76C}' },
                    12,
                    ui_font(),
                    DARK_TEXT,
                )
            }
            NavRow::Conversation(_) => (
                '\u{E8BD}',
                30,
                ui_font(),
                if selected {
                    DARK_TEXT
                } else {
                    DARK_TEXT_DISABLED
                },
            ),
            NavRow::Spacer => unreachable!(),
        };
        let icon_rect = Rect {
            left: surface.left + indent,
            top: surface.top,
            right: surface.left + indent + 22,
            bottom: surface.bottom,
        };
        draw_fluent_icon(draw.hdc, icon, icon_rect, color);
        let mut text_rect = Rect {
            left: icon_rect.right + 6,
            top: surface.top,
            right: surface.right - 8,
            bottom: surface.bottom,
        };
        SetBkMode(draw.hdc, TRANSPARENT);
        SetTextColor(draw.hdc, color);
        let old_font = SelectObject(draw.hdc, font);
        let label = wide(&text);
        DrawTextW(
            draw.hdc,
            label.as_ptr(),
            -1,
            &mut text_rect,
            DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
        );
        SelectObject(draw.hdc, old_font);
        true
    }

    unsafe fn draw_right_tab(draw: &DrawItemStruct) -> bool {
        let id = draw.ctl_id as i32;
        let glyph = match id {
            ID_FILES => '\u{E8B7}',
            ID_CHANGES => '\u{E8A5}',
            ID_VAULT => '\u{E8F1}',
            ID_ARTIFACTS => '\u{E7C3}',
            ID_TASKS => '\u{E73E}',
            ID_SETTINGS => '\u{E713}',
            _ => return false,
        };
        let active = ACTIVE_RIGHT_PANE.load(Ordering::SeqCst) == id as usize;
        FillRect(draw.hdc, &draw.rc_item, background_brush());
        let mut surface = draw.rc_item;
        surface.left += 1;
        surface.right -= 1;
        if active {
            FillRect(draw.hdc, &surface, surface_brush());
            let underline = Rect {
                left: surface.left + 5,
                top: surface.bottom - 3,
                right: surface.right - 5,
                bottom: surface.bottom,
            };
            FillRect(draw.hdc, &underline, accent_brush());
        }
        let compact = surface.right - surface.left < 54;
        let mut icon_rect = surface;
        if compact {
            icon_rect.left += 4;
            icon_rect.right -= 4;
        } else {
            icon_rect.left += 3;
            icon_rect.right = icon_rect.left + 20;
        }
        draw_fluent_icon(
            draw.hdc,
            glyph,
            icon_rect,
            if active {
                DARK_TEXT
            } else {
                DARK_TEXT_DISABLED
            },
        );
        if !compact {
            let mut text_rect = surface;
            text_rect.left = icon_rect.right;
            text_rect.right -= 2;
            SetBkMode(draw.hdc, TRANSPARENT);
            SetTextColor(
                draw.hdc,
                if active {
                    DARK_TEXT
                } else {
                    DARK_TEXT_DISABLED
                },
            );
            let old_font = SelectObject(draw.hdc, chat_label_font());
            let text = wide(&get_text(draw.hwnd_item));
            DrawTextW(
                draw.hdc,
                text.as_ptr(),
                -1,
                &mut text_rect,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
            );
            SelectObject(draw.hdc, old_font);
        }
        true
    }

    unsafe fn add_popup_item(menu: Hmenu, command: u32, text: &str, enabled: bool) {
        let text = wide(text);
        let flags = MF_STRING | if enabled { 0 } else { MF_GRAYED };
        AppendMenuW(menu, flags, command as usize, text.as_ptr());
    }

    unsafe fn add_popup_separator(menu: Hmenu) {
        AppendMenuW(menu, MF_SEPARATOR, 0, null());
    }

    unsafe fn popup_point(source: Hwnd, x: i32, y: i32) -> Point {
        if x == -1 && y == -1 {
            let mut point = Point { x: 0, y: 0 };
            GetCursorPos(&mut point);
            return point;
        }
        let _ = source;
        Point { x, y }
    }

    unsafe fn select_listbox_item_at_screen(list: Hwnd, screen: Point) -> Option<usize> {
        let mut local = screen;
        if ScreenToClient(list, &mut local) == 0 {
            return None;
        }
        let packed = ((local.y as u16 as u32) << 16) | local.x as u16 as u32;
        let result = SendMessageW(list, LB_ITEMFROMPOINT, 0, packed as Lparam) as u32;
        if result >> 16 != 0 {
            return None;
        }
        let index = (result & 0xffff) as usize;
        SendMessageW(list, LB_SETCURSEL, index, 0);
        Some(index)
    }

    unsafe fn chat_block_at_screen(transcript: Hwnd, screen: Point) -> Option<DesktopChatBlock> {
        let mut local = screen;
        if ScreenToClient(transcript, &mut local) == 0 {
            return None;
        }
        let scroll = chat_scroll_current().round() as i32;
        CHAT_LAYOUT_CACHE
            .get_or_init(|| Mutex::new(ChatLayoutCache::default()))
            .lock()
            .ok()
            .and_then(|cache| {
                cache.cards.iter().find_map(|card| {
                    let top = card.top - scroll;
                    let bottom = top + card.height;
                    (local.x >= card.x
                        && local.x <= card.x + card.width
                        && local.y >= top
                        && local.y <= bottom)
                        .then(|| card.block.clone())
                })
            })
    }

    unsafe fn selected_file_entry(parent: Hwnd) -> Option<super::DesktopFileEntry> {
        let list = GetDlgItem(parent, ID_FILE_LIST);
        let selected = SendMessageW(list, LB_GETCURSEL, 0, 0);
        if selected < 0 {
            return None;
        }
        FILE_BROWSER_LISTING
            .get_or_init(|| Mutex::new(DesktopFileListing::default()))
            .lock()
            .ok()
            .and_then(|listing| listing.entries.get(selected as usize).cloned())
    }

    unsafe fn dispatch_ui_action(parent: Hwnd, action: UiAction) {
        match action {
            UiAction::ActivateWorkspace(index) => {
                invoke(parent, move |host| host.switch_workspace(index));
            }
            UiAction::SelectConversation(index) => {
                invoke(parent, move |host| host.select_conversation(index));
            }
            UiAction::NewChat => {
                invoke(parent, |host| host.new_conversation());
            }
            UiAction::RefreshProject => {
                invoke(parent, |host| host.refresh());
            }
            UiAction::RebuildContextIndex => {
                queue_simple_work(parent, BackgroundAction::Index, "Context index");
            }
            UiAction::ArchiveConversation => {
                invoke(parent, |host| host.archive_conversation());
            }
            UiAction::CopyText(text) | UiAction::CopyPath(text) => {
                if text.is_empty() {
                    return;
                }
                if let Err(error) = set_clipboard_text(parent, &text) {
                    show_error(parent, &error);
                } else {
                    set_text(
                        GetDlgItem(parent, ID_STATUS),
                        "Cortex | Copied to clipboard",
                    );
                }
            }
            UiAction::RateMessage { message_id, score } => {
                rate_card(parent, &message_id, score);
            }
            UiAction::Regenerate { message_id } => {
                begin_redo(parent, &message_id);
            }
            UiAction::OpenWorkbenchFile(relative_path) => {
                open_file_in_workbench(parent, &relative_path);
            }
            UiAction::FocusAddProject => {
                LEFT_COLLAPSED.store(false, Ordering::SeqCst);
                layout(parent);
                SetFocus(GetDlgItem(parent, ID_WORKSPACE_PATH));
            }
            UiAction::OpenSettings => open_config_panel(parent),
            UiAction::OpenCommandPalette => open_command_palette(parent),
            UiAction::ShowPanel(panel) => match panel {
                UiPanel::Files => {
                    RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                    set_right_pane(parent, ID_FILES, "Files", "");
                    layout(parent);
                    load_file_browser(parent, false, "");
                }
                UiPanel::Changes => {
                    RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                    set_right_pane(
                        parent,
                        ID_CHANGES,
                        "Changes",
                        "Git diff + Cortex transaction review",
                    );
                    layout(parent);
                    invoke(parent, |host| host.show_changes());
                }
                UiPanel::Memory => {
                    RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                    set_right_pane(parent, ID_VAULT, "Memory", "Search project memory...");
                    layout(parent);
                    let query = get_text(GetDlgItem(parent, ID_QUERY));
                    invoke(parent, |host| host.search_vault(query.trim()));
                }
                UiPanel::Artifacts => {
                    RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                    set_right_pane(
                        parent,
                        ID_ARTIFACTS,
                        "Artifacts",
                        "Recent artifacts and visual evidence",
                    );
                    layout(parent);
                    invoke(parent, |host| host.show_artifacts());
                }
                UiPanel::Tasks => {
                    RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
                    set_right_pane(parent, ID_TASKS, "Tasks", "Recent Cortex jobs and progress");
                    layout(parent);
                    invoke(parent, |host| host.show_tasks());
                }
                UiPanel::Settings => open_config_panel(parent),
            },
            UiAction::ShowChat => {
                WORKBENCH_ACTIVE.store(false, Ordering::SeqCst);
                layout(parent);
            }
            UiAction::ShowWorkbench => {
                WORKBENCH_ACTIVE.store(true, Ordering::SeqCst);
                refresh_workbench_document_list(parent);
                show_active_workbench_document(parent);
                layout(parent);
            }
            UiAction::ToggleProjectSidebar => {
                LEFT_COLLAPSED.fetch_xor(true, Ordering::SeqCst);
                layout(parent);
            }
            UiAction::ToggleContextPanel => {
                RIGHT_COLLAPSED.fetch_xor(true, Ordering::SeqCst);
                layout(parent);
            }
            UiAction::RunBuild => {
                queue_simple_work(parent, BackgroundAction::Build, "Build check");
            }
            UiAction::ProviderStatus => {
                queue_simple_work(parent, BackgroundAction::Provider, "Provider probe");
            }
            UiAction::ScanLibrary => {
                queue_simple_work(parent, BackgroundAction::LibraryScan, "Scan library");
            }
        }
    }

    unsafe fn execute_context_command(
        parent: Hwnd,
        command: u32,
        nav_row: Option<NavRow>,
        chat: Option<DesktopChatBlock>,
        file: Option<super::DesktopFileEntry>,
    ) {
        match command {
            CMD_CTX_EXPORT_CHAT_TXT | CMD_CTX_EXPORT_CHAT_MARKDOWN | CMD_CTX_EXPORT_CHAT_JSON => {
                let Some(NavRow::Conversation(index)) = nav_row else {
                    return;
                };
                let (format, label) = match command {
                    CMD_CTX_EXPORT_CHAT_TXT => ("txt", "Chat exported as TXT"),
                    CMD_CTX_EXPORT_CHAT_MARKDOWN => ("markdown", "Chat exported as Markdown"),
                    _ => ("json", "Chat exported as JSON"),
                };
                let _ = invoke_export(parent, label, |host| host.export_conversation(index, format));
                return;
            }
            CMD_CTX_EXPORT_PROJECT_MARKDOWN => {
                let Some(NavRow::Workspace(index)) = nav_row else {
                    return;
                };
                let _ = invoke_export(parent, "Project chats exported as Markdown", |host| {
                    host.switch_workspace(index)?;
                    host.export_project_conversations("markdown")
                });
                return;
            }
            _ => {}
        }

        let action = match command {
            CMD_CTX_OPEN => match nav_row {
                Some(NavRow::Workspace(index)) => Some(UiAction::ActivateWorkspace(index)),
                Some(NavRow::Conversation(index)) => Some(UiAction::SelectConversation(index)),
                _ => None,
            },
            CMD_CTX_NEW_CHAT => Some(UiAction::NewChat),
            CMD_CTX_REFRESH => Some(UiAction::RefreshProject),
            CMD_CTX_INDEX => Some(UiAction::RebuildContextIndex),
            CMD_CTX_ARCHIVE => Some(UiAction::ArchiveConversation),
            CMD_CTX_COPY => {
                let text = chat
                    .as_ref()
                    .map(|block| block.text.clone())
                    .or_else(|| {
                        nav_row.and_then(|_| {
                            let list = GetDlgItem(parent, ID_WORKSPACES);
                            let selected = SendMessageW(list, LB_GETCURSEL, 0, 0);
                            (selected >= 0).then(|| listbox_item_text(list, selected as usize))
                        })
                    })
                    .or_else(|| {
                        let active = WORKBENCH_ACTIVE_DOCUMENT.load(Ordering::SeqCst);
                        WORKBENCH_DOCUMENTS
                            .get_or_init(|| Mutex::new(Vec::new()))
                            .lock()
                            .ok()
                            .and_then(|documents| {
                                documents.get(active).map(|item| item.content.clone())
                            })
                    })
                    .unwrap_or_default();
                (!text.is_empty()).then_some(UiAction::CopyText(text))
            }
            CMD_CTX_UPVOTE => chat.as_ref().and_then(|block| {
                (!block.message_id.is_empty()).then(|| UiAction::RateMessage {
                    message_id: block.message_id.clone(),
                    score: if block.feedback_score > 0 { 0 } else { 1 },
                })
            }),
            CMD_CTX_DOWNVOTE => chat.as_ref().and_then(|block| {
                (!block.message_id.is_empty()).then(|| UiAction::RateMessage {
                    message_id: block.message_id.clone(),
                    score: if block.feedback_score < 0 { 0 } else { -1 },
                })
            }),
            CMD_CTX_REGENERATE => chat.as_ref().and_then(|block| {
                (!block.message_id.is_empty()).then(|| UiAction::Regenerate {
                    message_id: block.message_id.clone(),
                })
            }),
            CMD_CTX_OPEN_WORKBENCH => file.as_ref().and_then(|entry| {
                (!entry.is_directory && !FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst))
                    .then(|| UiAction::OpenWorkbenchFile(entry.relative_path.clone()))
            }),
            CMD_CTX_COPY_PATH => {
                let path = file
                    .as_ref()
                    .map(|entry| entry.relative_path.clone())
                    .or_else(|| {
                        let active = WORKBENCH_ACTIVE_DOCUMENT.load(Ordering::SeqCst);
                        WORKBENCH_DOCUMENTS
                            .get_or_init(|| Mutex::new(Vec::new()))
                            .lock()
                            .ok()
                            .and_then(|documents| {
                                documents.get(active).map(|item| item.path.clone())
                            })
                    });
                path.map(UiAction::CopyPath)
            }
            CMD_CTX_NEW_PROJECT => Some(UiAction::FocusAddProject),
            CMD_CTX_SETTINGS => Some(UiAction::OpenSettings),
            CMD_CTX_COMMANDS => Some(UiAction::OpenCommandPalette),
            _ => None,
        };
        if let Some(action) = action {
            dispatch_ui_action(parent, action);
        }
    }

    unsafe fn show_native_context_menu(parent: Hwnd, source: Hwnd, x: i32, y: i32) {
        let point = popup_point(source, x, y);
        let source_id = if source.is_null() {
            0
        } else {
            GetDlgCtrlID(source)
        };
        let menu = CreatePopupMenu();
        if menu.is_null() {
            return;
        }

        let mut nav_row = None;
        let mut chat = None;
        let mut file = None;

        if source_id == ID_WORKSPACES {
            let index = if x == -1 && y == -1 {
                let selected = SendMessageW(source, LB_GETCURSEL, 0, 0);
                (selected >= 0).then_some(selected as usize)
            } else {
                select_listbox_item_at_screen(source, point).or_else(|| {
                    let selected = SendMessageW(source, LB_GETCURSEL, 0, 0);
                    (selected >= 0).then_some(selected as usize)
                })
            };
            nav_row = index.and_then(|index| {
                NAV_ROWS
                    .get_or_init(|| Mutex::new(Vec::new()))
                    .lock()
                    .ok()
                    .and_then(|rows| rows.get(index).copied())
            });
            match nav_row {
                Some(NavRow::Workspace(_)) => {
                    add_popup_item(menu, CMD_CTX_OPEN, "Open / Activate Project", true);
                    add_popup_item(menu, CMD_CTX_NEW_CHAT, "New Chat", true);
                    add_popup_separator(menu);
                    add_popup_item(menu, CMD_CTX_REFRESH, "Refresh Project", true);
                    add_popup_item(menu, CMD_CTX_INDEX, "Re-index Project Context", true);
                    add_popup_item(
                        menu,
                        CMD_CTX_EXPORT_PROJECT_MARKDOWN,
                        "Export Project Chats as Markdown",
                        true,
                    );
                    add_popup_separator(menu);
                    add_popup_item(menu, CMD_CTX_COPY, "Copy Project Name", true);
                }
                Some(NavRow::Conversation(_)) => {
                    add_popup_item(menu, CMD_CTX_OPEN, "Open Chat", true);
                    add_popup_item(menu, CMD_CTX_COPY, "Copy Chat Name", true);
                    add_popup_separator(menu);
                    add_popup_item(menu, CMD_CTX_EXPORT_CHAT_TXT, "Export Chat as TXT", true);
                    add_popup_item(
                        menu,
                        CMD_CTX_EXPORT_CHAT_MARKDOWN,
                        "Export Chat as Markdown",
                        true,
                    );
                    add_popup_item(menu, CMD_CTX_EXPORT_CHAT_JSON, "Export Chat as JSON", true);
                    add_popup_separator(menu);
                    add_popup_item(menu, CMD_CTX_ARCHIVE, "Archive Chat", true);
                }
                _ => {
                    add_popup_item(menu, CMD_CTX_NEW_PROJECT, "Add Project", true);
                    add_popup_item(menu, CMD_CTX_NEW_CHAT, "New Chat", true);
                }
            }
        } else if source_id == ID_TRANSCRIPT {
            chat = chat_block_at_screen(source, point);
            if let Some(block) = chat.as_ref() {
                add_popup_item(menu, CMD_CTX_COPY, "Copy Message", !block.text.is_empty());
                if block.role != "user" && !block.message_id.is_empty() {
                    add_popup_separator(menu);
                    add_popup_item(menu, CMD_CTX_UPVOTE, "Upvote", true);
                    add_popup_item(menu, CMD_CTX_DOWNVOTE, "Downvote", true);
                    add_popup_item(menu, CMD_CTX_REGENERATE, "Regenerate Response", true);
                }
            } else {
                add_popup_item(menu, CMD_CTX_NEW_CHAT, "New Chat", true);
                add_popup_item(menu, CMD_CTX_COMMANDS, "Command Palette", true);
            }
        } else if source_id == ID_FILE_LIST {
            if !(x == -1 && y == -1) {
                select_listbox_item_at_screen(source, point);
            }
            file = selected_file_entry(parent);
            let can_open = file.as_ref().is_some_and(|entry| {
                !entry.is_directory && !FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst)
            });
            add_popup_item(menu, CMD_CTX_OPEN_WORKBENCH, "Open in Workbench", can_open);
            add_popup_item(menu, CMD_CTX_COPY_PATH, "Copy Path", file.is_some());
            add_popup_separator(menu);
            add_popup_item(menu, CMD_CTX_REFRESH, "Refresh", true);
        } else if matches!(
            source_id,
            ID_WORKBENCH_EDITOR | ID_WORKBENCH_PATH | ID_WORKBENCH_TABS
        ) {
            let active = WORKBENCH_ACTIVE_DOCUMENT.load(Ordering::SeqCst);
            let has_document = WORKBENCH_DOCUMENTS
                .get_or_init(|| Mutex::new(Vec::new()))
                .lock()
                .map(|documents| active < documents.len())
                .unwrap_or(false);
            add_popup_item(menu, CMD_CTX_COPY, "Copy Document", has_document);
            add_popup_item(menu, CMD_CTX_COPY_PATH, "Copy Document Path", has_document);
            add_popup_separator(menu);
            add_popup_item(menu, CMD_CTX_COMMANDS, "Command Palette", true);
        } else if matches!(source_id, ID_INFO | ID_ACTIVITY) {
            let text = get_text(source);
            chat = Some(DesktopChatBlock {
                text,
                ..DesktopChatBlock::default()
            });
            add_popup_item(menu, CMD_CTX_COPY, "Copy Panel Text", true);
            add_popup_separator(menu);
            add_popup_item(menu, CMD_CTX_REFRESH, "Refresh", true);
        } else {
            add_popup_item(menu, CMD_CTX_NEW_CHAT, "New Chat", true);
            add_popup_item(menu, CMD_CTX_COMMANDS, "Command Palette", true);
            add_popup_separator(menu);
            add_popup_item(menu, CMD_CTX_REFRESH, "Refresh", true);
            add_popup_item(menu, CMD_CTX_SETTINGS, "Settings", true);
        }

        let command = TrackPopupMenuEx(
            menu,
            TPM_RIGHTBUTTON | TPM_RETURNCMD,
            point.x,
            point.y,
            parent,
            null(),
        );
        DestroyMenu(menu);
        if command != 0 {
            execute_context_command(parent, command, nav_row, chat, file);
        }
    }

    fn command_catalog() -> Vec<UiCommand> {
        [
            (
                "chat.new",
                "New Chat",
                "Chat",
                &["conversation", "compose"][..],
            ),
            ("view.chat", "Open Chat View", "View", &["conversation"][..]),
            (
                "view.workbench",
                "Open Workbench",
                "View",
                &["code", "editor"][..],
            ),
            (
                "panel.files",
                "Show Files",
                "Panel",
                &["browser", "project"][..],
            ),
            (
                "panel.changes",
                "Show Changes",
                "Panel",
                &["diff", "review"][..],
            ),
            (
                "panel.memory",
                "Show Memory",
                "Panel",
                &["vault", "context"][..],
            ),
            (
                "panel.artifacts",
                "Show Artifacts",
                "Panel",
                &["outputs"][..],
            ),
            ("panel.tasks", "Show Tasks", "Panel", &["jobs", "work"][..]),
            (
                "panel.settings",
                "Show Settings",
                "Panel",
                &["config", "preferences"][..],
            ),
            (
                "project.refresh",
                "Refresh Project",
                "Project",
                &["reload"][..],
            ),
            (
                "project.index",
                "Rebuild Context Index",
                "Project",
                &["search", "memory"][..],
            ),
            (
                "project.build",
                "Run Build Check",
                "Project",
                &["cargo", "compile"][..],
            ),
            (
                "provider.status",
                "Provider Status",
                "Cortex",
                &["lm studio", "model"][..],
            ),
            (
                "library.scan",
                "Scan Project Library",
                "Library",
                &["drive", "projects"][..],
            ),
            (
                "view.left",
                "Toggle Project Sidebar",
                "View",
                &["navigation"][..],
            ),
            (
                "view.right",
                "Toggle Context Panel",
                "View",
                &["files", "settings"][..],
            ),
        ]
        .into_iter()
        .map(|(id, title, category, keywords)| UiCommand {
            id: id.into(),
            title: title.into(),
            category: category.into(),
            keywords: keywords.iter().map(|value| (*value).into()).collect(),
        })
        .collect()
    }

    unsafe fn refresh_command_palette(hwnd: Hwnd) {
        let query = get_text(GetDlgItem(hwnd, ID_COMMAND_QUERY));
        let mut palette = CommandPalette::with_commands(command_catalog());
        palette.query = query;
        let matches = palette.matches(14);
        let list = GetDlgItem(hwnd, ID_COMMAND_LIST);
        SendMessageW(list, LB_RESETCONTENT, 0, 0);
        let mut results = Vec::new();
        for matched in matches {
            if let Some(command) = palette.commands.get(matched.command_index).cloned() {
                let label = wide(&format!("{}  ·  {}", command.category, command.title));
                SendMessageW(list, LB_ADDSTRING, 0, label.as_ptr() as Lparam);
                results.push(command);
            }
        }
        if !results.is_empty() {
            SendMessageW(list, LB_SETCURSEL, 0, 0);
        }
        if let Ok(mut stored) = COMMAND_PALETTE_RESULTS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        {
            *stored = results;
        }
    }

    unsafe fn open_command_palette(hwnd: Hwnd) {
        COMMAND_PALETTE_VISIBLE.store(true, Ordering::SeqCst);
        set_text(GetDlgItem(hwnd, ID_COMMAND_QUERY), "");
        refresh_command_palette(hwnd);
        layout(hwnd);
        SetFocus(GetDlgItem(hwnd, ID_COMMAND_QUERY));
    }

    unsafe fn close_command_palette(hwnd: Hwnd) {
        COMMAND_PALETTE_VISIBLE.store(false, Ordering::SeqCst);
        show_control(hwnd, ID_COMMAND_QUERY, false);
        show_control(hwnd, ID_COMMAND_LIST, false);
        show_control(hwnd, ID_COMMAND_HINT, false);
        SetFocus(GetDlgItem(
            hwnd,
            if WORKBENCH_ACTIVE.load(Ordering::SeqCst) {
                ID_WORKBENCH_EDITOR
            } else {
                ID_INPUT
            },
        ));
        InvalidateRect(hwnd, null(), 1);
    }

    fn control_ui_action(id: i32) -> Option<UiAction> {
        match id {
            ID_NEW_CHAT => Some(UiAction::NewChat),
            ID_ARCHIVE_CHAT => Some(UiAction::ArchiveConversation),
            ID_REFRESH => Some(UiAction::RefreshProject),
            ID_CONTEXT_INDEX => Some(UiAction::RebuildContextIndex),
            ID_LIBRARY_SCAN => Some(UiAction::ScanLibrary),
            ID_PROVIDER => Some(UiAction::ProviderStatus),
            ID_BUILD => Some(UiAction::RunBuild),
            ID_TOGGLE_LEFT => Some(UiAction::ToggleProjectSidebar),
            ID_TOGGLE_RIGHT => Some(UiAction::ToggleContextPanel),
            ID_MODE_CHAT => Some(UiAction::ShowChat),
            ID_MODE_WORKBENCH => Some(UiAction::ShowWorkbench),
            ID_FILES => Some(UiAction::ShowPanel(UiPanel::Files)),
            ID_CHANGES => Some(UiAction::ShowPanel(UiPanel::Changes)),
            ID_VAULT => Some(UiAction::ShowPanel(UiPanel::Memory)),
            ID_ARTIFACTS => Some(UiAction::ShowPanel(UiPanel::Artifacts)),
            ID_TASKS => Some(UiAction::ShowPanel(UiPanel::Tasks)),
            ID_SETTINGS => Some(UiAction::ShowPanel(UiPanel::Settings)),
            _ => None,
        }
    }

    unsafe fn execute_command_palette(hwnd: Hwnd) {
        let list = GetDlgItem(hwnd, ID_COMMAND_LIST);
        let selected = SendMessageW(list, LB_GETCURSEL, 0, 0);
        if selected < 0 {
            return;
        }
        let command = COMMAND_PALETTE_RESULTS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
            .ok()
            .and_then(|results| results.get(selected as usize).cloned());
        let Some(command) = command else {
            return;
        };
        close_command_palette(hwnd);
        let action = match command.id.as_str() {
            "chat.new" => Some(UiAction::NewChat),
            "view.chat" => Some(UiAction::ShowChat),
            "view.workbench" => Some(UiAction::ShowWorkbench),
            "panel.files" => Some(UiAction::ShowPanel(UiPanel::Files)),
            "panel.changes" => Some(UiAction::ShowPanel(UiPanel::Changes)),
            "panel.memory" => Some(UiAction::ShowPanel(UiPanel::Memory)),
            "panel.artifacts" => Some(UiAction::ShowPanel(UiPanel::Artifacts)),
            "panel.tasks" => Some(UiAction::ShowPanel(UiPanel::Tasks)),
            "panel.settings" => Some(UiAction::ShowPanel(UiPanel::Settings)),
            "project.refresh" => Some(UiAction::RefreshProject),
            "project.index" => Some(UiAction::RebuildContextIndex),
            "project.build" => Some(UiAction::RunBuild),
            "provider.status" => Some(UiAction::ProviderStatus),
            "library.scan" => Some(UiAction::ScanLibrary),
            "view.left" => Some(UiAction::ToggleProjectSidebar),
            "view.right" => Some(UiAction::ToggleContextPanel),
            _ => None,
        };
        if let Some(action) = action {
            dispatch_ui_action(hwnd, action);
        }
    }

    unsafe fn handle_global_shortcut(hwnd: Hwnd, message: &Msg) -> bool {
        if message.message != WM_KEYDOWN {
            return false;
        }
        let ctrl = (GetKeyState(VK_CONTROL) as u16 & 0x8000) != 0;
        let shift = (GetKeyState(VK_SHIFT) as u16 & 0x8000) != 0;

        if COMMAND_PALETTE_VISIBLE.load(Ordering::SeqCst) {
            match message.w_param {
                VK_ESCAPE => {
                    close_command_palette(hwnd);
                    return true;
                }
                VK_UP | VK_DOWN => {
                    let list = GetDlgItem(hwnd, ID_COMMAND_LIST);
                    let count = COMMAND_PALETTE_RESULTS
                        .get_or_init(|| Mutex::new(Vec::new()))
                        .lock()
                        .map(|items| items.len())
                        .unwrap_or(0);
                    if count > 0 {
                        let current = SendMessageW(list, LB_GETCURSEL, 0, 0).max(0) as usize;
                        let next = if message.w_param == VK_UP {
                            current.saturating_sub(1)
                        } else {
                            (current + 1).min(count - 1)
                        };
                        SendMessageW(list, LB_SETCURSEL, next, 0);
                    }
                    return true;
                }
                VK_RETURN => {
                    execute_command_palette(hwnd);
                    return true;
                }
                _ => {}
            }
        }

        if ctrl && (message.w_param == VK_K || (shift && message.w_param == VK_P)) {
            open_command_palette(hwnd);
            return true;
        }
        // O2D-R051N9STOR1J_H33_NAVIGATION_CONTEXT_KEYS
        // Keyboard context-menu access is handled centrally for navigation and
        // other native controls; no fragile listbox-specific subclass is required.
        if message.w_param == VK_APPS || (shift && message.w_param == VK_F10) {
            show_native_context_menu(hwnd, message.hwnd, -1, -1);
            return true;
        }
        false
    }

    unsafe fn control(
        parent: Hwnd,
        instance: Hinstance,
        class_name: &str,
        text: &str,
        style: u32,
        id: i32,
    ) -> Hwnd {
        let is_button = class_name.eq_ignore_ascii_case("BUTTON");
        let class_name = wide(class_name);
        let text = wide(text);
        let actual_style = if is_button {
            style | BS_OWNERDRAW | WS_CLIPSIBLINGS
        } else {
            style | WS_CLIPSIBLINGS
        };
        let hwnd = CreateWindowExW(
            0,
            class_name.as_ptr(),
            text.as_ptr(),
            actual_style,
            0,
            0,
            100,
            30,
            parent,
            id as usize as Hmenu,
            instance,
            null_mut(),
        );
        let font = ui_font();
        if !hwnd.is_null() {
            if is_button {
                // Disable light visual-style painting so WM_CTLCOLORBTN can use
                // the Cortex dark surface consistently.
                let empty = wide("");
                let _ = SetWindowTheme(hwnd, empty.as_ptr(), empty.as_ptr());
            } else {
                // On supported Windows builds this also darkens native scrollbars.
                let dark = wide("DarkMode_Explorer");
                let _ = SetWindowTheme(hwnd, dark.as_ptr(), null());
            }
            if !font.is_null() {
                SendMessageW(hwnd, WM_SETFONT, font as usize, 1);
            }
        }
        hwnd
    }

    unsafe fn current_shell_layout(hwnd: Hwnd) -> Option<ShellLayout> {
        let mut rect = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        if GetClientRect(hwnd, &mut rect) == 0 {
            return None;
        }
        let width = (rect.right - rect.left).max(900) as f32;
        let height = (rect.bottom - rect.top).max(600) as f32;
        ShellLayout::calculate(
            &UiTheme::default(),
            ShellLayoutInput {
                viewport: LayoutSize::new(width, height),
                left_collapsed: LEFT_COLLAPSED.load(Ordering::SeqCst),
                right_collapsed: RIGHT_COLLAPSED.load(Ordering::SeqCst),
                activity_expanded: ACTIVITY_EXPANDED.load(Ordering::SeqCst),
                activity_height: 240.0,
            },
        )
        .ok()
    }

    unsafe fn paint_shell_borders(hwnd: Hwnd) {
        let mut paint = PaintStruct {
            hdc: null_mut(),
            erase: 0,
            paint: Rect {
                left: 0,
                top: 0,
                right: 0,
                bottom: 0,
            },
            restore: 0,
            inc_update: 0,
            reserved: [0; 32],
        };
        let hdc = BeginPaint(hwnd, &mut paint);
        if hdc.is_null() {
            return;
        }

        let mut client = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        GetClientRect(hwnd, &mut client);
        FillRect(hdc, &client, background_brush());

        if let Some(shell) = current_shell_layout(hwnd) {
            for separator in [
                Rect {
                    left: shell.left.right().round() as i32 - 1,
                    top: shell.body.y.round() as i32,
                    right: shell.left.right().round() as i32 + 1,
                    bottom: shell.body.bottom().round() as i32,
                },
                Rect {
                    left: shell.right.x.round() as i32 - 1,
                    top: shell.body.y.round() as i32,
                    right: shell.right.x.round() as i32 + 1,
                    bottom: shell.body.bottom().round() as i32,
                },
                Rect {
                    left: 0,
                    top: shell.status.y.round() as i32 - 1,
                    right: client.right,
                    bottom: shell.status.y.round() as i32 + 1,
                },
            ] {
                FillRect(hdc, &separator, border_brush());
            }

            if !WORKBENCH_ACTIVE.load(Ordering::SeqCst) {
                let center = shell.center_content();
                let composer = Rect {
                    left: center.x.round() as i32 + 12,
                    top: shell.body.bottom().round() as i32 - 70,
                    right: center.right().round() as i32 - 12,
                    bottom: shell.body.bottom().round() as i32 - 4,
                };
                paint_rounded_surface(hdc, &composer, field_brush(), border_brush(), 18);
            }

            if COMMAND_PALETTE_VISIBLE.load(Ordering::SeqCst) {
                let center = shell.center_content();
                let center_left = center.x.round() as i32;
                let center_width = center.width.round() as i32;
                let palette_width = (center_width - 72).clamp(360, 720);
                let palette_x = center_left + (center_width - palette_width) / 2;
                let palette_y = shell.body.y.round() as i32 + 54;
                let palette_height =
                    (shell.body.bottom().round() as i32 - palette_y - 42).clamp(220, 430);
                let palette = Rect {
                    left: palette_x,
                    top: palette_y - 8,
                    right: palette_x + palette_width,
                    bottom: palette_y + palette_height,
                };
                paint_rounded_surface(hdc, &palette, surface_brush(), border_brush(), 16);
            }
        }

        EndPaint(hwnd, &paint);
    }

    unsafe fn refresh_workbench_document_list(hwnd: Hwnd) {
        let list = GetDlgItem(hwnd, ID_WORKBENCH_TABS);
        SendMessageW(list, LB_RESETCONTENT, 0, 0);
        let Ok(documents) = WORKBENCH_DOCUMENTS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        else {
            return;
        };
        for document in documents.iter() {
            let label = wide(&document.path);
            SendMessageW(list, LB_ADDSTRING, 0, label.as_ptr() as Lparam);
        }
        let active = WORKBENCH_ACTIVE_DOCUMENT.load(Ordering::SeqCst);
        if active != usize::MAX && active < documents.len() {
            SendMessageW(list, LB_SETCURSEL, active, 0);
        }
    }

    unsafe fn show_active_workbench_document(hwnd: Hwnd) {
        let active = WORKBENCH_ACTIVE_DOCUMENT.load(Ordering::SeqCst);
        let Ok(documents) = WORKBENCH_DOCUMENTS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        else {
            return;
        };
        let Some(document) = documents.get(active) else {
            set_text(GetDlgItem(hwnd, ID_WORKBENCH_PATH), "No document open");
            set_text(GetDlgItem(hwnd, ID_WORKBENCH_EDITOR), "");
            return;
        };
        set_text(
            GetDlgItem(hwnd, ID_WORKBENCH_PATH),
            &format!(
                "{}  ·  {}{}",
                document.path,
                if document.language.is_empty() {
                    "Text"
                } else {
                    &document.language
                },
                if document.truncated {
                    "  ·  preview truncated"
                } else {
                    ""
                },
            ),
        );
        set_text(GetDlgItem(hwnd, ID_WORKBENCH_EDITOR), &document.content);
    }

    unsafe fn open_file_in_workbench(hwnd: Hwnd, relative_path: &str) {
        let Some(host) = HOST.get() else {
            return;
        };
        let result = host
            .lock()
            .map_err(|_| "Cortex desktop host lock poisoned".to_string())
            .and_then(|mut host| host.open_workbench_file(relative_path));

        match result {
            Ok(document) => {
                let mut active = 0usize;
                if let Ok(mut documents) = WORKBENCH_DOCUMENTS
                    .get_or_init(|| Mutex::new(Vec::new()))
                    .lock()
                {
                    if let Some(index) =
                        documents.iter().position(|item| item.path == document.path)
                    {
                        documents[index] = document;
                        active = index;
                    } else {
                        documents.push(document);
                        active = documents.len() - 1;
                    }
                }
                WORKBENCH_ACTIVE_DOCUMENT.store(active, Ordering::SeqCst);
                WORKBENCH_ACTIVE.store(true, Ordering::SeqCst);
                refresh_workbench_document_list(hwnd);
                show_active_workbench_document(hwnd);
                layout(hwnd);
            }
            Err(error) => show_error(hwnd, &error),
        }
    }

    unsafe fn layout(hwnd: Hwnd) {
        let mut rect = Rect {
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
        };
        if GetClientRect(hwnd, &mut rect) == 0 {
            return;
        }
        let width = (rect.right - rect.left).max(900);
        let margin = 10;
        let top = 14;
        let left_collapsed = LEFT_COLLAPSED.load(Ordering::SeqCst);
        let right_collapsed = RIGHT_COLLAPSED.load(Ordering::SeqCst);
        let activity_expanded = ACTIVITY_EXPANDED.load(Ordering::SeqCst);
        let Some(shell) = current_shell_layout(hwnd) else {
            return;
        };

        let status_y = shell.status.y.round() as i32;
        let status_height = shell.status.height.round() as i32;
        let activity_top = shell.activity.y.round() as i32;
        let activity_height = shell.activity.height.round() as i32;
        let content_bottom = shell.body.bottom().round() as i32;
        let center_content = shell.center_content();
        let center_left = center_content.x.round() as i32;
        let center_width = center_content.width.round() as i32;

        move_control(
            hwnd,
            ID_STATUS,
            margin,
            status_y,
            width - 132,
            status_height - 2,
        );

        let sidebar = SidebarLayout::calculate(&UiTheme::default(), shell.left, left_collapsed);
        move_control(
            hwnd,
            ID_TOGGLE_LEFT,
            sidebar.toggle.x.round() as i32,
            sidebar.toggle.y.round() as i32,
            sidebar.toggle.width.round() as i32,
            sidebar.toggle.height.round() as i32,
        );
        set_text(
            GetDlgItem(hwnd, ID_TOGGLE_LEFT),
            if left_collapsed { "›" } else { "‹" },
        );

        let rail_ids = [
            ID_RAIL_PROJECTS,
            ID_RAIL_CHATS,
            ID_RAIL_FILES,
            ID_RAIL_ADD,
            ID_RAIL_CONFIG,
        ];

        if left_collapsed {
            for id in [
                ID_LEFT_TITLE,
                ID_WORKSPACE_PATH,
                ID_ATTACH_WORKSPACE,
                ID_LIBRARY_ROOT,
                ID_LIBRARY_SCAN,
                ID_WORKSPACES,
                ID_NEW_CHAT,
                ID_ARCHIVE_CHAT,
                ID_CONVERSATIONS,
            ] {
                show_control(hwnd, id, false);
            }
            for (id, rect) in rail_ids.iter().zip(sidebar.rail_items.iter()) {
                show_control(hwnd, *id, true);
                move_control(
                    hwnd,
                    *id,
                    rect.x.round() as i32,
                    rect.y.round() as i32,
                    rect.width.round() as i32,
                    rect.height.round() as i32,
                );
            }
        } else {
            for id in rail_ids {
                show_control(hwnd, id, false);
            }
            for id in [
                ID_LEFT_TITLE,
                ID_WORKSPACE_PATH,
                ID_ATTACH_WORKSPACE,
                ID_WORKSPACES,
                ID_NEW_CHAT,
                ID_ARCHIVE_CHAT,
            ] {
                show_control(hwnd, id, true);
            }
            show_control(hwnd, ID_LIBRARY_ROOT, false);
            show_control(hwnd, ID_LIBRARY_SCAN, false);
            show_control(hwnd, ID_CONVERSATIONS, false);

            move_control(
                hwnd,
                ID_LEFT_TITLE,
                sidebar.header.x.round() as i32,
                sidebar.header.y.round() as i32,
                sidebar.header.width.round() as i32,
                sidebar.header.height.round() as i32,
            );
            move_control(
                hwnd,
                ID_WORKSPACE_PATH,
                sidebar.project_path.x.round() as i32,
                sidebar.project_path.y.round() as i32,
                sidebar.project_path.width.round() as i32,
                sidebar.project_path.height.round() as i32,
            );
            move_control(
                hwnd,
                ID_ATTACH_WORKSPACE,
                sidebar.add_project.x.round() as i32,
                sidebar.add_project.y.round() as i32,
                sidebar.add_project.width.round() as i32,
                sidebar.add_project.height.round() as i32,
            );
            move_control(
                hwnd,
                ID_WORKSPACES,
                sidebar.project_list.x.round() as i32,
                sidebar.project_list.y.round() as i32,
                sidebar.project_list.width.round() as i32,
                sidebar.project_list.height.round() as i32,
            );
            move_control(
                hwnd,
                ID_NEW_CHAT,
                sidebar.new_chat.x.round() as i32,
                sidebar.new_chat.y.round() as i32,
                sidebar.new_chat.width.round() as i32,
                sidebar.new_chat.height.round() as i32,
            );
            move_control(
                hwnd,
                ID_ARCHIVE_CHAT,
                sidebar.archive_chat.x.round() as i32,
                sidebar.archive_chat.y.round() as i32,
                sidebar.archive_chat.width.round() as i32,
                sidebar.archive_chat.height.round() as i32,
            );
        }

        let mode_top = top;
        move_control(hwnd, ID_MODE_CHAT, center_left + 10, mode_top, 72, 30);
        move_control(hwnd, ID_MODE_WORKBENCH, center_left + 88, mode_top, 106, 30);

        let workbench_active = WORKBENCH_ACTIVE.load(Ordering::SeqCst);
        let chat_top = top + 38;
        let composer_height = 66;
        let thinking_height = 28;
        let redo_height = if REDO_ACTIVE.load(Ordering::SeqCst) {
            44
        } else {
            0
        };
        let composer_y = content_bottom - composer_height;

        for id in [ID_TRANSCRIPT, ID_THINKING_BUBBLE, ID_INPUT, ID_SEND] {
            show_control(hwnd, id, !workbench_active);
        }
        for id in [ID_WORKBENCH_TABS, ID_WORKBENCH_PATH, ID_WORKBENCH_EDITOR] {
            show_control(hwnd, id, workbench_active);
        }

        if workbench_active {
            move_control(
                hwnd,
                ID_WORKBENCH_TABS,
                center_left + 10,
                chat_top,
                220,
                content_bottom - chat_top - 8,
            );
            move_control(
                hwnd,
                ID_WORKBENCH_PATH,
                center_left + 240,
                chat_top,
                center_width - 250,
                26,
            );
            move_control(
                hwnd,
                ID_WORKBENCH_EDITOR,
                center_left + 240,
                chat_top + 30,
                center_width - 250,
                content_bottom - chat_top - 38,
            );
        }

        move_control(
            hwnd,
            ID_TRANSCRIPT,
            center_left + 8,
            chat_top,
            center_width - 16,
            composer_y - chat_top - thinking_height - redo_height - 12,
        );
        move_control(
            hwnd,
            ID_THINKING_BUBBLE,
            center_left + 18,
            composer_y - thinking_height - redo_height,
            center_width - 36,
            thinking_height,
        );
        let redo_visible = REDO_ACTIVE.load(Ordering::SeqCst) && !workbench_active;
        for id in [ID_REDO_INPUT, ID_REDO_APPLY, ID_REDO_CANCEL] {
            show_control(hwnd, id, redo_visible);
        }
        if redo_visible {
            let redo_y = composer_y - redo_height + 4;
            move_control(
                hwnd,
                ID_REDO_INPUT,
                center_left + 16,
                redo_y,
                center_width - 218,
                32,
            );
            move_control(
                hwnd,
                ID_REDO_APPLY,
                center_left + center_width - 194,
                redo_y,
                108,
                32,
            );
            move_control(
                hwnd,
                ID_REDO_CANCEL,
                center_left + center_width - 78,
                redo_y,
                62,
                32,
            );
        }
        move_control(
            hwnd,
            ID_INPUT,
            center_left + 28,
            composer_y + 8,
            center_width - 126,
            composer_height - 16,
        );
        move_control(
            hwnd,
            ID_SEND,
            center_left + center_width - 88,
            composer_y + 11,
            64,
            composer_height - 22,
        );

        let context_panel =
            ContextPanelLayout::calculate(&UiTheme::default(), shell.right, right_collapsed);
        move_control(
            hwnd,
            ID_TOGGLE_RIGHT,
            context_panel.toggle.x.round() as i32,
            context_panel.toggle.y.round() as i32,
            context_panel.toggle.width.round() as i32,
            context_panel.toggle.height.round() as i32,
        );
        set_text(
            GetDlgItem(hwnd, ID_TOGGLE_RIGHT),
            if right_collapsed { "‹" } else { "›" },
        );

        let right_ids = [
            ID_FILES,
            ID_CHANGES,
            ID_VAULT,
            ID_ARTIFACTS,
            ID_TASKS,
            ID_SETTINGS,
            ID_RIGHT_HEADER,
            ID_RIGHT_TITLE,
            ID_QUERY,
            ID_INFO,
        ];

        if right_collapsed {
            for id in right_ids {
                show_control(hwnd, id, false);
            }
            set_config_visible(hwnd, false);
            set_file_browser_visible(hwnd, false);
            show_control(hwnd, ID_SETTINGS, true);
            set_text(GetDlgItem(hwnd, ID_SETTINGS), "");
            move_control(
                hwnd,
                ID_SETTINGS,
                context_panel.collapsed_config.x.round() as i32,
                context_panel.collapsed_config.y.round() as i32,
                context_panel.collapsed_config.width.round() as i32,
                context_panel.collapsed_config.height.round() as i32,
            );
        } else {
            for id in right_ids {
                show_control(hwnd, id, true);
            }
            set_text(GetDlgItem(hwnd, ID_SETTINGS), "Settings");
            move_control(
                hwnd,
                ID_RIGHT_HEADER,
                context_panel.header.x.round() as i32,
                context_panel.header.y.round() as i32,
                context_panel.header.width.round() as i32,
                context_panel.header.height.round() as i32,
            );

            for (id, rect) in [
                ID_FILES,
                ID_CHANGES,
                ID_VAULT,
                ID_ARTIFACTS,
                ID_TASKS,
                ID_SETTINGS,
            ]
            .iter()
            .zip(context_panel.tabs.iter())
            {
                move_control(
                    hwnd,
                    *id,
                    rect.x.round() as i32,
                    rect.y.round() as i32,
                    rect.width.round() as i32,
                    rect.height.round() as i32,
                );
            }

            let content = context_panel.content;
            let tools_left = content.x.round() as i32;
            let tools_width = content.width.round() as i32;
            let content_top = content.y.round() as i32;

            if ACTIVE_RIGHT_PANE.load(Ordering::SeqCst) == ID_FILES as usize {
                set_config_visible(hwnd, false);
                set_file_browser_visible(hwnd, true);
                show_control(hwnd, ID_RIGHT_TITLE, false);
                show_control(hwnd, ID_QUERY, false);
                show_control(hwnd, ID_INFO, false);

                let scope_width = ((tools_width - 8) / 2).max(90);
                move_control(
                    hwnd,
                    ID_FILE_SCOPE_PROJECT,
                    tools_left,
                    content_top,
                    scope_width,
                    28,
                );
                move_control(
                    hwnd,
                    ID_FILE_SCOPE_LIBRARY,
                    tools_left + scope_width + 8,
                    content_top,
                    scope_width,
                    28,
                );
                move_control(hwnd, ID_FILE_HOME, tools_left, content_top + 36, 72, 28);
                move_control(hwnd, ID_FILE_UP, tools_left + 80, content_top + 36, 62, 28);
                move_control(
                    hwnd,
                    ID_FILE_PATH,
                    tools_left,
                    content_top + 72,
                    tools_width,
                    36,
                );
                move_control(
                    hwnd,
                    ID_FILE_LIST,
                    tools_left,
                    content_top + 114,
                    tools_width,
                    (content.bottom().round() as i32 - content_top - 114).max(80),
                );
            } else if ACTIVE_RIGHT_PANE.load(Ordering::SeqCst) == ID_SETTINGS as usize {
                set_file_browser_visible(hwnd, false);
                show_control(hwnd, ID_RIGHT_TITLE, false);
                show_control(hwnd, ID_QUERY, false);
                show_control(hwnd, ID_INFO, false);
                set_config_visible(hwnd, true);

                let tab_width = ((tools_width - margin * 4) / 5).max(58);
                for (index, id) in CONFIG_TABS.iter().enumerate() {
                    move_control(
                        hwnd,
                        *id,
                        tools_left + index as i32 * (tab_width + margin),
                        content_top,
                        tab_width,
                        28,
                    );
                }

                let mut row_y = content_top + 42;
                for index in 0..4 {
                    move_control(
                        hwnd,
                        CONFIG_LABELS[index],
                        tools_left,
                        row_y,
                        tools_width,
                        20,
                    );
                    move_control(
                        hwnd,
                        CONFIG_EDITS[index],
                        tools_left,
                        row_y + 22,
                        tools_width,
                        30,
                    );
                    row_y += 62;
                }
                move_control(hwnd, ID_CONFIG_APPLY, tools_left, row_y + 4, 92, 30);
                move_control(
                    hwnd,
                    ID_CONFIG_SECONDARY,
                    tools_left + 102,
                    row_y + 4,
                    112,
                    30,
                );
            } else {
                set_config_visible(hwnd, false);
                set_file_browser_visible(hwnd, false);
                move_control(
                    hwnd,
                    ID_RIGHT_TITLE,
                    tools_left,
                    content_top,
                    tools_width,
                    22,
                );
                move_control(
                    hwnd,
                    ID_QUERY,
                    tools_left,
                    content_top + 28,
                    tools_width,
                    30,
                );
                move_control(
                    hwnd,
                    ID_INFO,
                    tools_left,
                    content_top + 66,
                    tools_width,
                    (content.bottom().round() as i32 - content_top - 66).max(80),
                );
            }
        }

        for id in [
            ID_BUILD,
            ID_REFRESH,
            ID_CONTEXT_INDEX,
            ID_CONTEXT_INDEX_STATUS,
            ID_PROVIDER,
            ID_CANCEL,
            ID_INSPECT,
            ID_PLAN,
            ID_APPLY,
            ID_REPAIR,
        ] {
            show_control(hwnd, id, false);
        }
        move_control(hwnd, ID_TOGGLE_ACTIVITY, width - 116, status_y + 1, 106, 27);
        set_text(
            GetDlgItem(hwnd, ID_TOGGLE_ACTIVITY),
            if activity_expanded {
                "Hide Activity"
            } else {
                "Activity"
            },
        );
        for id in [
            ID_ACTIVITY_CORTEX_TAB,
            ID_ACTIVITY_LMSTUDIO_TAB,
            ID_ACTIVITY_JOBS_TAB,
            ID_ACTIVITY_BUILD_TAB,
            ID_ACTIVITY_GIT_TAB,
            ID_ACTIVITY_NOTIFICATIONS_TAB,
            ID_ACTIVITY,
        ] {
            show_control(hwnd, id, activity_expanded);
        }
        if activity_expanded {
            let activity_tabs = [
                ID_ACTIVITY_CORTEX_TAB,
                ID_ACTIVITY_LMSTUDIO_TAB,
                ID_ACTIVITY_JOBS_TAB,
                ID_ACTIVITY_BUILD_TAB,
                ID_ACTIVITY_GIT_TAB,
                ID_ACTIVITY_NOTIFICATIONS_TAB,
            ];
            let tab_width = ((width - margin * 2 - 5 * 8) / 6).max(88);
            for (index, id) in activity_tabs.iter().enumerate() {
                move_control(
                    hwnd,
                    *id,
                    margin + index as i32 * (tab_width + 8),
                    activity_top + 8,
                    tab_width,
                    28,
                );
            }
            move_control(
                hwnd,
                ID_ACTIVITY,
                margin,
                activity_top + 44,
                width - margin * 2,
                activity_height - 52,
            );
        }

        let palette_visible = COMMAND_PALETTE_VISIBLE.load(Ordering::SeqCst);
        for id in [ID_COMMAND_HINT, ID_COMMAND_QUERY, ID_COMMAND_LIST] {
            show_control(hwnd, id, palette_visible);
        }
        if palette_visible {
            let palette_width = (center_width - 72).clamp(360, 720);
            let palette_x = center_left + (center_width - palette_width) / 2;
            let palette_y = top + 54;
            let palette_height = (content_bottom - palette_y - 42).clamp(220, 430);
            move_control(
                hwnd,
                ID_COMMAND_HINT,
                palette_x + 12,
                palette_y,
                palette_width - 24,
                24,
            );
            move_control(
                hwnd,
                ID_COMMAND_QUERY,
                palette_x + 10,
                palette_y + 28,
                palette_width - 20,
                38,
            );
            move_control(
                hwnd,
                ID_COMMAND_LIST,
                palette_x + 10,
                palette_y + 74,
                palette_width - 20,
                palette_height - 84,
            );
        }

        // Panel toggles and WM_SIZE can expose pixels previously occupied by
        // a larger transcript/control. Repaint the whole shell and the newly
        // sized transcript so no old card pixels remain outside its bounds.
        InvalidateRect(hwnd, null(), 1);
        let transcript = GetDlgItem(hwnd, ID_TRANSCRIPT);
        if !transcript.is_null() {
            InvalidateRect(transcript, null(), 1);
        }
    }

    unsafe fn move_control(parent: Hwnd, id: i32, x: i32, y: i32, width: i32, height: i32) {
        let child = GetDlgItem(parent, id);
        if !child.is_null() {
            MoveWindow(child, x, y, width.max(1), height.max(1), 1);
        }
    }

    unsafe fn show_control(parent: Hwnd, id: i32, visible: bool) {
        let child = GetDlgItem(parent, id);
        if !child.is_null() {
            ShowWindow(child, if visible { SW_SHOW } else { SW_HIDE });
        }
    }

    fn ui_blocking_log_path() -> PathBuf {
        let base = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir);
        base.join("Open2D")
            .join("Cortex")
            .join("logs")
            .join("ui-blocking.log")
    }

    fn record_ui_blocking_boundary(label: &str, elapsed: Duration, detail: &str) {
        let path = ui_blocking_log_path();
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(
                file,
                "elapsed_ms={} boundary={} {}",
                elapsed.as_millis(),
                label,
                detail
            );
        }
    }

    unsafe fn capture_worker(hwnd: Hwnd) -> Result<(Box<dyn DesktopWorker>, String), String> {
        let Some(host) = HOST.get() else {
            return Err("Cortex desktop host is unavailable".into());
        };
        let Ok(mut host) = host.try_lock() else {
            return Err("Cortex UI state is momentarily busy; retry the request.".into());
        };
        let capture_started = Instant::now();
        let snapshot = host.snapshot();
        let target = format!(
            "{} / {}",
            snapshot.workspace_title,
            if snapshot.conversation_title.is_empty() {
                "new chat"
            } else {
                &snapshot.conversation_title
            }
        );
        let worker = host.spawn_worker()?;
        drop(host);
        let capture_elapsed = capture_started.elapsed();
        if capture_elapsed >= Duration::from_millis(50) {
            record_ui_blocking_boundary(
                "capture_worker",
                capture_elapsed,
                &format!("target={target}"),
            );
        }
        let _ = hwnd;
        Ok((worker, target))
    }

    unsafe fn queue_chat_work(hwnd: Hwnd, prompt: String) -> bool {
        let (worker, target) = match capture_worker(hwnd) {
            Ok(value) => value,
            Err(error) => {
                show_error(hwnd, &error);
                return false;
            }
        };
        let accepted = enqueue_work(
            hwnd,
            QueuedWork {
                worker,
                action: BackgroundAction::Chat(prompt),
                label: "Chat".into(),
                target,
            },
        );
        if accepted {
            set_text(GetDlgItem(hwnd, ID_INPUT), "");
        }
        accepted
    }

    unsafe fn queue_agent_work(hwnd: Hwnd, mode: String, prompt: String) -> bool {
        let (worker, target) = match capture_worker(hwnd) {
            Ok(value) => value,
            Err(error) => {
                show_error(hwnd, &error);
                return false;
            }
        };
        let label = match mode.as_str() {
            "inspect" => "Inspect",
            "plan" => "Plan",
            "apply" => "Code",
            "repair" => "Repair",
            _ => "Agent",
        };
        let accepted = enqueue_work(
            hwnd,
            QueuedWork {
                worker,
                action: BackgroundAction::Agent { mode, prompt },
                label: label.into(),
                target,
            },
        );
        if accepted {
            set_text(GetDlgItem(hwnd, ID_INPUT), "");
        }
        accepted
    }

    unsafe fn queue_simple_work(hwnd: Hwnd, action: BackgroundAction, label: &str) -> bool {
        let (worker, target) = match capture_worker(hwnd) {
            Ok(value) => value,
            Err(error) => {
                show_error(hwnd, &error);
                return false;
            }
        };
        enqueue_work(
            hwnd,
            QueuedWork {
                worker,
                action,
                label: label.into(),
                target,
            },
        )
    }

    fn work_semantic_key(work: &QueuedWork) -> String {
        let action = match &work.action {
            BackgroundAction::Chat(prompt) => format!("chat:{prompt}"),
            BackgroundAction::Agent { mode, prompt } => format!("agent:{mode}:{prompt}"),
            BackgroundAction::Provider => "provider".into(),
            BackgroundAction::Build => "build".into(),
            BackgroundAction::Index => "index".into(),
            BackgroundAction::Ingest(paths) => format!("ingest:{}", paths.join("\u{1f}")),
            BackgroundAction::LibraryScan => "library_scan".into(),
            BackgroundAction::Redo {
                message_id,
                instructions,
            } => format!("redo:{message_id}:{instructions}"),
        };
        format!("{}|{}|{action}", work.label.as_str(), work.target.as_str())
    }

    fn work_is_duplicate(key: &str) -> bool {
        let active_duplicate = ASYNC_BUSY.load(Ordering::SeqCst)
            && ACTIVE_WORK_KEY
                .get_or_init(|| Mutex::new(String::new()))
                .lock()
                .map(|active| active.as_str() == key)
                .unwrap_or(false);
        if active_duplicate {
            return true;
        }
        WORK_QUEUE
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
            .map(|queue| queue.iter().any(|queued| work_semantic_key(queued) == key))
            .unwrap_or(false)
    }

    unsafe fn enqueue_work(hwnd: Hwnd, work: QueuedWork) -> bool {
        let work_key = work_semantic_key(&work);
        if work_is_duplicate(&work_key) {
            set_text(
                GetDlgItem(hwnd, ID_STATUS),
                &format!(
                    "Cortex | duplicate request ignored — {} — {}",
                    work.label, work.target
                ),
            );
            update_thinking_bubble(hwnd);
            return false;
        }
        if ASYNC_BUSY.load(Ordering::SeqCst) {
            let label = work.label.clone();
            let target = work.target.clone();
            let queue_len = WORK_QUEUE
                .get_or_init(|| Mutex::new(VecDeque::new()))
                .lock()
                .map(|mut queue| {
                    queue.push_back(work);
                    queue.len()
                })
                .unwrap_or(0);
            set_text(
                GetDlgItem(hwnd, ID_STATUS),
                &format!("Cortex | queued #{queue_len}: {label} — {target}"),
            );
            update_thinking_bubble(hwnd);
            return true;
        }

        start_queued_work(hwnd, work)
    }

    unsafe fn start_queued_work(hwnd: Hwnd, mut work: QueuedWork) -> bool {
        if ASYNC_BUSY
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            if let Ok(mut queue) = WORK_QUEUE
                .get_or_init(|| Mutex::new(VecDeque::new()))
                .lock()
            {
                queue.push_front(work);
            }
            return true;
        }

        ASYNC_CANCEL_REQUESTED.store(false, Ordering::SeqCst);
        if let Ok(mut queue) = ASYNC_PROGRESS.get_or_init(|| Mutex::new(Vec::new())).lock() {
            queue.clear();
        }
        if let Ok(mut streamed) = ASYNC_STREAM_TEXT
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            streamed.clear();
        }
        if let Ok(mut active) = ACTIVE_WORK_LABEL
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            *active = format!("{} — {}", work.label, work.target);
        }
        if let Ok(mut active_key) = ACTIVE_WORK_KEY
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            *active_key = work_semantic_key(&work);
        }

        set_busy(hwnd, true);
        update_thinking_bubble(hwnd);
        set_text(
            GetDlgItem(hwnd, ID_STATUS),
            &format!("Cortex | {} — starting in background", work.label),
        );

        let hwnd_value = hwnd as usize;
        thread::spawn(move || {
            let started = Instant::now();
            let mut emit = |event| queue_progress(hwnd_value as Hwnd, event);
            let result = if ASYNC_CANCEL_REQUESTED.load(Ordering::SeqCst) {
                Err("Cortex operation cancelled before execution started.".into())
            } else {
                match &mut work.action {
                    BackgroundAction::Chat(prompt) => {
                        work.worker.send_message_stream(prompt, &mut emit)
                    }
                    BackgroundAction::Agent { mode, prompt } => {
                        queue_progress(
                            hwnd_value as Hwnd,
                            CortexStreamEvent::status(
                                "desktop",
                                CortexStreamKind::Status,
                                "working",
                                format!("{} active", work.label),
                                started.elapsed().as_millis() as u64,
                            ),
                        );
                        work.worker.run_agent_stream(mode, prompt, &mut emit)
                    }
                    BackgroundAction::Provider => work.worker.show_provider_status(),
                    BackgroundAction::Build => work.worker.run_build_check(),
                    BackgroundAction::Index => work.worker.rebuild_context_index(),
                    BackgroundAction::Ingest(paths) => work.worker.ingest_paths(paths),
                    BackgroundAction::LibraryScan => work.worker.scan_library(),
                    BackgroundAction::Redo {
                        message_id,
                        instructions,
                    } => work.worker.redo_message(message_id, instructions),
                }
            };

            let result = result.and_then(|_| work.worker.persist_state());
            let cancel_requested = ASYNC_CANCEL_REQUESTED.load(Ordering::SeqCst);
            if let Ok(mut slot) = ASYNC_RESULT.get_or_init(|| Mutex::new(None)).lock() {
                *slot = Some(AsyncCompletion {
                    result,
                    clear_input: false,
                    cancel_requested,
                });
            }
            unsafe {
                PostMessageW(hwnd_value as Hwnd, WM_ASYNC_COMPLETE, 0, 0);
            }
        });
        true
    }

    // O2D-R051N9STOR1H_NATIVE_CANCEL_BRIDGE
    // Cancellation must never wait on provider/model-host work on the Win32 UI
    // thread. Signal the local completion guard immediately, then ask the
    // authoritative DesktopHost to terminate durable execution/provider state
    // from a detached control thread.
    unsafe fn request_active_cancel(hwnd: Hwnd, close_when_idle: bool) {
        ASYNC_CANCEL_REQUESTED.store(true, Ordering::SeqCst);
        if close_when_idle {
            CLOSE_WHEN_IDLE.store(true, Ordering::SeqCst);
        }
        set_text(
            GetDlgItem(hwnd, ID_STATUS),
            if close_when_idle {
                "Cortex | Cancelling active operation before close..."
            } else {
                "Cortex | Cancel requested — terminating active execution safely..."
            },
        );

        let hwnd_value = hwnd as usize;
        thread::spawn(move || {
            let result = HOST
                .get()
                .ok_or_else(|| "Desktop host is not initialized.".to_string())
                .and_then(|host| {
                    host.lock()
                        .map_err(|_| "Desktop host lock poisoned during cancellation.".to_string())
                })
                .and_then(|mut host| host.cancel_active_request());

            if let Err(error) = result {
                append_ui_blocking_log(&format!(
                    "terminal cancellation control path failed: {error}"
                ));
            }
            unsafe {
                PostMessageW(hwnd_value as Hwnd, WM_UI_TICK, 0, 0);
            }
        });
    }

    fn clear_work_queue() {
        if let Ok(mut queue) = WORK_QUEUE
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
        {
            queue.clear();
        }
    }

    fn queue_progress(hwnd: Hwnd, event: CortexStreamEvent) {
        if let Ok(mut queue) = ASYNC_PROGRESS.get_or_init(|| Mutex::new(Vec::new())).lock() {
            queue.push(event);
        }
        unsafe {
            PostMessageW(hwnd, WM_ASYNC_PROGRESS, 0, 0);
        }
    }

    unsafe fn apply_async_progress(hwnd: Hwnd) {
        let events = ASYNC_PROGRESS
            .get()
            .and_then(|queue| queue.lock().ok())
            .map(|mut queue| std::mem::take(&mut *queue))
            .unwrap_or_default();

        for event in events {
            // Text deltas belong to the detached worker's captured conversation. They are
            // deliberately not appended into whichever chat happens to be visible now.
            // The worker persists the final conversation; refresh shows it when that
            // project/chat is selected.
            let elapsed = if event.elapsed_ms >= 1000 {
                format!(" — {:.1}s", event.elapsed_ms as f64 / 1000.0)
            } else {
                String::new()
            };
            set_text(
                GetDlgItem(hwnd, ID_STATUS),
                &format!("Cortex | {}{}", event.message, elapsed),
            );
        }
        update_thinking_bubble(hwnd);
    }

    unsafe fn complete_async(hwnd: Hwnd) {
        let completion = ASYNC_RESULT
            .get()
            .and_then(|slot| slot.lock().ok())
            .and_then(|mut slot| slot.take());

        ASYNC_BUSY.store(false, Ordering::SeqCst);
        ASYNC_CANCEL_REQUESTED.store(false, Ordering::SeqCst);
        if let Ok(mut active) = ACTIVE_WORK_LABEL
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            active.clear();
        }
        if let Ok(mut active_key) = ACTIVE_WORK_KEY
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            active_key.clear();
        }
        set_busy(hwnd, false);
        update_thinking_bubble(hwnd);
        set_text(GetDlgItem(hwnd, ID_STATUS), "Cortex | Ready");

        if let Some(completion) = completion {
            match completion.result {
                Ok(()) => {
                    if completion.clear_input {
                        set_text(GetDlgItem(hwnd, ID_INPUT), "");
                    }
                    refresh(hwnd);
                    if completion.cancel_requested {
                        set_text(
                            GetDlgItem(hwnd, ID_STATUS),
                            "Cortex | Cancel was requested; operation returned safely — review results",
                        );
                    }
                }
                Err(error) => {
                    if !completion.cancel_requested {
                        if let Some(host) = HOST.get() {
                            if let Ok(mut host) = host.try_lock() {
                                let _ = host.record_error_message("Background request", &error);
                            }
                        }
                        set_text(
                            GetDlgItem(hwnd, ID_STATUS),
                            "Cortex | Request failed safely — error recorded in chat",
                        );
                    }
                    refresh(hwnd);
                    if completion.cancel_requested {
                        set_text(
                            GetDlgItem(hwnd, ID_STATUS),
                            "Cortex | Operation cancel requested — review activity before retrying",
                        );
                    }
                }
            }
        } else {
            refresh(hwnd);
        }

        if CLOSE_WHEN_IDLE.load(Ordering::SeqCst) {
            let queue_empty = WORK_QUEUE
                .get_or_init(|| Mutex::new(VecDeque::new()))
                .lock()
                .map(|queue| queue.is_empty())
                .unwrap_or(true);
            if queue_empty {
                CLOSE_WHEN_IDLE.store(false, Ordering::SeqCst);
                DestroyWindow(hwnd);
                return;
            }
        }

        let next = WORK_QUEUE
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
            .ok()
            .and_then(|mut queue| queue.pop_front());
        if let Some(next) = next {
            start_queued_work(hwnd, next);
        } else {
            update_thinking_bubble(hwnd);
            SetFocus(GetDlgItem(hwnd, ID_INPUT));
        }
    }

    unsafe fn set_busy(hwnd: Hwnd, busy: bool) {
        // Background work must not disable project navigation, the composer, or Send.
        // A second Send is captured against the currently selected project/chat and queued.
        let cancel = GetDlgItem(hwnd, ID_CANCEL);
        if !cancel.is_null() {
            EnableWindow(cancel, if busy { 1 } else { 0 });
        }
        let send = GetDlgItem(hwnd, ID_SEND);
        if !send.is_null() {
            set_text(send, if busy { "Queue" } else { "Send" });
            EnableWindow(send, 1);
        }
        update_thinking_bubble(hwnd);
    }

    unsafe fn invoke(
        hwnd: Hwnd,
        operation: impl FnOnce(&mut dyn DesktopHost) -> Result<(), String>,
    ) -> bool {
        let Some(host) = HOST.get() else {
            show_error(hwnd, "Cortex desktop host is unavailable");
            return false;
        };
        let mut host = match host.try_lock() {
            Ok(host) => host,
            Err(_) => {
                set_text(
                    GetDlgItem(hwnd, ID_STATUS),
                    "Cortex | UI state is momentarily busy — retrying is safe",
                );
                return false;
            }
        };
        match operation(host.as_mut()) {
            Ok(()) => {
                drop(host);
                refresh(hwnd);
                true
            }
            Err(error) => {
                show_error(hwnd, &error);
                drop(host);
                refresh(hwnd);
                false
            }
        }
    }

    unsafe fn invoke_bool_result(
        hwnd: Hwnd,
        true_message: &str,
        false_message: &str,
        operation: impl FnOnce(&mut dyn DesktopHost) -> Result<bool, String>,
    ) -> bool {
        let Some(host) = HOST.get() else {
            show_error(hwnd, "Cortex desktop host is unavailable");
            return false;
        };
        let Ok(mut host) = host.try_lock() else {
            set_text(
                GetDlgItem(hwnd, ID_STATUS),
                "Cortex | UI state is momentarily busy — retrying is safe",
            );
            return false;
        };
        match operation(host.as_mut()) {
            Ok(changed) => {
                let message = format!(
                    "Cortex | {}",
                    if changed { true_message } else { false_message }
                );
                drop(host);
                refresh(hwnd);
                set_text(GetDlgItem(hwnd, ID_STATUS), &message);
                true
            }
            Err(error) => {
                drop(host);
                show_error(hwnd, &error);
                false
            }
        }
    }

    unsafe fn invoke_export(
        hwnd: Hwnd,
        label: &str,
        operation: impl FnOnce(&mut dyn DesktopHost) -> Result<String, String>,
    ) -> bool {
        let Some(host) = HOST.get() else {
            show_error(hwnd, "Cortex desktop host is unavailable");
            return false;
        };
        let Ok(mut host) = host.try_lock() else {
            set_text(
                GetDlgItem(hwnd, ID_STATUS),
                "Cortex | UI state is momentarily busy — retrying is safe",
            );
            return false;
        };
        match operation(host.as_mut()) {
            Ok(path) => {
                let message = format!("Cortex | {label}: {path}");
                drop(host);
                refresh(hwnd);
                set_text(GetDlgItem(hwnd, ID_STATUS), &message);
                true
            }
            Err(error) => {
                drop(host);
                show_error(hwnd, &error);
                false
            }
        }
    }

    unsafe fn render_agent_preview(hwnd: Hwnd, prompt: &str, mode_label: &str) {
        let mut blocks = HOST
            .get()
            .and_then(|host| host.try_lock().ok())
            .map(|mut host| host.snapshot().chat_blocks)
            .unwrap_or_default();
        blocks.push(DesktopChatBlock {
            message_id: String::new(),
            role: "user".into(),
            label: "You".into(),
            text: prompt.to_string(),
            kind: "message".into(),
            path: String::new(),
            language: String::new(),
            status: String::new(),
            created_unix_ms: 0,
            feedback_score: 0,
            revision: 1,
        });
        blocks.push(DesktopChatBlock {
            message_id: String::new(),
            role: "assistant".into(),
            label: format!("Cortex · {mode_label}"),
            text: "Working on this request…".into(),
            kind: "message".into(),
            path: String::new(),
            language: String::new(),
            status: String::new(),
            created_unix_ms: 0,
            feedback_score: 0,
            revision: 1,
        });
        render_chat_blocks(hwnd, &blocks);
        force_scroll_transcript_to_end(hwnd);
    }

    unsafe fn start_ui_ticker(hwnd: Hwnd) {
        if UI_TICKER_RUNNING
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return;
        }
        let hwnd_value = hwnd as usize;
        thread::spawn(move || {
            while UI_TICKER_RUNNING.load(Ordering::SeqCst) {
                thread::sleep(Duration::from_millis(420));
                unsafe {
                    PostMessageW(hwnd_value as Hwnd, WM_THINKING_TICK, 0, 0);
                }
            }
        });
    }

    unsafe fn update_thinking_bubble(hwnd: Hwnd) {
        let bubble = GetDlgItem(hwnd, ID_THINKING_BUBBLE);
        if bubble.is_null() {
            return;
        }
        let queued = WORK_QUEUE
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
            .map(|queue| queue.len())
            .unwrap_or(0);
        if !ASYNC_BUSY.load(Ordering::SeqCst) && queued == 0 {
            set_text(bubble, "");
            ShowWindow(bubble, SW_HIDE);
            return;
        }
        ShowWindow(bubble, SW_SHOW);
        let frame = THINKING_FRAME.fetch_add(1, Ordering::SeqCst) % 4 + 1;
        let dots = ".".repeat(frame);
        let active = ACTIVE_WORK_LABEL
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
            .map(|value| value.clone())
            .unwrap_or_else(|_| "Working".into());
        let queue_suffix = if queued > 0 {
            format!("  ·  {queued} queued")
        } else {
            String::new()
        };
        set_text(bubble, &format!("Cortex {dots}  {active}{queue_suffix}"));
    }

    unsafe fn invalidate_activity_tabs(hwnd: Hwnd) {
        for id in [
            ID_ACTIVITY_CORTEX_TAB,
            ID_ACTIVITY_LMSTUDIO_TAB,
            ID_ACTIVITY_JOBS_TAB,
            ID_ACTIVITY_BUILD_TAB,
            ID_ACTIVITY_GIT_TAB,
            ID_ACTIVITY_NOTIFICATIONS_TAB,
        ] {
            let child = GetDlgItem(hwnd, id);
            if !child.is_null() {
                InvalidateRect(child, null(), 1);
            }
        }
    }

    fn lmstudio_log_text() -> String {
        LMSTUDIO_LOG_LINES
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
            .map(|lines| {
                if lines.is_empty() {
                    "LM Studio live server log stream is not started yet.\r\n\
Select this tab to start `lms log stream --source server`."
                        .to_string()
                } else {
                    lines.iter().cloned().collect::<Vec<_>>().join("\r\n")
                }
            })
            .unwrap_or_else(|_| "LM Studio log buffer is unavailable.".into())
    }

    fn push_lmstudio_log(line: impl Into<String>) {
        let line = line.into();
        if let Ok(mut lines) = LMSTUDIO_LOG_LINES
            .get_or_init(|| Mutex::new(VecDeque::new()))
            .lock()
        {
            lines.push_back(line.clone());
            while lines.len() > 2000 {
                lines.pop_front();
            }
        }
        if let Ok(mut pending) = LMSTUDIO_LOG_PENDING
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        {
            pending.push(line);
        }
    }

    unsafe fn append_pending_lmstudio_activity(hwnd: Hwnd) {
        if !ACTIVITY_EXPANDED.load(Ordering::SeqCst)
            || ACTIVE_ACTIVITY_PANE.load(Ordering::SeqCst) != ID_ACTIVITY_LMSTUDIO_TAB as usize
        {
            return;
        }

        let pending = LMSTUDIO_LOG_PENDING
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
            .map(|mut pending| std::mem::take(&mut *pending))
            .unwrap_or_default();
        if pending.is_empty() {
            return;
        }

        let activity = GetDlgItem(hwnd, ID_ACTIVITY);
        let length = GetWindowTextLengthW(activity).max(0) as usize;
        SendMessageW(activity, EM_SETSEL, length, length as Lparam);
        let mut text = String::new();
        if length > 0 {
            text.push_str("\r\n");
        }
        text.push_str(&pending.join("\r\n"));
        let wide_text = wide(&text);
        SendMessageW(activity, EM_REPLACESEL, 0, wide_text.as_ptr() as Lparam);
        let end = GetWindowTextLengthW(activity).max(0) as usize;
        SendMessageW(activity, EM_SETSEL, end, end as Lparam);
        SendMessageW(activity, EM_SCROLLCARET, 0, 0);
        SendMessageW(activity, WM_VSCROLL, SB_BOTTOM, 0);
    }

    unsafe fn render_active_activity(hwnd: Hwnd) {
        if !ACTIVITY_EXPANDED.load(Ordering::SeqCst) {
            return;
        }

        let pane = ACTIVE_ACTIVITY_PANE.load(Ordering::SeqCst);
        let text = if pane == ID_ACTIVITY_LMSTUDIO_TAB as usize {
            lmstudio_log_text()
        } else {
            let body = CORTEX_ACTIVITY_TEXT
                .get_or_init(|| Mutex::new(String::new()))
                .lock()
                .map(|value| value.clone())
                .unwrap_or_default();
            let heading = if pane == ID_ACTIVITY_JOBS_TAB as usize {
                "JOBS"
            } else if pane == ID_ACTIVITY_BUILD_TAB as usize {
                "BUILD"
            } else if pane == ID_ACTIVITY_GIT_TAB as usize {
                "GIT / RECOVERY"
            } else if pane == ID_ACTIVITY_NOTIFICATIONS_TAB as usize {
                "NOTIFICATIONS"
            } else {
                "CORTEX ACTIVITY"
            };
            format!("{heading}\r\n────────────────────────────────────────\r\n{body}")
        };

        let activity = GetDlgItem(hwnd, ID_ACTIVITY);
        set_text(activity, &text);
        if ACTIVE_ACTIVITY_PANE.load(Ordering::SeqCst) == ID_ACTIVITY_LMSTUDIO_TAB as usize {
            if let Ok(mut pending) = LMSTUDIO_LOG_PENDING
                .get_or_init(|| Mutex::new(Vec::new()))
                .lock()
            {
                pending.clear();
            }
        }
        let length = GetWindowTextLengthW(activity).max(0) as usize;
        SendMessageW(activity, EM_SETSEL, length, length as Lparam);
        SendMessageW(activity, EM_SCROLLCARET, 0, 0);
        SendMessageW(activity, WM_VSCROLL, SB_BOTTOM, 0);
    }

    fn resolve_lms_executable() -> PathBuf {
        if let Ok(home) = env::var("USERPROFILE") {
            let candidate = PathBuf::from(home)
                .join(".lmstudio")
                .join("bin")
                .join("lms.exe");
            if candidate.is_file() {
                return candidate;
            }
        }
        PathBuf::from("lms")
    }

    unsafe fn start_lmstudio_log_stream(hwnd: Hwnd) {
        if LMSTUDIO_LOG_RUNNING
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return;
        }

        let executable = resolve_lms_executable();
        let mut command = Command::new(&executable);
        command
            .args(["log", "stream", "--source", "server"])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }

        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                push_lmstudio_log(format!(
                    "[Cortex] Could not start LM Studio log stream with `{}`: {error}\r\n\
LM Studio includes the `lms` CLI; bootstrap it if necessary and reselect this tab.",
                    executable.display()
                ));
                LMSTUDIO_LOG_RUNNING.store(false, Ordering::SeqCst);
                PostMessageW(hwnd, WM_LMSTUDIO_LOG, 0, 0);
                return;
            }
        };

        let Some(stdout) = child.stdout.take() else {
            push_lmstudio_log("[Cortex] LM Studio log stream opened without stdout.");
            let _ = child.kill();
            LMSTUDIO_LOG_RUNNING.store(false, Ordering::SeqCst);
            PostMessageW(hwnd, WM_LMSTUDIO_LOG, 0, 0);
            return;
        };

        if let Ok(mut slot) = LMSTUDIO_LOG_CHILD.get_or_init(|| Mutex::new(None)).lock() {
            *slot = Some(child);
        }

        push_lmstudio_log(format!(
            "[Cortex] Streaming LM Studio server/developer logs via `{}`.",
            executable.display()
        ));
        PostMessageW(hwnd, WM_LMSTUDIO_LOG, 0, 0);

        let hwnd_value = hwnd as usize;
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            let mut last_ui_post = Instant::now()
                .checked_sub(Duration::from_millis(125))
                .unwrap_or_else(Instant::now);
            for line in reader.lines() {
                match line {
                    Ok(line) => {
                        push_lmstudio_log(line);
                        if last_ui_post.elapsed() >= Duration::from_millis(125) {
                            unsafe {
                                PostMessageW(hwnd_value as Hwnd, WM_LMSTUDIO_LOG, 0, 0);
                            }
                            last_ui_post = Instant::now();
                        }
                    }
                    Err(error) => {
                        push_lmstudio_log(format!(
                            "[Cortex] LM Studio log stream read error: {error}"
                        ));
                        break;
                    }
                }
            }

            LMSTUDIO_LOG_RUNNING.store(false, Ordering::SeqCst);
            if let Ok(mut slot) = LMSTUDIO_LOG_CHILD.get_or_init(|| Mutex::new(None)).lock() {
                *slot = None;
            }
            unsafe {
                PostMessageW(hwnd_value as Hwnd, WM_LMSTUDIO_LOG, 0, 0);
            }
        });
    }

    fn stop_lmstudio_log_stream() {
        LMSTUDIO_LOG_RUNNING.store(false, Ordering::SeqCst);
        if let Ok(mut slot) = LMSTUDIO_LOG_CHILD.get_or_init(|| Mutex::new(None)).lock() {
            if let Some(child) = slot.as_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
            *slot = None;
        }
    }

    const CONFIG_TABS: [i32; 5] = [
        ID_CONFIG_TAB_GENERAL,
        ID_CONFIG_TAB_LIBRARY,
        ID_CONFIG_TAB_PROVIDERS,
        ID_CONFIG_TAB_MODELS,
        ID_CONFIG_TAB_APPEARANCE,
    ];
    const CONFIG_LABELS: [i32; 4] = [
        ID_CONFIG_LABEL_1,
        ID_CONFIG_LABEL_2,
        ID_CONFIG_LABEL_3,
        ID_CONFIG_LABEL_4,
    ];
    const CONFIG_EDITS: [i32; 4] = [
        ID_CONFIG_EDIT_1,
        ID_CONFIG_EDIT_2,
        ID_CONFIG_EDIT_3,
        ID_CONFIG_EDIT_4,
    ];

    unsafe fn set_config_visible(hwnd: Hwnd, visible: bool) {
        for id in CONFIG_TABS
            .into_iter()
            .chain(CONFIG_LABELS)
            .chain(CONFIG_EDITS)
            .chain([ID_CONFIG_APPLY, ID_CONFIG_SECONDARY])
        {
            show_control(hwnd, id, visible);
        }
    }

    unsafe fn config_row(hwnd: Hwnd, index: usize, label: &str, value: &str) {
        set_text(GetDlgItem(hwnd, CONFIG_LABELS[index]), label);
        set_text(GetDlgItem(hwnd, CONFIG_EDITS[index]), value);
        show_control(hwnd, CONFIG_LABELS[index], true);
        show_control(hwnd, CONFIG_EDITS[index], true);
    }

    unsafe fn load_config_tab(hwnd: Hwnd) {
        let Some(host) = HOST.get() else {
            return;
        };
        let Ok(mut host) = host.try_lock() else {
            return;
        };
        let snapshot = match host.config_snapshot() {
            Ok(snapshot) => snapshot,
            Err(error) => {
                drop(host);
                show_error(hwnd, &error);
                return;
            }
        };
        drop(host);

        for id in CONFIG_LABELS.into_iter().chain(CONFIG_EDITS) {
            show_control(hwnd, id, false);
        }
        show_control(hwnd, ID_CONFIG_SECONDARY, false);

        match CONFIG_TAB.load(Ordering::SeqCst) {
            0 => {
                config_row(hwnd, 0, "Service port", &snapshot.service_port.to_string());
                config_row(
                    hwnd,
                    1,
                    "Auto-start service (true/false)",
                    if snapshot.auto_start_service {
                        "true"
                    } else {
                        "false"
                    },
                );
            }
            1 => {
                config_row(hwnd, 0, "Cortex Library root", &snapshot.library_root);
                set_text(GetDlgItem(hwnd, ID_CONFIG_SECONDARY), "Scan Library");
                show_control(hwnd, ID_CONFIG_SECONDARY, true);
            }
            2 => {
                config_row(hwnd, 0, "AI provider (native/lmstudio)", &snapshot.provider);
                config_row(
                    hwnd,
                    1,
                    "Native model-host port",
                    &snapshot.native_model_host_port.to_string(),
                );
                config_row(
                    hwnd,
                    2,
                    "Native runtime bootstrap (true/false)",
                    if snapshot.native_auto_bootstrap {
                        "true"
                    } else {
                        "false"
                    },
                );
                config_row(
                    hwnd,
                    3,
                    "Max native models loaded (1-8)",
                    &snapshot.native_models_max.to_string(),
                );
            }
            3 => {
                config_row(
                    hwnd,
                    0,
                    "Chat model (blank = automatic)",
                    &snapshot.chat_model,
                );
                config_row(
                    hwnd,
                    1,
                    "Tool/code model (blank = automatic)",
                    &snapshot.tool_model,
                );
                config_row(
                    hwnd,
                    2,
                    "Vision model (blank = automatic)",
                    &snapshot.vision_model,
                );
                config_row(
                    hwnd,
                    3,
                    "Embedding model (blank = automatic)",
                    &snapshot.embedding_model,
                );
            }
            _ => {
                config_row(hwnd, 0, "Theme (dark/light/system)", &snapshot.theme);
                config_row(
                    hwnd,
                    1,
                    "Compact tool cards (true/false)",
                    if snapshot.compact_tool_cards {
                        "true"
                    } else {
                        "false"
                    },
                );
            }
        }
        for id in CONFIG_TABS {
            InvalidateRect(GetDlgItem(hwnd, id), null(), 1);
        }
    }

    unsafe fn apply_config_tab(hwnd: Hwnd) {
        let values = CONFIG_EDITS.map(|id| get_text(GetDlgItem(hwnd, id)));
        let updates: Vec<(&str, &str)> = match CONFIG_TAB.load(Ordering::SeqCst) {
            0 => vec![
                ("service_port", values[0].trim()),
                ("auto_start_service", values[1].trim()),
            ],
            1 => vec![("library_root", values[0].trim())],
            2 => vec![
                ("provider", values[0].trim()),
                ("native_model_host_port", values[1].trim()),
                ("native_auto_bootstrap", values[2].trim()),
                ("native_models_max", values[3].trim()),
            ],
            3 => vec![
                ("chat_model", values[0].trim()),
                ("tool_model", values[1].trim()),
                ("vision_model", values[2].trim()),
                ("embedding_model", values[3].trim()),
            ],
            _ => vec![
                ("theme", values[0].trim()),
                ("compact_tool_cards", values[1].trim()),
            ],
        };

        let Some(host) = HOST.get() else {
            return;
        };
        let Ok(mut host) = host.try_lock() else {
            show_error(hwnd, "Cortex configuration is busy. Try Apply again.");
            return;
        };
        for (key, value) in updates {
            if key == "library_root" && value.is_empty() {
                continue;
            }
            if let Err(error) = host.set_config_value(key, value) {
                drop(host);
                show_error(hwnd, &format!("Could not save {key}: {error}"));
                return;
            }
        }
        drop(host);
        set_text(GetDlgItem(hwnd, ID_STATUS), "Cortex | Configuration saved");
        load_config_tab(hwnd);
    }

    unsafe fn open_config_panel(hwnd: Hwnd) {
        RIGHT_COLLAPSED.store(false, Ordering::SeqCst);
        set_right_pane(hwnd, ID_SETTINGS, "Settings", "");
        layout(hwnd);
        set_config_visible(hwnd, true);
        load_config_tab(hwnd);
    }

    const FILE_BROWSER_IDS: [i32; 6] = [
        ID_FILE_SCOPE_PROJECT,
        ID_FILE_SCOPE_LIBRARY,
        ID_FILE_HOME,
        ID_FILE_UP,
        ID_FILE_PATH,
        ID_FILE_LIST,
    ];

    unsafe fn set_file_browser_visible(hwnd: Hwnd, visible: bool) {
        for id in FILE_BROWSER_IDS {
            show_control(hwnd, id, visible);
        }
    }

    unsafe fn load_file_browser(hwnd: Hwnd, library_scope: bool, relative: &str) {
        let Some(host) = HOST.get() else {
            return;
        };
        let Ok(mut host) = host.try_lock() else {
            return;
        };
        let listing = match host.browse_files(library_scope, relative) {
            Ok(listing) => listing,
            Err(error) => {
                drop(host);
                show_error(hwnd, &error);
                return;
            }
        };
        drop(host);

        FILE_BROWSER_LIBRARY_SCOPE.store(library_scope, Ordering::SeqCst);
        let list = GetDlgItem(hwnd, ID_FILE_LIST);
        SendMessageW(list, LB_RESETCONTENT, 0, 0);
        for entry in &listing.entries {
            let marker = if entry.is_directory { "[DIR]" } else { "     " };
            let size = if entry.is_directory {
                String::new()
            } else {
                format!("  {} B", entry.bytes)
            };
            let label = wide(&format!("{marker} {}{size}", entry.name));
            SendMessageW(list, LB_ADDSTRING, 0, label.as_ptr() as Lparam);
        }
        set_text(
            GetDlgItem(hwnd, ID_FILE_PATH),
            &format!(
                "{}: {}{}{}",
                listing.scope,
                listing.root,
                if listing.current.is_empty() { "" } else { "\\" },
                listing.current.replace('/', "\\")
            ),
        );
        if let Ok(mut stored) = FILE_BROWSER_LISTING
            .get_or_init(|| Mutex::new(DesktopFileListing::default()))
            .lock()
        {
            *stored = listing;
        }
    }

    unsafe fn file_browser_up(hwnd: Hwnd) {
        let current = FILE_BROWSER_LISTING
            .get_or_init(|| Mutex::new(DesktopFileListing::default()))
            .lock()
            .map(|listing| listing.current.clone())
            .unwrap_or_default();
        let parent = PathBuf::from(current)
            .parent()
            .map(|path| path.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default();
        load_file_browser(
            hwnd,
            FILE_BROWSER_LIBRARY_SCOPE.load(Ordering::SeqCst),
            &parent,
        );
    }

    unsafe fn set_right_pane(hwnd: Hwnd, id: i32, title: &str, cue: &str) {
        ACTIVE_RIGHT_PANE.store(id as usize, Ordering::SeqCst);
        set_text(GetDlgItem(hwnd, ID_RIGHT_TITLE), title);
        let cue = wide(cue);
        SendMessageW(
            GetDlgItem(hwnd, ID_QUERY),
            EM_SETCUEBANNER,
            1,
            cue.as_ptr() as Lparam,
        );
        for button in [
            ID_FILES,
            ID_CHANGES,
            ID_VAULT,
            ID_ARTIFACTS,
            ID_TASKS,
            ID_SETTINGS,
        ] {
            let child = GetDlgItem(hwnd, button);
            if !child.is_null() {
                InvalidateRect(child, null(), 1);
            }
        }
    }

    #[derive(Clone, Debug)]
    struct MarkdownSegment {
        code: bool,
        language: String,
        text: String,
    }

    fn split_markdown_segments(text: &str) -> Vec<MarkdownSegment> {
        let normalized = text.replace("\r\n", "\n");
        let mut result = Vec::new();
        let mut current = Vec::<String>::new();
        let mut in_code = false;
        let mut language = String::new();

        let flush = |result: &mut Vec<MarkdownSegment>,
                     current: &mut Vec<String>,
                     code: bool,
                     language: &str| {
            if current.is_empty() {
                return;
            }
            let text = current.join("\r\n");
            if !text.trim().is_empty() {
                result.push(MarkdownSegment {
                    code,
                    language: language.to_string(),
                    text,
                });
            }
            current.clear();
        };

        for line in normalized.lines() {
            let trimmed = line.trim_start();
            if let Some(rest) = trimmed.strip_prefix("```") {
                flush(&mut result, &mut current, in_code, &language);
                if in_code {
                    in_code = false;
                    language.clear();
                } else {
                    in_code = true;
                    language = rest.trim().to_string();
                }
                continue;
            }
            current.push(line.to_string());
        }
        flush(&mut result, &mut current, in_code, &language);

        if result.is_empty() && !text.trim().is_empty() {
            result.push(MarkdownSegment {
                code: false,
                language: String::new(),
                text: text.to_string(),
            });
        }
        result
    }

    unsafe fn render_chat_blocks(parent: Hwnd, blocks: &[DesktopChatBlock]) {
        if let Ok(mut stored) = CHAT_CARD_BLOCKS
            .get_or_init(|| Mutex::new(Vec::new()))
            .lock()
        {
            *stored = blocks.to_vec();
        }
        CHAT_LAYOUT_DIRTY.store(true, Ordering::SeqCst);
        let chat = GetDlgItem(parent, ID_TRANSCRIPT);
        if !chat.is_null() {
            InvalidateRect(chat, null(), 0);
        }
    }

    unsafe fn refresh(hwnd: Hwnd) {
        let Some(host) = HOST.get() else {
            return;
        };
        let Ok(mut host) = host.try_lock() else {
            return;
        };
        let snapshot = host.snapshot();
        drop(host);
        apply_snapshot(hwnd, &snapshot);
    }

    fn chat_signature(snapshot: &DesktopSnapshot) -> u64 {
        let mut hasher = DefaultHasher::new();
        snapshot.workspace_title.hash(&mut hasher);
        snapshot.conversation_title.hash(&mut hasher);
        snapshot.active_conversation.hash(&mut hasher);
        snapshot.transcript.hash(&mut hasher);
        for block in &snapshot.chat_blocks {
            block.message_id.hash(&mut hasher);
            block.role.hash(&mut hasher);
            block.label.hash(&mut hasher);
            block.text.hash(&mut hasher);
            block.kind.hash(&mut hasher);
            block.path.hash(&mut hasher);
            block.language.hash(&mut hasher);
            block.status.hash(&mut hasher);
            block.created_unix_ms.hash(&mut hasher);
            block.feedback_score.hash(&mut hasher);
            block.revision.hash(&mut hasher);
        }
        hasher.finish()
    }

    unsafe fn apply_snapshot(hwnd: Hwnd, snapshot: &DesktopSnapshot) {
        let workspace = if snapshot.workspace_title.is_empty() {
            "Workspace"
        } else {
            &snapshot.workspace_title
        };
        let conversation = if snapshot.conversation_title.is_empty() {
            "No conversation"
        } else {
            &snapshot.conversation_title
        };
        set_text(hwnd, &format!("Cortex — {workspace} — {conversation}"));
        set_text(GetDlgItem(hwnd, ID_STATUS), &snapshot.status);
        if !ASYNC_BUSY.load(Ordering::SeqCst) {
            EnableWindow(
                GetDlgItem(hwnd, ID_CANCEL),
                if snapshot.provider_recovery_pending { 1 } else { 0 },
            );
        }

        let signature = chat_signature(snapshot);
        let previous_signature = LAST_CHAT_SIGNATURE.swap(signature, Ordering::SeqCst);
        if signature != previous_signature {
            if snapshot.chat_blocks.is_empty() {
                let fallback = [DesktopChatBlock {
                    message_id: String::new(),
                    role: "assistant".into(),
                    label: "Cortex".into(),
                    text: snapshot.transcript.clone(),
                    kind: "message".into(),
                    path: String::new(),
                    language: String::new(),
                    status: String::new(),
                    created_unix_ms: 0,
                    feedback_score: 0,
                    revision: 1,
                }];
                render_chat_blocks(hwnd, &fallback);
            } else {
                render_chat_blocks(hwnd, &snapshot.chat_blocks);
            }
            auto_scroll_transcript(hwnd);
        }

        set_text(GetDlgItem(hwnd, ID_INFO), &snapshot.info);
        if let Ok(mut value) = CORTEX_ACTIVITY_TEXT
            .get_or_init(|| Mutex::new(String::new()))
            .lock()
        {
            *value = snapshot.activity.clone();
        }
        render_active_activity(hwnd);

        let active_workspace = snapshot.active_workspace.unwrap_or(usize::MAX);
        let previous_active = LAST_ACTIVE_WORKSPACE.swap(active_workspace, Ordering::SeqCst);
        if previous_active != active_workspace {
            EXPANDED_WORKSPACE.store(active_workspace, Ordering::SeqCst);
        }
        let mut expanded = EXPANDED_WORKSPACE.load(Ordering::SeqCst);
        if expanded != usize::MAX && expanded >= snapshot.workspaces.len() {
            expanded = active_workspace;
            EXPANDED_WORKSPACE.store(expanded, Ordering::SeqCst);
        }

        let navigation = GetDlgItem(hwnd, ID_WORKSPACES);
        SendMessageW(navigation, LB_RESETCONTENT, 0, 0);
        let mut rows = Vec::new();
        let mut selected_row = None;
        for (workspace_index, title) in snapshot.workspaces.iter().enumerate() {
            if workspace_index > 0 {
                let spacer = wide(" ");
                let spacer_row = rows.len();
                SendMessageW(navigation, LB_ADDSTRING, 0, spacer.as_ptr() as Lparam);
                SendMessageW(navigation, LB_SETITEMHEIGHT, spacer_row, 10);
                rows.push(NavRow::Spacer);
            }

            let is_expanded = workspace_index == expanded;
            let label = wide(title);
            let row_index = rows.len();
            SendMessageW(navigation, LB_ADDSTRING, 0, label.as_ptr() as Lparam);
            SendMessageW(navigation, LB_SETITEMHEIGHT, row_index, 38);
            rows.push(NavRow::Workspace(workspace_index));
            if workspace_index == active_workspace
                && (!is_expanded || snapshot.active_conversation.is_none())
            {
                selected_row = Some(row_index);
            }
            if is_expanded && workspace_index == active_workspace {
                for (conversation_index, title) in snapshot.conversations.iter().enumerate() {
                    let label = wide(title);
                    let child_row = rows.len();
                    SendMessageW(navigation, LB_ADDSTRING, 0, label.as_ptr() as Lparam);
                    SendMessageW(navigation, LB_SETITEMHEIGHT, child_row, 30);
                    rows.push(NavRow::Conversation(conversation_index));
                    if snapshot.active_conversation == Some(conversation_index) {
                        selected_row = Some(child_row);
                    }
                }
            }
        }
        if let Ok(mut stored) = NAV_ROWS.get_or_init(|| Mutex::new(Vec::new())).lock() {
            *stored = rows;
        }
        if let Some(row) = selected_row {
            SendMessageW(navigation, LB_SETCURSEL, row, 0);
        }

        let legacy_conversations = GetDlgItem(hwnd, ID_CONVERSATIONS);
        SendMessageW(legacy_conversations, LB_RESETCONTENT, 0, 0);
    }

    unsafe fn auto_scroll_transcript(hwnd: Hwnd) {
        let transcript = GetDlgItem(hwnd, ID_TRANSCRIPT);
        if transcript.is_null() {
            return;
        }
        if CHAT_FOLLOW_END.load(Ordering::SeqCst) {
            set_chat_scroll_target(transcript, chat_max_scroll(transcript), false);
        }
    }

    unsafe fn force_scroll_transcript_to_end(hwnd: Hwnd) {
        let transcript = GetDlgItem(hwnd, ID_TRANSCRIPT);
        if transcript.is_null() {
            return;
        }
        CHAT_FOLLOW_END.store(true, Ordering::SeqCst);
        set_chat_scroll_target(transcript, chat_max_scroll(transcript), false);
    }

    unsafe fn set_text(hwnd: Hwnd, text: &str) {
        if hwnd.is_null() {
            return;
        }
        let value = wide(text);
        SetWindowTextW(hwnd, value.as_ptr());
    }

    unsafe fn get_text(hwnd: Hwnd) -> String {
        if hwnd.is_null() {
            return String::new();
        }
        let length = GetWindowTextLengthW(hwnd);
        if length <= 0 {
            return String::new();
        }
        let mut buffer = vec![0u16; length as usize + 1];
        let copied = GetWindowTextW(hwnd, buffer.as_mut_ptr(), buffer.len() as i32);
        String::from_utf16_lossy(&buffer[..copied.max(0) as usize])
    }

    unsafe fn show_error(hwnd: Hwnd, error: &str) {
        let message = wide(error);
        let caption = wide("Cortex");
        MessageBoxW(hwnd, message.as_ptr(), caption.as_ptr(), 0x10);
    }

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(std::iter::once(0)).collect()
    }
}
