//! Cortex Vault: deterministic lexical retrieval plus optional local embeddings.
use cortex_protocol::{EmbeddingProvider, EmbeddingRequest};
use serde::{Deserialize, Serialize};
use std::cmp::Reverse;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LibraryItemKind {
    RegisteredProject,
    ProjectCandidate,
    SourceRepository,
    AssetCollection,
    Documents,
    Archive,
    BuildOutput,
    DependencyCache,
    Folder,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LibraryCatalogRecord {
    pub path: PathBuf,
    pub kind: LibraryItemKind,
    pub project_id: Option<String>,
    pub bytes: u64,
    pub modified_unix_ms: u128,
    pub is_directory: bool,
    pub content_hash: Option<String>,
    pub last_seen_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LibraryMemoryRecord {
    pub id: String,
    pub scope: String,
    pub project_id: Option<String>,
    pub title: String,
    pub content: String,
    #[serde(default)]
    pub source_paths: Vec<PathBuf>,
    #[serde(default)]
    pub tags: Vec<String>,
    pub created_unix_ms: u128,
    pub updated_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OrganizationSuggestion {
    pub id: String,
    pub path: PathBuf,
    pub category: String,
    pub reason: String,
    pub confidence: u8,
    pub proposed_action: String,
    pub status: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct LibraryScanCursor {
    pub volume_identity: Option<String>,
    pub change_journal_id: Option<u64>,
    pub next_usn: Option<i64>,
    pub fallback_scan_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct VaultStoragePolicy {
    pub max_bytes: Option<u64>,
    pub warning_percent: u8,
    pub critical_percent: u8,
    #[serde(default)]
    pub category_budgets: BTreeMap<String, u64>,
    #[serde(default)]
    pub project_budgets: BTreeMap<String, u64>,
}

impl Default for VaultStoragePolicy {
    fn default() -> Self {
        Self {
            max_bytes: None,
            warning_percent: 85,
            critical_percent: 95,
            category_budgets: BTreeMap::new(),
            project_budgets: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct VaultUsageSnapshot {
    pub captured_unix_ms: u128,
    pub managed_bytes: u64,
    pub catalog_items: usize,
    #[serde(default)]
    pub bytes_by_category: BTreeMap<String, u64>,
    #[serde(default)]
    pub bytes_by_project: BTreeMap<String, u64>,
    pub reclaimable_bytes: u64,
    pub duplicate_bytes: u64,
    pub quota_bytes: Option<u64>,
    pub quota_used_percent: Option<u8>,
    pub quota_state: String,
    #[serde(default)]
    pub category_budget_used_percent: BTreeMap<String, u8>,
    #[serde(default)]
    pub project_budget_used_percent: BTreeMap<String, u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct KnowledgeNode {
    pub id: String,
    pub kind: String,
    pub label: String,
    pub project_id: Option<String>,
    pub state: String,
    pub provenance: String,
    #[serde(default)]
    pub source_paths: Vec<PathBuf>,
    pub updated_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct KnowledgeEdge {
    pub from: String,
    pub relation: String,
    pub to: String,
    pub provenance: String,
    pub updated_unix_ms: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LibraryMemoryDatabase {
    pub schema_version: u32,
    pub library_root: PathBuf,
    pub catalog: BTreeMap<String, LibraryCatalogRecord>,
    pub memories: Vec<LibraryMemoryRecord>,
    pub organization: Vec<OrganizationSuggestion>,
    pub scan_cursor: LibraryScanCursor,
    #[serde(default)]
    pub storage_policy: VaultStoragePolicy,
    #[serde(default)]
    pub metrics_history: Vec<VaultUsageSnapshot>,
    #[serde(default)]
    pub knowledge_nodes: BTreeMap<String, KnowledgeNode>,
    #[serde(default)]
    pub knowledge_edges: Vec<KnowledgeEdge>,
    pub updated_unix_ms: u128,
}

impl LibraryMemoryDatabase {
    pub fn open(library_root: &Path) -> Result<Self, String> {
        let path = Self::database_path(library_root);
        if path.is_file() {
            let mut database: Self =
                serde_json::from_slice(&fs::read(&path).map_err(|error| error.to_string())?)
                    .map_err(|error| {
                        format!("invalid Cortex Vault memory {}: {error}", path.display())
                    })?;
            database.library_root = library_root.to_path_buf();
            return Ok(database);
        }
        let database = Self {
            schema_version: 1,
            library_root: library_root.to_path_buf(),
            catalog: BTreeMap::new(),
            memories: Vec::new(),
            organization: Vec::new(),
            scan_cursor: LibraryScanCursor::default(),
            storage_policy: VaultStoragePolicy::default(),
            metrics_history: Vec::new(),
            knowledge_nodes: BTreeMap::new(),
            knowledge_edges: Vec::new(),
            updated_unix_ms: library_unix_ms(),
        };
        database.save()?;
        Ok(database)
    }

    pub fn database_path(library_root: &Path) -> PathBuf {
        library_root
            .join(".cortex")
            .join("memory")
            .join("library_memory.json")
    }

    pub fn save(&self) -> Result<(), String> {
        let path = Self::database_path(&self.library_root);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::write(
            &path,
            serde_json::to_vec_pretty(self).map_err(|error| error.to_string())?,
        )
        .map_err(|error| {
            format!(
                "failed to save Cortex Vault memory {}: {error}",
                path.display()
            )
        })
    }

    pub fn record_catalog_path(
        &mut self,
        path: &Path,
        kind: LibraryItemKind,
        project_id: Option<String>,
    ) -> Result<(), String> {
        let canonical = fs::canonicalize(path).map_err(|error| error.to_string())?;
        if !canonical.starts_with(&self.library_root) {
            return Err("catalog path is outside the Cortex Vault".into());
        }
        let metadata = fs::metadata(&canonical).map_err(|error| error.to_string())?;
        let now = library_unix_ms();
        let key = canonical.to_string_lossy().replace('\\', "/");
        self.catalog.insert(
            key,
            LibraryCatalogRecord {
                path: canonical,
                kind,
                project_id,
                bytes: if metadata.is_file() {
                    metadata.len()
                } else {
                    0
                },
                modified_unix_ms: metadata_modified_ms(&metadata),
                is_directory: metadata.is_dir(),
                content_hash: None,
                last_seen_unix_ms: now,
            },
        );
        self.updated_unix_ms = now;
        Ok(())
    }

    pub fn remember(
        &mut self,
        scope: &str,
        project_id: Option<String>,
        title: &str,
        content: &str,
        source_paths: Vec<PathBuf>,
        tags: Vec<String>,
    ) -> String {
        let now = library_unix_ms();
        let id = format!("{now}-{}-memory", self.memories.len());
        self.memories.push(LibraryMemoryRecord {
            id: id.clone(),
            scope: scope.to_string(),
            project_id,
            title: title.to_string(),
            content: content.to_string(),
            source_paths,
            tags,
            created_unix_ms: now,
            updated_unix_ms: now,
        });
        self.updated_unix_ms = now;
        id
    }

    pub fn propose_organization(
        &mut self,
        path: PathBuf,
        category: &str,
        reason: &str,
        confidence: u8,
        proposed_action: &str,
    ) -> String {
        let now = library_unix_ms();
        let id = format!("{now}-{}-org", self.organization.len());
        self.organization.push(OrganizationSuggestion {
            id: id.clone(),
            path,
            category: category.to_string(),
            reason: reason.to_string(),
            confidence: confidence.min(100),
            proposed_action: proposed_action.to_string(),
            status: "pending".into(),
        });
        self.updated_unix_ms = now;
        id
    }

    pub fn pending_organization(&self) -> Vec<&OrganizationSuggestion> {
        self.organization
            .iter()
            .filter(|suggestion| suggestion.status == "pending")
            .collect()
    }

    pub fn set_storage_policy(&mut self, mut policy: VaultStoragePolicy) -> Result<(), String> {
        policy.warning_percent = policy.warning_percent.clamp(1, 99);
        policy.critical_percent = policy.critical_percent.clamp(policy.warning_percent, 100);
        self.storage_policy = policy;
        self.updated_unix_ms = library_unix_ms();
        self.save()
    }

    pub fn usage_snapshot(&self) -> VaultUsageSnapshot {
        let mut bytes_by_category = BTreeMap::<String, u64>::new();
        let mut bytes_by_project = BTreeMap::<String, u64>::new();
        let mut hashes = BTreeMap::<String, (u64, u64)>::new();
        let mut managed_bytes = 0u64;
        let mut reclaimable_bytes = 0u64;
        for record in self.catalog.values() {
            if record.is_directory {
                continue;
            }
            managed_bytes = managed_bytes.saturating_add(record.bytes);
            let category = bytes_by_category
                .entry(library_item_kind_label(&record.kind).to_string())
                .or_default();
            *category = category.saturating_add(record.bytes);
            if let Some(project_id) = record.project_id.as_ref() {
                let entry = bytes_by_project.entry(project_id.clone()).or_default();
                *entry = entry.saturating_add(record.bytes);
            }
            if matches!(
                record.kind,
                LibraryItemKind::BuildOutput | LibraryItemKind::DependencyCache
            ) {
                reclaimable_bytes = reclaimable_bytes.saturating_add(record.bytes);
            }
            if let Some(hash) = record.content_hash.as_ref() {
                let entry = hashes.entry(hash.clone()).or_insert((record.bytes, 0));
                entry.1 = entry.1.saturating_add(1);
            }
        }
        let duplicate_bytes = hashes
            .values()
            .map(|(bytes, count)| bytes.saturating_mul(count.saturating_sub(1)))
            .sum();
        let quota_used_percent = self.storage_policy.max_bytes.and_then(|max| {
            (max > 0).then_some(((managed_bytes.saturating_mul(100) / max).min(100)) as u8)
        });
        let quota_state = match quota_used_percent {
            Some(percent) if percent >= self.storage_policy.critical_percent => "critical",
            Some(percent) if percent >= self.storage_policy.warning_percent => "warning",
            Some(_) => "healthy",
            None => "unbounded",
        }
        .to_string();
        let category_budget_used_percent = self
            .storage_policy
            .category_budgets
            .iter()
            .map(|(category, budget)| {
                let used = bytes_by_category.get(category).copied().unwrap_or_default();
                let percent = used
                    .saturating_mul(100)
                    .checked_div(*budget)
                    .map(|value| value.min(100) as u8)
                    .unwrap_or(100);
                (category.clone(), percent)
            })
            .collect();
        let project_budget_used_percent = self
            .storage_policy
            .project_budgets
            .iter()
            .map(|(project, budget)| {
                let used = bytes_by_project.get(project).copied().unwrap_or_default();
                let percent = used
                    .saturating_mul(100)
                    .checked_div(*budget)
                    .map(|value| value.min(100) as u8)
                    .unwrap_or(100);
                (project.clone(), percent)
            })
            .collect();
        VaultUsageSnapshot {
            captured_unix_ms: library_unix_ms(),
            managed_bytes,
            catalog_items: self.catalog.len(),
            bytes_by_category,
            bytes_by_project,
            reclaimable_bytes,
            duplicate_bytes,
            quota_bytes: self.storage_policy.max_bytes,
            quota_used_percent,
            quota_state,
            category_budget_used_percent,
            project_budget_used_percent,
        }
    }

    pub fn ensure_allocation_within_policy(&self, additional_bytes: u64) -> Result<(), String> {
        let Some(max_bytes) = self.storage_policy.max_bytes else {
            return Ok(());
        };
        let used = self.usage_snapshot().managed_bytes;
        let projected = used.saturating_add(additional_bytes);
        if projected > max_bytes {
            return Err(format!(
                "Cortex Vault hard storage ceiling would be exceeded: used={used} additional={additional_bytes} limit={max_bytes}"
            ));
        }
        Ok(())
    }

    pub fn ensure_scoped_allocation_within_policy(
        &self,
        project_id: Option<&str>,
        category: Option<&str>,
        additional_bytes: u64,
    ) -> Result<(), String> {
        self.ensure_allocation_within_policy(additional_bytes)?;
        let snapshot = self.usage_snapshot();
        if let Some((category, limit)) = category.and_then(|category| {
            self.storage_policy
                .category_budgets
                .get(category)
                .map(|limit| (category, limit))
        }) {
            let used = snapshot
                .bytes_by_category
                .get(category)
                .copied()
                .unwrap_or_default();
            if used.saturating_add(additional_bytes) > *limit {
                return Err(format!(
                    "Cortex Vault category budget would be exceeded: category={category} used={used} additional={additional_bytes} limit={limit}"
                ));
            }
        }
        if let Some((project_id, limit)) = project_id.and_then(|project_id| {
            self.storage_policy
                .project_budgets
                .get(project_id)
                .map(|limit| (project_id, limit))
        }) {
            let used = snapshot
                .bytes_by_project
                .get(project_id)
                .copied()
                .unwrap_or_default();
            if used.saturating_add(additional_bytes) > *limit {
                return Err(format!(
                    "Cortex Vault project budget would be exceeded: project={project_id} used={used} additional={additional_bytes} limit={limit}"
                ));
            }
        }
        Ok(())
    }

    pub fn record_usage_snapshot(&mut self) -> Result<VaultUsageSnapshot, String> {
        let snapshot = self.usage_snapshot();
        self.metrics_history.push(snapshot.clone());
        if self.metrics_history.len() > 366 {
            let excess = self.metrics_history.len() - 366;
            self.metrics_history.drain(..excess);
        }
        self.updated_unix_ms = library_unix_ms();
        self.save()?;
        Ok(snapshot)
    }

    pub fn upsert_knowledge_node(&mut self, mut node: KnowledgeNode) {
        node.updated_unix_ms = library_unix_ms();
        self.knowledge_nodes.insert(node.id.clone(), node);
        self.updated_unix_ms = library_unix_ms();
    }

    pub fn relate(&mut self, from: &str, relation: &str, to: &str, provenance: &str) {
        let now = library_unix_ms();
        if let Some(existing) = self
            .knowledge_edges
            .iter_mut()
            .find(|edge| edge.from == from && edge.relation == relation && edge.to == to)
        {
            existing.provenance = provenance.to_string();
            existing.updated_unix_ms = now;
        } else {
            self.knowledge_edges.push(KnowledgeEdge {
                from: from.to_string(),
                relation: relation.to_string(),
                to: to.to_string(),
                provenance: provenance.to_string(),
                updated_unix_ms: now,
            });
        }
        self.updated_unix_ms = now;
    }

    pub fn knowledge_status(&self, project_id: Option<&str>) -> serde_json::Value {
        let nodes = self
            .knowledge_nodes
            .values()
            .filter(|node| {
                project_id.is_none_or(|project| node.project_id.as_deref() == Some(project))
            })
            .count();
        let edges = self
            .knowledge_edges
            .iter()
            .filter(|edge| {
                project_id.is_none_or(|project| {
                    self.knowledge_nodes
                        .get(&edge.from)
                        .and_then(|node| node.project_id.as_deref())
                        == Some(project)
                        || self
                            .knowledge_nodes
                            .get(&edge.to)
                            .and_then(|node| node.project_id.as_deref())
                            == Some(project)
                })
            })
            .count();
        serde_json::json!({
            "nodes": nodes,
            "edges": edges,
            "memories": self.memories.iter().filter(|memory| project_id.is_none_or(|project| memory.project_id.as_deref() == Some(project))).count(),
            "updated_unix_ms": self.updated_unix_ms
        })
    }

    pub fn compile_context(
        &self,
        project_id: Option<&str>,
        query: &str,
        limit: usize,
    ) -> Vec<String> {
        let tokens = tokenize(query);
        let mut candidates = Vec::<(usize, u128, String)>::new();
        for memory in self.memories.iter().filter(|memory| {
            project_id.is_none_or(|project| memory.project_id.as_deref() == Some(project))
        }) {
            let haystack = format!(
                "{} {} {}",
                memory.title,
                memory.content,
                memory.tags.join(" ")
            )
            .to_ascii_lowercase();
            let score = tokens
                .iter()
                .filter(|token| haystack.contains(token.as_str()))
                .count();
            if score > 0 || tokens.is_empty() {
                candidates.push((
                    score,
                    memory.updated_unix_ms,
                    format!(
                        "Memory [{}]: {} — {}",
                        memory.scope, memory.title, memory.content
                    ),
                ));
            }
        }
        for node in self.knowledge_nodes.values().filter(|node| {
            project_id.is_none_or(|project| node.project_id.as_deref() == Some(project))
        }) {
            let relationships = self
                .knowledge_edges
                .iter()
                .filter(|edge| {
                    let other = if edge.from == node.id {
                        Some(edge.to.as_str())
                    } else if edge.to == node.id {
                        Some(edge.from.as_str())
                    } else {
                        None
                    };
                    other.is_some_and(|other| {
                        self.knowledge_nodes.get(other).is_none_or(|other_node| {
                            other_node.project_id.is_none()
                                || other_node.project_id.as_deref() == node.project_id.as_deref()
                        })
                    })
                })
                .map(|edge| format!("{} -{}-> {}", edge.from, edge.relation, edge.to))
                .collect::<Vec<_>>();
            let haystack = format!(
                "{} {} {} {} {}",
                node.kind,
                node.label,
                node.state,
                node.provenance,
                relationships.join(" ")
            )
            .to_ascii_lowercase();
            let score = tokens
                .iter()
                .filter(|token| haystack.contains(token.as_str()))
                .count();
            if score > 0 || tokens.is_empty() {
                let relations = if relationships.is_empty() {
                    String::new()
                } else {
                    format!(" | relations: {}", relationships.join("; "))
                };
                candidates.push((
                    score,
                    node.updated_unix_ms,
                    format!(
                        "Knowledge [{}] {} | state={} | provenance={}{}",
                        node.kind, node.label, node.state, node.provenance, relations
                    ),
                ));
            }
        }
        candidates.sort_by_key(|(score, updated, _)| (Reverse(*score), Reverse(*updated)));
        candidates
            .into_iter()
            .take(limit.max(1))
            .map(|(_, _, text)| text)
            .collect()
    }
}

fn library_item_kind_label(kind: &LibraryItemKind) -> &'static str {
    match kind {
        LibraryItemKind::RegisteredProject => "projects",
        LibraryItemKind::ProjectCandidate => "project_candidates",
        LibraryItemKind::SourceRepository => "source",
        LibraryItemKind::AssetCollection => "assets",
        LibraryItemKind::Documents => "documents",
        LibraryItemKind::Archive => "archives",
        LibraryItemKind::BuildOutput => "build_output",
        LibraryItemKind::DependencyCache => "dependency_cache",
        LibraryItemKind::Folder => "folders",
        LibraryItemKind::Unknown => "unknown",
    }
}

fn metadata_modified_ms(metadata: &fs::Metadata) -> u128 {
    metadata
        .modified()
        .ok()
        .and_then(|value| value.duration_since(UNIX_EPOCH).ok())
        .map(|value| value.as_millis())
        .unwrap_or_default()
}

fn library_unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ProjectIndex {
    pub schema_version: u32,
    pub documents: Vec<IndexedDocument>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IndexedDocument {
    pub path: PathBuf,
    pub text: String,
    pub tokens: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MemoryHit {
    pub path: PathBuf,
    pub score: usize,
    pub preview: String,
}

impl ProjectIndex {
    pub fn build(root: &Path, files: &[PathBuf], max_bytes_per_file: usize) -> Self {
        let mut documents = Vec::new();
        for relative in files {
            let path = root.join(relative);
            let Ok(meta) = fs::metadata(&path) else {
                continue;
            };
            if meta.len() > max_bytes_per_file as u64 {
                continue;
            }
            let Ok(text) = fs::read_to_string(&path) else {
                continue;
            };
            let tokens = tokenize(&text);
            documents.push(IndexedDocument {
                path: relative.clone(),
                text,
                tokens,
            });
        }
        Self {
            schema_version: 1,
            documents,
        }
    }

    pub fn search(&self, query: &str, limit: usize) -> Vec<MemoryHit> {
        let query_tokens = tokenize(query);
        let mut hits: Vec<MemoryHit> = self
            .documents
            .iter()
            .filter_map(|doc| {
                let mut score = 0usize;
                for query in &query_tokens {
                    score += doc.tokens.iter().filter(|token| *token == query).count() * 4;
                    if doc
                        .path
                        .to_string_lossy()
                        .to_ascii_lowercase()
                        .contains(query)
                    {
                        score += 8;
                    }
                }
                if score == 0 {
                    return None;
                }
                let preview = best_preview(&doc.text, &query_tokens);
                Some(MemoryHit {
                    path: doc.path.clone(),
                    score,
                    preview,
                })
            })
            .collect();
        hits.sort_by_key(|hit| Reverse(hit.score));
        hits.truncate(limit);
        hits
    }

    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        fs::write(path, serde_json::to_vec(self).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }

    pub fn load(path: &Path) -> Result<Self, String> {
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }
}

fn tokenize(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_ascii_alphanumeric() && c != '_' && c != '-')
        .filter(|token| token.len() >= 2)
        .map(|token| token.to_ascii_lowercase())
        .collect()
}

fn best_preview(text: &str, query: &[String]) -> String {
    for line in text.lines() {
        let lower = line.to_ascii_lowercase();
        if query.iter().any(|token| lower.contains(token)) {
            return line.trim().chars().take(300).collect();
        }
    }
    text.lines()
        .next()
        .unwrap_or_default()
        .chars()
        .take(300)
        .collect()
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Vault {
    pub schema_version: u32,
    pub lexical: ProjectIndex,
    pub embeddings: Vec<EmbeddingRecord>,
    pub embedding_model: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EmbeddingRecord {
    pub path: PathBuf,
    pub vector: Vec<f32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VaultHit {
    pub path: PathBuf,
    pub score: f32,
    pub lexical_score: Option<usize>,
    pub vector_score: Option<f32>,
    pub preview: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VaultStatus {
    pub documents: usize,
    pub embedded_documents: usize,
    pub embedding_model: Option<String>,
}
impl Vault {
    pub fn build_lexical(root: &Path, files: &[PathBuf], max: usize) -> Self {
        Self {
            schema_version: 1,
            lexical: ProjectIndex::build(root, files, max),
            embeddings: Vec::new(),
            embedding_model: None,
        }
    }
    pub fn status(&self) -> VaultStatus {
        VaultStatus {
            documents: self.lexical.documents.len(),
            embedded_documents: self.embeddings.len(),
            embedding_model: self.embedding_model.clone(),
        }
    }
    pub fn rebuild_embeddings(
        &mut self,
        p: &dyn EmbeddingProvider,
        model: &str,
        max_docs: usize,
        max_chars: usize,
    ) -> Result<usize, String> {
        let docs = self
            .lexical
            .documents
            .iter()
            .take(max_docs.clamp(1, 20000))
            .collect::<Vec<_>>();
        let mut rec = Vec::new();
        for chunk in docs.chunks(16) {
            let input = chunk
                .iter()
                .map(|d| {
                    d.text
                        .chars()
                        .take(max_chars.clamp(256, 16000))
                        .collect::<String>()
                })
                .collect::<Vec<_>>();
            let vecs = p
                .embed(&EmbeddingRequest {
                    model: Some(model.into()),
                    input,
                })
                .map_err(|e| e.to_string())?;
            for (d, v) in chunk.iter().zip(vecs) {
                rec.push(EmbeddingRecord {
                    path: d.path.clone(),
                    vector: v,
                });
            }
        }
        self.embeddings = rec;
        self.embedding_model = Some(model.into());
        Ok(self.embeddings.len())
    }
    pub fn search(
        &self,
        q: &str,
        limit: usize,
        p: Option<&dyn EmbeddingProvider>,
    ) -> Result<Vec<VaultHit>, String> {
        let limit = limit.clamp(1, 100);
        let lexical = self.lexical.search(q, limit * 4);
        let mut m = BTreeMap::<PathBuf, VaultHit>::new();
        for (rank, h) in lexical.iter().enumerate() {
            m.insert(
                h.path.clone(),
                VaultHit {
                    path: h.path.clone(),
                    score: (1.0 / (rank as f32 + 1.0)) * 0.60,
                    lexical_score: Some(h.score),
                    vector_score: None,
                    preview: h.preview.clone(),
                },
            );
        }
        if let (Some(p), Some(model)) = (p, self.embedding_model.as_deref()) {
            if !self.embeddings.is_empty() {
                let qv = p
                    .embed(&EmbeddingRequest {
                        model: Some(model.into()),
                        input: vec![q.into()],
                    })
                    .map_err(|e| e.to_string())?;
                if let Some(qv) = qv.first() {
                    let mut vh = self
                        .embeddings
                        .iter()
                        .map(|r| (r.path.clone(), cosine(qv, &r.vector)))
                        .collect::<Vec<_>>();
                    vh.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                    for (path, sim) in vh.into_iter().take(limit * 4) {
                        let e = m.entry(path.clone()).or_insert(VaultHit {
                            path,
                            score: 0.0,
                            lexical_score: None,
                            vector_score: None,
                            preview: String::new(),
                        });
                        e.vector_score = Some(sim);
                        e.score += ((sim + 1.0) * 0.5).clamp(0.0, 1.0) * 0.40;
                    }
                }
            }
        }
        let mut out = m.into_values().collect::<Vec<_>>();
        out.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        out.truncate(limit);
        Ok(out)
    }
    pub fn save(&self, path: &Path) -> Result<(), String> {
        if let Some(p) = path.parent() {
            fs::create_dir_all(p).map_err(|e| e.to_string())?;
        }
        fs::write(path, serde_json::to_vec(self).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }
    pub fn load(path: &Path) -> Result<Self, String> {
        serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())
    }
}
fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.is_empty() || a.len() != b.len() {
        return 0.0;
    }
    let (mut d, mut an, mut bn) = (0.0, 0.0, 0.0);
    for (x, y) in a.iter().zip(b) {
        d += x * y;
        an += x * x;
        bn += y * y;
    }
    let den = an.sqrt() * bn.sqrt();
    if den <= f32::EPSILON {
        0.0
    } else {
        d / den
    }
}
#[cfg(test)]
mod tests {
    use super::*;

    fn temp_library(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!("cortex-vault-{name}-{}", std::process::id()))
    }

    #[test]
    fn identity() {
        let v = [1.0, 2.0];
        assert!((cosine(&v, &v) - 1.0).abs() < 0.0001);
    }

    #[test]
    fn storage_metrics_track_quota_reclaimable_and_duplicates() {
        let root = temp_library("metrics");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let mut db = LibraryMemoryDatabase::open(&root).unwrap();
        db.storage_policy.max_bytes = Some(1_000);
        db.storage_policy.warning_percent = 50;
        db.storage_policy.critical_percent = 90;
        db.storage_policy
            .category_budgets
            .insert("assets".into(), 700);
        db.storage_policy
            .project_budgets
            .insert("project-a".into(), 900);
        let now = library_unix_ms();
        for (path, kind, bytes, hash) in [
            ("a.bin", LibraryItemKind::AssetCollection, 300, Some("same")),
            ("b.bin", LibraryItemKind::AssetCollection, 300, Some("same")),
            ("target.bin", LibraryItemKind::BuildOutput, 200, None),
        ] {
            db.catalog.insert(
                path.into(),
                LibraryCatalogRecord {
                    path: PathBuf::from(path),
                    kind,
                    project_id: Some("project-a".into()),
                    bytes,
                    modified_unix_ms: now,
                    is_directory: false,
                    content_hash: hash.map(str::to_string),
                    last_seen_unix_ms: now,
                },
            );
        }
        let snapshot = db.usage_snapshot();
        assert_eq!(snapshot.managed_bytes, 800);
        assert_eq!(snapshot.reclaimable_bytes, 200);
        assert_eq!(snapshot.duplicate_bytes, 300);
        assert_eq!(snapshot.quota_state, "warning");
        assert_eq!(
            snapshot.category_budget_used_percent.get("assets"),
            Some(&85)
        );
        assert_eq!(
            snapshot.project_budget_used_percent.get("project-a"),
            Some(&88)
        );
        assert!(db.ensure_allocation_within_policy(199).is_ok());
        assert!(db.ensure_allocation_within_policy(201).is_err());
        assert!(db
            .ensure_scoped_allocation_within_policy(Some("project-a"), Some("assets"), 50)
            .is_ok());
        assert!(db
            .ensure_scoped_allocation_within_policy(Some("project-a"), Some("assets"), 150)
            .is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn knowledge_graph_and_context_are_project_scoped() {
        let root = temp_library("knowledge");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let mut db = LibraryMemoryDatabase::open(&root).unwrap();
        db.upsert_knowledge_node(KnowledgeNode {
            id: "repair-1".into(),
            kind: "repair".into(),
            label: "Repair dossier".into(),
            project_id: Some("project-a".into()),
            state: "active".into(),
            provenance: "checkpoint".into(),
            source_paths: vec![PathBuf::from("logs/checkpoint.log")],
            updated_unix_ms: 0,
        });
        db.upsert_knowledge_node(KnowledgeNode {
            id: "checkpoint-1".into(),
            kind: "checkpoint".into(),
            label: "Checkpoint".into(),
            project_id: Some("project-a".into()),
            state: "failed".into(),
            provenance: "project_native".into(),
            source_paths: vec![],
            updated_unix_ms: 0,
        });
        db.relate(
            "repair-1",
            "responds_to",
            "checkpoint-1",
            "repair_coordinator",
        );
        db.memories.push(LibraryMemoryRecord {
            id: "memory-a".into(),
            scope: "project".into(),
            project_id: Some("project-a".into()),
            title: "wgpu repair".into(),
            content: "Exact dependency grounding is required before API-sensitive writes.".into(),
            source_paths: vec![],
            tags: vec!["wgpu".into()],
            created_unix_ms: 1,
            updated_unix_ms: 2,
        });
        let status = db.knowledge_status(Some("project-a"));
        assert_eq!(
            status.get("nodes").and_then(serde_json::Value::as_u64),
            Some(2)
        );
        assert_eq!(
            status.get("edges").and_then(serde_json::Value::as_u64),
            Some(1)
        );
        let context = db.compile_context(Some("project-a"), "wgpu grounding", 4);
        assert_eq!(context.len(), 1);
        assert!(context[0].contains("Exact dependency grounding"));
        let _ = fs::remove_dir_all(root);
    }
}

// -----------------------------------------------------------------------------
// Ember Vault production-library contracts (O2D H21-H24)
// -----------------------------------------------------------------------------

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum VaultProductionKind {
    Asset,
    LogicCard,
    Template,
    CodePattern,
    KnowledgePack,
    PcgRule,
    EntityArchetype,
    AnimationLibrary,
    AudioGraph,
    UiComponent,
    GeneratedDerivative,
    TestEvidence,
    Schema,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum VaultReadiness {
    Certified,
    AttributionRequired,
    ReviewRequired,
    ReferenceOnly,
    Blocked,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct VaultProvenance {
    pub title: String,
    pub author: Option<String>,
    pub source_url: Option<String>,
    pub repository_url: Option<String>,
    pub download_url: Option<String>,
    pub license_id: Option<String>,
    pub license_url: Option<String>,
    pub attribution_text: Option<String>,
    pub upstream_version: Option<String>,
    pub upstream_commit: Option<String>,
    pub checksum_sha256: Option<String>,
    pub fetched_unix_ms: Option<u128>,
    pub original_item_id: Option<String>,
    #[serde(default)]
    pub derivative_lineage: Vec<String>,
}

impl VaultProvenance {
    pub fn readiness(&self) -> VaultReadiness {
        if self.license_id.as_deref().unwrap_or("").trim().is_empty()
            || self.source_url.as_deref().unwrap_or("").trim().is_empty()
        {
            return VaultReadiness::ReviewRequired;
        }
        if self
            .attribution_text
            .as_deref()
            .is_some_and(|value| !value.trim().is_empty())
        {
            VaultReadiness::AttributionRequired
        } else {
            VaultReadiness::Certified
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VaultProductionItem {
    pub schema_version: u32,
    pub id: String,
    pub kind: VaultProductionKind,
    pub display_name: String,
    pub vault_path: PathBuf,
    pub provenance: VaultProvenance,
    pub readiness: VaultReadiness,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub project_ids: Vec<String>,
    #[serde(default)]
    pub dependencies: Vec<String>,
    #[serde(default)]
    pub metadata: serde_json::Value,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LogicPort {
    pub name: String,
    pub value_type: String,
    pub required: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LogicCardContract {
    pub schema_version: u32,
    pub id: String,
    pub version: String,
    pub title: String,
    pub runtime: String,
    #[serde(default)]
    pub inputs: Vec<LogicPort>,
    #[serde(default)]
    pub outputs: Vec<LogicPort>,
    #[serde(default)]
    pub dependencies: Vec<String>,
    #[serde(default)]
    pub validation_rules: Vec<String>,
    #[serde(default)]
    pub examples: Vec<String>,
    pub provenance: VaultProvenance,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum OrganizationMode {
    Scan,
    Plan,
    Apply,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PlannedMove {
    pub source: PathBuf,
    pub destination: PathBuf,
    pub source_sha256: Option<String>,
    pub reason: String,
    pub requires_approval: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct OrganizationPlan {
    pub schema_version: u32,
    pub mode: OrganizationMode,
    pub library_root: PathBuf,
    pub moves: Vec<PlannedMove>,
    pub destructive_operations: Vec<String>,
    pub rollback_manifest: Option<PathBuf>,
}

impl OrganizationPlan {
    pub fn can_apply(&self) -> bool {
        matches!(self.mode, OrganizationMode::Apply)
            && self.destructive_operations.is_empty()
            && self.moves.iter().all(|planned| planned.requires_approval)
    }
}
