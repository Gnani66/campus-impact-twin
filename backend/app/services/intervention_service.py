"""
Intervention service (Phase 9).

Loads the library, filters it to what the evidence actually
supports, and returns the options worth considering.

This service deliberately does not rank. Ranking is Phase 10's
job, and keeping the two apart is what makes it possible to say
an option was *refused* rather than merely out-ranked. The
difference matters when someone asks why the expensive
intervention never appeared.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.intervention_rules import (
    DEFAULT_INTERVENTION_CONFIG,
    check_evidence_eligibility,
    evidence_quality_for,
    quality_meets,
)
from app.models.intervention import Intervention
from app.repositories.intervention_repository import (
    list_interventions,
)


logger = logging.getLogger(__name__)


class InterventionService:
    """
    Offers the interventions a zone's evidence supports.
    """

    def __init__(
        self, config=DEFAULT_INTERVENTION_CONFIG
    ):
        self.config = config

    def available(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        names: Optional[List[str]] = None,
        eligible_only: bool = True,
    ) -> List[Intervention]:
        """
        The library, filtered.

        `eligible_only` defaults to True so an intervention an
        operator has retired cannot be offered by a code path
        that forgot to check the status enum. Callers that need
        to show retired rows pass False.
        """

        library = list_interventions(
            domain=domain,
            status="eligible" if eligible_only else status,
            names=names,
        )

        if not eligible_only:
            library = [
                item for item in library if item.enabled
            ] or library

        return library

    def eligible(
        self,
        interventions: List[Intervention],
        evidence_score: Optional[float],
    ) -> Dict[str, Any]:
        """
        Splits the library by whether the evidence supports it.

        Refused interventions are returned rather than dropped.
        A shortlist that hides what it rejected gives the reader
        no way to tell an oversight from a judgement.
        """

        permitted: List[Intervention] = []
        refused: Dict[str, List[str]] = {}

        quality = evidence_quality_for(evidence_score)

        for intervention in interventions:
            result = check_evidence_eligibility(
                evidence_score,
                intervention.minimum_evidence_quality,
            )

            if result.eligible:
                permitted.append(intervention)
            else:
                refused[intervention.code] = result.reasons

        if refused:
            logger.info(
                "%d of %d interventions were refused; evidence "
                "scores %s (%s)",
                len(refused),
                len(interventions),
                evidence_score,
                quality,
            )

        return {
            "permitted": permitted,
            "refused": refused,
            "evidence_quality": quality,
        }

    def for_zone(
        self,
        zone_code: str,
        evidence_score: Optional[float],
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        What may be offered for a zone, and what may not.
        """

        library = self.available(domain=domain)

        split = self.eligible(library, evidence_score)

        return {
            "zone_code": zone_code,
            "evidence_score": evidence_score,
            "evidence_quality": split["evidence_quality"],
            "permitted": split["permitted"],
            "refused": split["refused"],
        }


intervention_service = InterventionService()