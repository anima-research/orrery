import { useEffect, useState } from "react";
import { Dashboard } from "./Dashboard";
import { ProjectView } from "./ProjectView";

function parseHash(): { page: "dashboard" } | { page: "project"; id: string } {
  const m = window.location.hash.match(/^#\/p\/([a-z0-9]+)/);
  return m ? { page: "project", id: m[1] } : { page: "dashboard" };
}

export function App() {
  const [route, setRoute] = useState(parseHash());

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <>
      {route.page === "dashboard" ? (
        <Dashboard />
      ) : (
        <ProjectView projectId={route.id} key={route.id} />
      )}
    </>
  );
}
