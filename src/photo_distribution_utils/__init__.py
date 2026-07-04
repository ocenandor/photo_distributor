"""End-to-end photo distribution workflow."""

from .apply_distribution_plan import (
    DEFAULT_SFACE_MODEL_PATH,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_YUNET_MODEL_PATH,
    DistributionArtifacts,
    DistributionConfig,
    DistributionCounters,
    DistributionPlanApplyResult,
    DistributionResult,
    apply_distribution_plan,
    cleanup_local_artifacts,
)
from .cloud_files import EventPhotoRecord, download_event_photos, validate_cloud_event_folder
from .output_files_structure import (
    CopyPlanRecord,
    CopyPlanBuildResult,
    DistributionOutputFolders,
    build_distribution_copy_plan,
    build_distribution_output_folders,
    join_disk_path,
)
from .event_artifacts import (
    EventArtifactPaths,
    local_event_key_from_folder,
    prepare_event_artifact_paths,
)
from .workflow import run_distribution

__all__ = [
    "CopyPlanRecord",
    "CopyPlanBuildResult",
    "DEFAULT_SFACE_MODEL_PATH",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_YUNET_MODEL_PATH",
    "DistributionArtifacts",
    "DistributionConfig",
    "DistributionCounters",
    "DistributionOutputFolders",
    "DistributionPlanApplyResult",
    "DistributionResult",
    "EventArtifactPaths",
    "EventPhotoRecord",
    "apply_distribution_plan",
    "build_distribution_copy_plan",
    "build_distribution_output_folders",
    "cleanup_local_artifacts",
    "download_event_photos",
    "join_disk_path",
    "local_event_key_from_folder",
    "prepare_event_artifact_paths",
    "run_distribution",
    "validate_cloud_event_folder",
]
