import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import TimeZoneBar from "./TimeZoneBar";
import MacLookupBar from "./MacLookupBar";

export default function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden bg-background">
        <TimeZoneBar />
        <MacLookupBar />
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
