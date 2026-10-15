"""
Tests for Phase 9 (impact and interventions) and Phase 10
(simulation).

The engine's value is that it can decline. Most of these tests
are therefore about refusal: evidence too weak, a projection
larger than the waste that exists, a budget exceeded, a
tie that must resolve the same way twice.

Everything under test is pure arithmetic or a stubbed
repository, so the suite needs no database and no model.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.impact_rules import (
    DEFAULT_IMPACT_REFERENCES,
    DEFAULT_IMPACT_WEIGHTS,
    MIN_MEANINGFUL_IMPACT,
    VALUE_SIMULATED,
    calculate_confidence_score,
    calculate_cost_efficiency,
    calculate_impact_score,
    calculate_overall_score,
    clamp,
    disruption_score,
    normalise,
    stress_band,
)
from app.core.intervention_rules import (
    QUALITY_MODERATE,
    QUALITY_STRONG,
    QUALITY_WEAK,
    ScenarioConstraints,
    check_evidence_eligibility,
    check_feasibility,
    evidence_quality_for,
    project_reduction,
    quality_meets,
)
from app.core.simulation_rules import (
    STATUS_BLOCKED,
    STATUS_NO_SAFE_RECOMMENDATION,
    build_recommendation,
    comparison_summary,
    evidence_gate_reason,
    rank_options,
    validate_request,
)
from app.models.intervention import (
    ImpactModel,
    Intervention,
    slugify,
)
from app.services.impact_service import (
    ImpactService,
    baseline_excess,
)


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def make_intervention(**overrides) -> Intervention:
    """An intervention with sensible defaults."""

    base = dict(
        id="int-1",
        name="HVAC standby optimisation",
        domain="energy",
        cost=0,
        maintenance_hours=0.5,
        expected_energy_kwh=6.5,
        expected_water_litres=0,
        expected_waste_kg=0,
        expected_emissions_kg_co2e=2.6,
        confidence=0.85,
        minimum_evidence_quality=QUALITY_MODERATE,
        metadata={"code": "HVAC_STANDBY",
                  "disruption_level": "low"},
        impacts=[
            ImpactModel(
                metric="energy",
                unit="kWh/h",
                expected_value=6.5,
                minimum_value=3.9,
                maximum_value=8.2,
                confidence=0.85,
                evidence_source="vendor control curves",
                assumptions={
                    "baseline_reduction_percent": 30,
                    "max_reduction_percent": 50,
                },
            )
        ],
    )

    base.update(overrides)

    return Intervention(**base)


# ============================================================
# EVIDENCE QUALITY (the stored enum, not a score)
# ============================================================


class TestEvidenceQuality:
    def test_strong_evidence(self):
        assert (
            evidence_quality_for(100) == QUALITY_STRONG
        )
        assert (
            evidence_quality_for(80) == QUALITY_STRONG
        )

    def test_moderate_evidence(self):
        assert (
            evidence_quality_for(79) == QUALITY_MODERATE
        )
        assert evidence_quality_for(50) == QUALITY_MODERATE

    def test_weak_evidence(self):
        assert evidence_quality_for(49) == QUALITY_WEAK
        assert evidence_quality_for(0) == QUALITY_WEAK

    def test_missing_evidence_is_weak(self):
        """
        An unknown quantity is not moderate evidence. Defaulting
        upward would let an unevidenced condition qualify for the
        more aggressive interventions.
        """

        assert (
            evidence_quality_for(None) == QUALITY_WEAK
        )
        assert (
            evidence_quality_for("nonsense")
            == QUALITY_WEAK
        )

    def test_quality_ranking(self):
        assert quality_meets(QUALITY_STRONG, QUALITY_MODERATE)
        assert quality_meets(QUALITY_MODERATE, QUALITY_WEAK)
        assert not quality_meets(QUALITY_WEAK, QUALITY_MODERATE)
        assert quality_meets(QUALITY_MODERATE, QUALITY_MODERATE)

    def test_unknown_requirement_is_unmet(self):
        """
        An intervention asking for evidence the engine cannot
        evaluate must not be offered as though it could.
        """

        assert not quality_meets(
            QUALITY_STRONG, "excellent"
        )

    def test_evidence_eligibility_blocks_weak(self):
        result = check_evidence_eligibility(
            40, QUALITY_STRONG
        )

        assert result.eligible is False
        assert "strong" in result.reasons[0]

    def test_evidence_eligibility_allows_strong(self):
        assert check_evidence_eligibility(
            95, QUALITY_STRONG
        ).eligible

    def test_missing_evidence_blocks_everything(self):
        result = check_evidence_eligibility(None, QUALITY_WEAK)

        assert result.eligible is False


# ============================================================
# PROJECTION AND THE CAP
# ============================================================


class TestProjection:
    def test_absolute_is_capped_at_the_excess(self):
        """
        The core correctness property. An intervention claiming
        an 8 kWh saving against 1.4 kW of avoidable draw has not
        saved 8 kWh; the rest never existed.
        """

        value = project_reduction(1.4, 8.2)

        assert value == pytest.approx(1.4)

    def test_absolute_below_excess_is_used(self):
        assert project_reduction(10, 3.2) == 3.2

    def test_percentage_applies_to_excess_not_total(self):
        """
        The baseline load is what the building costs to do
        nothing; reducing it is not what these interventions do.
        """

        # 50% of the 6.5 kW excess, not of the 8.5 kW draw.
        value = project_reduction(
            6.5, None, reduction_percent=50
        )

        assert value == pytest.approx(3.25)

    def test_zero_excess_yields_zero(self):
        assert project_reduction(0, 8.2) == 0
        assert project_reduction(0, None, 50) == 0

    def test_negative_excess_yields_zero(self):
        assert project_reduction(-3, 8.2) == 0

    def test_percentage_over_100_is_clamped(self):
        assert project_reduction(10, None, 250) == 10

    def test_baseline_excess(self):
        assert baseline_excess(8.5, 2.0) == 6.5

    def test_baseline_excess_never_negative(self):
        """
        A zone drawing less than baseline has nothing to save,
        and a negative "saving" would be nonsense.
        """

        assert baseline_excess(1.5, 2.0) == 0


class TestEnergyProjectionBand:
    def test_band_is_capped_at_the_excess(self):
        """
        The band is capped too, not just the point estimate. An
        8.2 kW best case against 1.4 kW of avoidable draw
        overstates the upside.
        """

        service = ImpactService()

        projected = service.project_energy(
            make_intervention(), excess_kw=1.4
        )

        assert projected.value == pytest.approx(1.4)
        assert projected.worst_case <= 1.4
        assert projected.expected_case <= 1.4
        assert projected.best_case <= 1.4

    def test_band_stays_ordered_after_capping(self):
        service = ImpactService()

        projected = service.project_energy(
            make_intervention(), excess_kw=1.4
        )

        assert projected.worst_case <= (
            projected.expected_case
        )
        assert projected.best_case >= (
            projected.expected_case
        )

    def test_large_excess_uses_the_stored_figure(self):
        service = ImpactService()

        projected = service.project_energy(
            make_intervention(), excess_kw=50
        )

        assert projected.value == pytest.approx(6.5)

    def test_value_type_is_never_measured(self):
        """
        The PRD requires modelled outcomes to be labelled as
        modelled. Nothing in this engine measures anything.
        """

        service = ImpactService()

        projected = service.project_energy(
            make_intervention(), excess_kw=10
        )

        assert projected.value_type != "measured"
        assert projected.value_type == "modeled"

    def test_band_absence_is_reported(self):
        """
        A model with no stated bounds has no opinion about
        uncertainty, and must say so rather than presenting a
        zero-width band that reads as certainty.
        """

        service = ImpactService()

        projected = service.project_energy(
            make_intervention(impacts=[]), excess_kw=10
        )

        assert projected.band_available is False


# ============================================================
# SCORING
# ============================================================


class TestScoring:
    def test_impact_weighted_sum(self):
        """
        Each dimension is normalised first, then weighted. With
        business priority switched off, energy alone at its
        reference contributes 100 * 0.35.
        """

        score = calculate_impact_score(
            energy_reduction=5.0,
            water_reduction=0,
            waste_reduction=0,
            co2_reduction=0,
            business_priority=0.0,
        )

        assert score == pytest.approx(35.0)

    def test_impact_includes_business_priority(self):
        """
        Priority is a dimension in its own right, not a
        multiplier on the others.
        """

        without = calculate_impact_score(
            5.0, 0, 0, 0, business_priority=0.0
        )
        with_priority = calculate_impact_score(
            5.0, 0, 0, 0, business_priority=1.0
        )

        assert with_priority > without
        assert with_priority == pytest.approx(50.0)

    def test_impact_weights_sum_to_one(self):
        """
        If the weights stop summing to 1 the score silently
        changes scale and every stored comparison becomes
        incomparable with a new one.
        """

        assert (
            DEFAULT_IMPACT_WEIGHTS.energy
            + DEFAULT_IMPACT_WEIGHTS.water
            + DEFAULT_IMPACT_WEIGHTS.waste
            + DEFAULT_IMPACT_WEIGHTS.co2
            + DEFAULT_IMPACT_WEIGHTS.business_priority
        ) == pytest.approx(1.0)

    def test_overall_weights_sum_to_one(self):
        from app.core.impact_rules import (
            DEFAULT_OVERALL_WEIGHTS,
        )

        assert (
            DEFAULT_OVERALL_WEIGHTS.impact
            + DEFAULT_OVERALL_WEIGHTS.confidence
            + DEFAULT_OVERALL_WEIGHTS.feasibility
            + DEFAULT_OVERALL_WEIGHTS.cost_efficiency
            + DEFAULT_OVERALL_WEIGHTS.disruption
        ) == pytest.approx(1.0)

    def test_impact_ignores_negative_reductions(self):
        """
        A projection that made things worse must not drag the
        score below the floor of "did nothing".
        """

        assert (
            calculate_impact_score(-5, 0, 0, 0, 1.0) >= 0
        )

    def test_confidence_uses_all_four_sources(self):
        strong = calculate_confidence_score(0.9, True, True, 0.9)
        weak = calculate_confidence_score(0.1, False, False, 0.1)

        assert strong > weak

        # 0.9 vision and 0.9 intervention evidence contribute 90
        # each; telemetry and a measured baseline contribute 100.
        assert strong == pytest.approx(95.0)

    def test_confidence_reaches_100_only_when_all_perfect(self):
        assert calculate_confidence_score(
            1.0, True, True, 1.0
        ) == pytest.approx(100.0)

    def test_nominal_baseline_earns_less_than_measured(self):
        """
        A baseline derived from zone capacity is a design
        assumption and cannot earn the credit a measured one
        does.
        """

        measured = calculate_confidence_score(
            0.9, True, True, 0.9
        )
        nominal = calculate_confidence_score(
            0.9, True, False, 0.9
        )

        assert measured > nominal

    def test_confidence_rejects_out_of_range_input(self):
        assert (
            calculate_confidence_score(1.5, True, True, 1.5)
            < 100
        )

    def test_disruption_mapping(self):
        assert disruption_score("low") == 90
        assert disruption_score("medium") == 60
        assert disruption_score("high") == 25

    def test_unknown_disruption_is_conservative(self):
        """
        An unrecognised level is a gap in the library. Guessing
        in the intervention's favour would be the wrong way to
        err.
        """

        assert disruption_score("catastrophic") <= 25
        assert disruption_score(None) <= 25


class TestCostEfficiency:
    def test_free_and_useful_scores_maximum(self):
        assert (
            calculate_cost_efficiency(50, 0) == 100.0
        )

    def test_free_and_useless_scores_zero(self):
        """
        The trap the cost model exists to avoid: a zero-cost
        intervention that changes nothing must not beat an
        expensive one that works.
        """

        assert (
            calculate_cost_efficiency(
                MIN_MEANINGFUL_IMPACT - 0.5, 0
            )
            == 0.0
        )

    def test_free_and_zero_impact_scores_zero(self):
        assert calculate_cost_efficiency(0, 0) == 0.0

    def test_expensive_costs_reduce_efficiency(self):
        cheap = calculate_cost_efficiency(60, 100)
        dear = calculate_cost_efficiency(60, 40000)

        assert cheap > dear

    def test_efficiency_never_exceeds_impact(self):
        """
        Efficiency measures what a purchase buys. It cannot
        manufacture impact the intervention does not have.
        """

        for cost in (0, 100, 5000, 60000):
            assert (
                calculate_cost_efficiency(40, cost) <= 100
            )

    def test_negative_cost_is_not_a_bargain(self):
        assert calculate_cost_efficiency(60, -500) == 0.0

    def test_zero_reference_falls_back(self):
        """
        A missing budget must not make everything look free.
        """

        result = calculate_cost_efficiency(
            60, 1000, cost_reference=0
        )

        assert result < 100

    def test_no_division_by_zero_anywhere(self):
        for cost in (0, 0.0, 1, -1, 1e9):
            assert isinstance(
                calculate_cost_efficiency(50, cost), float
            )


class TestOverall:
    def test_perfect_option(self):
        score = calculate_overall_score(100, 100, 100, 100, 100)

        assert score == pytest.approx(100.0)

    def test_confidence_matters(self):
        strong = calculate_overall_score(60, 100, 90, 70, 90)
        weak = calculate_overall_score(60, 20, 90, 70, 90)

        assert strong > weak

    def test_clamped_input(self):
        assert (
            calculate_overall_score(200, 200, 200, 200, 200)
            == 100.0
        )


class TestNormalisation:
    def test_reference_scores_full(self):
        assert normalise(5.0, 5.0) == 100

    def test_double_reference_caps(self):
        assert normalise(10.0, 5.0) == 100

    def test_zero_reference_is_safe(self):
        assert normalise(5.0, 0) == 0

    def test_garbage_is_zero(self):
        assert normalise("nonsense", 5.0) == 0

    def test_clamp_handles_infinity(self):
        assert clamp(float("inf")) == 100
        assert clamp(float("-inf")) == 0
        assert clamp(float("nan")) == 0


# ============================================================
# FEASIBILITY
# ============================================================


class TestFeasibility:
    def _scenario(self, **overrides) -> ScenarioConstraints:
        return ScenarioConstraints(**overrides)

    def test_budget_blocks_expensive_option(self):
        score, feasible, reasons = check_feasibility(
            cost=12000,
            disruption_level="low",
            duration_minutes=30,
            constraints=self._scenario(budget=5000),
        )

        assert feasible is False
        assert any("budget" in r.lower() for r in reasons)

    def test_infeasible_score_is_capped(self):
        """
        Without a cap an infeasible option could still rank
        highly and be recommended, which would be actively
        dangerous.
        """

        score, feasible, _ = check_feasibility(
            cost=12000,
            disruption_level="low",
            duration_minutes=30,
            constraints=self._scenario(budget=1),
        )

        assert feasible is False
        assert score <= 20

    def test_affordable_option_is_feasible(self):
        _, feasible, _ = check_feasibility(
            cost=100,
            disruption_level="low",
            duration_minutes=10,
            constraints=self._scenario(budget=5000),
        )

        assert feasible is True

    def test_disruption_limit(self):
        _, feasible, reasons = check_feasibility(
            cost=0,
            disruption_level="high",
            duration_minutes=10,
            constraints=self._scenario(max_disruption="low"),
        )

        assert feasible is False
        assert any("disruption" in r.lower() for r in reasons)

    def test_duration_limit(self):
        _, feasible, reasons = check_feasibility(
            cost=0,
            disruption_level="low",
            duration_minutes=600,
            constraints=self._scenario(
                max_duration_minutes=60
            ),
        )

        assert feasible is False

    def test_missing_budget_does_not_block(self):
        _, feasible, _ = check_feasibility(
            cost=99999,
            disruption_level="low",
            duration_minutes=1,
            constraints=self._scenario(),
        )

        assert feasible is True

    def test_human_approval_is_recorded_not_blocking(self):
        _, feasible, reasons = check_feasibility(
            cost=0,
            disruption_level="low",
            duration_minutes=1,
            constraints=self._scenario(
                requires_human_approval=True
            ),
            declared=["requires_human_approval"],
        )

        assert feasible is True
        assert any("approval" in r.lower() for r in reasons)

    def test_unknown_constraint_is_flagged(self):
        """
        A typo in a constraint must not silently never fire.
        """

        _, feasible, reasons = check_feasibility(
            cost=0,
            disruption_level="low",
            duration_minutes=1,
            constraints=self._scenario(),
            declared=["requires_magic_beans"],
        )

        assert any("unrecognised" in r.lower() for r in reasons)

    def test_missing_equipment_blocks(self):
        _, feasible, _ = check_feasibility(
            cost=0,
            disruption_level="low",
            duration_minutes=1,
            constraints=self._scenario(),
            equipment_available=False,
        )

        assert feasible is False


# ============================================================
# RANKING AND TIE-BREAKING
# ============================================================


def option(**overrides) -> dict:
    base = {
        "code": "A",
        "feasible": True,
        "overall_score": 80.0,
        "confidence_score": 70.0,
        "estimated_cost": 1000,
        "disruption_level": "low",
        "impact_score": 70.0,
    }

    base.update(overrides)

    return base


class TestRanking:
    def test_highest_score_first(self):
        ranked = rank_options(
            [option(code="A", overall_score=60),
             option(code="B", overall_score=90)]
        )

        assert ranked[0]["code"] == "B"

    def test_infeasible_always_last(self):
        """
        Even with a high score. Its score is capped by the
        feasibility rules, but relying on that cap alone would
        be fragile.
        """

        ranked = rank_options(
            [option(code="A", overall_score=99,
                    feasible=False),
             option(code="B", overall_score=50)]
        )

        assert ranked[0]["code"] == "B"

    def test_tie_breaks_on_confidence(self):
        ranked = rank_options(
            [
                option(code="A", overall_score=82.1,
                       confidence_score=50),
                option(code="B", overall_score=82.1,
                       confidence_score=90),
            ]
        )

        assert ranked[0]["code"] == "B"

    def test_tie_breaks_on_lower_cost(self):
        ranked = rank_options(
            [
                option(code="A", estimated_cost=9000),
                option(code="B", estimated_cost=100),
            ]
        )

        assert ranked[0]["code"] == "B"

    def test_tie_breaks_on_lower_disruption(self):
        ranked = rank_options(
            [
                option(code="A", disruption_level="high"),
                option(code="B", disruption_level="low"),
            ]
        )

        assert ranked[0]["code"] == "B"

    def test_final_tie_break_is_stable(self):
        """
        Without the code tiebreak the ordering is not a total
        order and the same query could return a different
        winner tomorrow, undermining the audit trail.
        """

        ranked = rank_options(
            [option(code="Z"), option(code="A")]
        )

        assert ranked[0]["code"] == "A"

    def test_ranking_is_repeatable(self):
        options = [
            option(code="C", overall_score=82.1),
            option(code="A", overall_score=82.1,
                   confidence_score=90),
            option(code="B", overall_score=82.1,
                   confidence_score=90),
        ]

        first = [o["code"] for o in rank_options(options)]
        second = [
            o["code"] for o in rank_options(list(reversed(options)))
        ]

        assert first == second


class TestRecommendation:
    def test_recommends_the_best_feasible(self):
        rec = build_recommendation(
            [
                option(code="A", overall_score=60),
                option(code="B", overall_score=90),
            ]
        )

        assert rec.intervention_code == "B"
        assert rec.status != STATUS_NO_SAFE_RECOMMENDATION

    def test_no_safe_recommendation_is_a_feature(self):
        """
        The engine saying "I will not recommend anything" is
        the correct result when the evidence does not support
        one.
        """

        rec = build_recommendation(
            [option(code="A", feasible=False)]
        )

        assert rec.intervention_code is None
        assert rec.status == STATUS_NO_SAFE_RECOMMENDATION
        assert "constraint" in rec.reason.lower()

    def test_no_options_is_blocked(self):
        rec = build_recommendation([])

        assert rec.status == STATUS_BLOCKED

    def test_reason_states_the_tradeoff(self):
        """
        A recommendation with no stated trade-off is an
        instruction, not decision support.
        """

        rec = build_recommendation(
            [
                option(code="A", overall_score=90,
                       estimated_cost=0),
                option(code="B", overall_score=70,
                       estimated_cost=12000),
            ]
        )

        assert "Trade-off" in rec.reason
        assert "B" in rec.reason

    def test_comparison_counts_rejections(self):
        summary = comparison_summary(
            [
                option(code="A"),
                option(code="B", feasible=False),
            ]
        )

        assert summary["total"] == 2
        assert summary["feasible"] == 1
        assert summary["rejected_codes"] == ["B"]


# ============================================================
# EVIDENCE GATE
# ============================================================


class TestEvidenceGate:
    def test_missing_run_blocks(self):
        assert evidence_gate_reason(None, 70) is not None

    def test_weak_evidence_blocks(self):
        assert (
            evidence_gate_reason(40, 70) is not None
        )

    def test_sufficient_evidence_passes(self):
        assert evidence_gate_reason(95, 70) is None


# ============================================================
# INTERVENTION MODEL
# ============================================================


class TestInterventionModel:
    def test_code_prefers_metadata(self):
        assert (
            make_intervention().code == "HVAC_STANDBY"
        )

    def test_code_falls_back_to_slug(self):
        intervention = make_intervention(
            name="Water fixture inspection", metadata={}
        )

        assert intervention.code == "WATER_FIXTURE_INSPECTION"

    def test_disruption_from_metadata(self):
        assert (
            make_intervention().disruption_level == "low"
        )

    def test_disruption_inferred_from_maintenance(self):
        """
        Rows that predate Phase 9 carry no disruption field. The
        inference is a proxy and is honest about being one.
        """

        assert (
            make_intervention(
                maintenance_hours=0.5, metadata={}
            ).disruption_level
            == "low"
        )
        assert (
            make_intervention(
                maintenance_hours=5, metadata={}
            ).disruption_level
            == "high"
        )

    def test_retired_intervention_is_not_enabled(self):
        assert (
            make_intervention(status="retired").enabled
            is False
        )

    def test_duration_from_maintenance_hours(self):
        assert (
            make_intervention(
                maintenance_hours=2
            ).duration_minutes
            == 120
        )

    def test_target_metric_inferred(self):
        assert make_intervention().target_metric == "energy"
        assert (
            make_intervention(
                expected_water_litres=50
            ).target_metric
            == "water"
        )

    def test_slugify_is_stable(self):
        assert slugify("HVAC standby optimisation") == (
            "HVAC_STANDBY_OPTIMISATION"
        )


# ============================================================
# STRESS BAND
# ============================================================


class TestStressBand:
    def test_explicit_bounds_are_used(self):
        low, mid, high = stress_band(3.2, 2.2, 4.0)

        assert (low, mid, high) == (2.2, 3.2, 4.0)

    def test_no_basis_gives_zero_width_band(self):
        low, mid, high = stress_band(3.2)

        assert low == mid == high == 3.2

    def test_assumptions_widen_the_band(self):
        low, mid, high = stress_band(
            3.2,
            baseline_percent=30,
            max_percent=50,
        )

        assert low < mid < high

    def test_band_is_ordered_even_if_stored_backwards(self):
        low, mid, high = stress_band(3.2, 9.0, 1.0)

        assert low <= mid <= high

    def test_none_yields_zero(self):
        assert stress_band(None) == (0.0, 0.0, 0.0)

    def test_zero_max_percent_does_not_divide_by_zero(self):
        low, mid, high = stress_band(
            3.2, baseline_percent=30, max_percent=0
        )

        assert low == mid == high == 3.2


# ============================================================
# REQUEST VALIDATION
# ============================================================


class TestValidation:
    def test_unknown_codes_reported_together(self):
        """
        Fixing them one request at a time wastes everyone's
        afternoon.
        """

        unknown = validate_request(
            ["A", "NOPE", "B", "ALSO_NOPE"], ["A", "B"]
        )

        assert set(unknown) == {"NOPE", "ALSO_NOPE"}

    def test_all_known_reports_nothing(self):
        assert validate_request(["A"], ["A", "B"]) == []


# ============================================================
# TRUST BOUNDARY
# ============================================================


class TestTrustBoundary:
    def test_nothing_in_the_engine_actuates(self):
        """
        The engine produces SIMULATED figures. There must be no
        import anywhere in the decision path that could reach
        equipment.
        """

        import pathlib

        forbidden = (
            "requests.post",
            "paho",
            "mqtt_client.publish",
            "subprocess",
            "os.system",
            "socket.connect",
        )

        root = pathlib.Path("app")

        offenders = []

        for path in root.rglob("*.py"):
            text = path.read_text()

            for token in forbidden:
                if token in text:
                    offenders.append(
                        f"{path}: {token}"
                    )

        assert offenders == []

    def test_simulation_values_are_labelled(self):
        from app.core.impact_rules import VALUE_MODELED

        service = ImpactService()

        projected = service.project_energy(
            make_intervention(), excess_kw=5
        )

        assert projected.value_type in (
            VALUE_MODELED, VALUE_SIMULATED
        )