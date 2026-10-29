import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";

// Pages are loaded when first opened: the map, charts and tables are large and most visits use only a few of them.
const DataSources = lazy(() => import("./pages/DataSources"));
const Datasets = lazy(() => import("./pages/Datasets"));
const Ingestion = lazy(() => import("./pages/Ingestion"));
const DataQuality = lazy(() => import("./pages/DataQuality"));
const Forecast = lazy(() => import("./pages/Forecast"));
const Anomalies = lazy(() => import("./pages/Anomalies"));
const Risk = lazy(() => import("./pages/Risk"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Profile = lazy(() => import("./pages/Profile"));
const RiskAlerts = lazy(() => import("./pages/RiskAlerts"));
const OceanData = lazy(() => import("./pages/OceanData"));
const ModelPerformance = lazy(() => import("./pages/ModelPerformance"));
const ModelBenchmark = lazy(() => import("./pages/ModelBenchmark"));
const OceanMapPage = lazy(() => import("./pages/OceanMapPage"));
const Heatwaves = lazy(() => import("./pages/Heatwaves"));
const SpeciesList = lazy(() => import("./pages/SpeciesList"));
const SpeciesDetail = lazy(() => import("./pages/SpeciesDetail"));
const EcologicalRisk = lazy(() => import("./pages/EcologicalRisk"));

const loading = <p role="status" className="p-4 text-sm text-slate-600">Loading…</p>;

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={loading}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/risk-alerts" element={<RiskAlerts />} />
              <Route path="/ocean-data" element={<OceanData />} />
              <Route path="/performance" element={<ModelPerformance />} />
              <Route path="/benchmark" element={<ModelBenchmark />} />
              <Route path="/data-sources" element={<DataSources />} />
              <Route path="/datasets" element={<Datasets />} />
              <Route path="/ingestion" element={<Ingestion />} />
              <Route path="/data-quality" element={<DataQuality />} />
              <Route path="/forecast" element={<Forecast />} />
              <Route path="/anomaly" element={<Anomalies />} />
              <Route path="/risk" element={<Risk />} />
              <Route path="/ocean-map" element={<OceanMapPage />} />
              <Route path="/map" element={<OceanMapPage />} />
              <Route path="/heatwaves" element={<Heatwaves />} />
              <Route path="/species" element={<SpeciesList />} />
              <Route path="/species/:aphiaId" element={<SpeciesDetail />} />
              <Route path="/ecological-risk" element={<EcologicalRisk />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/profile" element={<Profile />} />
            </Route>
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
