import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";

export interface CPEInfo {
  serial: string;
  mac: string | null;
  date_from: string | null;
  date_to: string | null;
}

interface CPEContextType {
  cpeId: string | null;        // serial used as the CPE identifier
  cpeInfo: CPEInfo | null;     // full CPE metadata
  setCPE: (cpe: CPEInfo) => void;
  clearCPE: () => void;
}

const CPEContext = createContext<CPEContextType | null>(null);

export function CPEProvider({ children }: { children: ReactNode }) {
  const [cpeId, setCpeId] = useState<string | null>(
    sessionStorage.getItem("cpe_id")
  );
  const [cpeInfo, setCpeInfo] = useState<CPEInfo | null>(() => {
    const stored = sessionStorage.getItem("cpe_info");
    return stored ? JSON.parse(stored) : null;
  });

  const setCPE = useCallback((cpe: CPEInfo) => {
    setCpeId(cpe.serial);
    setCpeInfo(cpe);
    sessionStorage.setItem("cpe_id", cpe.serial);
    sessionStorage.setItem("cpe_info", JSON.stringify(cpe));
  }, []);

  const clearCPE = useCallback(() => {
    setCpeId(null);
    setCpeInfo(null);
    sessionStorage.removeItem("cpe_id");
    sessionStorage.removeItem("cpe_info");
  }, []);

  return (
    <CPEContext.Provider value={{ cpeId, cpeInfo, setCPE, clearCPE }}>
      {children}
    </CPEContext.Provider>
  );
}

export function useCPE() {
  const ctx = useContext(CPEContext);
  if (!ctx) throw new Error("useCPE must be used within CPEProvider");
  return ctx;
}
