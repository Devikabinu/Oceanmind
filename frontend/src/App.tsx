import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import DataSources from "./pages/DataSources";
import Datasets from "./pages/Datasets";
import Ingestion from "./pages/Ingestion";
import DataQuality from "./pages/DataQuality";
import Forecast from "./pages/Forecast";
import Anomalies from "./pages/Anomalies";
import Risk from "./pages/Risk";
import Alerts from "./pages/Alerts";
import Profile from "./pages/Profile";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
            <Route path="/data-sources" element={<DataSources />} />
            <Route path="/datasets" element={<Datasets />} />
            <Route path="/ingestion" element={<Ingestion />} />
            <Route path="/data-quality" element={<DataQuality />} />
            <Route path="/forecast" element={<Forecast />} />
            <Route path="/anomaly" element={<Anomalies />} />
            <Route path="/risk" element={<Risk />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/profile" element={<Profile />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
