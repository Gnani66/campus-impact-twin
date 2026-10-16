"""
Digital twin service (Phase 12).

Assembles the 3D view's view of the campus from data this project
already stores. It writes nothing and owns no state.

The important behaviour is what it refuses to do. It does not
invent a metric this deployment cannot measure, and it does not
paint a zone green when the readings behind that green are stale.
A twin that is confidently wrong is more damaging than one that
is visibly incomplete, because the whole point is to let somebody
trust the picture.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.twin_rules import (
    DEFAULT_TWIN_THRESHOLDS,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_OFFLINE,
    STATUS_WARNING,
    determine_status,
    entity_id_for_code,
    occupancy_ratio,
    reconcile_status_with_incidents,
    status_reasons,
)
from app.repositories.digital_twin_repository import (
    DigitalTwinRepository,
)
from app.schemas.digital_twin import (
    TwinEntity,
    TwinMetrics,
    TwinSnapshot,
)


logger = logging.getLogger(__name__)


def _parse(value) -> Optional[datetime]:
    if not value:
        return None

    text = str(value)

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


class DigitalTwinService:
    """
    Builds a campus snapshot for the 3D view.
    """

    def __init__(
        self,
        repository: Optional[DigitalTwinRepository] = None,
        thresholds=DEFAULT_TWIN_THRESHOLDS,
    ):
        self.repository = repository or DigitalTwinRepository()
        self.thresholds = thresholds

    # ------------------------------------------------------

    def snapshot(
        self,
        campus_code: Optional[str] = None,
    ) -> TwinSnapshot:
        now = datetime.now(timezone.utc)

        zones = self.repository.zones(campus_code)

        entities = self._entities_for(zones, now)

        counts: Dict[str, int] = {
            STATUS_NORMAL: 0,
            STATUS_WARNING: 0,
            STATUS_CRITICAL: 0,
            STATUS_OFFLINE: 0,
        }

        for entity in entities:
            counts[entity.status] = (
                counts.get(entity.status, 0) + 1
            )

        logger.info(
            "Digital twin snapshot: %d entities (%d critical, "
            "%d warning, %d offline)",
            len(entities),
            counts.get(STATUS_CRITICAL, 0),
            counts.get(STATUS_WARNING, 0),
            counts.get(STATUS_OFFLINE, 0),
        )

        return TwinSnapshot(
            timestamp=now,
            entities=entities,
            counts=counts,
        )

    def entity(
        self, entity_id: str
    ) -> Optional[TwinEntity]:
        """
        One entity by its twin id or its zone code.

        Both accepted so a client can use whichever identifier it
        holds, and so a URL pasted by a person works.
        """

        snapshot = self.snapshot()

        for entity in snapshot.entities:
            if entity.id == entity_id:
                return entity

        for entity in snapshot.entities:
            if entity.code.upper() == entity_id.upper():
                return entity

        return None

    # ------------------------------------------------------
    # Assembly
    # ------------------------------------------------------

    def _entities_for(
        self,
        zones: List[Dict[str, Any]],
        now: datetime,
    ) -> List[TwinEntity]:
        if not zones:
            return []

        zone_ids = [
            str(zone["id"]) for zone in zones if zone.get("id")
        ]

        telemetry = self.repository.latest_by_metric(zone_ids)
        incidents = self.repository.open_incidents(zone_ids)
        approvals = self.repository.pending_approval_count(zone_ids)

        return [
            self._entity_for(zone, telemetry, incidents, approvals, now)
            for zone in zones
        ]

    def _entity_for(
        self,
        zone: Dict[str, Any],
        telemetry: Dict[str, Dict[str, Dict[str, Any]]],
        incidents: Dict[str, List[Dict[str, Any]]],
        approvals: Dict[str, int],
        now: datetime,
    ) -> TwinEntity:
        zone_id = str(zone.get("id"))
        code = zone.get("code") or ""

        readings = telemetry.get(zone_id, {})

        capacity = zone.get("capacity")

        metrics = self._metrics(readings, capacity)

        # Populated here rather than in `_metrics`, because the
        # ratio is a derived judgement rather than a reading:
        # it needs capacity, which the metrics mapper does not
        # otherwise reason about.
        metrics.occupancy_ratio = ratio_value = occupancy_ratio(
            metrics.occupancy, metrics.capacity
        )

        # Offline is decided on the newest reading of any metric,
        # not on each metric separately: a zone whose sensors all
        # died together is one offline zone, and colouring half
        # its dimensions grey would be misleading.
        observed_at = self._newest_timestamp(readings)

        offline = (
            observed_at is None
            or (now - observed_at).total_seconds()
            > self.thresholds.telemetry_offline_after_seconds
        )

        ratio = ratio_value

        status = determine_status(
            temperature=metrics.temperature,
            humidity=metrics.humidity,
            aqi=metrics.aqi,
            co2_ppm=metrics.eco2,
            occupancy_ratio_value=ratio,
            sound=metrics.sound,
            offline=offline,
            thresholds=self.thresholds,
        )

        reasons = (
            ["Telemetry is stale or absent, so no live reading "
             "is available."]
            if offline
            else status_reasons(
                temperature=metrics.temperature,
                humidity=metrics.humidity,
                aqi=metrics.aqi,
                co2_ppm=metrics.eco2,
                occupancy_ratio_value=ratio,
                sound=metrics.sound,
                thresholds=self.thresholds,
            )
        )

        correlation = self.repository.latest_correlation(code)

        zone_incidents = incidents.get(zone_id, [])

        # The status above came from readings alone, which cannot
        # see an incident. Reconciled here, where both facts exist:
        # a zone with an open critical incident must not present as
        # normal beside a list of critical issues.
        status, incident_reasons = (
            reconcile_status_with_incidents(
                status, zone_incidents
            )
        )

        if incident_reasons:
            reasons = list(reasons) + incident_reasons

        return TwinEntity(
            id=entity_id_for_code(code),
            zone_id=zone_id,
            code=code,
            name=zone.get("name") or code,
            type=zone.get("zone_type") or "other",
            status=status,
            metrics=metrics,
            reasons=reasons,
            active_issues=self._issues(
                zone_incidents, correlation
            ),
            open_incident_count=len(zone_incidents),
            correlation_run_id=(
                correlation.get("id") if correlation else None
            ),
            correlation_status=(
                correlation.get("result_status")
                if correlation
                else None
            ),
            root_cause=(
                correlation.get("root_cause")
                if correlation
                else None
            ),
            pending_approvals=approvals.get(zone_id, 0),
            model_object=zone.get("twin_model_object"),
            position=self._position(zone),
            scale=self._scale(zone),
            latitude=(zone.get("latitude")
                      if "latitude" in zone else None),
            observed_at=(
                observed_at.isoformat() if observed_at else None
            ),
            metadata=(
                zone.get("metadata")
                if isinstance(zone.get("metadata"), dict)
                else {}
            ),
        )

    # ------------------------------------------------------
    # Mapping
    # ------------------------------------------------------

    @staticmethod
    def _metrics(
        readings: Dict[str, Dict[str, Any]],
        capacity: Optional[int],
    ) -> TwinMetrics:
        """
        Map stored readings onto the twin contract.

        Metrics this deployment does not measure stay None. The
        stored `co2` reading in ppm is what the contract calls
        `eco2`; the two names are recorded here so the rename is
        visible rather than looking like a different quantity.
        """

        def value(metric: str) -> Optional[float]:
            row = readings.get(metric)

            if not row:
                return None

            return row.get("value")

        return TwinMetrics(
            temperature=value("temperature"),
            humidity=value("humidity"),
            pressure=None,
            aqi=None,
            tvoc=None,
            eco2=value("co2"),
            light=None,
            sound=None,
            uv=None,
            occupancy=value("occupancy"),
            occupancy_ratio=None,
            energy=value("energy"),
            capacity=capacity,
        )

    @staticmethod
    def _newest_timestamp(
        readings: Dict[str, Dict[str, Any]]
    ) -> Optional[datetime]:
        newest = None

        for row in readings.values():
            moment = _parse(row.get("timestamp"))

            if moment and (newest is None or moment > newest):
                newest = moment

        return newest

    @staticmethod
    def _issues(
        incidents: List[Dict[str, Any]],
        correlation: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        What a reader should be told is wrong.

        Drawn from the same incident and correlation records the
        operational engine raised, so clicking a marker explains
        itself with the official finding rather than a second
        narrative that could drift from it.
        """

        issues: List[str] = []

        for incident in incidents[:3]:
            title = incident.get("title") or "Open incident"

            severity = incident.get("severity")

            issues.append(
                f"{title} ({severity})"
                if severity
                else title
            )

        root_cause = (
            correlation.get("root_cause")
            if correlation
            else None
        )

        if root_cause and root_cause not in issues:
            issues.append(root_cause)

        return issues

    @staticmethod
    def _position(
        zone: Dict[str, Any]
    ) -> Optional[List[float]]:
        """
        An explicit 3D placement, when the database supplies one.

        Read from metadata rather than a hardcoded frontend table
        so that placing a new zone is a data change, not a code
        change. Absent is normal: the frontend falls back to
        deriving a position from the model's bounding box, which
        is more robust than coordinates chosen by eye.
        """

        metadata = zone.get("metadata")

        if not isinstance(metadata, dict):
            return None

        position = metadata.get("twin_position")

        if (
            isinstance(position, list)
            and len(position) == 3
            and all(
                isinstance(v, (int, float)) for v in position
            )
        ):
            return [float(v) for v in position]

        return None

    @staticmethod
    def _scale(zone: Dict[str, Any]) -> Optional[float]:
        metadata = zone.get("metadata")

        if not isinstance(metadata, dict):
            return None

        scale = metadata.get("twin_scale")

        try:
            return float(scale) if scale is not None else None
        except (TypeError, ValueError):
            return None


digital_twin_service = DigitalTwinService()