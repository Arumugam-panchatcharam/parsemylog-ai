import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/hooks/useAuth";
import { ProjectProvider } from "@/hooks/useProject";
import { CPEProvider } from "@/hooks/useCPE";
import AppLayout from "@/components/layout/AppLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import LogViewerPage from "@/pages/LogViewerPage";
import PatternPage from "@/pages/PatternPage";
import TelemetryPage from "@/pages/TelemetryPage";
import AIAnalysisPage from "@/pages/AIAnalysisPage";
import PatternAnalyzerPage from "@/pages/PatternAnalyzerPage";
import CPEOverviewPage from "@/pages/CPEOverviewPage";
import AdminPage from "@/pages/AdminPage";
import ProfilePage from "@/pages/ProfilePage";
import ChatPage from "@/pages/ChatPage";
import PcapAnalyzerPage from "@/pages/PcapAnalyzerPage";
import TelemetryCsvAnalyzerPage from "@/pages/TelemetryCsvAnalyzerPage";
import BatchJobsPage from "@/pages/BatchJobsPage";
import BatchJobDetailPage from "@/pages/BatchJobDetailPage";
import KnowledgeGraphPage from "@/pages/KnowledgeGraphPage";
import IssueAnalysisPage from "@/pages/IssueAnalysisPage";
import type { ReactNode } from "react";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }
  return user ? <>{children}</> : <Navigate to="/login" />;
}

function AdminRoute({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;
  if (!user?.is_admin) return <Navigate to="/dashboard" />;
  return <>{children}</>;
}

function AppRoutes() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-primary border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/dashboard" /> : <LoginPage />} />

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
        <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
        <Route path="/projects/:projectId/batch-jobs" element={<BatchJobsPage />} />
        <Route path="/projects/:projectId/batch-jobs/:jobId" element={<BatchJobDetailPage />} />
        <Route path="/workspace/viewer" element={<LogViewerPage />} />
        <Route path="/workspace/pattern" element={<PatternPage />} />
        <Route path="/workspace/telemetry" element={<TelemetryPage />} />
        <Route path="/workspace/ai" element={<AIAnalysisPage />} />
        <Route path="/workspace/pattern-analyzer" element={<PatternAnalyzerPage />} />
        <Route path="/workspace/cpe-overview" element={<CPEOverviewPage />} />
        <Route path="/workspace/issue-analysis" element={<IssueAnalysisPage />} />
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
            <BrowserRouter>
              <AppRoutes />
            </BrowserRouter>
          </CPEProvider>
        </ProjectProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
