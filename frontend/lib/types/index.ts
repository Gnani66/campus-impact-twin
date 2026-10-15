export type ResourceDomain =
  | "energy"
  | "water"
  | "waste";

export type EvidenceSource =
  | "camera"
  | "telemetry"
  | "schedule"
  | "simulation"
  | "import";

export type EvidenceQuality =
  | "insufficient"
  | "weak"
  | "moderate"
  | "strong";

export type OccupancyState =
  | "occupied"
  | "uncertain"
  | "potentially_unoccupied";

export type IncidentSeverity =
  | "low"
  | "medium"
  | "high"
  | "critical";

export type IncidentStatus =
  | "open"
  | "under_review"
  | "resolved"
  | "dismissed";

export type InterventionStatus =
  | "eligible"
  | "requires_review"
  | "ineligible";

export type DecisionStatus =
  | "draft"
  | "recommended"
  | "approved"
  | "rejected";

export type PriorityProfile =
  | "environment_first"
  | "budget_efficient"
  | "risk_aware";

export interface Building {
  id: string;
  name: string;
  code: string;
  description?: string;
}

export interface OperatingSchedule {
  startHour: number;
  endHour: number;
  activeDays: number[];
  timezone: string;
}

export interface Zone {
  id: string;
  buildingId: string;
  name: string;
  code: string;
  type:
    | "lecture_hall"
    | "classroom"
    | "lab"
    | "office"
    | "common";
  floor: number;
  schedule: OperatingSchedule;
}

export interface TelemetryReading {
  id: string;
  zoneId: string;
  resource: ResourceDomain;
  metric: string;
  unit: string;
  value: number;
  timestamp: string;
  provenance: "observed" | "simulated" | "imported";
}

export interface OccupancyObservation {
  id: string;
  zoneId: string;
  timestamp: string;
  detectedPeople: number;
  confidence: number;
  source: EvidenceSource;
  quality: EvidenceQuality;
}

export interface EvidenceItem {
  id: string;
  source: EvidenceSource;
  description: string;
  timestamp?: string;
  confidence?: number;
  quality: EvidenceQuality;
  referenceId?: string;
}

export interface Incident {
  id: string;
  zoneId: string;
  domain: ResourceDomain;
  title: string;
  description: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  impactScore: number;
  evidenceIds: string[];
  triggerRule: string;
  createdAt: string;
}

export interface Intervention {
  id: string;
  name: string;
  domain: ResourceDomain;
  description: string;

  cost: number;
  maintenanceHours: number;

  expectedEnergyKwh: number;
  expectedWaterLitres: number;
  expectedWasteKg: number;
  expectedEmissionsKgCo2e: number;

  confidence: number;

  minimumEvidenceQuality: EvidenceQuality;

  prerequisites: string[];
  incompatibleWith: string[];

  status: InterventionStatus;
}

export interface OptimizationConstraints {
  budget: number;
  maintenanceHours: number;
}

export interface ObjectiveWeights {
  environmental: number;
  financial: number;
  risk: number;
}

export interface OptimizationProfile {
  id: PriorityProfile;
  name: string;
  description: string;
  weights: ObjectiveWeights;
}

export interface Portfolio {
  id: string;
  interventionIds: string[];

  totalCost: number;
  totalMaintenanceHours: number;

  energyImpactKwh: number;
  waterImpactLitres: number;
  wasteImpactKg: number;
  emissionsImpactKgCo2e: number;

  environmentalScore: number;
  financialScore: number;
  riskScore: number;
  objectiveScore: number;

  feasible: boolean;
  feasibilityReasons: string[];
}

export interface StressTestScenario {
  id: string;
  name: string;
  description: string;

  budgetMultiplier?: number;
  maintenanceMultiplier?: number;
  confidenceMultiplier?: number;
  costMultiplier?: number;
  impactMultiplier?: number;
}

export interface StressTestResult {
  scenarioId: string;
  selectedPortfolioId: string | null;
  originalPortfolioRetained: boolean;
  reason: string;
}

export interface Scenario {
  id: string;
  name: string;
  zoneId: string;

  constraints: OptimizationConstraints;
  profile: OptimizationProfile;

  occupancyConfidence: number;
  telemetryFreshnessMinutes: number;

  createdAt: string;
}

export interface DecisionRun {
  id: string;
  scenarioId: string;

  selectedPortfolio: Portfolio;
  alternatives: Portfolio[];

  stressTests: StressTestResult[];

  status: DecisionStatus;

  createdAt: string;
}

export interface AuditEvent {
  id: string;
  decisionId?: string;
  type:
    | "observation"
    | "incident_created"
    | "optimization"
    | "stress_test"
    | "explanation"
    | "approval"
    | "rejection"
    | "scenario_reset";

  message: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}