"""
Vision observation service (Phase 7).

Orchestration only: validate the zone, run the detector,
build the observation, persist it. Inference lives in the
`vision` package and HTTP lives in `app.api.vision`.

This service deliberately does not create incidents, does not
touch `telemetry_readings` and does not actuate anything. A
camera count and an IoT occupancy count are different
measurements of the same zone; comparing them is a deliberate
design decision for a later phase, so what is stored here is
the raw observation and its evidence.
"""

import logging
from datetime import (
    datetime,
    timezone,
)
from typing import Any, Optional

from app.db.supabase import get_supabase
from app.schemas.vision import (
    VisionAnalysisResponse,
    VisionObservation,
    VisionObservationResponse,
)
from vision.config import (
    OBSERVATION_TYPE,
    OBSERVATION_UNIT,
)
from vision.detector import (
    VisionError,
    build_detector_from_settings,
)


logger = logging.getLogger(__name__)


TABLE = "vision_observations"

# How many rows the latest-observation lookup will consider.
# The query is ordered and sliced to one, so this only bounds
# the scan PostgREST performs.
MAX_LATEST_SCAN = 1


class ZoneNotFoundError(VisionError):
    """The supplied zone code does not exist."""


class VisionPersistenceError(VisionError):
    """The observation could not be written."""


class VisionService:
    """
    Stateless apart from its detector, which caches the
    loaded model between calls.
    """

    def __init__(self, detector: Any = None) -> None:
        self._detector = (
            detector
            if detector is not None
            else build_detector_from_settings()
        )

        # Count of writes skipped because an identical
        # observation was already stored. Exposed for
        # observability; it is not part of any API response.
        self.deduplicated = 0

    @property
    def detector(self) -> Any:
        return self._detector

    # --- zone resolution -----------------------------------------

    def resolve_zone(self, zone_code: str) -> dict:
        """
        Confirms the zone exists and returns its canonical row.

        The caller supplies a code, never an id. `zones.code` is
        globally unique, so one lookup resolves the zone
        unambiguously and there is no campus parameter for a
        caller to get wrong.

        Only the code is accepted. There is no zone-id path:
        a caller that does not know the code is expected to be
        told the zone does not exist rather than to have one
        guessed for it.

        Campus is not returned. `zones` has no `campus_id`
        column; it hangs off a floor, which hangs off a
        building, which hangs off a campus. Because
        `vision_observations.zone_code` is constrained to
        `zones(code)`, a stored observation can only name a
        zone that really exists, and its campus follows from
        that zone without being asserted by this service.
        """

        client = get_supabase()

        rows = (
            client.table("zones")
            .select("id,code,name,floor_id,capacity")
            .eq("code", zone_code)
            .limit(1)
            .execute()
            .data
        )

        if not rows:
            raise ZoneNotFoundError(
                f"Zone '{zone_code}' does not exist"
            )

        zone = rows[0]

        if zone.get("code") != zone_code:
            raise ZoneNotFoundError(
                f"Zone '{zone_code}' did not resolve to the "
                "requested zone"
            )

        logger.info(
            "Resolved vision zone %s -> %s",
            zone_code,
            zone.get("id"),
        )

        return zone

    # --- analysis -------------------------------------------------

    def analyze(
        self,
        camera_id: str,
        zone_code: str,
        image_bytes: bytes,
        declared_content_type: Optional[str] = None,
        observed_at: Optional[datetime] = None,
    ) -> VisionAnalysisResponse:
        """
        Analyses an uploaded image and stores the observation.

        Raises `ZoneNotFoundError` before any inference runs,
        so a bad zone costs one query rather than a model call.
        Raises `VisionPersistenceError` if the insert does not
        succeed; the caller must not be told it did.

        Passing `observed_at` opts into idempotent persistence:
        re-running the same observation for the same camera and
        zone at the same timestamp reuses the stored row instead
        of writing a duplicate. Omitting it uses a fresh
        server timestamp, which is always a new observation.
        """

        zone = self.resolve_zone(zone_code)

        result = self._detector.detect(
            image_bytes,
            declared_content_type=declared_content_type,
        )

        caller_supplied_time = observed_at is not None

        observed = observed_at or datetime.now(timezone.utc)

        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)

        observation = VisionObservation(
            camera_id=camera_id,
            zone_code=zone["code"],
            observation_type=OBSERVATION_TYPE,
            value=result.people_count,
            unit=OBSERVATION_UNIT,
            confidence=result.confidence,
            observed_at=observed,
            evidence=result.evidence,
        )

        stored = self._persist(
            observation,
            deduplicate=caller_supplied_time,
        )

        logger.info(
            "Stored vision observation %s: camera=%s "
            "zone=%s people=%d confidence=%.3f",
            stored.get("id") if isinstance(stored, dict)
            else "?",
            camera_id,
            zone["code"],
            result.people_count,
            result.confidence,
        )

        return VisionAnalysisResponse(
            camera_id=observation.camera_id,
            zone_code=observation.zone_code,
            people_count=observation.value,
            confidence=observation.confidence,
            observed_at=observation.observed_at,
            detections=[
                item
                for item in _detections_from_evidence(
                    observation.evidence
                )
            ],
        )

    # --- persistence ---------------------------------------------

    def _persist(
        self,
        observation: VisionObservation,
        deduplicate: bool = False,
    ) -> dict:
        """
        Writes the observation and returns the stored row.

        An empty result is a failure, not a success with no
        data: the caller is told persistence worked only when
        the database confirmed the row.

        When `deduplicate` is set, a row already stored for the
        same camera, zone and `observed_at` is returned instead
        of writing a second one. `vision_observations` has no
        natural key beyond its generated id, so this is the
        only identity the current schema supports, and it is
        offered only when the caller supplied `observed_at`
        itself. A server-generated timestamp is unique per call
        by construction, so checking for it would cost a query
        and never match.
        """

        if deduplicate:
            existing = self._find_existing(observation)

            if existing is not None:
                self.deduplicated += 1

                logger.info(
                    "Reused existing vision observation for "
                    "camera=%s zone=%s observed_at=%s",
                    observation.camera_id,
                    observation.zone_code,
                    observation.observed_at.isoformat(),
                )

                return existing

        row = {
            "camera_id": observation.camera_id,
            "zone_code": observation.zone_code,
            "observation_type": observation.observation_type,
            "value": observation.value,
            "unit": observation.unit,
            "confidence": observation.confidence,
            "observed_at": observation.observed_at.isoformat(),
            "evidence": observation.evidence,
        }

        try:
            inserted = (
                get_supabase()
                .table(TABLE)
                .insert(row)
                .execute()
                .data
            )
        except Exception as exc:
            # The driver error can carry the database host,
            # connection details or other infrastructure text.
            # It is logged here and kept as the exception cause,
            # and the message the caller receives is fixed.
            logger.exception(
                "Failed to store a vision observation for "
                "zone=%s camera=%s",
                observation.zone_code,
                observation.camera_id,
            )

            raise VisionPersistenceError(
                "Failed to store the vision observation"
            ) from exc

        if not inserted:
            raise VisionPersistenceError(
                "The vision observation was not stored"
            )

        return inserted[0]

    def _find_existing(
        self,
        observation: VisionObservation,
    ) -> Optional[dict]:
        """
        Returns a previously stored row matching this
        observation's identity, or None.

        A read failure here is not fatal: the write is
        attempted anyway and the database remains the
        authority. Swallowing the error only forgoes the
        optimisation, it never fabricates or drops an
        observation.
        """

        try:
            rows = (
                get_supabase()
                .table(TABLE)
                .select("*")
                .eq("camera_id", observation.camera_id)
                .eq("zone_code", observation.zone_code)
                .eq(
                    "observed_at",
                    observation.observed_at.isoformat(),
                )
                .order("id", desc=True)
                .limit(1)
                .execute()
                .data
            )
        except Exception:
            logger.warning(
                "Vision duplicate check failed; writing "
                "without it",
                exc_info=True,
            )

            return None

        return rows[0] if rows else None

    # --- retrieval -------------------------------------------------

    def latest_for_zone(
        self,
        zone_code: str,
    ) -> Optional[VisionObservationResponse]:
        """
        Returns the newest stored observation for a zone.

        Ordered by `observed_at` descending with `id` as the
        tie-breaker, so two rows sharing a timestamp resolve to
        the same answer every time. Inference is never rerun
        here: this returns what was stored, which may be
        arbitrarily old.
        """

        self.resolve_zone(zone_code)

        rows = (
            get_supabase()
            .table(TABLE)
            .select("*")
            .eq("zone_code", zone_code)
            .order("observed_at", desc=True)
            .order("id", desc=True)
            .limit(MAX_LATEST_SCAN)
            .execute()
            .data
        )

        if not rows:
            return None

        row = rows[0]

        return VisionObservationResponse(
            id=str(row.get("id")),
            camera_id=str(row.get("camera_id")),
            zone_code=str(row.get("zone_code")),
            observation_type=str(
                row.get("observation_type")
            ),
            value=int(row.get("value") or 0),
            unit=str(row.get("unit")),
            confidence=float(
                row.get("confidence") or 0.0
            ),
            observed_at=row.get("observed_at"),
            evidence=row.get("evidence"),
            created_at=row.get("created_at"),
        )

    def is_available(self) -> bool:
        """Whether inference could run in this deployment."""

        return bool(self._detector.is_available())


def _detections_from_evidence(
    evidence: list,
) -> list:
    """
    Rebuilds response detections from stored evidence so the
    analyze response and the stored row cannot disagree.
    """

    from app.schemas.vision import (
        BoundingBox,
        PersonDetection,
    )

    detections = []

    for item in evidence or []:
        if not isinstance(item, dict):
            continue

        bbox = item.get("bbox")

        if not isinstance(bbox, dict):
            continue

        try:
            detections.append(
                PersonDetection(
                    label=str(
                        item.get("label") or "person"
                    ),
                    confidence=float(item["confidence"]),
                    bbox=BoundingBox(
                        x1=float(bbox["x1"]),
                        y1=float(bbox["y1"]),
                        x2=float(bbox["x2"]),
                        y2=float(bbox["y2"]),
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return detections


vision_service = VisionService()