//! Canonical reversible source-write transaction authority.

use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const REPLACEMENT_RECOVERY_GUIDANCE: &str =
    "Do not repeat identical replacement arguments. Do not repeat the same replacement arguments. Re-read the current file and retry with a smaller unique target taken from the current source.";

#[derive(Clone, Debug, Serialize, Deserialize)]
struct TransactionManifest {
    id: String,
    state: TransactionState,
    touched: BTreeSet<PathBuf>,
    created: BTreeSet<PathBuf>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
enum TransactionState {
    Active,
    Committed,
    RolledBack,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct TransactionSummary {
    pub id: String,
    pub touched: Vec<PathBuf>,
    pub created: Vec<PathBuf>,
}

pub struct TransactionManager {
    workspace_root: PathBuf,
    transaction_root: PathBuf,
    active: Option<TransactionManifest>,
}

impl TransactionManager {
    pub fn new(
        workspace_root: impl AsRef<Path>,
        state_root: impl AsRef<Path>,
    ) -> Result<Self, String> {
        let workspace_root = fs::canonicalize(workspace_root).map_err(|error| error.to_string())?;
        let transaction_root = state_root.as_ref().join("transactions");
        fs::create_dir_all(&transaction_root).map_err(|error| error.to_string())?;
        let active = load_active(&transaction_root)?;
        Ok(Self {
            workspace_root,
            transaction_root,
            active,
        })
    }

    pub fn begin(&mut self, label: &str) -> Result<String, String> {
        if self.active.is_some() {
            return Err("a Cortex transaction is already active".into());
        }

        let id = format!("{}-{}-{}", unix_ms(), std::process::id(), sanitize(label));
        let manifest = TransactionManifest {
            id: id.clone(),
            state: TransactionState::Active,
            touched: BTreeSet::new(),
            created: BTreeSet::new(),
        };

        fs::create_dir_all(self.dir(&id).join("backup")).map_err(|error| error.to_string())?;
        self.active = Some(manifest);
        self.persist()?;
        Ok(id)
    }

    pub fn active_id(&self) -> Option<&str> {
        self.active
            .as_ref()
            .map(|transaction| transaction.id.as_str())
    }

    pub fn active_summary(&self) -> Option<TransactionSummary> {
        self.active.as_ref().map(|transaction| TransactionSummary {
            id: transaction.id.clone(),
            touched: transaction.touched.iter().cloned().collect(),
            created: transaction.created.iter().cloned().collect(),
        })
    }

    pub fn checkpoint_path(&mut self, relative: impl AsRef<Path>) -> Result<(), String> {
        let relative = normalize_for_workspace(&self.workspace_root, relative.as_ref())?;
        self.checkpoint(&relative)?;
        self.persist()
    }

    pub fn write_text(&mut self, relative: impl AsRef<Path>, content: &str) -> Result<(), String> {
        let relative = normalize_for_workspace(&self.workspace_root, relative.as_ref())?;
        self.checkpoint(&relative)?;

        let path = self.resolve(&relative)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }

        fs::write(path, content.as_bytes()).map_err(|error| error.to_string())?;
        self.persist()
    }

    pub fn replace_text(
        &mut self,
        relative: impl AsRef<Path>,
        old: &str,
        new: &str,
        expected: usize,
    ) -> Result<usize, String> {
        let relative = normalize_for_workspace(&self.workspace_root, relative.as_ref())?;
        let path = self.resolve(&relative)?;
        let text = fs::read_to_string(&path).map_err(|error| error.to_string())?;
        let count = text.matches(old).count();

        if count == expected {
            self.write_text(relative, &text.replace(old, new))?;
            return Ok(count);
        }

        // H67E/H67F: exact matching remains authoritative. For a single
        // guarded replacement only, tolerate formatting-only whitespace drift
        // first. If that cannot identify the requested block, use a unique
        // contextual pair of non-empty line anchors as a second fail-closed
        // recovery path.
        // H67F safe recovery 3: exact -> whitespace-normalized -> contextual
        // line-anchor. This is the complete bounded matching pipeline; there is
        // no recursive or fourth mutation-recovery stage.
        if count == 0 && expected == 1 {
            if let Some(range) = unique_whitespace_normalized_range(&text, old)? {
                let mut updated = String::with_capacity(
                    text.len()
                        .saturating_sub(range.end - range.start)
                        .saturating_add(new.len()),
                );
                updated.push_str(&text[..range.start]);
                updated.push_str(new);
                updated.push_str(&text[range.end..]);
                self.write_text(relative, &updated)?;
                return Ok(1);
            }

            if let Some(range) = unique_line_anchor_range(&text, old)? {
                let mut updated = String::with_capacity(
                    text.len()
                        .saturating_sub(range.end - range.start)
                        .saturating_add(new.len()),
                );
                updated.push_str(&text[..range.start]);
                updated.push_str(new);
                updated.push_str(&text[range.end..]);
                self.write_text(relative, &updated)?;
                return Ok(1);
            }
        }

        Err(format!(
            "replace guard failed for {}: expected {expected} occurrences, found {count}. {REPLACEMENT_RECOVERY_GUIDANCE}",
            relative.display()
        ))
    }

    pub fn commit(&mut self) -> Result<Option<String>, String> {
        let Some(mut transaction) = self.active.take() else {
            return Ok(None);
        };

        transaction.state = TransactionState::Committed;
        persist_manifest(&self.dir(&transaction.id), &transaction)?;
        Ok(Some(transaction.id))
    }

    pub fn rollback(&mut self) -> Result<Option<String>, String> {
        let Some(mut transaction) = self.active.take() else {
            return Ok(None);
        };

        let directory = self.dir(&transaction.id);

        for relative in transaction.touched.iter().rev() {
            let backup = directory.join("backup").join(relative);
            let destination = self.resolve(relative)?;
            if backup.exists() {
                if let Some(parent) = destination.parent() {
                    fs::create_dir_all(parent).map_err(|error| error.to_string())?;
                }
                fs::copy(backup, destination).map_err(|error| error.to_string())?;
            }
        }

        for relative in transaction.created.iter().rev() {
            let destination = self.resolve(relative)?;
            if destination.is_file() {
                fs::remove_file(destination).map_err(|error| error.to_string())?;
            }
        }

        transaction.state = TransactionState::RolledBack;
        persist_manifest(&directory, &transaction)?;
        Ok(Some(transaction.id))
    }

    fn checkpoint(&mut self, relative: &Path) -> Result<(), String> {
        if self.active.is_none() {
            return Err("write requested without an active Cortex transaction".into());
        }

        // Resolve and validate the workspace path before taking the mutable
        // transaction borrow. This keeps path-safety validation intact without
        // overlapping immutable and mutable borrows of `self`.
        let source = self.resolve(relative)?;
        let transaction_root = self.transaction_root.clone();

        let transaction = self
            .active
            .as_mut()
            .expect("active transaction was checked above");

        if transaction.touched.contains(relative) || transaction.created.contains(relative) {
            return Ok(());
        }

        if source.exists() {
            let backup = transaction_root
                .join(&transaction.id)
                .join("backup")
                .join(relative);

            if let Some(parent) = backup.parent() {
                fs::create_dir_all(parent).map_err(|error| error.to_string())?;
            }

            fs::copy(&source, &backup).map_err(|error| error.to_string())?;
            transaction.touched.insert(relative.to_path_buf());
        } else {
            transaction.created.insert(relative.to_path_buf());
        }

        Ok(())
    }

    fn resolve(&self, relative: &Path) -> Result<PathBuf, String> {
        let relative = normalize(relative)?;
        let candidate = self.workspace_root.join(relative);
        ensure_within_root(&self.workspace_root, &candidate)?;
        Ok(candidate)
    }

    fn persist(&self) -> Result<(), String> {
        if let Some(transaction) = &self.active {
            persist_manifest(&self.dir(&transaction.id), transaction)?;
        }
        Ok(())
    }

    fn dir(&self, id: &str) -> PathBuf {
        self.transaction_root.join(id)
    }
}

fn load_active(root: &Path) -> Result<Option<TransactionManifest>, String> {
    let mut active = Vec::new();

    for entry in fs::read_dir(root).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?.path();
        let manifest_path = path.join("transaction.json");
        if !manifest_path.is_file() {
            continue;
        }

        let transaction: TransactionManifest =
            serde_json::from_slice(&fs::read(&manifest_path).map_err(|error| error.to_string())?)
                .map_err(|error| error.to_string())?;

        if transaction.state == TransactionState::Active {
            active.push(transaction);
        }
    }

    active.sort_by(|left, right| left.id.cmp(&right.id));

    match active.len() {
        0 => Ok(None),
        1 => Ok(active.pop()),
        count => Err(format!(
            "found {count} active Cortex transactions; resolve transaction manifests before continuing"
        )),
    }
}

fn persist_manifest(directory: &Path, transaction: &TransactionManifest) -> Result<(), String> {
    fs::create_dir_all(directory).map_err(|error| error.to_string())?;
    fs::write(
        directory.join("transaction.json"),
        serde_json::to_vec_pretty(transaction).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())
}

fn ensure_within_root(root: &Path, candidate: &Path) -> Result<(), String> {
    let mut probe = candidate;

    loop {
        if probe.exists() {
            let canonical = fs::canonicalize(probe).map_err(|error| error.to_string())?;
            if !canonical.starts_with(root) {
                return Err(format!(
                    "workspace path escapes through link/reparse point: {}",
                    candidate.display()
                ));
            }
            return Ok(());
        }

        probe = probe
            .parent()
            .ok_or_else(|| format!("unsafe workspace path: {}", candidate.display()))?;
    }
}

fn normalize(path: &Path) -> Result<PathBuf, String> {
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        Err(format!("unsafe workspace path: {}", path.display()))
    } else {
        Ok(path.to_path_buf())
    }
}

/// Convert either a relative path or an absolute in-workspace path to the one canonical
/// workspace-relative identity used by transaction manifests and backup paths.
fn normalize_for_workspace(root: &Path, path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return normalize(path);
    }
    if path
        .components()
        .any(|component| matches!(component, Component::ParentDir))
    {
        return Err(format!("unsafe workspace path: {}", path.display()));
    }

    let canonical_root = fs::canonicalize(root).map_err(|error| error.to_string())?;
    let mut probe = path;
    while !probe.exists() {
        probe = probe
            .parent()
            .ok_or_else(|| format!("unsafe workspace path: {}", path.display()))?;
    }
    let canonical_probe = fs::canonicalize(probe).map_err(|error| error.to_string())?;
    let relative_probe = canonical_probe.strip_prefix(&canonical_root).map_err(|_| {
        format!(
            "workspace path escapes authoritative root: {}",
            path.display()
        )
    })?;
    let suffix = path
        .strip_prefix(probe)
        .map_err(|_| format!("unsafe workspace path: {}", path.display()))?;
    normalize(&relative_probe.join(suffix))
}

/// Return the one source byte range whose non-whitespace character stream
/// matches `pattern`. This intentionally supports only a unique candidate: if
/// formatting normalization makes two regions equivalent, the mutation is
/// rejected rather than guessed.
fn unique_whitespace_normalized_range(
    text: &str,
    pattern: &str,
) -> Result<Option<std::ops::Range<usize>>, String> {
    let pattern_chars: Vec<char> = pattern
        .chars()
        .filter(|character| !character.is_whitespace())
        .collect();

    if pattern_chars.is_empty() {
        return Err("adaptive replacement pattern contains only whitespace".into());
    }

    let source_chars: Vec<(usize, usize, char)> = text
        .char_indices()
        .filter(|(_, character)| !character.is_whitespace())
        .map(|(start, character)| (start, start + character.len_utf8(), character))
        .collect();

    if pattern_chars.len() > source_chars.len() {
        return Ok(None);
    }

    let mut matched_range = None;
    for start in 0..=(source_chars.len() - pattern_chars.len()) {
        let candidate = &source_chars[start..start + pattern_chars.len()];
        if !candidate
            .iter()
            .map(|(_, _, character)| *character)
            .eq(pattern_chars.iter().copied())
        {
            continue;
        }

        if matched_range.is_some() {
            return Err(format!(
                "adaptive replacement is ambiguous after whitespace normalization. {REPLACEMENT_RECOVERY_GUIDANCE}"
            ));
        }

        let mut range_start = candidate[0].0;
        let mut range_end = candidate[candidate.len() - 1].1;

        if pattern
            .chars()
            .next()
            .is_some_and(|character| character.is_whitespace())
        {
            while let Some((previous, character)) = text[..range_start].char_indices().next_back() {
                if !character.is_whitespace() {
                    break;
                }
                range_start = previous;
            }
        }

        if pattern
            .chars()
            .next_back()
            .is_some_and(|character| character.is_whitespace())
        {
            for character in text[range_end..].chars() {
                if !character.is_whitespace() {
                    break;
                }
                range_end += character.len_utf8();
            }
        }

        matched_range = Some(range_start..range_end);
    }

    Ok(matched_range)
}

fn unique_line_anchor_range(
    text: &str,
    pattern: &str,
) -> Result<Option<std::ops::Range<usize>>, String> {
    struct LineSpan {
        start: usize,
        content_end: usize,
        line_end: usize,
        normalized: String,
    }

    fn line_spans(value: &str) -> Vec<LineSpan> {
        let mut spans = Vec::new();
        let mut start = 0usize;

        for segment in value.split_inclusive('\n') {
            let line_end = start + segment.len();
            let content_end = if segment.ends_with("\r\n") {
                line_end.saturating_sub(2)
            } else if segment.ends_with('\n') {
                line_end.saturating_sub(1)
            } else {
                line_end
            };

            let normalized = value[start..content_end]
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");

            spans.push(LineSpan {
                start,
                content_end,
                line_end,
                normalized,
            });
            start = line_end;
        }

        if start < value.len() {
            let content_end = value.len();
            let normalized = value[start..content_end]
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");
            spans.push(LineSpan {
                start,
                content_end,
                line_end: content_end,
                normalized,
            });
        }

        spans
    }

    let pattern_lines = line_spans(pattern);
    let meaningful_pattern: Vec<(usize, &LineSpan)> = pattern_lines
        .iter()
        .enumerate()
        .filter(|(_, line)| !line.normalized.is_empty())
        .collect();

    // A contextual range needs two independent line anchors. A one-line
    // request remains under the exact/whitespace-normalized guards.
    if meaningful_pattern.len() < 2 {
        return Ok(None);
    }

    let first_pattern = meaningful_pattern[0].1;
    let last_pattern = meaningful_pattern[meaningful_pattern.len() - 1].1;

    let source_lines = line_spans(text);
    let source_anchor_indices: Vec<usize> = source_lines
        .iter()
        .enumerate()
        .filter(|(_, line)| !line.normalized.is_empty())
        .map(|(index, _)| index)
        .collect();

    let mut matched_range = None;
    for (first_position, &first_source_index) in source_anchor_indices.iter().enumerate() {
        if source_lines[first_source_index].normalized != first_pattern.normalized {
            continue;
        }

        for &last_source_index in source_anchor_indices.iter().skip(first_position + 1) {
            if source_lines[last_source_index].normalized != last_pattern.normalized {
                continue;
            }

            let range_end = if pattern.ends_with('\n') {
                source_lines[last_source_index].line_end
            } else {
                source_lines[last_source_index].content_end
            };
            let candidate = source_lines[first_source_index].start..range_end;

            if matched_range.is_some() {
                return Err(format!(
                    "contextual line-anchor replacement is ambiguous: no unique contextual line-anchor range exists. {REPLACEMENT_RECOVERY_GUIDANCE}"
                ));
            }

            matched_range = Some(candidate);
        }
    }

    Ok(matched_range)
}

fn sanitize(value: &str) -> String {
    let sanitized: String = value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .collect();

    if sanitized.is_empty() {
        "transaction".into()
    } else {
        sanitized
    }
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

    fn temporary_workspace(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "open2d-cortex-transactions-{label}-{}-{}",
            std::process::id(),
            unix_ms()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn parent_path_rejected() {
        assert!(normalize(Path::new("../outside")).is_err());
    }

    #[test]
    fn absolute_in_workspace_path_normalizes_to_transaction_relative_identity() {
        let root = temporary_workspace("absolute-path");
        let workspace = root.join("workspace");
        fs::create_dir_all(workspace.join("src")).unwrap();
        fs::write(workspace.join("src/main.rs"), "fn main() {}\n").unwrap();
        let canonical_root = fs::canonicalize(&workspace).unwrap();
        let absolute = fs::canonicalize(workspace.join("src/main.rs")).unwrap();
        assert_eq!(
            normalize_for_workspace(&canonical_root, &absolute).unwrap(),
            PathBuf::from("src").join("main.rs")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn write_text_creates_real_project_file_and_rollback_removes_it() {
        let root = temporary_workspace("write-rollback");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(&workspace).unwrap();

        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("write-test").unwrap();
        transactions
            .write_text("src/generated.rs", "pub const VALUE: u32 = 7;\n")
            .unwrap();

        let generated = workspace.join("src/generated.rs");
        assert_eq!(
            fs::read_to_string(&generated).unwrap(),
            "pub const VALUE: u32 = 7;\n"
        );

        transactions.rollback().unwrap();
        assert!(!generated.exists());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_edits_real_project_file_and_rollback_restores_it() {
        let root = temporary_workspace("replace-rollback");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/main.rs");
        fs::write(&target, "fn main() { println!(\"old\"); }\n").unwrap();

        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("replace-test").unwrap();
        assert_eq!(
            transactions
                .replace_text("src/main.rs", "println!(\"old\")", "println!(\"new\")", 1)
                .unwrap(),
            1
        );
        assert_eq!(
            fs::read_to_string(&target).unwrap(),
            "fn main() { println!(\"new\"); }\n"
        );

        transactions.rollback().unwrap();
        assert_eq!(
            fs::read_to_string(&target).unwrap(),
            "fn main() { println!(\"old\"); }\n"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_accepts_unique_whitespace_normalized_range() {
        let root = temporary_workspace("adaptive-unique");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/lib.rs");
        fs::write(
            &target,
            "pub fn value() -> u32 {\n    if true {\n        7\n    } else {\n        9\n    }\n}\n",
        )
        .unwrap();

        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("adaptive-unique-test").unwrap();
        let old = "if true { 7 } else { 9 }";
        let new = "if true {\n        8\n    } else {\n        9\n    }";
        assert_eq!(
            transactions
                .replace_text("src/lib.rs", old, new, 1)
                .unwrap(),
            1
        );
        assert!(fs::read_to_string(&target).unwrap().contains("        8\n"));

        transactions.rollback().unwrap();
        assert!(fs::read_to_string(&target).unwrap().contains("        7\n"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_rejects_ambiguous_whitespace_normalized_range() {
        let root = temporary_workspace("adaptive-ambiguous");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/lib.rs");
        fs::write(
            &target,
            "fn one() { value( 1 ); }\nfn two() { value(\n    1\n); }\n",
        )
        .unwrap();

        let original = fs::read_to_string(&target).unwrap();
        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("adaptive-ambiguous-test").unwrap();
        let error = transactions
            .replace_text("src/lib.rs", "value(1);", "value(2);", 1)
            .unwrap_err();
        assert!(error.contains("ambiguous"));
        assert!(error.contains("Do not repeat identical replacement arguments"));
        assert!(error.contains("Do not repeat the same replacement arguments"));
        assert_eq!(fs::read_to_string(&target).unwrap(), original);

        transactions.rollback().unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_accepts_unique_contextual_line_anchor_range() {
        let root = temporary_workspace("line-anchor-unique");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/lib.rs");
        fs::write(
            &target,
            "fn configure() {\n    begin_config();\n    let current = 42;\n    apply_config(current);\n    finish_config();\n}\n",
        )
        .unwrap();

        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("line-anchor-unique-test").unwrap();
        let old = "    begin_config();\n    let legacy = 7;\n    apply_config(legacy);\n    finish_config();";
        let new = "    begin_config();\n    let current = 84;\n    apply_config(current);\n    finish_config();";
        assert_eq!(
            transactions
                .replace_text("src/lib.rs", old, new, 1)
                .unwrap(),
            1
        );

        let updated = fs::read_to_string(&target).unwrap();
        assert!(updated.contains("let current = 84;"));
        assert!(!updated.contains("let current = 42;"));

        transactions.rollback().unwrap();
        assert!(fs::read_to_string(&target)
            .unwrap()
            .contains("let current = 42;"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_rejects_ambiguous_contextual_line_anchor_range() {
        let root = temporary_workspace("line-anchor-ambiguous");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/lib.rs");
        fs::write(
            &target,
            "fn one() {\n    begin_config();\n    let current = 1;\n    finish_config();\n}\n\nfn two() {\n    begin_config();\n    let current = 2;\n    finish_config();\n}\n",
        )
        .unwrap();

        let original = fs::read_to_string(&target).unwrap();
        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("line-anchor-ambiguous-test").unwrap();
        let old = "    begin_config();\n    let legacy = 7;\n    finish_config();";
        let error = transactions
            .replace_text(
                "src/lib.rs",
                old,
                "    begin_config();\n    let current = 9;\n    finish_config();",
                1,
            )
            .unwrap_err();

        assert!(error.contains("contextual line-anchor replacement is ambiguous"));
        assert!(error.contains("no unique"));
        assert!(error.contains("Do not repeat identical replacement arguments"));
        assert!(error.contains("Do not repeat the same replacement arguments"));
        assert_eq!(fs::read_to_string(&target).unwrap(), original);

        transactions.rollback().unwrap();
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn replace_text_guard_failure_includes_recovery_guidance() {
        let root = temporary_workspace("guard-guidance");
        let workspace = root.join("workspace");
        let state = root.join("state");
        fs::create_dir_all(workspace.join("src")).unwrap();
        let target = workspace.join("src/lib.rs");
        fs::write(&target, "pub const VALUE: u32 = 7;\n").unwrap();

        let mut transactions = TransactionManager::new(&workspace, &state).unwrap();
        transactions.begin("guard-guidance-test").unwrap();
        let error = transactions
            .replace_text(
                "src/lib.rs",
                "pub const MISSING: u32 = 8;",
                "pub const MISSING: u32 = 9;",
                1,
            )
            .unwrap_err();
        assert!(error.contains("Do not repeat identical replacement arguments"));
        assert!(error.contains("Do not repeat the same replacement arguments"));
        assert!(error.contains("Re-read the current file"));
        assert_eq!(
            fs::read_to_string(&target).unwrap(),
            "pub const VALUE: u32 = 7;\n"
        );

        transactions.rollback().unwrap();
        fs::remove_dir_all(root).unwrap();
    }
}
