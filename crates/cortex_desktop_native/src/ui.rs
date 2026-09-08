//! Cortex-owned retained UI primitives.
//!
//! This module is deliberately platform-neutral. Win32 remains the native window/input
//! backend while Cortex owns widget identity, theme tokens, logical sizing, layout,
//! clipping intent, state, and responsive composition.

use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct WidgetId(String);

impl WidgetId {
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        let trimmed = value.trim();
        if trimmed.is_empty() {
            return Err("Cortex widget id cannot be empty".into());
        }
        if !trimmed.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-' | '/')
        }) {
            return Err(format!("invalid Cortex widget id: {trimmed}"));
        }
        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct UiScale {
    factor: f32,
}

impl UiScale {
    pub const ONE: Self = Self { factor: 1.0 };

    pub fn new(factor: f32) -> Self {
        Self {
            factor: factor.clamp(0.75, 2.0),
        }
    }

    pub fn factor(self) -> f32 {
        self.factor
    }

    pub fn px(self, logical: f32) -> i32 {
        (logical * self.factor).round() as i32
    }
}

impl Default for UiScale {
    fn default() -> Self {
        Self::ONE
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LayoutSize {
    pub width: f32,
    pub height: f32,
}

impl LayoutSize {
    pub const fn new(width: f32, height: f32) -> Self {
        Self { width, height }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LayoutRect {
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
}

impl LayoutRect {
    pub const fn new(x: f32, y: f32, width: f32, height: f32) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }

    pub fn right(self) -> f32 {
        self.x + self.width
    }

    pub fn bottom(self) -> f32 {
        self.y + self.height
    }

    pub fn contains(self, x: f32, y: f32) -> bool {
        x >= self.x && x <= self.right() && y >= self.y && y <= self.bottom()
    }

    pub fn inset(self, insets: Insets) -> Self {
        Self {
            x: self.x + insets.left,
            y: self.y + insets.top,
            width: (self.width - insets.left - insets.right).max(0.0),
            height: (self.height - insets.top - insets.bottom).max(0.0),
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Insets {
    pub left: f32,
    pub top: f32,
    pub right: f32,
    pub bottom: f32,
}

impl Insets {
    pub const ZERO: Self = Self {
        left: 0.0,
        top: 0.0,
        right: 0.0,
        bottom: 0.0,
    };

    pub const fn all(value: f32) -> Self {
        Self {
            left: value,
            top: value,
            right: value,
            bottom: value,
        }
    }

    pub const fn symmetric(horizontal: f32, vertical: f32) -> Self {
        Self {
            left: horizontal,
            top: vertical,
            right: horizontal,
            bottom: vertical,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Axis {
    Horizontal,
    Vertical,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum UiDensity {
    Compact,
    #[default]
    Comfortable,
    Spacious,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WidgetKind {
    Root,
    Row,
    Column,
    Stack,
    SplitView,
    ScrollView,
    Drawer,
    Sidebar,
    Panel,
    TabBar,
    TreeView,
    Breadcrumb,
    Button,
    IconButton,
    TextBox,
    SearchBox,
    Label,
    Card,
    Badge,
    Status,
    ChatMessage,
    CodeCard,
    FileCard,
    ProjectCard,
    RoadmapCard,
    JobCard,
    ArtifactCard,
    ApprovalCard,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WidgetState {
    pub visible: bool,
    pub enabled: bool,
    pub hovered: bool,
    pub focused: bool,
    pub pressed: bool,
    pub selected: bool,
    pub scroll_offset: f32,
}

impl WidgetState {
    pub fn interactive_default() -> Self {
        Self {
            visible: true,
            enabled: true,
            ..Self::default()
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LayoutConstraints {
    pub min_width: f32,
    pub preferred_width: f32,
    pub max_width: f32,
    pub min_height: f32,
    pub preferred_height: f32,
    pub max_height: f32,
    pub flex: f32,
}

impl LayoutConstraints {
    pub const fn flexible() -> Self {
        Self {
            min_width: 0.0,
            preferred_width: 0.0,
            max_width: f32::MAX,
            min_height: 0.0,
            preferred_height: 0.0,
            max_height: f32::MAX,
            flex: 1.0,
        }
    }

    pub const fn fixed(width: f32, height: f32) -> Self {
        Self {
            min_width: width,
            preferred_width: width,
            max_width: width,
            min_height: height,
            preferred_height: height,
            max_height: height,
            flex: 0.0,
        }
    }

    fn axis_min(self, axis: Axis) -> f32 {
        match axis {
            Axis::Horizontal => self.min_width,
            Axis::Vertical => self.min_height,
        }
    }

    fn axis_preferred(self, axis: Axis) -> f32 {
        match axis {
            Axis::Horizontal => self.preferred_width,
            Axis::Vertical => self.preferred_height,
        }
    }

    fn axis_max(self, axis: Axis) -> f32 {
        match axis {
            Axis::Horizontal => self.max_width,
            Axis::Vertical => self.max_height,
        }
    }
}

impl Default for LayoutConstraints {
    fn default() -> Self {
        Self::flexible()
    }
}

#[derive(Clone, Debug)]
pub struct LayoutNode {
    pub id: WidgetId,
    pub kind: WidgetKind,
    pub axis: Axis,
    pub constraints: LayoutConstraints,
    pub padding: Insets,
    pub gap: f32,
    pub state: WidgetState,
    pub bounds: LayoutRect,
    pub clip: bool,
    pub children: Vec<LayoutNode>,
}

impl LayoutNode {
    pub fn new(id: impl Into<String>, kind: WidgetKind) -> Result<Self, String> {
        Ok(Self {
            id: WidgetId::new(id)?,
            kind,
            axis: Axis::Vertical,
            constraints: LayoutConstraints::default(),
            padding: Insets::ZERO,
            gap: 0.0,
            state: WidgetState::interactive_default(),
            bounds: LayoutRect::default(),
            clip: false,
            children: Vec::new(),
        })
    }

    pub fn row(id: impl Into<String>) -> Result<Self, String> {
        let mut node = Self::new(id, WidgetKind::Row)?;
        node.axis = Axis::Horizontal;
        Ok(node)
    }

    pub fn column(id: impl Into<String>) -> Result<Self, String> {
        Self::new(id, WidgetKind::Column)
    }

    pub fn with_constraints(mut self, constraints: LayoutConstraints) -> Self {
        self.constraints = constraints;
        self
    }

    pub fn with_padding(mut self, padding: Insets) -> Self {
        self.padding = padding;
        self
    }

    pub fn with_gap(mut self, gap: f32) -> Self {
        self.gap = gap.max(0.0);
        self
    }

    pub fn with_clip(mut self, clip: bool) -> Self {
        self.clip = clip;
        self
    }

    pub fn push(&mut self, child: LayoutNode) {
        self.children.push(child);
    }

    pub fn find(&self, id: &str) -> Option<&LayoutNode> {
        if self.id.as_str() == id {
            return Some(self);
        }
        self.children.iter().find_map(|child| child.find(id))
    }

    pub fn find_mut(&mut self, id: &str) -> Option<&mut LayoutNode> {
        if self.id.as_str() == id {
            return Some(self);
        }
        self.children
            .iter_mut()
            .find_map(|child| child.find_mut(id))
    }

    pub fn layout(&mut self, bounds: LayoutRect) {
        self.bounds = bounds;
        if !self.state.visible || self.children.is_empty() {
            return;
        }

        let inner = bounds.inset(self.padding);
        let visible_indices = self
            .children
            .iter()
            .enumerate()
            .filter_map(|(index, child)| child.state.visible.then_some(index))
            .collect::<Vec<_>>();
        if visible_indices.is_empty() {
            return;
        }

        let total_gap = self.gap * visible_indices.len().saturating_sub(1) as f32;
        let available_main = match self.axis {
            Axis::Horizontal => inner.width,
            Axis::Vertical => inner.height,
        }
        .max(0.0)
            - total_gap;

        let mut allocated = vec![0.0f32; self.children.len()];
        let mut fixed = 0.0f32;
        let mut flex_total = 0.0f32;

        for index in &visible_indices {
            let child = &self.children[*index];
            let preferred = child.constraints.axis_preferred(self.axis).clamp(
                child.constraints.axis_min(self.axis),
                child.constraints.axis_max(self.axis),
            );
            allocated[*index] = preferred;
            fixed += preferred;
            flex_total += child.constraints.flex.max(0.0);
        }

        let remaining = (available_main - fixed).max(0.0);
        if remaining > 0.0 && flex_total > 0.0 {
            for index in &visible_indices {
                let child = &self.children[*index];
                let share = remaining * (child.constraints.flex.max(0.0) / flex_total);
                let current = allocated[*index];
                allocated[*index] = (current + share).min(child.constraints.axis_max(self.axis));
            }
        }

        // If preferred sizes overflow, shrink toward minimum sizes proportionally.
        let total_allocated = visible_indices
            .iter()
            .map(|index| allocated[*index])
            .sum::<f32>();
        let overflow = (total_allocated - available_main).max(0.0);
        if overflow > 0.0 {
            let shrink_capacity = visible_indices
                .iter()
                .map(|index| {
                    let child = &self.children[*index];
                    (allocated[*index] - child.constraints.axis_min(self.axis)).max(0.0)
                })
                .sum::<f32>();
            if shrink_capacity > 0.0 {
                for index in &visible_indices {
                    let child = &self.children[*index];
                    let capacity =
                        (allocated[*index] - child.constraints.axis_min(self.axis)).max(0.0);
                    allocated[*index] -= overflow * (capacity / shrink_capacity);
                }
            }
        }

        let mut cursor = match self.axis {
            Axis::Horizontal => inner.x,
            Axis::Vertical => inner.y,
        };

        for index in visible_indices {
            let child_main = allocated[index].max(0.0);
            let child_bounds = match self.axis {
                Axis::Horizontal => {
                    LayoutRect::new(cursor, inner.y, child_main, inner.height.max(0.0))
                }
                Axis::Vertical => {
                    LayoutRect::new(inner.x, cursor, inner.width.max(0.0), child_main)
                }
            };
            self.children[index].layout(child_bounds);
            cursor += child_main + self.gap;
        }
    }

    pub fn flatten_bounds(&self) -> BTreeMap<String, LayoutRect> {
        let mut output = BTreeMap::new();
        self.flatten_into(&mut output);
        output
    }

    fn flatten_into(&self, output: &mut BTreeMap<String, LayoutRect>) {
        output.insert(self.id.as_str().to_string(), self.bounds);
        for child in &self.children {
            child.flatten_into(output);
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct VirtualListItem {
    pub id: WidgetId,
    pub extent: f32,
}

impl VirtualListItem {
    pub fn new(id: impl Into<String>, extent: f32) -> Result<Self, String> {
        Ok(Self {
            id: WidgetId::new(id)?,
            extent: extent.max(1.0),
        })
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VirtualListWindow {
    pub first: usize,
    pub last_exclusive: usize,
    pub leading_extent: f32,
    pub visible_extent: f32,
    pub total_extent: f32,
}

impl VirtualListWindow {
    pub fn is_empty(&self) -> bool {
        self.first >= self.last_exclusive
    }

    pub fn len(&self) -> usize {
        self.last_exclusive.saturating_sub(self.first)
    }
}

pub struct VirtualList;

impl VirtualList {
    pub fn window(
        items: &[VirtualListItem],
        scroll_offset: f32,
        viewport_extent: f32,
        overscan: f32,
    ) -> VirtualListWindow {
        if items.is_empty() {
            return VirtualListWindow::default();
        }

        let total_extent = items.iter().map(|item| item.extent).sum::<f32>();
        let viewport_extent = viewport_extent.max(1.0);
        let max_scroll = (total_extent - viewport_extent).max(0.0);
        let scroll_offset = scroll_offset.clamp(0.0, max_scroll);
        let start = (scroll_offset - overscan.max(0.0)).max(0.0);
        let end = (scroll_offset + viewport_extent + overscan.max(0.0)).min(total_extent);

        let mut cursor = 0.0f32;
        let mut first = 0usize;
        let mut last_exclusive = items.len();
        let mut found_first = false;

        for (index, item) in items.iter().enumerate() {
            let next = cursor + item.extent;
            if !found_first && next >= start {
                first = index;
                found_first = true;
            }
            if cursor <= end {
                last_exclusive = index + 1;
            } else {
                break;
            }
            cursor = next;
        }

        let leading_extent = items
            .iter()
            .take(first)
            .map(|item| item.extent)
            .sum::<f32>();
        let visible_extent = items[first..last_exclusive]
            .iter()
            .map(|item| item.extent)
            .sum::<f32>();

        VirtualListWindow {
            first,
            last_exclusive,
            leading_extent,
            visible_extent,
            total_extent,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ScrollAnchor {
    pub item_id: WidgetId,
    pub offset_within_item: f32,
}

impl ScrollAnchor {
    pub fn capture(items: &[VirtualListItem], scroll_offset: f32) -> Option<Self> {
        let mut cursor = 0.0f32;
        let scroll_offset = scroll_offset.max(0.0);
        for item in items {
            let next = cursor + item.extent;
            if scroll_offset <= next {
                return Some(Self {
                    item_id: item.id.clone(),
                    offset_within_item: (scroll_offset - cursor).max(0.0),
                });
            }
            cursor = next;
        }
        items.last().map(|item| Self {
            item_id: item.id.clone(),
            offset_within_item: item.extent,
        })
    }

    pub fn restore(&self, items: &[VirtualListItem]) -> Option<f32> {
        let mut cursor = 0.0f32;
        for item in items {
            if item.id == self.item_id {
                return Some(cursor + self.offset_within_item.min(item.extent));
            }
            cursor += item.extent;
        }
        None
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WorkbenchDocument {
    pub path: String,
    pub language: String,
    pub content: String,
    pub dirty: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkbenchState {
    pub documents: Vec<WorkbenchDocument>,
    pub active: Option<usize>,
}

impl WorkbenchState {
    pub fn open(&mut self, document: WorkbenchDocument) -> usize {
        if let Some(index) = self
            .documents
            .iter()
            .position(|item| item.path == document.path)
        {
            self.documents[index] = document;
            self.active = Some(index);
            return index;
        }
        self.documents.push(document);
        let index = self.documents.len() - 1;
        self.active = Some(index);
        index
    }

    pub fn select(&mut self, index: usize) -> bool {
        if index < self.documents.len() {
            self.active = Some(index);
            true
        } else {
            false
        }
    }

    pub fn active_document(&self) -> Option<&WorkbenchDocument> {
        self.active.and_then(|index| self.documents.get(index))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DiffRowKind {
    Context,
    Added,
    Removed,
    Modified,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiffRow {
    pub before_line: Option<u32>,
    pub after_line: Option<u32>,
    pub before: String,
    pub after: String,
    pub kind: DiffRowKind,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DiffView {
    pub path: String,
    pub rows: Vec<DiffRow>,
    pub truncated: bool,
}

fn parse_hunk_start(header: &str) -> Option<(u32, u32)> {
    let mut parts = header.split_whitespace();
    parts.next()?;
    let old = parts.next()?.trim_start_matches('-');
    let new = parts.next()?.trim_start_matches('+');
    Some((
        old.split(',').next()?.parse().ok()?,
        new.split(',').next()?.parse().ok()?,
    ))
}

pub fn parse_unified_diff(diff: &str, max_rows: usize) -> DiffView {
    let normalized = diff.replace("\r\n", "\n");
    let mut view = DiffView::default();
    let mut old_line = 1u32;
    let mut new_line = 1u32;
    let mut removed = Vec::<(u32, String)>::new();
    let mut added = Vec::<(u32, String)>::new();

    fn flush(
        view: &mut DiffView,
        removed: &mut Vec<(u32, String)>,
        added: &mut Vec<(u32, String)>,
    ) {
        let count = removed.len().max(added.len());
        for index in 0..count {
            let before = removed.get(index);
            let after = added.get(index);
            view.rows.push(DiffRow {
                before_line: before.map(|item| item.0),
                after_line: after.map(|item| item.0),
                before: before.map(|item| item.1.clone()).unwrap_or_default(),
                after: after.map(|item| item.1.clone()).unwrap_or_default(),
                kind: match (before.is_some(), after.is_some()) {
                    (true, true) => DiffRowKind::Modified,
                    (true, false) => DiffRowKind::Removed,
                    (false, true) => DiffRowKind::Added,
                    _ => DiffRowKind::Context,
                },
            });
        }
        removed.clear();
        added.clear();
    }

    for line in normalized.lines() {
        if let Some(path) = line.strip_prefix("+++ ") {
            view.path = path.trim_start_matches("b/").to_string();
            continue;
        }
        if line.starts_with("--- ") || line.starts_with("diff --git ") || line.starts_with("index ")
        {
            continue;
        }
        if line.starts_with("@@") {
            flush(&mut view, &mut removed, &mut added);
            if let Some((old, new)) = parse_hunk_start(line) {
                old_line = old;
                new_line = new;
            }
            continue;
        }
        if line.starts_with("\\ No newline") {
            continue;
        }

        if let Some(text) = line.strip_prefix('-') {
            removed.push((old_line, text.to_string()));
            old_line += 1;
        } else if let Some(text) = line.strip_prefix('+') {
            added.push((new_line, text.to_string()));
            new_line += 1;
        } else {
            flush(&mut view, &mut removed, &mut added);
            let text = line.strip_prefix(' ').unwrap_or(line);
            view.rows.push(DiffRow {
                before_line: Some(old_line),
                after_line: Some(new_line),
                before: text.to_string(),
                after: text.to_string(),
                kind: DiffRowKind::Context,
            });
            old_line += 1;
            new_line += 1;
        }

        if view.rows.len() >= max_rows {
            view.truncated = true;
            break;
        }
    }
    flush(&mut view, &mut removed, &mut added);
    if view.rows.len() > max_rows {
        view.rows.truncate(max_rows);
        view.truncated = true;
    }
    view
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CodeLine {
    pub number: usize,
    pub text: String,
}

pub fn code_lines(text: &str) -> Vec<CodeLine> {
    let normalized = text.replace("\r\n", "\n");
    if normalized.is_empty() {
        return vec![CodeLine {
            number: 1,
            text: String::new(),
        }];
    }
    normalized
        .split('\n')
        .enumerate()
        .map(|(index, line)| CodeLine {
            number: index + 1,
            text: line.to_string(),
        })
        .collect()
}

pub fn code_language_label(language: &str) -> String {
    let language = language.trim();
    if language.is_empty() {
        "CODE".into()
    } else {
        language.to_ascii_uppercase()
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SmoothScrollController {
    current: f32,
    target: f32,
    max_offset: f32,
    smoothing: f32,
}

impl Default for SmoothScrollController {
    fn default() -> Self {
        Self {
            current: 0.0,
            target: 0.0,
            max_offset: 0.0,
            smoothing: 0.28,
        }
    }
}

impl SmoothScrollController {
    pub fn new(max_offset: f32) -> Self {
        let mut controller = Self::default();
        controller.set_max_offset(max_offset);
        controller
    }

    pub fn current(self) -> f32 {
        self.current
    }
    pub fn target(self) -> f32 {
        self.target
    }
    pub fn max_offset(self) -> f32 {
        self.max_offset
    }

    pub fn set_max_offset(&mut self, max_offset: f32) {
        self.max_offset = max_offset.max(0.0);
        self.current = self.current.clamp(0.0, self.max_offset);
        self.target = self.target.clamp(0.0, self.max_offset);
    }

    pub fn set_target(&mut self, target: f32) {
        self.target = target.clamp(0.0, self.max_offset);
    }

    pub fn nudge(&mut self, delta: f32) {
        self.set_target(self.target + delta);
    }

    pub fn apply_wheel_delta(&mut self, wheel_delta: i32, logical_pixels_per_notch: f32) {
        let notches = wheel_delta as f32 / 120.0;
        self.nudge(-notches * logical_pixels_per_notch);
    }

    pub fn jump_to(&mut self, offset: f32) {
        let offset = offset.clamp(0.0, self.max_offset);
        self.current = offset;
        self.target = offset;
    }

    pub fn is_animating(self) -> bool {
        (self.target - self.current).abs() >= 0.5
    }

    pub fn near_end(self, threshold: f32) -> bool {
        self.max_offset - self.target <= threshold.max(0.0)
    }

    pub fn step(&mut self) -> bool {
        let remaining = self.target - self.current;
        if remaining.abs() < 0.5 {
            self.current = self.target;
            return false;
        }
        let mut movement = remaining * self.smoothing;
        if movement.abs() < 0.75 {
            movement = remaining.signum() * 0.75;
        }
        if movement.abs() > remaining.abs() {
            movement = remaining;
        }
        self.current = (self.current + movement).clamp(0.0, self.max_offset);
        self.is_animating()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScrollStickiness {
    PreserveAnchor,
    StickToEnd,
}

pub fn chat_scroll_policy(
    previous_offset: f32,
    previous_total: f32,
    viewport_extent: f32,
) -> ScrollStickiness {
    let distance_from_end =
        (previous_total - viewport_extent.max(1.0) - previous_offset.max(0.0)).max(0.0);
    if distance_from_end <= 24.0 {
        ScrollStickiness::StickToEnd
    } else {
        ScrollStickiness::PreserveAnchor
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct UiAcceptanceProfile {
    pub name: &'static str,
    pub viewport: LayoutSize,
    pub scale: UiScale,
}

impl UiAcceptanceProfile {
    pub fn standard_profiles() -> [Self; 6] {
        [
            Self {
                name: "laptop-1366",
                viewport: LayoutSize::new(1366.0, 768.0),
                scale: UiScale::new(1.0),
            },
            Self {
                name: "1080p-100",
                viewport: LayoutSize::new(1920.0, 1080.0),
                scale: UiScale::new(1.0),
            },
            Self {
                name: "1440p-125",
                viewport: LayoutSize::new(2560.0, 1440.0),
                scale: UiScale::new(1.25),
            },
            Self {
                name: "4k-200",
                viewport: LayoutSize::new(3840.0, 2160.0),
                scale: UiScale::new(2.0),
            },
            Self {
                name: "ultrawide-3440",
                viewport: LayoutSize::new(3440.0, 1440.0),
                scale: UiScale::new(1.0),
            },
            Self {
                name: "super-ultrawide-5120",
                viewport: LayoutSize::new(5120.0, 1440.0),
                scale: UiScale::new(1.0),
            },
        ]
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UiAcceptanceIssue {
    pub profile: String,
    pub message: String,
}

#[derive(Clone, Debug, Default)]
pub struct UiAcceptanceReport {
    pub checked_profiles: usize,
    pub issues: Vec<UiAcceptanceIssue>,
}

impl UiAcceptanceReport {
    pub fn passed(&self) -> bool {
        self.issues.is_empty()
    }
}

pub fn validate_shell_profiles(profiles: &[UiAcceptanceProfile]) -> UiAcceptanceReport {
    let mut report = UiAcceptanceReport {
        checked_profiles: profiles.len(),
        issues: Vec::new(),
    };

    for profile in profiles {
        let theme = UiTheme::dark(profile.scale, UiDensity::Comfortable);

        for &(left_collapsed, right_collapsed, activity_expanded) in &[
            (false, false, false),
            (true, false, false),
            (false, true, false),
            (true, true, false),
            (false, false, true),
        ] {
            let input = ShellLayoutInput {
                viewport: profile.viewport,
                left_collapsed,
                right_collapsed,
                activity_expanded,
                activity_height: 240.0,
            };
            let shell = match ShellLayout::calculate(&theme, input) {
                Ok(shell) => shell,
                Err(error) => {
                    report.issues.push(UiAcceptanceIssue {
                        profile: profile.name.to_string(),
                        message: format!("layout calculation failed: {error}"),
                    });
                    continue;
                }
            };

            let state = format!(
                "left_collapsed={left_collapsed}, right_collapsed={right_collapsed}, activity={activity_expanded}"
            );

            if shell.left.right() > shell.center.x + 0.5 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: format!("left pane overlaps center ({state})"),
                });
            }
            if shell.center.right() > shell.right.x + 0.5 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: format!("center overlaps right pane ({state})"),
                });
            }
            if shell.body.bottom() > shell.status.y + 0.5 && !activity_expanded {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: format!("body overlaps status ({state})"),
                });
            }
            if activity_expanded {
                if shell.body.bottom() > shell.activity.y + 0.5 {
                    report.issues.push(UiAcceptanceIssue {
                        profile: profile.name.to_string(),
                        message: format!("body overlaps Activity drawer ({state})"),
                    });
                }
                if shell.activity.bottom() > shell.status.y + 0.5 {
                    report.issues.push(UiAcceptanceIssue {
                        profile: profile.name.to_string(),
                        message: format!("Activity drawer overlaps status ({state})"),
                    });
                }
            }
            if shell.center.width < 320.0 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: format!(
                        "center workspace below 320 logical units: {:.1} ({state})",
                        shell.center.width
                    ),
                });
            }
            if shell.root.right() > profile.viewport.width + 0.5
                || shell.root.bottom() > profile.viewport.height + 0.5
            {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: format!("root escaped viewport ({state})"),
                });
            }
        }
    }

    report
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SidebarLayout {
    pub bounds: LayoutRect,
    pub toggle: LayoutRect,
    pub header: LayoutRect,
    pub project_path: LayoutRect,
    pub add_project: LayoutRect,
    pub project_list: LayoutRect,
    pub new_chat: LayoutRect,
    pub archive_chat: LayoutRect,
    pub rail_items: [LayoutRect; 5],
}

impl SidebarLayout {
    pub fn calculate(theme: &UiTheme, bounds: LayoutRect, collapsed: bool) -> Self {
        let pad = theme.spacing_sm;
        let row_h = 34.0;
        let toggle = LayoutRect::new(bounds.x + pad, bounds.y, 34.0, 30.0);
        let header = LayoutRect::new(
            toggle.right() + theme.spacing_sm,
            bounds.y + 2.0,
            (bounds.width - 92.0).max(0.0),
            28.0,
        );

        let mut rail_items = [LayoutRect::default(); 5];
        let mut rail_y = bounds.y + 42.0;
        for item in &mut rail_items {
            *item = LayoutRect::new(bounds.x + 8.0, rail_y, 38.0, 36.0);
            rail_y += 44.0;
        }

        if collapsed {
            return Self {
                bounds,
                toggle,
                header,
                project_path: LayoutRect::default(),
                add_project: LayoutRect::default(),
                project_list: LayoutRect::default(),
                new_chat: LayoutRect::default(),
                archive_chat: LayoutRect::default(),
                rail_items,
            };
        }

        let top_controls_y = bounds.y + 40.0;
        let add_w = 102.0;
        let project_path = LayoutRect::new(
            bounds.x + pad,
            top_controls_y,
            (bounds.width - add_w - pad * 3.0).max(80.0),
            row_h,
        );
        let add_project = LayoutRect::new(project_path.right() + pad, top_controls_y, add_w, row_h);

        let footer_h = 38.0;
        let list_y = top_controls_y + row_h + theme.spacing_md;
        let list_bottom = bounds.bottom() - footer_h - theme.spacing_sm;
        let project_list = LayoutRect::new(
            bounds.x + pad,
            list_y,
            (bounds.width - pad * 2.0).max(0.0),
            (list_bottom - list_y).max(80.0),
        );

        let footer_y = bounds.bottom() - footer_h;
        let new_chat = LayoutRect::new(bounds.x + pad, footer_y, 96.0, 30.0);
        let archive_chat =
            LayoutRect::new(new_chat.right() + theme.spacing_sm, footer_y, 88.0, 30.0);

        Self {
            bounds,
            toggle,
            header,
            project_path,
            add_project,
            project_list,
            new_chat,
            archive_chat,
            rail_items,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ContextPanelLayout {
    pub bounds: LayoutRect,
    pub toggle: LayoutRect,
    pub header: LayoutRect,
    pub tabs: [LayoutRect; 6],
    pub content: LayoutRect,
    pub collapsed_config: LayoutRect,
}

impl ContextPanelLayout {
    pub fn calculate(theme: &UiTheme, bounds: LayoutRect, collapsed: bool) -> Self {
        let pad = theme.spacing_sm;
        let toggle = LayoutRect::new(bounds.right() - 44.0, bounds.y, 34.0, 30.0);
        let header = LayoutRect::new(
            bounds.x + pad,
            bounds.y + 2.0,
            (bounds.width - 60.0).max(0.0),
            28.0,
        );
        let collapsed_config = LayoutRect::new(bounds.right() - 42.0, bounds.y + 40.0, 32.0, 32.0);

        let mut tabs = [LayoutRect::default(); 6];
        if !collapsed {
            let usable = (bounds.width - pad * 2.0).max(0.0);
            let gap = theme.spacing_xs;
            let tab_w = ((usable - gap * 5.0) / 6.0).max(48.0);
            for (index, tab) in tabs.iter_mut().enumerate() {
                *tab = LayoutRect::new(
                    bounds.x + pad + index as f32 * (tab_w + gap),
                    bounds.y + 40.0,
                    tab_w,
                    34.0,
                );
            }
        }

        let content_y = bounds.y + 84.0;
        let content = LayoutRect::new(
            bounds.x + pad,
            content_y,
            (bounds.width - pad * 2.0).max(0.0),
            (bounds.bottom() - content_y - pad).max(0.0),
        );

        Self {
            bounds,
            toggle,
            header,
            tabs,
            content,
            collapsed_config,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UiCommand {
    pub id: String,
    pub title: String,
    pub category: String,
    pub keywords: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommandMatch {
    pub command_index: usize,
    pub score: i32,
}

#[derive(Clone, Debug, Default)]
pub struct CommandPalette {
    pub query: String,
    pub selected: usize,
    pub commands: Vec<UiCommand>,
}

impl CommandPalette {
    pub fn with_commands(commands: Vec<UiCommand>) -> Self {
        Self {
            commands,
            ..Self::default()
        }
    }

    pub fn matches(&self, limit: usize) -> Vec<CommandMatch> {
        let query = self.query.trim().to_ascii_lowercase();
        let mut matches = self
            .commands
            .iter()
            .enumerate()
            .filter_map(|(index, command)| {
                let haystack = format!(
                    "{} {} {}",
                    command.title,
                    command.category,
                    command.keywords.join(" ")
                )
                .to_ascii_lowercase();
                command_score(&query, &haystack).map(|score| CommandMatch {
                    command_index: index,
                    score,
                })
            })
            .collect::<Vec<_>>();

        matches.sort_by(|left, right| {
            right.score.cmp(&left.score).then_with(|| {
                self.commands[left.command_index]
                    .title
                    .cmp(&self.commands[right.command_index].title)
            })
        });
        matches.truncate(limit);
        matches
    }
}

fn command_score(query: &str, haystack: &str) -> Option<i32> {
    if query.is_empty() {
        return Some(0);
    }
    if let Some(position) = haystack.find(query) {
        return Some(10_000 - position as i32);
    }

    let mut cursor = 0usize;
    let mut gaps = 0i32;
    for needle in query.chars() {
        let slice = &haystack[cursor..];
        let position = slice.find(needle)?;
        gaps += position as i32;
        cursor += position + needle.len_utf8();
    }
    Some(1_000 - gaps)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyIntent {
    NextFocus,
    PreviousFocus,
    Activate,
    Cancel,
    CommandPalette,
    Find,
    PageUp,
    PageDown,
}

#[derive(Clone, Debug, Default)]
pub struct FocusRing {
    order: Vec<WidgetId>,
    active: Option<usize>,
}

impl FocusRing {
    pub fn new(order: Vec<WidgetId>) -> Self {
        let active = (!order.is_empty()).then_some(0);
        Self { order, active }
    }

    pub fn active(&self) -> Option<&WidgetId> {
        self.active.and_then(|index| self.order.get(index))
    }

    pub fn focus(&mut self, id: &str) -> bool {
        let Some(index) = self.order.iter().position(|item| item.as_str() == id) else {
            return false;
        };
        self.active = Some(index);
        true
    }

    pub fn advance(&mut self, backwards: bool) -> Option<&WidgetId> {
        if self.order.is_empty() {
            self.active = None;
            return None;
        }
        let current = self.active.unwrap_or(0);
        self.active = Some(if backwards {
            if current == 0 {
                self.order.len() - 1
            } else {
                current - 1
            }
        } else {
            (current + 1) % self.order.len()
        });
        self.active()
    }
}

pub fn validate_sidebar_context_profiles(profiles: &[UiAcceptanceProfile]) -> UiAcceptanceReport {
    let mut report = UiAcceptanceReport {
        checked_profiles: profiles.len(),
        issues: Vec::new(),
    };

    for profile in profiles {
        let theme = UiTheme::dark(profile.scale, UiDensity::Comfortable);
        for &(left_collapsed, right_collapsed) in
            &[(false, false), (true, false), (false, true), (true, true)]
        {
            let shell = match ShellLayout::calculate(
                &theme,
                ShellLayoutInput {
                    viewport: profile.viewport,
                    left_collapsed,
                    right_collapsed,
                    activity_expanded: false,
                    activity_height: 240.0,
                },
            ) {
                Ok(shell) => shell,
                Err(error) => {
                    report.issues.push(UiAcceptanceIssue {
                        profile: profile.name.to_string(),
                        message: error,
                    });
                    continue;
                }
            };

            let sidebar = SidebarLayout::calculate(&theme, shell.left, left_collapsed);
            let context = ContextPanelLayout::calculate(&theme, shell.right, right_collapsed);

            if !left_collapsed && sidebar.project_list.right() > shell.left.right() + 0.5 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: "sidebar project list escaped left pane".into(),
                });
            }
            if !right_collapsed && context.content.x < shell.right.x - 0.5 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: "context content escaped into center workspace".into(),
                });
            }
            if context.collapsed_config.right() > shell.right.right() + 0.5 {
                report.issues.push(UiAcceptanceIssue {
                    profile: profile.name.to_string(),
                    message: "collapsed context control escaped right rail".into(),
                });
            }
        }
    }

    report
}

#[derive(Clone, Debug)]
pub struct UiTheme {
    pub density: UiDensity,
    pub scale: UiScale,
    pub spacing_xs: f32,
    pub spacing_sm: f32,
    pub spacing_md: f32,
    pub spacing_lg: f32,
    pub spacing_xl: f32,
    pub radius_sm: f32,
    pub radius_md: f32,
    pub radius_lg: f32,
    pub text_caption: f32,
    pub text_label: f32,
    pub text_body: f32,
    pub text_body_large: f32,
    pub text_heading: f32,
    pub text_code: f32,
    pub sidebar_expanded: f32,
    pub sidebar_collapsed: f32,
    pub context_expanded: f32,
    pub context_collapsed: f32,
    pub status_height: f32,
}

impl UiTheme {
    pub fn dark(scale: UiScale, density: UiDensity) -> Self {
        let density_factor = match density {
            UiDensity::Compact => 0.88,
            UiDensity::Comfortable => 1.0,
            UiDensity::Spacious => 1.16,
        };
        Self {
            density,
            scale,
            spacing_xs: 4.0 * density_factor,
            spacing_sm: 8.0 * density_factor,
            spacing_md: 12.0 * density_factor,
            spacing_lg: 16.0 * density_factor,
            spacing_xl: 24.0 * density_factor,
            radius_sm: 6.0,
            radius_md: 10.0,
            radius_lg: 16.0,
            text_caption: 12.0,
            text_label: 14.0,
            text_body: 16.0,
            text_body_large: 18.0,
            text_heading: 22.0,
            text_code: 15.0,
            sidebar_expanded: 300.0,
            sidebar_collapsed: 54.0,
            context_expanded: 400.0,
            context_collapsed: 44.0,
            status_height: 30.0,
        }
    }
}

impl Default for UiTheme {
    fn default() -> Self {
        Self::dark(UiScale::ONE, UiDensity::Comfortable)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ShellLayoutInput {
    pub viewport: LayoutSize,
    pub left_collapsed: bool,
    pub right_collapsed: bool,
    pub activity_expanded: bool,
    pub activity_height: f32,
}

impl ShellLayoutInput {
    pub fn new(viewport: LayoutSize) -> Self {
        Self {
            viewport,
            left_collapsed: false,
            right_collapsed: false,
            activity_expanded: false,
            activity_height: 240.0,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct ShellLayout {
    pub root: LayoutRect,
    pub body: LayoutRect,
    pub left: LayoutRect,
    pub center: LayoutRect,
    pub right: LayoutRect,
    pub activity: LayoutRect,
    pub status: LayoutRect,
}

impl ShellLayout {
    pub fn calculate(theme: &UiTheme, input: ShellLayoutInput) -> Result<Self, String> {
        let viewport = LayoutRect::new(
            0.0,
            0.0,
            input.viewport.width.max(1.0),
            input.viewport.height.max(1.0),
        );

        let left_width = if input.left_collapsed {
            theme.sidebar_collapsed
        } else {
            theme.sidebar_expanded
        };
        let right_width = if input.right_collapsed {
            theme.context_collapsed
        } else {
            theme.context_expanded
        };
        let activity_height = if input.activity_expanded {
            input.activity_height.max(120.0)
        } else {
            0.0
        };

        let mut root = LayoutNode::column("shell.root")?;
        root.padding = Insets {
            left: 0.0,
            top: 14.0,
            right: 0.0,
            bottom: 0.0,
        };

        let mut body = LayoutNode::row("shell.body")?;
        body.constraints = LayoutConstraints {
            min_width: 1.0,
            preferred_width: input.viewport.width,
            max_width: f32::MAX,
            min_height: 120.0,
            preferred_height: 600.0,
            max_height: f32::MAX,
            flex: 1.0,
        };

        body.push(
            LayoutNode::new("shell.left", WidgetKind::Sidebar)?
                .with_constraints(LayoutConstraints::fixed(left_width, 1.0)),
        );

        let mut center = LayoutNode::new("shell.center", WidgetKind::Panel)?;
        center.constraints = LayoutConstraints {
            min_width: 320.0,
            preferred_width: 640.0,
            max_width: f32::MAX,
            min_height: 120.0,
            preferred_height: 600.0,
            max_height: f32::MAX,
            flex: 1.0,
        };
        center.padding = Insets::symmetric(10.0, 0.0);
        center.clip = true;
        body.push(center);

        body.push(
            LayoutNode::new("shell.right", WidgetKind::Panel)?
                .with_constraints(LayoutConstraints::fixed(right_width, 1.0)),
        );

        root.push(body);

        let mut activity = LayoutNode::new("shell.activity", WidgetKind::Drawer)?;
        activity.constraints = LayoutConstraints::fixed(input.viewport.width, activity_height);
        activity.state.visible = input.activity_expanded;
        activity.clip = true;
        root.push(activity);

        root.push(
            LayoutNode::new("shell.status", WidgetKind::Status)?.with_constraints(
                LayoutConstraints::fixed(input.viewport.width, theme.status_height),
            ),
        );

        root.layout(viewport);

        Ok(Self {
            root: viewport,
            body: root
                .find("shell.body")
                .map(|node| node.bounds)
                .unwrap_or_default(),
            left: root
                .find("shell.left")
                .map(|node| node.bounds)
                .unwrap_or_default(),
            center: root
                .find("shell.center")
                .map(|node| node.bounds)
                .unwrap_or_default(),
            right: root
                .find("shell.right")
                .map(|node| node.bounds)
                .unwrap_or_default(),
            activity: root
                .find("shell.activity")
                .map(|node| node.bounds)
                .unwrap_or_default(),
            status: root
                .find("shell.status")
                .map(|node| node.bounds)
                .unwrap_or_default(),
        })
    }

    pub fn center_content(self) -> LayoutRect {
        self.center.inset(Insets::symmetric(10.0, 0.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_are_stable_and_reject_whitespace() {
        assert_eq!(
            WidgetId::new("chat.message.42").unwrap().as_str(),
            "chat.message.42"
        );
        assert!(WidgetId::new("chat message").is_err());
    }

    #[test]
    fn dpi_scale_converts_logical_units() {
        assert_eq!(UiScale::new(1.25).px(16.0), 20);
        assert_eq!(UiScale::new(4.0).factor(), 2.0);
    }

    #[test]
    fn row_layout_respects_fixed_and_flexible_children() {
        let mut root = LayoutNode::row("root").unwrap().with_gap(8.0);
        root.push(
            LayoutNode::new("left", WidgetKind::Sidebar)
                .unwrap()
                .with_constraints(LayoutConstraints::fixed(100.0, 100.0)),
        );
        let mut center = LayoutNode::new("center", WidgetKind::Panel).unwrap();
        center.constraints = LayoutConstraints {
            min_width: 200.0,
            preferred_width: 200.0,
            max_width: f32::MAX,
            min_height: 100.0,
            preferred_height: 100.0,
            max_height: f32::MAX,
            flex: 1.0,
        };
        root.push(center);
        root.push(
            LayoutNode::new("right", WidgetKind::Panel)
                .unwrap()
                .with_constraints(LayoutConstraints::fixed(120.0, 100.0)),
        );

        root.layout(LayoutRect::new(0.0, 0.0, 1000.0, 600.0));

        assert_eq!(root.find("left").unwrap().bounds.width, 100.0);
        assert_eq!(root.find("right").unwrap().bounds.width, 120.0);
        assert!(root.find("center").unwrap().bounds.width > 700.0);
        assert!(root.find("center").unwrap().bounds.right() <= 1000.0);
    }

    #[test]
    fn hidden_children_do_not_consume_layout_space() {
        let mut root = LayoutNode::row("root").unwrap();
        let mut hidden = LayoutNode::new("hidden", WidgetKind::Panel).unwrap();
        hidden.constraints = LayoutConstraints::fixed(300.0, 100.0);
        hidden.state.visible = false;
        root.push(hidden);

        let mut center = LayoutNode::new("center", WidgetKind::Panel).unwrap();
        center.constraints = LayoutConstraints::flexible();
        root.push(center);

        root.layout(LayoutRect::new(0.0, 0.0, 800.0, 400.0));
        assert_eq!(root.find("center").unwrap().bounds.width, 800.0);
    }

    #[test]
    fn widget_tree_can_be_inspected_by_stable_id() {
        let mut root = LayoutNode::column("root").unwrap();
        root.push(LayoutNode::new("project.sidebar", WidgetKind::Sidebar).unwrap());
        root.layout(LayoutRect::new(0.0, 0.0, 500.0, 500.0));
        let flattened = root.flatten_bounds();
        assert!(flattened.contains_key("project.sidebar"));
    }
    #[test]
    fn shell_sidebars_resize_center_without_overlap() {
        let theme = UiTheme::default();
        let expanded = ShellLayout::calculate(
            &theme,
            ShellLayoutInput {
                viewport: LayoutSize::new(1920.0, 1080.0),
                left_collapsed: false,
                right_collapsed: false,
                activity_expanded: false,
                activity_height: 240.0,
            },
        )
        .unwrap();
        let collapsed = ShellLayout::calculate(
            &theme,
            ShellLayoutInput {
                viewport: LayoutSize::new(1920.0, 1080.0),
                left_collapsed: true,
                right_collapsed: true,
                activity_expanded: false,
                activity_height: 240.0,
            },
        )
        .unwrap();

        assert!(collapsed.center.width > expanded.center.width);
        assert!(expanded.left.right() <= expanded.center.x);
        assert!(expanded.center.right() <= expanded.right.x);
        assert!(collapsed.left.right() <= collapsed.center.x);
        assert!(collapsed.center.right() <= collapsed.right.x);
    }

    #[test]
    fn activity_drawer_reduces_body_height_but_not_status_height() {
        let theme = UiTheme::default();
        let closed = ShellLayout::calculate(
            &theme,
            ShellLayoutInput {
                viewport: LayoutSize::new(1600.0, 900.0),
                left_collapsed: false,
                right_collapsed: false,
                activity_expanded: false,
                activity_height: 240.0,
            },
        )
        .unwrap();
        let open = ShellLayout::calculate(
            &theme,
            ShellLayoutInput {
                viewport: LayoutSize::new(1600.0, 900.0),
                left_collapsed: false,
                right_collapsed: false,
                activity_expanded: true,
                activity_height: 240.0,
            },
        )
        .unwrap();

        assert!(open.body.height < closed.body.height);
        assert_eq!(open.status.height, closed.status.height);
        assert_eq!(open.activity.height, 240.0);
    }

    #[test]
    fn ultrawide_layout_preserves_large_center_workspace() {
        let theme = UiTheme::default();
        let shell = ShellLayout::calculate(
            &theme,
            ShellLayoutInput {
                viewport: LayoutSize::new(5120.0, 1440.0),
                left_collapsed: false,
                right_collapsed: false,
                activity_expanded: false,
                activity_height: 240.0,
            },
        )
        .unwrap();

        assert!(shell.center.width > 4000.0);
        assert!(shell.status.bottom() <= shell.root.bottom());
    }

    #[test]
    fn virtual_list_only_returns_visible_window_with_overscan() {
        let items = (0..100)
            .map(|index| VirtualListItem::new(format!("item.{index}"), 40.0).unwrap())
            .collect::<Vec<_>>();
        let window = VirtualList::window(&items, 1200.0, 400.0, 80.0);

        assert!(window.first > 20);
        assert!(window.last_exclusive < 50);
        assert!(window.len() < items.len());
        assert_eq!(window.total_extent, 4000.0);
    }

    #[test]
    fn scroll_anchor_survives_items_added_above() {
        let original = vec![
            VirtualListItem::new("a", 50.0).unwrap(),
            VirtualListItem::new("b", 50.0).unwrap(),
            VirtualListItem::new("c", 50.0).unwrap(),
        ];
        let anchor = ScrollAnchor::capture(&original, 75.0).unwrap();
        assert_eq!(anchor.item_id.as_str(), "b");

        let expanded = vec![
            VirtualListItem::new("new", 30.0).unwrap(),
            VirtualListItem::new("a", 50.0).unwrap(),
            VirtualListItem::new("b", 50.0).unwrap(),
            VirtualListItem::new("c", 50.0).unwrap(),
        ];
        assert_eq!(anchor.restore(&expanded), Some(105.0));
    }

    #[test]
    fn chat_only_sticks_to_end_when_reader_was_already_near_end() {
        assert_eq!(
            chat_scroll_policy(580.0, 1000.0, 400.0),
            ScrollStickiness::StickToEnd
        );
        assert_eq!(
            chat_scroll_policy(200.0, 1000.0, 400.0),
            ScrollStickiness::PreserveAnchor
        );
    }

    #[test]
    fn standard_shell_acceptance_profiles_have_no_overlap() {
        let profiles = UiAcceptanceProfile::standard_profiles();
        let report = validate_shell_profiles(&profiles);
        assert!(
            report.passed(),
            "responsive shell acceptance failed: {:?}",
            report.issues
        );
        assert_eq!(report.checked_profiles, 6);
    }

    #[test]
    fn ui_scale_is_part_of_acceptance_profile() {
        let profiles = UiAcceptanceProfile::standard_profiles();
        assert_eq!(profiles[2].scale.factor(), 1.25);
        assert_eq!(profiles[2].scale.px(16.0), 20);
        assert_eq!(profiles[3].scale.factor(), 2.0);
    }

    #[test]
    fn sidebar_expansion_uses_one_retained_geometry_authority() {
        let theme = UiTheme::default();
        let bounds = LayoutRect::new(0.0, 14.0, 300.0, 1000.0);
        let sidebar = SidebarLayout::calculate(&theme, bounds, false);

        assert!(sidebar.project_path.right() <= sidebar.add_project.x);
        assert!(sidebar.add_project.right() <= bounds.right() + 0.5);
        assert!(sidebar.project_list.bottom() <= sidebar.new_chat.y + 0.5);
        assert!(sidebar.archive_chat.right() <= bounds.right() + 0.5);
    }

    #[test]
    fn collapsed_sidebar_rail_stays_inside_its_bounds() {
        let theme = UiTheme::default();
        let bounds = LayoutRect::new(0.0, 14.0, 54.0, 900.0);
        let sidebar = SidebarLayout::calculate(&theme, bounds, true);
        for item in sidebar.rail_items {
            assert!(item.x >= bounds.x);
            assert!(item.right() <= bounds.right() + 0.5);
        }
    }

    #[test]
    fn context_panel_tabs_and_content_do_not_overlap() {
        let theme = UiTheme::default();
        let bounds = LayoutRect::new(1520.0, 14.0, 400.0, 1000.0);
        let panel = ContextPanelLayout::calculate(&theme, bounds, false);

        let tab_y = panel.tabs[0].y;
        for tab in panel.tabs {
            assert!(tab.x >= bounds.x);
            assert!(tab.right() <= bounds.right() + 0.5);
            assert!((tab.y - tab_y).abs() <= 0.5);
            assert!(tab.bottom() <= panel.content.y + 0.5);
        }
        for pair in panel.tabs.windows(2) {
            assert!(pair[0].right() <= pair[1].x + 0.5);
        }
        assert!(panel.content.right() <= bounds.right() + 0.5);
    }

    #[test]
    fn collapsed_context_control_remains_in_reserved_rail() {
        let theme = UiTheme::default();
        let bounds = LayoutRect::new(1876.0, 14.0, 44.0, 900.0);
        let panel = ContextPanelLayout::calculate(&theme, bounds, true);
        assert!(panel.collapsed_config.x >= bounds.x);
        assert!(panel.collapsed_config.right() <= bounds.right() + 0.5);
    }

    #[test]
    fn command_palette_ranks_exact_phrase_over_sparse_subsequence() {
        let mut palette = CommandPalette::with_commands(vec![
            UiCommand {
                id: "project.build".into(),
                title: "Build Current Project".into(),
                category: "Project".into(),
                keywords: vec!["cargo".into(), "compile".into()],
            },
            UiCommand {
                id: "project.browser".into(),
                title: "Browse Project".into(),
                category: "Project".into(),
                keywords: vec!["files".into()],
            },
        ]);
        palette.query = "build".into();
        let matches = palette.matches(10);
        assert_eq!(matches[0].command_index, 0);
    }

    #[test]
    fn command_palette_searches_categories_and_keywords() {
        let mut palette = CommandPalette::with_commands(vec![UiCommand {
            id: "library.scan".into(),
            title: "Refresh Vault".into(),
            category: "Vault".into(),
            keywords: vec!["scan".into(), "drive".into()],
        }]);
        palette.query = "scan".into();
        assert_eq!(palette.matches(10).len(), 1);
    }

    #[test]
    fn focus_ring_wraps_in_both_directions() {
        let mut ring = FocusRing::new(vec![
            WidgetId::new("left.projects").unwrap(),
            WidgetId::new("chat.input").unwrap(),
            WidgetId::new("right.files").unwrap(),
        ]);
        assert_eq!(ring.active().unwrap().as_str(), "left.projects");
        ring.advance(true);
        assert_eq!(ring.active().unwrap().as_str(), "right.files");
        ring.advance(false);
        assert_eq!(ring.active().unwrap().as_str(), "left.projects");
    }

    #[test]
    fn focus_ring_can_target_stable_widget_id() {
        let mut ring = FocusRing::new(vec![
            WidgetId::new("chat.input").unwrap(),
            WidgetId::new("chat.send").unwrap(),
        ]);
        assert!(ring.focus("chat.send"));
        assert_eq!(ring.active().unwrap().as_str(), "chat.send");
        assert!(!ring.focus("missing.widget"));
    }

    #[test]
    fn sidebar_and_context_widget_profiles_pass_standard_resolutions() {
        let profiles = UiAcceptanceProfile::standard_profiles();
        let report = validate_sidebar_context_profiles(&profiles);
        assert!(
            report.passed(),
            "sidebar/context acceptance failed: {:?}",
            report.issues
        );
    }

    #[test]
    fn smooth_scroll_accumulates_precision_wheel_input() {
        let mut scroll = SmoothScrollController::new(1000.0);
        scroll.jump_to(500.0);
        scroll.apply_wheel_delta(-30, 72.0);
        assert_eq!(scroll.target(), 518.0);
        scroll.apply_wheel_delta(-30, 72.0);
        assert_eq!(scroll.target(), 536.0);
    }

    #[test]
    fn smooth_scroll_converges_without_overshooting() {
        let mut scroll = SmoothScrollController::new(1000.0);
        scroll.set_target(420.0);
        let mut previous = scroll.current();
        for _ in 0..128 {
            scroll.step();
            assert!(scroll.current() >= previous);
            assert!(scroll.current() <= 420.0);
            previous = scroll.current();
            if !scroll.is_animating() {
                break;
            }
        }
        assert_eq!(scroll.current(), 420.0);
    }

    #[test]
    fn smooth_scroll_clamps_when_content_shrinks() {
        let mut scroll = SmoothScrollController::new(1200.0);
        scroll.jump_to(1100.0);
        scroll.set_max_offset(300.0);
        assert_eq!(scroll.current(), 300.0);
        assert_eq!(scroll.target(), 300.0);
    }

    #[test]
    fn smooth_scroll_near_end_uses_target() {
        let mut scroll = SmoothScrollController::new(1000.0);
        scroll.jump_to(500.0);
        scroll.set_target(990.0);
        assert!(scroll.near_end(24.0));
    }

    #[test]
    fn chat_style_virtualization_bounds_long_conversations() {
        let items = (0..1_000)
            .map(|index| {
                VirtualListItem::new(
                    format!("chat.card.{index}"),
                    140.0 + (index % 3) as f32 * 24.0,
                )
                .unwrap()
            })
            .collect::<Vec<_>>();

        let window = VirtualList::window(&items, 72_000.0, 1_080.0, 240.0);

        assert!(window.len() < 20);
        assert!(window.first > 100);
        assert!(window.last_exclusive < items.len());
    }

    #[test]
    fn code_lines_preserve_whitespace_and_blank_lines() {
        let lines = code_lines("fn main() {\n    work();\n\n}");
        assert_eq!(lines.len(), 4);
        assert_eq!(lines[1].text, "    work();");
        assert_eq!(lines[2].text, "");
        assert_eq!(lines[3].number, 4);
    }

    #[test]
    fn code_language_labels_are_stable() {
        assert_eq!(code_language_label("rust"), "RUST");
        assert_eq!(code_language_label(""), "CODE");
    }

    #[test]
    fn unified_diff_pairs_changes_side_by_side() {
        let view = parse_unified_diff(
            "--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -2,2 +2,2 @@\n-old();\n+new();\n same();",
            100,
        );
        assert_eq!(view.path, "src/lib.rs");
        assert_eq!(view.rows[0].kind, DiffRowKind::Modified);
        assert_eq!(view.rows[0].before, "old();");
        assert_eq!(view.rows[0].after, "new();");
    }

    #[test]
    fn unified_diff_chat_view_is_bounded() {
        let mut diff = String::from("--- a/a\n+++ b/a\n@@ -1 +1 @@\n");
        for index in 0..500 {
            diff.push_str(&format!("+line {index}\n"));
        }
        let view = parse_unified_diff(&diff, 80);
        assert!(view.rows.len() <= 80);
        assert!(view.truncated);
    }

    #[test]
    fn workbench_reopens_existing_document_without_duplicate_tab() {
        let mut state = WorkbenchState::default();
        state.open(WorkbenchDocument {
            path: "src/lib.rs".into(),
            language: "Rust".into(),
            content: "one".into(),
            dirty: false,
        });
        state.open(WorkbenchDocument {
            path: "src/lib.rs".into(),
            language: "Rust".into(),
            content: "two".into(),
            dirty: false,
        });
        assert_eq!(state.documents.len(), 1);
        assert_eq!(state.active_document().unwrap().content, "two");
    }
}
