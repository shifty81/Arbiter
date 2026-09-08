# Command / Event / Job Contract

## Command
An intent to do something.
- CommandId
- ProjectId
- ConversationId?
- Actor
- Capability
- Parameters
- PolicyDecision
- CreatedAt

All entry surfaces—Chat, Workbench, GUI buttons, plugins, automation—must resolve to the same typed command authority.

## Job
A durable execution of a command.
- JobId
- CommandId
- ProjectId
- State
- Phase
- ResourceRequest
- CancellationState
- ResumeState
- ResultRefs
- ArtifactRefs
- StartedAt / UpdatedAt / CompletedAt

## Event
An immutable fact emitted while work occurs.
- EventId
- JobId?
- CommandId?
- ProjectId
- ConversationId?
- EventType
- Severity
- Timestamp
- SafePayload
- ArtifactRefs
- Provenance

## Projection rules
- Chat: human-readable selected Job/Event projection + conversation messages.
- Activity: all operational Events.
- Jobs: Job records.
- Build: build/certification events and artifacts.
- Git: Git/review state and events.
- Notifications: actionable notification/review events.
- Providers: provider telemetry.
No projection may substitute Activity text merely because its own store is empty.
