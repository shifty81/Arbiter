//! Compatibility facade. Canonical event authority is `cortex_jobs`.

pub use cortex_jobs::{
    ActivityEvent, ActivityKind, ActivityStore, ExecutionPhase, ExecutionTranscriptEntry,
    TranscriptVisibility,
};
