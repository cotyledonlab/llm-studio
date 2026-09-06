# LLM Studio

The language of a producer-led studio in which agents generate performances and propose changes while the producer retains authority over the accepted REAPER session.

## Language

**Producer**:
The human who directs the music, chooses takes and owns final authority over the accepted session.
_Avoid_: User, operator

**Accepted session**:
The REAPER project that is authoritative for the audible mix, routing, processing and editable automation.
_Avoid_: DAW mirror, agent session

**Take**:
An immutable rendered or symbolic performance candidate tied to an arrangement revision and instrument state.
_Avoid_: Version, output file

**Proposal**:
A bounded, reviewable change to exact session targets that has not modified the accepted session.
_Avoid_: Command, suggestion

**Qualified instrument**:
An instrument whose exact package, licence, state-restoration procedure and observed render behaviour are recorded for a supported host.
_Avoid_: Installed plugin, available sound

**Catalogue provisioning**:
A producer-approved workflow that acquires, verifies, installs and qualifies a pinned instrument or effect before session use.
_Avoid_: Automatic plugin installation, plugin marketplace

**Studio bootstrap**:
The idempotent setup of REAPER's approved scripts, bridge queues and control-surface configuration, with changes previewed and verified.
_Avoid_: Manual DAW setup, arbitrary configuration
