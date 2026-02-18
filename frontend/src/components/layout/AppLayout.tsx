import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import TimeZoneBar from "./TimeZoneBar";

export default function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden bg-background">
        <TimeZoneBar />
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
