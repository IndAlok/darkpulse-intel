import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ui.boundary", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6">
          <h2 className="text-lg font-semibold text-ink">This view failed to render</h2>
          <p className="mt-2 text-sm text-muted">
            A client error stopped this page. Reload or open another route. The API was not
            marked unavailable.
          </p>
          <button
            className="mt-4 rounded bg-teal px-3 py-1.5 text-sm text-bg"
            onClick={() => this.setState({ error: null })}
          >
            Try this view again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
