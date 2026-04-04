import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { ProjectProvider } from "@/hooks/useProject";
import { CPEProvider } from "@/hooks/useCPE";
import AppLayout from "@/components/layout/AppLayout";
import { ErrorBoundary, Loading } from "@/components/ui";
import {
  QUERY_RETRY_DEFAULT,
  QUERY_STALE_TIME_MS,
} from "@/lib/constants";

const LoginPage = lazy(() => import("@/pages/LoginPage"));
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const LogViewerPage = lazy(() => import("@/pages/LogViewerPage"));
const PatternPage = lazy(() => import("@/pages/PatternPage"));
const TelemetryPage = lazy(() => import("@/pages/TelemetryPage"));
const SyslogPage = lazy(() => import("@/pages/SyslogPage"));
const SelfHealPage = lazy(() => import("@/pages/SelfHealPage"));
const AIAnalysisPage = lazy(() => import("@/pages/AIAnalysisPage"));
const PatternAnalyzerPage = lazy(() => import("@/pages/PatternAnalyzerPage"));
const CPEOverviewPage = lazy(() => import("@/pages/CPEOverviewPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));
const ProfilePage = lazy(() => import("@/pages/ProfilePage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const PcapAnalyzerPage = lazy(() => import("@/pages/PcapAnalyzerPage"));
const TelemetryCsvAnalyzerPage = lazy(() => import("@/pages/TelemetryCsvAnalyzerPage"));
const BatchJobsPage = lazy(() => import("@/pages/BatchJobsPage"));
const BatchJobDetailPage = lazy(() => import("@/pages/BatchJobDetailPage"));
const KnowledgeGraphPage = lazy(() => import("@/pages/KnowledgeGraphPage"));
const IssueAnalysisPage = lazy(() => import("@/pages/IssueAnalysisPage"));
const MLPipelinePage = lazy(() => import("@/pages/MLPipelinePage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: QUERY_STALE_TIME_MS,
      retry: QUERY_RETRY_DEFAULT,
      refetchOnWindowFocus: false,
    },
  },
});

function RouteFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-8">
      <Loading label="Loading page…" size="lg" />
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loading size="md" label="Checking session…" />
      </div>
    );
  }
  return user ? <>{children}</> : <Navigate to="/login" />;
}

function AdminRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center p-8">
        <Loading label="Loading…" />
      </div>
    );
  }
  if (!user?.is_admin) return <Navigate to="/dashboard" />;
  return <>{children}</>;
}

function AppRoutes() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loading size="md" label="Checking session…" />
      </div>
    );
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={user ? <Navigate to="/dashboard" /> : <LoginPage />}
      />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/knowledge-graph" element={<KnowledgeGraphPage />} />
        <Route path="/pcap" element={<PcapAnalyzerPage />} />
        <Route path="/telemetry-csv" element={<TelemetryCsvAnalyzerPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminPage />
            </AdminRoute>
          }
        />
        <Route path="/projects/:projectId/batch-jobs" element={<BatchJobsPage />} />
        <Route path="/projects/:projectId/batch-jobs/:jobId" element={<BatchJobDetailPage />} />
        <Route path="/workspace/viewer" element={<LogViewerPage />} />
        <Route path="/workspace/pattern" element={<PatternPage />} />
        <Route path="/workspace/telemetry" element={<TelemetryPage />} />
        <Route path="/workspace/syslog" element={<SyslogPage />} />
        <Route path="/workspace/selfheal" element={<SelfHealPage />} />
        <Route path="/workspace/ai" element={<AIAnalysisPage />} />
        <Route path="/workspace/pattern-analyzer" element={<PatternAnalyzerPage />} />
        <Route path="/workspace/cpe-overview" element={<CPEOverviewPage />} />
        <Route path="/workspace/issue-analysis" element={<IssueAnalysisPage />} />
        <Route path="/workspace/ml-pipeline" element={<MLPipelinePage />} />
        <Route path="/workspace/chat" element={<ChatPage />} />
      </Route>

      <Route path="*" element={<Navigate to={user ? "/dashboard" : "/login"} />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ProjectProvider>
          <CPEProvider>
            <ErrorBoundary fallbackTitle="Application error">
              <BrowserRouter>
                <Suspense fallback={<RouteFallback />}>
                  <AppRoutes />
                </Suspense>
              </BrowserRouter>
            </ErrorBoundary>
          </CPEProvider>
        </ProjectProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
