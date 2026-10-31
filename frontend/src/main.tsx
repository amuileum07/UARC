import { createRoot } from "react-dom/client";
import "dockview-react/dist/styles/dockview.css";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./styles.css";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { installErrorReporting, reportFrontendError } from "./lib/diagnostics";
installErrorReporting();
window.CESIUM_BASE_URL = import.meta.env.DEV
  ? "/node_modules/cesium/Build/Cesium/"
  : "./cesium/";
const element = document.getElementById("root");
if (!element) throw new Error("Missing application root.");
createRoot(element, {
  onUncaughtError: (error, info) =>
    reportFrontendError(
      "react",
      error,
      "React root",
      info.componentStack ?? "",
    ),
  onRecoverableError: (error, info) =>
    reportFrontendError(
      "react",
      error,
      "React recovery",
      info.componentStack ?? "",
    ),
}).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
