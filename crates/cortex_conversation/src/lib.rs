//! Persistent standalone Cortex conversations.

use cortex_execution::{CompactionNotice, ExecutionTranscriptEntry};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static CONVERSATION_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ConversationRole {
    User,
    Assistant,
    System,
    Tool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConversationMessage {
    pub id: String,
    pub role: ConversationRole,
    pub content: String,
    pub created_unix_ms: u128,
    #[serde(default)]
    pub feedback_score: i8,
    #[serde(default = "default_revision")]
    pub revision: u32,
    #[serde(default)]
    pub parent_message_id: Option<String>,
    #[serde(default)]
    pub superseded_by: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Conversation {
    pub schema_version: u32,
    pub id: String,
    pub title: String,
    pub workspace_root: PathBuf,
    pub created_unix_ms: u128,
    pub updated_unix_ms: u128,
    pub archived: bool,
    pub messages: Vec<ConversationMessage>,
}

pub struct ConversationStore {
    root: PathBuf,
    workspace_root: PathBuf,
}

impl ConversationStore {
    pub fn open(
        state_root: impl AsRef<Path>,
        workspace_root: impl AsRef<Path>,
    ) -> Result<Self, String> {
        let root = state_root.as_ref().join("conversations");
        fs::create_dir_all(&root).map_err(|error| error.to_string())?;
        Ok(Self {
            root,
            workspace_root: workspace_root.as_ref().to_path_buf(),
        })
    }

    pub fn create(&self, title: &str) -> Result<Conversation, String> {
        let now = unix_ms();
        let conversation = Conversation {
            schema_version: 1,
            id: next_conversation_id(&self.root, now)?,
            title: if title.trim().is_empty() {
                "New conversation".into()
            } else {
                title.trim().to_string()
            },
            workspace_root: self.workspace_root.clone(),
            created_unix_ms: now,
            updated_unix_ms: now,
            archived: false,
            messages: Vec::new(),
        };
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn load(&self, id: &str) -> Result<Conversation, String> {
        validate_id(id)?;
        let path = self.root.join(format!("{id}.json"));
        let conversation: Conversation =
            serde_json::from_slice(&fs::read(&path).map_err(|error| {
                format!(
                    "conversation not found or unreadable {}: {error}",
                    path.display()
                )
            })?)
            .map_err(|error| error.to_string())?;

        if !same_workspace_root(&conversation.workspace_root, &self.workspace_root) {
            return Err(format!(
                "conversation `{id}` belongs to workspace `{}` rather than `{}`",
                conversation.workspace_root.display(),
                self.workspace_root.display()
            ));
        }

        Ok(conversation)
    }

    pub fn save(&self, conversation: &Conversation) -> Result<(), String> {
        validate_id(&conversation.id)?;
        let path = self.root.join(format!("{}.json", conversation.id));
        fs::write(
            path,
            serde_json::to_vec_pretty(conversation).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())
    }

    pub fn append(
        &self,
        id: &str,
        role: ConversationRole,
        content: impl Into<String>,
    ) -> Result<Conversation, String> {
        self.append_at(id, role, content, unix_ms())
    }

    pub fn append_at(
        &self,
        id: &str,
        role: ConversationRole,
        content: impl Into<String>,
        created_unix_ms: u128,
    ) -> Result<Conversation, String> {
        let mut conversation = self.load(id)?;
        conversation.messages.push(ConversationMessage {
            id: format!("{created_unix_ms}-{}-msg", conversation.messages.len()),
            role,
            content: content.into(),
            created_unix_ms,
            feedback_score: 0,
            revision: 1,
            parent_message_id: None,
            superseded_by: None,
        });
        conversation.updated_unix_ms = conversation.updated_unix_ms.max(created_unix_ms);
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn append_execution_entry(
        &self,
        id: &str,
        entry: &ExecutionTranscriptEntry,
    ) -> Result<Conversation, String> {
        if !entry.chat_visible() {
            return self.load(id);
        }
        self.append_at(
            id,
            ConversationRole::Assistant,
            entry.render_chat_markdown(),
            entry.created_unix_ms,
        )
    }

    pub fn append_compaction_notice(
        &self,
        id: &str,
        notice: &CompactionNotice,
    ) -> Result<Conversation, String> {
        // Compaction is non-destructive: the full transcript remains stored. This appends only a
        // visible checkpoint explaining that the model-facing context was condensed.
        self.append_at(
            id,
            ConversationRole::System,
            notice.render_chat_markdown(),
            notice.created_unix_ms,
        )
    }

    pub fn update_message_content(
        &self,
        conversation_id: &str,
        message_id: &str,
        content: impl Into<String>,
    ) -> Result<Conversation, String> {
        let mut conversation = self.load(conversation_id)?;
        let message = conversation
            .messages
            .iter_mut()
            .find(|message| message.id == message_id)
            .ok_or_else(|| format!("conversation message not found: {message_id}"))?;
        message.content = content.into();
        conversation.updated_unix_ms = unix_ms();
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn set_feedback(
        &self,
        conversation_id: &str,
        message_id: &str,
        score: i8,
    ) -> Result<Conversation, String> {
        let mut conversation = self.load(conversation_id)?;
        let message = conversation
            .messages
            .iter_mut()
            .find(|message| message.id == message_id)
            .ok_or_else(|| format!("conversation message not found: {message_id}"))?;
        message.feedback_score = score.clamp(-1, 1);
        conversation.updated_unix_ms = unix_ms();
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn append_revision(
        &self,
        conversation_id: &str,
        parent_message_id: &str,
        content: impl Into<String>,
    ) -> Result<Conversation, String> {
        let mut conversation = self.load(conversation_id)?;
        let parent_index = conversation
            .messages
            .iter()
            .position(|message| message.id == parent_message_id)
            .ok_or_else(|| format!("conversation message not found: {parent_message_id}"))?;
        let revision = conversation.messages[parent_index]
            .revision
            .saturating_add(1);
        let now = unix_ms();
        let new_id = format!("{now}-{}-msg", conversation.messages.len());
        conversation.messages[parent_index].superseded_by = Some(new_id.clone());
        conversation.messages.push(ConversationMessage {
            id: new_id,
            role: ConversationRole::Assistant,
            content: content.into(),
            created_unix_ms: now,
            feedback_score: 0,
            revision,
            parent_message_id: Some(parent_message_id.to_string()),
            superseded_by: None,
        });
        conversation.updated_unix_ms = now;
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn rename(&self, id: &str, title: &str) -> Result<Conversation, String> {
        let mut conversation = self.load(id)?;
        conversation.title = title.trim().to_string();
        conversation.updated_unix_ms = unix_ms();
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn archive(&self, id: &str) -> Result<Conversation, String> {
        let mut conversation = self.load(id)?;
        conversation.archived = true;
        conversation.updated_unix_ms = unix_ms();
        self.save(&conversation)?;
        Ok(conversation)
    }

    pub fn list(&self, include_archived: bool) -> Result<Vec<Conversation>, String> {
        let mut conversations = Vec::new();
        for entry in fs::read_dir(&self.root).map_err(|error| error.to_string())? {
            let entry = entry.map_err(|error| error.to_string())?;
            if entry.path().extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let Ok(conversation) = serde_json::from_slice::<Conversation>(
                &fs::read(entry.path()).map_err(|error| error.to_string())?,
            ) else {
                continue;
            };
            if !same_workspace_root(&conversation.workspace_root, &self.workspace_root) {
                continue;
            }
            if include_archived || !conversation.archived {
                conversations.push(conversation);
            }
        }
        conversations.sort_by_key(|conversation| std::cmp::Reverse(conversation.updated_unix_ms));
        Ok(conversations)
    }
}

fn next_conversation_id(root: &Path, now: u128) -> Result<String, String> {
    for _ in 0..1024 {
        let sequence = CONVERSATION_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let id = format!("{now}-{}-{sequence}-chat", std::process::id());
        if !root.join(format!("{id}.json")).exists() {
            return Ok(id);
        }
    }

    Err("could not allocate a unique Cortex conversation id after 1024 attempts".into())
}

fn same_workspace_root(left: &Path, right: &Path) -> bool {
    let left = fs::canonicalize(left).unwrap_or_else(|_| left.to_path_buf());
    let right = fs::canonicalize(right).unwrap_or_else(|_| right.to_path_buf());
    workspace_path_identity(&left) == workspace_path_identity(&right)
}

#[cfg(windows)]
fn workspace_path_identity(path: &Path) -> String {
    path.to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_ascii_lowercase()
}

#[cfg(not(windows))]
fn workspace_path_identity(path: &Path) -> String {
    path.to_string_lossy()
        .replace('\\', "/")
        .trim_end_matches('/')
        .to_string()
}

fn default_revision() -> u32 {
    1
}

fn validate_id(id: &str) -> Result<(), String> {
    if id.is_empty()
        || !id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return Err("invalid Cortex conversation id".into());
    }
    Ok(())
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conversations_are_isolated_by_workspace_root_even_when_state_storage_is_shared() {
        let base = std::env::temp_dir().join(format!(
            "cortex-conversation-isolation-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        let state = base.join("shared-state");
        let project_a = base.join("project-a");
        let project_b = base.join("project-b");
        fs::create_dir_all(&state).unwrap();
        fs::create_dir_all(&project_a).unwrap();
        fs::create_dir_all(&project_b).unwrap();

        let a = ConversationStore::open(&state, &project_a).unwrap();
        let b = ConversationStore::open(&state, &project_b).unwrap();

        let a_chat = a.create("A only").unwrap();
        let b_chat = b.create("B only").unwrap();

        assert_ne!(a_chat.id, b_chat.id);
        assert_eq!(a.list(false).unwrap().len(), 1);
        assert_eq!(a.list(false).unwrap()[0].title, "A only");
        assert_eq!(b.list(false).unwrap().len(), 1);
        assert_eq!(b.list(false).unwrap()[0].title, "B only");

        assert!(a.load(&b_chat.id).is_err());
        assert!(b.load(&a_chat.id).is_err());

        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn message_content_can_be_updated_without_appending_duplicate_status_cards() {
        let root = std::env::temp_dir().join(format!(
            "cortex-conversation-update-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ConversationStore::open(&root, &root).unwrap();
        let chat = store.create("Provider recovery").unwrap();
        let chat = store
            .append(&chat.id, ConversationRole::Assistant, "waiting")
            .unwrap();
        let message_id = chat.messages.last().unwrap().id.clone();

        store
            .update_message_content(&chat.id, &message_id, "ready")
            .unwrap();
        let loaded = store.load(&chat.id).unwrap();
        assert_eq!(loaded.messages.len(), 1);
        assert_eq!(loaded.messages[0].content, "ready");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rapid_conversation_creation_never_reuses_a_file_id() {
        let root = std::env::temp_dir().join(format!(
            "cortex-conversation-id-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();

        let store = ConversationStore::open(&root, &root).unwrap();
        let first = store.create("First").unwrap();
        let second = store.create("Second").unwrap();

        assert_ne!(first.id, second.id);
        assert_eq!(store.list(false).unwrap().len(), 2);
        assert_eq!(store.load(&first.id).unwrap().title, "First");
        assert_eq!(store.load(&second.id).unwrap().title, "Second");

        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn conversation_round_trip() {
        let root = std::env::temp_dir().join(format!(
            "cortex-conversation-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ConversationStore::open(&root, &root).unwrap();
        let conversation = store.create("Test").unwrap();
        store
            .append(&conversation.id, ConversationRole::User, "hello")
            .unwrap();
        let loaded = store.load(&conversation.id).unwrap();
        assert_eq!(loaded.messages.len(), 1);
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn execution_transcript_entries_are_persisted_with_their_authoritative_time() {
        let root = std::env::temp_dir().join(format!(
            "cortex-conversation-execution-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ConversationStore::open(&root, &root).unwrap();
        let chat = store.create("Execution transcript").unwrap();
        let mut entry = ExecutionTranscriptEntry::new(
            cortex_execution::ExecutionPhase::Tool,
            "Editing src/main.rs",
            "source.replace_text completed",
        );
        entry.tool = Some("source.replace_text".into());
        let timestamp = entry.created_unix_ms;
        let updated = store.append_execution_entry(&chat.id, &entry).unwrap();
        let message = updated.messages.last().unwrap();
        assert_eq!(message.created_unix_ms, timestamp);
        assert!(message.content.contains("Editing src/main.rs"));
        assert!(message.content.contains("source.replace_text completed"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn compaction_notice_does_not_delete_conversation_history() {
        let root = std::env::temp_dir().join(format!(
            "cortex-conversation-compaction-test-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        let store = ConversationStore::open(&root, &root).unwrap();
        let chat = store.create("Compaction").unwrap();
        let chat = store
            .append(&chat.id, ConversationRole::User, "keep this message")
            .unwrap();
        let notice = CompactionNotice::new(14_900, 4_200, "tokens", None);
        let compacted = store.append_compaction_notice(&chat.id, &notice).unwrap();
        assert_eq!(compacted.messages.len(), chat.messages.len() + 1);
        assert!(compacted.messages[0].content.contains("keep this message"));
        assert!(compacted
            .messages
            .last()
            .unwrap()
            .content
            .contains("Full conversation history remains preserved"));
        fs::remove_dir_all(root).unwrap();
    }
}
