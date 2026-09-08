//! Native bounded project discovery for Cortex.
//!
//! Discovery is intentionally read-only.  It uses `ignore` for Git-aware
//! traversal and `globset` for project-marker classification.  Existing
//! registered workspaces may be refreshed into `cortex_project_registry`, but
//! newly discovered candidates are never silently attached or promoted.

use cortex_project::{
    ProjectContract, ProjectId, ProjectRelationship, ProjectRelationshipKind,
};
use cortex_project_registry::{
    ProjectRegistryProjectionState, ProjectRegistryProjectionStore,
};
use cortex_registry::WorkspaceRegistry;
use globset::{Glob, GlobSet, GlobSetBuilder};
use ignore::WalkBuilder;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const DISCOVERY_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryConfig {
    pub max_depth: usize,
    pub max_directories: usize,
    pub max_candidates: usize,
    pub include_hidden: bool,
    pub follow_links: bool,
}

impl Default for DiscoveryConfig {
    fn default() -> Self {
        Self {
            max_depth: 20,
            max_directories: 20_000,
            max_candidates: 2_000,
            include_hidden: false,
            follow_links: false,
        }
    }
}

impl DiscoveryConfig {
    pub fn validate(&self) -> Result<(), String> {
        if self.max_depth == 0 {
            return Err("discovery max_depth must be at least 1".into());
        }
        if self.max_directories == 0 {
            return Err("discovery max_directories must be at least 1".into());
        }
        if self.max_candidates == 0 {
            return Err("discovery max_candidates must be at least 1".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryMarkerKind {
    ProjectControl,
    Cargo,
    Node,
    Python,
    Cmake,
    VisualStudioSolution,
    VisualStudioProject,
    DotNetSolution,
    Go,
    JavaGradle,
    JavaMaven,
    Godot,
    Unreal,
    GitRepository,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryMarker {
    pub kind: DiscoveryMarkerKind,
    pub path: PathBuf,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryCandidate {
    pub root: PathBuf,
    pub name: String,
    pub kind: String,
    pub confidence: u8,
    pub strong_boundary: bool,
    #[serde(default)]
    pub markers: Vec<DiscoveryMarker>,
    #[serde(default)]
    pub languages: BTreeSet<String>,
    #[serde(default)]
    pub project_id: Option<ProjectId>,
    #[serde(default)]
    pub family: Option<String>,
    #[serde(default)]
    pub registered_workspace_id: Option<String>,
    pub signature: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryDuplicateGroup {
    pub signature: String,
    pub roots: Vec<PathBuf>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryFamilyCandidate {
    pub normalized_family: String,
    pub roots: Vec<PathBuf>,
    pub confidence: u8,
    pub reason: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryStats {
    pub scanned_directories: u64,
    pub walk_errors: u64,
    pub suppressed_nested_candidates: u64,
    pub candidate_limit_hits: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DiscoveryReport {
    pub schema_version: u32,
    pub scan_roots: Vec<PathBuf>,
    pub config: DiscoveryConfig,
    pub stats: DiscoveryStats,
    pub candidates: Vec<DiscoveryCandidate>,
    pub duplicate_groups: Vec<DiscoveryDuplicateGroup>,
    pub family_candidates: Vec<DiscoveryFamilyCandidate>,
    pub relationship_proposals: Vec<ProjectRelationship>,
    pub cancelled: bool,
    pub truncated: bool,
    pub project_registry_refreshed: bool,
    pub registered_projection_count: usize,
    pub generated_unix_ms: u128,
}

pub struct DiscoveryEngine {
    config: DiscoveryConfig,
    marker_set: GlobSet,
}

impl DiscoveryEngine {
    pub fn new(config: DiscoveryConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(Self {
            config,
            marker_set: build_marker_set()?,
        })
    }

    pub fn config(&self) -> &DiscoveryConfig {
        &self.config
    }

    pub fn scan_roots<I, P>(&self, roots: I) -> Result<DiscoveryReport, String>
    where
        I: IntoIterator<Item = P>,
        P: AsRef<Path>,
    {
        self.scan_roots_with_cancel(roots, || false)
    }

    pub fn scan_roots_with_cancel<I, P, F>(
        &self,
        roots: I,
        mut should_cancel: F,
    ) -> Result<DiscoveryReport, String>
    where
        I: IntoIterator<Item = P>,
        P: AsRef<Path>,
        F: FnMut() -> bool,
    {
        let mut scan_roots = Vec::new();
        for root in roots {
            let canonical = fs::canonicalize(root.as_ref()).map_err(|error| {
                format!(
                    "failed to resolve discovery root {}: {error}",
                    root.as_ref().display()
                )
            })?;
            if !canonical.is_dir() {
                return Err(format!(
                    "discovery root is not a directory: {}",
                    canonical.display()
                ));
            }
            if !scan_roots.contains(&canonical) {
                scan_roots.push(canonical);
            }
        }
        if scan_roots.is_empty() {
            return Err("at least one discovery root is required".into());
        }

        let mut stats = DiscoveryStats::default();
        let mut raw_candidates = Vec::new();
        let mut cancelled = false;
        let mut truncated = false;

        for root in &scan_roots {
            if should_cancel() {
                cancelled = true;
                break;
            }

            let mut builder = WalkBuilder::new(root);
            builder
                .hidden(!self.config.include_hidden)
                .follow_links(self.config.follow_links)
                .git_ignore(true)
                .git_global(true)
                .git_exclude(true)
                .parents(true)
                .max_depth(Some(self.config.max_depth));

            for entry in builder.build() {
                if should_cancel() {
                    cancelled = true;
                    break;
                }
                if stats.scanned_directories as usize >= self.config.max_directories {
                    truncated = true;
                    break;
                }
                if raw_candidates.len() >= self.config.max_candidates {
                    stats.candidate_limit_hits = stats.candidate_limit_hits.saturating_add(1);
                    truncated = true;
                    break;
                }

                let entry = match entry {
                    Ok(entry) => entry,
                    Err(_) => {
                        stats.walk_errors = stats.walk_errors.saturating_add(1);
                        continue;
                    }
                };

                let is_dir = entry.file_type().is_some_and(|kind| kind.is_dir());
                if !is_dir {
                    continue;
                }

                stats.scanned_directories = stats.scanned_directories.saturating_add(1);

                if let Some(candidate) = self.classify_directory(entry.path())? {
                    raw_candidates.push(candidate);
                }
            }

            if cancelled || truncated {
                break;
            }
        }

        let (mut candidates, suppressed) = suppress_nested_weak_candidates(raw_candidates);
        stats.suppressed_nested_candidates = suppressed as u64;
        candidates.sort_by(|left, right| {
            right
                .confidence
                .cmp(&left.confidence)
                .then_with(|| left.root.cmp(&right.root))
        });

        let duplicate_groups = duplicate_groups(&candidates);
        let family_candidates = family_candidates(&candidates);
        let relationship_proposals =
            relationship_proposals(&candidates, &duplicate_groups, &family_candidates);

        Ok(DiscoveryReport {
            schema_version: DISCOVERY_SCHEMA_VERSION,
            scan_roots,
            config: self.config.clone(),
            stats,
            candidates,
            duplicate_groups,
            family_candidates,
            relationship_proposals,
            cancelled,
            truncated,
            project_registry_refreshed: false,
            registered_projection_count: 0,
            generated_unix_ms: unix_millis(),
        })
    }

    pub fn scan_and_refresh_registered<I, P>(
        &self,
        roots: I,
        registry: &WorkspaceRegistry,
        projections: &ProjectRegistryProjectionStore,
    ) -> Result<(DiscoveryReport, ProjectRegistryProjectionState), String>
    where
        I: IntoIterator<Item = P>,
        P: AsRef<Path>,
    {
        let mut report = self.scan_roots(roots)?;
        let registry_state = registry.state()?;

        for candidate in &mut report.candidates {
            candidate.registered_workspace_id = registry_state
                .workspaces
                .iter()
                .find(|workspace| workspace.root == candidate.root)
                .map(|workspace| workspace.id.clone());
        }

        let projection_state = projections.refresh_all(registry)?;
        report.project_registry_refreshed = true;
        report.registered_projection_count = projection_state.projects.len();
        Ok((report, projection_state))
    }

    fn classify_directory(&self, root: &Path) -> Result<Option<DiscoveryCandidate>, String> {
        let mut markers = Vec::new();

        let entries = match fs::read_dir(root) {
            Ok(entries) => entries,
            Err(_) => return Ok(None),
        };

        for entry in entries.filter_map(Result::ok) {
            let name = entry.file_name();
            let name_path = Path::new(&name);
            if self.marker_set.is_match(name_path) {
                if let Some(kind) = marker_kind(name.to_string_lossy().as_ref()) {
                    markers.push(DiscoveryMarker {
                        kind,
                        path: entry.path(),
                    });
                }
            }
        }

        if root.join(".git").exists() {
            markers.push(DiscoveryMarker {
                kind: DiscoveryMarkerKind::GitRepository,
                path: root.join(".git"),
            });
        }

        markers.sort_by(|left, right| {
            left.kind
                .cmp(&right.kind)
                .then_with(|| left.path.cmp(&right.path))
        });
        markers.dedup();

        if markers.is_empty() {
            return Ok(None);
        }

        let contract = ProjectContract::load_optional(root)?;
        let project_id = contract.as_ref().map(|value| value.project.id.clone());
        let explicit_family = contract
            .as_ref()
            .and_then(|value| value.project.family.clone())
            .filter(|value| !value.trim().is_empty());

        let name = contract
            .as_ref()
            .map(|value| value.project.name.clone())
            .filter(|value| !value.trim().is_empty())
            .or_else(|| {
                root.file_name()
                    .and_then(|value| value.to_str())
                    .map(ToOwned::to_owned)
            })
            .unwrap_or_else(|| root.display().to_string());

        let has = |kind: DiscoveryMarkerKind| markers.iter().any(|marker| marker.kind == kind);

        let (kind, confidence, strong_boundary) = if let Some(contract) = contract.as_ref() {
            (
                contract.project.kind.0.clone(),
                100,
                true,
            )
        } else if has(DiscoveryMarkerKind::Cargo) {
            ("rust".into(), 85, false)
        } else if has(DiscoveryMarkerKind::VisualStudioSolution)
            || has(DiscoveryMarkerKind::DotNetSolution)
            || has(DiscoveryMarkerKind::VisualStudioProject)
        {
            ("dotnet".into(), 80, false)
        } else if has(DiscoveryMarkerKind::Node) {
            ("node".into(), 78, false)
        } else if has(DiscoveryMarkerKind::Python) {
            ("python".into(), 78, false)
        } else if has(DiscoveryMarkerKind::Cmake) {
            ("cmake".into(), 76, false)
        } else if has(DiscoveryMarkerKind::Go) {
            ("go".into(), 76, false)
        } else if has(DiscoveryMarkerKind::JavaGradle)
            || has(DiscoveryMarkerKind::JavaMaven)
        {
            ("java".into(), 76, false)
        } else if has(DiscoveryMarkerKind::Godot) {
            ("godot".into(), 82, false)
        } else if has(DiscoveryMarkerKind::Unreal) {
            ("unreal".into(), 82, false)
        } else {
            ("git".into(), 60, false)
        };

        let mut languages = BTreeSet::new();
        for marker in &markers {
            match marker.kind {
                DiscoveryMarkerKind::Cargo => {
                    languages.insert("rust".into());
                }
                DiscoveryMarkerKind::Node => {
                    languages.insert("javascript/typescript".into());
                }
                DiscoveryMarkerKind::Python => {
                    languages.insert("python".into());
                }
                DiscoveryMarkerKind::Cmake => {
                    languages.insert("c/c++".into());
                }
                DiscoveryMarkerKind::VisualStudioSolution
                | DiscoveryMarkerKind::VisualStudioProject
                | DiscoveryMarkerKind::DotNetSolution => {
                    languages.insert("dotnet".into());
                }
                DiscoveryMarkerKind::Go => {
                    languages.insert("go".into());
                }
                DiscoveryMarkerKind::JavaGradle | DiscoveryMarkerKind::JavaMaven => {
                    languages.insert("java".into());
                }
                _ => {}
            }
        }

        let signature = candidate_signature(root, &markers);
        let family = explicit_family.or_else(|| {
            let normalized = normalize_family_name(&name);
            (!normalized.is_empty()).then_some(normalized)
        });

        Ok(Some(DiscoveryCandidate {
            root: root.to_path_buf(),
            name,
            kind,
            confidence,
            strong_boundary,
            markers,
            languages,
            project_id,
            family,
            registered_workspace_id: None,
            signature,
        }))
    }
}

fn build_marker_set() -> Result<GlobSet, String> {
    let mut builder = GlobSetBuilder::new();
    for pattern in [
        "project.control.json",
        "Cargo.toml",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "CMakeLists.txt",
        "*.sln",
        "*.slnx",
        "*.csproj",
        "*.fsproj",
        "go.mod",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "pom.xml",
        "project.godot",
        "*.uproject",
    ] {
        builder.add(
            Glob::new(pattern)
                .map_err(|error| format!("invalid discovery marker glob {pattern}: {error}"))?,
        );
    }
    builder
        .build()
        .map_err(|error| format!("failed to build discovery marker set: {error}"))
}

fn marker_kind(name: &str) -> Option<DiscoveryMarkerKind> {
    let lower = name.to_ascii_lowercase();
    match lower.as_str() {
        "project.control.json" => Some(DiscoveryMarkerKind::ProjectControl),
        "cargo.toml" => Some(DiscoveryMarkerKind::Cargo),
        "package.json" => Some(DiscoveryMarkerKind::Node),
        "pyproject.toml" | "setup.py" | "requirements.txt" => {
            Some(DiscoveryMarkerKind::Python)
        }
        "cmakelists.txt" => Some(DiscoveryMarkerKind::Cmake),
        "go.mod" => Some(DiscoveryMarkerKind::Go),
        "build.gradle" | "build.gradle.kts" | "settings.gradle" | "settings.gradle.kts" => {
            Some(DiscoveryMarkerKind::JavaGradle)
        }
        "pom.xml" => Some(DiscoveryMarkerKind::JavaMaven),
        "project.godot" => Some(DiscoveryMarkerKind::Godot),
        _ if lower.ends_with(".sln") => Some(DiscoveryMarkerKind::VisualStudioSolution),
        _ if lower.ends_with(".slnx") => Some(DiscoveryMarkerKind::DotNetSolution),
        _ if lower.ends_with(".csproj") || lower.ends_with(".fsproj") => {
            Some(DiscoveryMarkerKind::VisualStudioProject)
        }
        _ if lower.ends_with(".uproject") => Some(DiscoveryMarkerKind::Unreal),
        _ => None,
    }
}

fn suppress_nested_weak_candidates(
    mut candidates: Vec<DiscoveryCandidate>,
) -> (Vec<DiscoveryCandidate>, usize) {
    candidates.sort_by(|left, right| {
        path_depth(&left.root)
            .cmp(&path_depth(&right.root))
            .then_with(|| right.confidence.cmp(&left.confidence))
            .then_with(|| left.root.cmp(&right.root))
    });

    let mut kept = Vec::<DiscoveryCandidate>::new();
    let mut suppressed = 0usize;

    for candidate in candidates {
        let governed_ancestor = kept.iter().any(|parent| {
            parent.strong_boundary
                && candidate.root != parent.root
                && candidate.root.starts_with(&parent.root)
        });

        if governed_ancestor && !candidate.strong_boundary {
            suppressed = suppressed.saturating_add(1);
            continue;
        }

        kept.push(candidate);
    }

    (kept, suppressed)
}

fn duplicate_groups(candidates: &[DiscoveryCandidate]) -> Vec<DiscoveryDuplicateGroup> {
    let mut grouped = BTreeMap::<String, Vec<PathBuf>>::new();
    for candidate in candidates {
        grouped
            .entry(candidate.signature.clone())
            .or_default()
            .push(candidate.root.clone());
    }

    grouped
        .into_iter()
        .filter_map(|(signature, mut roots)| {
            if roots.len() < 2 {
                return None;
            }
            roots.sort();
            Some(DiscoveryDuplicateGroup { signature, roots })
        })
        .collect()
}

fn family_candidates(candidates: &[DiscoveryCandidate]) -> Vec<DiscoveryFamilyCandidate> {
    let mut grouped = BTreeMap::<String, Vec<&DiscoveryCandidate>>::new();
    for candidate in candidates {
        let family = candidate
            .family
            .clone()
            .unwrap_or_else(|| normalize_family_name(&candidate.name));
        if !family.is_empty() {
            grouped.entry(family).or_default().push(candidate);
        }
    }

    grouped
        .into_iter()
        .filter_map(|(normalized_family, candidates)| {
            if candidates.len() < 2 {
                return None;
            }

            let mut roots = candidates
                .iter()
                .map(|candidate| candidate.root.clone())
                .collect::<Vec<_>>();
            roots.sort();

            let identical_signature = candidates
                .iter()
                .map(|candidate| candidate.signature.as_str())
                .collect::<BTreeSet<_>>()
                .len()
                == 1;

            Some(DiscoveryFamilyCandidate {
                normalized_family,
                roots,
                confidence: if identical_signature { 95 } else { 75 },
                reason: if identical_signature {
                    "normalized family name and project-marker signature match".into()
                } else {
                    "normalized family name matches".into()
                },
            })
        })
        .collect()
}

fn relationship_proposals(
    candidates: &[DiscoveryCandidate],
    duplicates: &[DiscoveryDuplicateGroup],
    families: &[DiscoveryFamilyCandidate],
) -> Vec<ProjectRelationship> {
    let by_root = candidates
        .iter()
        .map(|candidate| (candidate.root.clone(), candidate))
        .collect::<BTreeMap<_, _>>();

    let duplicate_roots = duplicates
        .iter()
        .flat_map(|group| {
            let mut pairs = Vec::new();
            for (index, left) in group.roots.iter().enumerate() {
                for right in group.roots.iter().skip(index + 1) {
                    pairs.push((left.clone(), right.clone()));
                }
            }
            pairs
        })
        .collect::<BTreeSet<_>>();

    let mut proposals = Vec::new();

    for family in families {
        for (index, left_root) in family.roots.iter().enumerate() {
            for right_root in family.roots.iter().skip(index + 1) {
                let Some(left) = by_root.get(left_root) else {
                    continue;
                };
                let Some(right) = by_root.get(right_root) else {
                    continue;
                };
                let (Some(from), Some(to)) = (&left.project_id, &right.project_id) else {
                    continue;
                };
                if from == to {
                    continue;
                }

                let is_duplicate = duplicate_roots
                    .contains(&(left_root.clone(), right_root.clone()))
                    || duplicate_roots.contains(&(right_root.clone(), left_root.clone()));

                proposals.push(ProjectRelationship {
                    from: from.clone(),
                    to: to.clone(),
                    kind: if is_duplicate {
                        ProjectRelationshipKind::RelatedCopy
                    } else {
                        ProjectRelationshipKind::DerivedFrom
                    },
                    confidence: if is_duplicate {
                        95
                    } else {
                        family.confidence
                    },
                    reason: family.reason.clone(),
                });
            }
        }
    }

    proposals.sort_by(|left, right| {
        left.from
            .cmp(&right.from)
            .then_with(|| left.to.cmp(&right.to))
            .then_with(|| left.kind.cmp(&right.kind))
            .then_with(|| left.reason.cmp(&right.reason))
    });
    proposals.dedup();
    proposals
}

fn normalize_family_name(value: &str) -> String {
    let mut normalized = value
        .trim()
        .to_ascii_lowercase()
        .replace([' ', '_'], "-");

    for suffix in [
        "-main",
        "-master",
        "-copy",
        "-backup",
        "-old",
        "-new",
        "-source",
        "-repo",
    ] {
        if normalized.ends_with(suffix) {
            normalized.truncate(normalized.len().saturating_sub(suffix.len()));
        }
    }

    while normalized.contains("--") {
        normalized = normalized.replace("--", "-");
    }

    let bytes = normalized.as_bytes();
    if let Some(index) = normalized.rfind("-v") {
        let tail = &bytes[index + 2..];
        if !tail.is_empty() && tail.iter().all(u8::is_ascii_digit) {
            normalized.truncate(index);
        }
    }

    normalized.trim_matches('-').to_string()
}

fn candidate_signature(root: &Path, markers: &[DiscoveryMarker]) -> String {
    let mut hash = 0xcbf29ce484222325u64;

    for marker in markers {
        let relative = marker.path.strip_prefix(root).unwrap_or(&marker.path);
        fnv_update(&mut hash, relative.to_string_lossy().as_bytes());

        if marker.path.is_file() {
            if let Ok(bytes) = fs::read(&marker.path) {
                let limit = bytes.len().min(1024 * 1024);
                fnv_update(&mut hash, &bytes[..limit]);
            }
        }
    }

    format!("{hash:016x}")
}

fn fnv_update(hash: &mut u64, bytes: &[u8]) {
    for byte in bytes {
        *hash ^= u64::from(*byte);
        *hash = hash.wrapping_mul(0x100000001b3);
    }
}

fn path_depth(path: &Path) -> usize {
    path.components().count()
}

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "cortex-discovery-{label}-{}-{}",
            std::process::id(),
            unix_millis()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn write(path: impl AsRef<Path>, text: &str) {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, text).unwrap();
    }

    #[test]
    fn governed_root_suppresses_nested_weak_cargo_projects() {
        let root = temp_root("boundary");
        write(
            root.join("project.control.json"),
            r#"{
                "schema_version":1,
                "project":{
                    "id":"cortex-test",
                    "name":"Cortex Test",
                    "kind":"rust-workspace"
                }
            }"#,
        );
        write(root.join("Cargo.toml"), "[workspace]\n");
        write(
            root.join("crates/child/Cargo.toml"),
            "[package]\nname=\"child\"\nversion=\"0.1.0\"\n",
        );

        let engine = DiscoveryEngine::new(DiscoveryConfig::default()).unwrap();
        let report = engine.scan_roots([&root]).unwrap();

        assert_eq!(report.candidates.len(), 1);
        assert_eq!(
            report.candidates[0].project_id.as_ref().unwrap().as_str(),
            "cortex-test"
        );
        assert!(report.stats.suppressed_nested_candidates >= 1);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn identical_marker_material_forms_duplicate_group() {
        let root = temp_root("duplicates");
        for name in ["alpha", "alpha-copy"] {
            write(
                root.join(name).join("Cargo.toml"),
                "[package]\nname=\"same\"\nversion=\"0.1.0\"\n",
            );
        }

        let engine = DiscoveryEngine::new(DiscoveryConfig::default()).unwrap();
        let report = engine.scan_roots([&root]).unwrap();

        assert_eq!(report.duplicate_groups.len(), 1);
        assert_eq!(report.duplicate_groups[0].roots.len(), 2);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn family_normalization_removes_copy_and_version_suffixes() {
        assert_eq!(normalize_family_name("Havenwild-main"), "havenwild");
        assert_eq!(normalize_family_name("Havenwild Copy"), "havenwild");
        assert_eq!(normalize_family_name("Havenwild-v12"), "havenwild");
    }

    #[test]
    fn cancellation_reports_partial_truth() {
        let root = temp_root("cancel");
        write(root.join("Cargo.toml"), "[workspace]\n");
        let engine = DiscoveryEngine::new(DiscoveryConfig::default()).unwrap();
        let mut calls = 0usize;
        let report = engine
            .scan_roots_with_cancel([&root], || {
                calls = calls.saturating_add(1);
                calls > 1
            })
            .unwrap();
        assert!(report.cancelled);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn depth_budget_is_part_of_serialized_config() {
        let config = DiscoveryConfig {
            max_depth: 20,
            max_directories: 500,
            max_candidates: 100,
            include_hidden: false,
            follow_links: false,
        };
        let encoded = serde_json::to_string(&config).unwrap();
        let decoded: DiscoveryConfig = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded.max_depth, 20);
        assert_eq!(decoded.max_directories, 500);
    }
}
