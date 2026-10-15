import { apiClient } from "./client";
import type {
  Alert,
  AlertStatus,
  AnomalyDetection,
  EcologicalRiskScore,
  Paginated,
  SSTForecast,
} from "../types";

type Params = Record<string, string | number | boolean | undefined>;

export async function listForecasts(params: Params = {}): Promise<Paginated<SSTForecast>> {
  const { data } = await apiClient.get<Paginated<SSTForecast>>("/forecast", { params });
  return data;
}

export async function listAnomalies(params: Params = {}): Promise<Paginated<AnomalyDetection>> {
  const { data } = await apiClient.get<Paginated<AnomalyDetection>>("/anomaly", { params });
  return data;
}

export async function listRiskScores(params: Params = {}): Promise<Paginated<EcologicalRiskScore>> {
  const { data } = await apiClient.get<Paginated<EcologicalRiskScore>>("/risk", { params });
  return data;
}

export async function listAlerts(params: Params = {}): Promise<Paginated<Alert>> {
  const { data } = await apiClient.get<Paginated<Alert>>("/alerts", { params });
  return data;
}

export async function updateAlertStatus(alertId: string, status: AlertStatus): Promise<Alert> {
  const { data } = await apiClient.patch<Alert>(`/alerts/${alertId}`, { status });
  return data;
}

export interface AlertSummary {
  by_status: Record<AlertStatus, number>;
  open: number;
  open_by_severity: Record<"LOW" | "MEDIUM" | "HIGH" | "CRITICAL", number>;
  open_high_or_critical: number;
}

export async function getAlertSummary(): Promise<AlertSummary> {
  const { data } = await apiClient.get<AlertSummary>("/alerts/summary");
  return data;
}
