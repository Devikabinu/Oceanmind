export type UserRole = "ADMIN" | "RESEARCHER" | "USER";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export type DataSourceStatus = "ACTIVE" | "INACTIVE" | "DEPRECATED";

export interface DataSource {
  id: string;
  name: string;
  provider: string;
  dataset: string;
  version: string;
  description: string;
  source_url: string;
  status: DataSourceStatus;
  last_updated: string;
}

export type DatasetKind = "ENVIRONMENTAL" | "BIODIVERSITY";

export interface Dataset {
  id: string;
  data_source_id: string;
  name: string;
  kind: DatasetKind;
  temporal_start: string | null;
  temporal_end: string | null;
  min_latitude: number | null;
  max_latitude: number | null;
  min_longitude: number | null;
  max_longitude: number | null;
  record_count: number;
  created_at: string;
  updated_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type IngestionJobStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export interface IngestionJob {
  id: string;
  data_source_id: string;
  dataset_id: string | null;
  status: IngestionJobStatus;
  params: Record<string, unknown>;
  records_read: number;
  records_valid: number;
  records_rejected: number;
  records_modified: number;
  execution_time_seconds: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface IngestionRequest {
  start_date: string;
  end_date: string;
  min_latitude: number;
  max_latitude: number;
  min_longitude: number;
  max_longitude: number;
}

export interface DataQualityReport {
  id: string;
  dataset_id: string;
  ingestion_job_id: string;
  records_read: number;
  records_valid: number;
  records_rejected: number;
  missing_values: number;
  duplicate_records: number;
  invalid_coordinates: number;
  invalid_timestamps: number;
  invalid_sst: number;
  outliers: number;
  schema_mismatches: number;
  details: Record<string, unknown>;
  created_at: string;
}

export interface OceanObservation {
  id: string;
  dataset_id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  sst: number | null;
  sst_anomaly: number | null;
  measurement_error: number | null;
  ice_concentration: number | null;
  source_record_id: string | null;
}

export interface BiodiversityObservation {
  id: string;
  dataset_id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  scientific_name: string;
  occurrence_status: string | null;
  min_depth: number | null;
  max_depth: number | null;
  source_record_id: string | null;
  species_name?: string | null;
  species_aphia_id?: number | null;
  taxon_class?: string | null;
}

export interface SSTForecast {
  id: string;
  dataset_id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  predicted_sst: number;
  forecast_horizon_days: number;
  model_version: string;
  created_at: string;
}

export interface AnomalyDetection {
  id: string;
  observation_id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  anomaly_score: number;
  is_anomaly: boolean;
  model_version: string;
  created_at: string;
}

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface EcologicalRiskScore {
  id: string;
  biodiversity_observation_id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  risk_score: number;
  risk_level: RiskLevel;
  contributing_factors: Record<string, unknown>;
  created_at: string;
}

export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlertStatus = "NEW" | "ACKNOWLEDGED" | "RESOLVED";

export interface AlertDetails {
  key: string;
  driver: string;
  region: string;
  reasons: string[];
  data_sources: string[];
  classification: string;
  recommendation: string;
  species?: { aphia_id: number | null; scientific_name: string; common_name?: string | null }[];
  evidence?: Record<string, unknown>;
  evidence_summary?: { label: string; value: string }[];
}

export interface Alert {
  id: string;
  alert_type: string;
  severity: AlertSeverity;
  latitude: number;
  longitude: number;
  timestamp: string;
  message: string;
  status: AlertStatus;
  related_forecast_id: string | null;
  related_anomaly_id: string | null;
  related_risk_id: string | null;
  details: AlertDetails | null;
  created_at: string;
  resolved_at: string | null;
}
