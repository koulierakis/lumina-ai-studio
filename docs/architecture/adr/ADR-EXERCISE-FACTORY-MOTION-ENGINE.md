# ADR: Provider-neutral Motion Engine for Athletico Exercise Factory

## Status
Accepted for Proof of Concept.

## Decision
Lumina owns a canonical skeleton, movement-family registry, pose-source abstraction, family-specific biomechanical rules and pose renderer. External datasets and image providers are adapters, never the internal representation.

The first PoC is Bodyweight Squat -> SQUAT_PATTERN with three explicitly manual, verified-reference poses. No claim is made that these poses originate from InfiniteRep or another dataset.

The existing Lumina Identity Packs, media persistence, job lifecycle and image-provider architecture remain authoritative. The motion layer must integrate with them rather than duplicate them.

## Provider boundary
The existing image provider contract currently models text/image references but does not advertise a pose-conditioning capability. Qwen-Image-Edit-2509 is therefore not marked supported until its official/current integration and a real generation are verified. No model weights are downloaded by this change.

## Rollback
Remove backend/motion_engine, its focused test, and this ADR. No user data or persistence schema is changed.
