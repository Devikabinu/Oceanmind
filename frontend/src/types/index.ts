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
}
