// Entry of the development-only map fixture (map-fixture.html, served by Vite under /__map-fixture/; D312).
import { createRoot } from "react-dom/client";
import "../../styles.css";
import "./fixture.css";
import { FixtureRoot } from "./FixtureApp";

createRoot(document.getElementById("root")!).render(<FixtureRoot />);
