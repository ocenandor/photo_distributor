"""Workflow for matching event photos to participants and copying them on Disk."""

from __future__ import annotations

from face_analysis import EventPhotoForAnalysis, FaceAnalyzer, ReferenceImageForAnalysis, YuNetConfig
from forms_export import ingest_forms_export
from .apply_distribution_plan import (
    DistributionArtifacts,
    DistributionConfig,
    DistributionCounters,
    DistributionResult,
    apply_distribution_plan,
)
from .cloud_files import download_event_photos, validate_cloud_event_folder
from .output_files_structure import (
    build_distribution_copy_plan,
    build_distribution_output_folders,
)
from .event_artifacts import prepare_event_artifact_paths
from yandex_disk import YandexDiskClient


def run_distribution(
    event_folder: str,
    form_id: str,
    *,
    config: DistributionConfig,
) -> DistributionResult:
    """Create runtime services and run the full distribution workflow.

    Args:
        event_folder: Source/output Yandex Disk folder for event photos.
        form_id: Yandex Forms subfolder id under `/Yandex.Forms`.
        config: Explicit run configuration built by the CLI boundary.

    Returns:
        Public run counters and local artifact paths.

    Side effects:
        Loads Yandex Disk credentials from the environment, downloads files for
        analysis, writes a local copy-plan JSON artifact, and copies existing
        remote photos on Disk.
    """

    disk_client = YandexDiskClient.from_env()
    validate_cloud_event_folder(disk_client, event_folder)
    event_artifacts = prepare_event_artifact_paths(event_folder, config)

    forms_ingest = ingest_forms_export(
        disk_client,
        form_id,
        data_dir=config.forms_data_dir,
    )
    event_photos = download_event_photos(
        disk_client,
        event_artifacts.event_folder,
        event_artifacts.local_event_photos_dir,
    )
    output_folders = build_distribution_output_folders(
        list(forms_ingest.participants),
        config.quarantine_folder_name,
    )

    analyzer = FaceAnalyzer(
        config.yunet_model_path,
        config.sface_model_path,
        detector_config=YuNetConfig(),
    )

    analysis_result = analyzer.analyze_distribution(
        [
            ReferenceImageForAnalysis(
                participant_id=reference_image.participant_id,
                local_path=reference_image.local_path,
            )
            for reference_image in forms_ingest.reference_images
        ],
        [
            EventPhotoForAnalysis(
                id=event_photo.id,
                local_path=event_photo.local_path,
            )
            for event_photo in event_photos
        ],
        config.similarity_threshold,
    )
    copy_plan = build_distribution_copy_plan(
        event_photos=event_photos,
        face_matches=list(analysis_result.face_matches),
        output_folders=output_folders,
        event_folder=event_artifacts.event_folder,
        copy_plan_path=event_artifacts.copy_plan_path,
    )
    plan_apply_result = apply_distribution_plan(
        copy_plan.copy_plan,
        disk_client=disk_client,
        output_folders=output_folders,
        event_folder=event_artifacts.event_folder,
    )

    return DistributionResult(
        counts=DistributionCounters(
            participants_count=len(forms_ingest.participants),
            reference_embeddings_count=analysis_result.reference_embeddings_count,
            event_photos_count=analysis_result.event_photos_count,
            event_faces_count=analysis_result.event_faces_count,
            face_matches_count=analysis_result.face_matches_count,
            planned_copies_count=copy_plan.planned_copies_count,
            copied_to_disk_count=plan_apply_result.copied_to_disk_count,
            quarantined_photos_count=copy_plan.quarantined_photos_count,
        ),
        artifacts=DistributionArtifacts(
            copy_plan_path=copy_plan.copy_plan_path,
            local_artifact_paths=(
                config.forms_data_dir,
                event_artifacts.local_event_photos_dir,
                event_artifacts.copy_plan_dir,
            ),
        ),
    )
