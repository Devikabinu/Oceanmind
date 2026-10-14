import { apiClient } from "./client";
import type { DataSource, Dataset, Paginated } from "../types";

export async function listDataSources(): Promise<DataSource[]> {
  const { data } = await apiClient.get<DataSource[]>("/data-sources");
  return data;
}

export async function listDatasets(params: {
  page?: number;
  page_size?: number;
  data_source_id?: string;
} = {}): Promise<Paginated<Dataset>> {
  const { data } = await apiClient.get<Paginated<Dataset>>("/datasets", { params });
  return data;
}
