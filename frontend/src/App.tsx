import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LoadingState } from "./components/feedback";
import { RequireAuth } from "./components/RequireRole";
import { AppLayout } from "./layouts/AppLayout";

const Login = lazy(() => import("./pages/Login"));
const Overview = lazy(() => import("./pages/Overview"));
const Infrastructure = lazy(() => import("./pages/Infrastructure"));
const Servers = lazy(() => import("./pages/Servers"));
const ServerDetails = lazy(() => import("./pages/ServerDetails"));
const Services = lazy(() => import("./pages/Services"));
const ServiceDetails = lazy(() => import("./pages/ServiceDetails"));
const Incidents = lazy(() => import("./pages/Incidents"));
const IncidentDetails = lazy(() => import("./pages/IncidentDetails"));
const Recovery = lazy(() => import("./pages/Recovery"));
const RecoveryHistory = lazy(() => import("./pages/RecoveryHistory"));
const Logs = lazy(() => import("./pages/Logs"));
const Alerts = lazy(() => import("./pages/Alerts"));
const Reports = lazy(() => import("./pages/Reports"));
const AuditLogs = lazy(() => import("./pages/AuditLogs"));
const Users = lazy(() => import("./pages/Users"));
const Settings = lazy(() => import("./pages/Settings"));
const Profile = lazy(() => import("./pages/Profile"));

export default function App() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
          <Route index element={<Overview />} />
          <Route path="infrastructure" element={<Infrastructure />} />
          <Route path="servers" element={<Servers />} />
          <Route path="servers/:id" element={<ServerDetails />} />
          <Route path="services" element={<Services />} />
          <Route path="services/:id" element={<ServiceDetails />} />
          <Route path="incidents" element={<Incidents />} />
          <Route path="incidents/:id" element={<IncidentDetails />} />
          <Route path="recovery" element={<Recovery />} />
          <Route path="recovery/history" element={<RecoveryHistory />} />
          <Route path="logs" element={<Logs />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="reports" element={<Reports />} />
          <Route path="audit-logs" element={<RequireAuth role="ADMIN"><AuditLogs /></RequireAuth>} />
          <Route path="users" element={<RequireAuth role="ADMIN"><Users /></RequireAuth>} />
          <Route path="settings" element={<Settings />} />
          <Route path="profile" element={<Profile />} />
          <Route path="*" element={<div className="card mx-auto mt-16 max-w-md p-6 text-center"><h1 className="text-lg font-semibold">Page not found</h1></div>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
