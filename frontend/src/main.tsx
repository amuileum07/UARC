import { createRoot } from "react-dom/client";
import "dockview-react/dist/styles/dockview.css";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./styles.css";
import { App } from "./App";
window.CESIUM_BASE_URL = import.meta.env.DEV
  ? "/node_modules/cesium/Build/Cesium/"
  : "./cesium/";
const element = document.getElementById("root");
if (!element) throw new Error("Missing application root.");
createRoot(element).render(<App />);
