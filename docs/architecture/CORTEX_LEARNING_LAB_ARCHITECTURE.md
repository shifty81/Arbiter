# Cortex Learning Lab — Consolidated Architecture

The Learning Lab is a governed post-training platform, not a live-learning feature.

## One new authority
Prefer one `cortex_learning` domain initially instead of creating separate crates for episodes,
datasets, rewards and evaluations. Split only if size/compile boundaries later justify it.

It owns:
- EpisodeId
- DatasetId / DatasetVersion
- FixtureSuiteId
- RewardPolicyId
- TrainingRunId
- EvaluationId
- ModelCandidateId
- curriculum and active-learning metadata

It delegates:
- durable jobs -> cortex_jobs
- artifacts/generations -> cortex_artifacts
- physical model/dataset storage -> cortex_vault
- sandbox mutation -> cortex_transactions/workspace
- permissions/trust/network -> cortex_permissions
- execution/certification -> cortex_execution
- provider/model invocation -> cortex_provider

## Learning lifecycle
Ordinary use -> structured sanitized Episode -> eligibility/provenance -> Dataset -> sandbox rollouts ->
reward vector + hard gates -> SFT/DPO/GRPO/distillation -> Candidate -> held-out/adversarial/runtime
evaluation -> Certified -> Shadow/Canary -> human-governed promotion.

## Hard rules
- no hidden chain-of-thought storage;
- no normal-use weight updates;
- no training rollout against authoritative source;
- no benchmark/hidden-evaluator contamination;
- no model self-promotion;
- no scalar reward can compensate for a hard policy/sandbox violation.
