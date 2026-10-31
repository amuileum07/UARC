import { Component, type ErrorInfo, type ReactNode } from "react";
import { reportFrontendError } from "../lib/diagnostics";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportFrontendError(
      "react",
      error,
      "ErrorBoundary",
      info.componentStack ?? "",
    );
  }

  render() {
    if (this.state.failed)
      return (
        <main className="empty" role="alert">
          화면 오류가 발생했습니다. 앱을 다시 열어 저장된 설계를 불러오세요.
          저장하지 않은 변경은 복구되지 않을 수 있습니다.
        </main>
      );
    return this.props.children;
  }
}
