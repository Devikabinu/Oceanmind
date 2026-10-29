import { apiClient } from "./client";
import type { IngestionJob, IngestionRequest, Paginated } from "../types";

export type IngestionSource = "noaa" | "obis";

export async function startIngestion(
  source: IngestionSource,
  payload: IngestionRequest,
): Promise<IngestionJob> {
  const { data } = await apiClient.post<IngestionJob>(`/ingestion/${source}`, payload);
  return data;
}

export async function listIngestionJobs(params: {
  page?: number;
  page_size?: number;
} = {}): Promise<IngestionJob[]> {
  const { data } = await apiClient.get<IngestionJob[]>("/ingestion/jobs", { params });
  return data;
}

export async function getIngestionJob(jobId: string): Promise<IngestionJob> {
  const { data } = await apiClient.get<IngestionJob>(`/ingestion/jobs/${jobId}`);
  return data;
}

export async function listOceanObservations(
  params: Record<string, unknown> = {},
): Promise<Paginated<import("../types").OceanObservation>> {
  const { data } = await apiClient.get("/ocean-observations", { params });
  return data;
}

export async function listBiodiversityObservations(
  params: Record<string, unknown> = {},
): Promise<Paginated<import("../types").BiodiversityObservation>> {
  const { data } = await apiClient.get("/biodiversity-observations", { params });
  return data;
}
