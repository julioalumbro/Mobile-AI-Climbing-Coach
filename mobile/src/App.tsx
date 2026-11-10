import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { api, ApiError, getInviteCode, setInviteCode } from "./api";
import AnalysisScreen from "./screens/AnalysisScreen";
import HomeScreen from "./screens/HomeScreen";
import InviteScreen from "./screens/InviteScreen";
import NewAnalysisScreen from "./screens/NewAnalysisScreen";
import type { Me } from "./types";

// Hash routes keep the phone's back gesture working: #/, #/new, #/a/<id>
type Route = { name: "home" } | { name: "new" } | { name: "analysis"; id: string };

function parseRoute(): Route {
  const hash = window.location.hash.replace(/^#/, "");
  const match = hash.match(/^\/a\/([0-9a-f]{32})$/);
  if (match) return { name: "analysis", id: match[1] };
  if (hash === "/new") return { name: "new" };
  return { name: "home" };
}

function navigate(path: string) {
  window.location.hash = path;
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute);
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(() => getInviteCode() !== null);

  useEffect(() => {
    const onHash = () => {
      setRoute(parseRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Check the saved code on start (whatever screen the app opens on), and
  // refresh usage counts whenever the tester returns home.
  useEffect(() => {
    if (!getInviteCode()) return;
    if (me && route.name !== "home") return;
    api.me()
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          setInviteCode(null);
          setMe(null);
        }
      })
      .finally(() => setChecking(false));
  }, [route.name]);

  if (checking && !me) {
    return <div className="grid min-h-dvh place-items-center"><Loader2 className="h-7 w-7 animate-spin text-slate-500" /></div>;
  }

  if (!me) return <InviteScreen onSignedIn={(next) => { setMe(next); navigate("/"); }} />;

  if (route.name === "new") {
    return (
      <NewAnalysisScreen
        maxSeconds={me.max_video_seconds}
        onBack={() => navigate("/")}
        onCreated={(id) => window.location.replace(`#/a/${id}`)}
      />
    );
  }
  if (route.name === "analysis") {
    return <AnalysisScreen id={route.id} onBack={() => navigate("/")} />;
  }
  return (
    <HomeScreen
      me={me}
      onNew={() => navigate("/new")}
      onOpen={(id) => navigate(`/a/${id}`)}
      onSignOut={() => { setInviteCode(null); setMe(null); }}
    />
  );
}
