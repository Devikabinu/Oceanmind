import { apiClient } from "./client";
import type { DataQualityReport } from "../types";

export async function getQualityReports(datasetId: string): Promise<DataQualityReport[]> {
  const { data } = await apiClient.get<DataQualityReport[]>(`/data-quality/${datasetId}`);
  return data;
}
