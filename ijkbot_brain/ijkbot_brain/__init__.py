"""ijkbot_brain package."""

from ijkbot_brain.llm_client import (
    LandmarkID,
    LANDMARK_DETAILS,
    CommandInterpretation,
    LLMClient,
    main as llm_main
)

try:
    from ijkbot_brain.mission_sm import (
        MissionState,
        MissionStateMachine,
        Waypoint,
        LogEntry,
        LANDMARK_WAYPOINTS,
        START_WAYPOINT,
        main as sm_main
    )
except ImportError:
    pass

__all__ = [
    "LandmarkID",
    "LANDMARK_DETAILS",
    "CommandInterpretation",
    "LLMClient",
    "llm_main",
    "MissionState",
    "MissionStateMachine",
    "Waypoint",
    "LogEntry",
    "LANDMARK_WAYPOINTS",
    "START_WAYPOINT",
    "sm_main",
]
