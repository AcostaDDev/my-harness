import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { I18nProvider } from "./Language";
import { usePath } from "./navigation";
import { Page } from "./Page";
import { ArchiveNotice } from "./pages/Archive";
import { parse } from "./router.ts";
import { SessionGate } from "./SessionGate";
import { ServiceModeProvider, useServiceMode } from "./ServiceMode";
import { Shell } from "./Shell";
import "./styles.css";

function App() {
  const route = parse(usePath());
  const mode = useServiceMode();
  return <Shell route={route}>{mode?.read_only_archive && <ArchiveNotice />}<Page route={route} /></Shell>;
}

createRoot(document.getElementById("root")!).render(<StrictMode><I18nProvider><SessionGate><ServiceModeProvider><App /></ServiceModeProvider></SessionGate></I18nProvider></StrictMode>);
