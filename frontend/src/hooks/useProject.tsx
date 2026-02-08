import { createContext, useContext, useState, type ReactNode } from "react";

interface ProjectContextType {
  projectId: string | null;
  projectName: string | null;
  userId: number | null;
  setProject: (id: string, name: string, userId: number) => void;
  clearProject: () => void;
}

const ProjectContext = createContext<ProjectContextType | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState<string | null>(
    sessionStorage.getItem("project_id")
  );
  const [projectName, setProjectName] = useState<string | null>(
    sessionStorage.getItem("project_name")
  );
  const [userId, setUserId] = useState<number | null>(
    Number(sessionStorage.getItem("project_user_id")) || null
  );

  const setProject = (id: string, name: string, uid: number) => {
    setProjectId(id);
    setProjectName(name);
    setUserId(uid);
    sessionStorage.setItem("project_id", id);
    sessionStorage.setItem("project_name", name);
    sessionStorage.setItem("project_user_id", String(uid));
  };

  const clearProject = () => {
    setProjectId(null);
    setProjectName(null);
    setUserId(null);
    sessionStorage.removeItem("project_id");
    sessionStorage.removeItem("project_name");
    sessionStorage.removeItem("project_user_id");
  };

  return (
    <ProjectContext.Provider value={{ projectId, projectName, userId, setProject, clearProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used within ProjectProvider");
  return ctx;
}
