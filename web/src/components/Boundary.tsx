import { Component, type ReactNode } from "react";

/* One bad exchange must not white-screen the app. A render error anywhere under here is caught,
   reported in place, and the rest of the page keeps working — including the sidebar, so a broken
   thread can still be navigated away from or deleted. */

interface Props { children: ReactNode; onReset?: () => void }
interface State { err: Error | null }

export class Boundary extends Component<Props, State> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err };
  }

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="my-6 p-4 border border-[var(--rule-2)]">
        <div className="label !text-amber mb-2">this answer could not be displayed</div>
        <div className="font-mono text-[11px] text-slate leading-relaxed break-all">
          {this.state.err.message}
        </div>
        <button
          className="label hover:!text-paper mt-3"
          onClick={() => { this.setState({ err: null }); this.props.onReset?.(); }}
        >
          ▸ try again
        </button>
      </div>
    );
  }
}
