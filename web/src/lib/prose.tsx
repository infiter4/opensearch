import { Fragment, type ReactNode } from "react";
import type { SentenceRef, Verdict } from "./protocol";
import { MARK } from "./protocol";

/* Renders the answer from its AUTHORITATIVE text + sentence offsets. The backend guarantees
   text[start:end] === sentence.text, so marks can never drift onto the wrong words — the same
   invariant the verifier itself depends on. Markdown is handled inline per sentence (bold, code,
   italics, citation chips) and structurally per block (headings, bullets, tables), because a
   generic markdown renderer would destroy the offsets the marks hang on. */

export interface SentenceDress {
  verdict: Verdict | null;      // null = uncited prose, wears no mark
  repairing: boolean;
  healed: boolean;
  focused: boolean;
  retractedText?: string;       // original words of a withdrawn sentence
  note?: string;                // tooltip: why the mark landed
}

interface ProseProps {
  text: string;
  sentences: SentenceRef[];
  dress: (s: SentenceRef) => SentenceDress;
  onCite: (sourceId: number, sentenceId: string) => void;
  onFocus?: (sentenceId: string) => void;
}

const CITE = /\[(\d+)\]/g;
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[\d+\])/g;

function inline(text: string, sid: string, onCite: ProseProps["onCite"]): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0, k = 0;
  for (const m of text.matchAll(INLINE)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("[")) {
      const n = Number(tok.slice(1, -1));
      out.push(
        <button
          key={`c${k++}`}
          className="cite"
          onClick={(e) => { e.stopPropagation(); onCite(n, sid); }}
        >
          {n}
        </button>,
      );
    } else if (tok.startsWith("**")) {
      out.push(<strong key={`b${k++}`}>{tok.slice(2, -2)}</strong>);
    } else if (tok.startsWith("`")) {
      out.push(
        <code key={`k${k++}`} className="font-mono text-[0.82em] bg-ground-2 px-1 py-px rounded border border-[var(--rule)]">
          {tok.slice(1, -1)}
        </code>,
      );
    } else {
      out.push(<em key={`i${k++}`}>{tok.slice(1, -1)}</em>);
    }
    last = m.index! + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function markClass(d: SentenceDress): string {
  const parts = ["mk"];
  if (d.verdict) parts.push(`mk-${d.verdict}`);
  if (d.repairing) parts.push("mk-repairing");
  else if (d.healed) parts.push("mk-healed");
  if (d.focused) parts.push("mk-focus");
  return parts.join(" ");
}

/** One sentence, dressed in its mark. Block styling comes from its own leading markdown. */
function Line({ s, raw, d, onCite, onFocus }: {
  s: SentenceRef; raw: string; d: SentenceDress;
  onCite: ProseProps["onCite"]; onFocus?: ProseProps["onFocus"];
}) {
  let body = raw;
  if (!body && d.retractedText) {
    // A withdrawn sentence stays on the page, struck through — redlined copy, not a deletion.
    return (
      <span className="mk mk-retracted" data-note={d.note ?? MARK.retracted.word}>
        {d.retractedText}
      </span>
    );
  }
  if (!body) return null;

  let prefix: ReactNode = null;
  let cls = markClass(d);

  const h = body.match(/^(#{1,6})\s+/);
  if (h) {
    body = body.slice(h[0].length);
    cls += " block font-semibold text-[1.12em] mt-4 mb-1";
  } else if (/^[-*+]\s/.test(body)) {
    body = body.replace(/^[-*+]\s/, "");
    prefix = <span className="text-slate select-none">&thinsp;•&ensp;</span>;
  } else if (/^\d+\.\s/.test(body)) {
    const n = body.match(/^(\d+)\.\s/)!;
    body = body.slice(n[0].length);
    prefix = <span className="text-slate font-mono text-[0.85em] select-none">{n[1]}.&ensp;</span>;
  }


  return (
    <>
      {prefix}
      <span
        className={cls}
        data-note={d.note}
        onClick={onFocus ? () => onFocus(s.id) : undefined}
        style={onFocus && d.verdict ? { cursor: "pointer" } : undefined}
      >
        {inline(body, s.id, onCite)}
      </span>
    </>
  );
}

const isRow = (t: string) => t.trimStart().startsWith("|");
const isRule = (t: string) => /^\|[\s|:-]+\|?\s*$/.test(t.trim());
const cells = (t: string) => t.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

/** A run of consecutive markdown rows becomes ONE real table. Rendering each row as its own
 *  block turns a compact price table into a page of loose monospace pipes. */
function Table({ rows, dress, onCite }: {
  rows: { s: SentenceRef; raw: string }[]; dress: ProseProps["dress"]; onCite: ProseProps["onCite"];
}) {
  const body = rows.filter((r) => !isRule(r.raw));
  if (!body.length) return null;
  const [head, ...rest] = body;
  return (
    <table className="my-3 text-[0.84em] border-collapse w-full">
      <thead>
        <tr className="border-b border-[var(--rule)]">
          {cells(head.raw).map((c, i) => (
            <th key={i} className="text-left font-semibold py-1 pr-4 label !text-[9px]">{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rest.map((r) => {
          const d = dress(r.s);
          return (
            <tr key={r.s.id} className="border-b border-[var(--rule)]/50" data-note={d.note}>
              {cells(r.raw).map((c, i) => (
                <td key={i}
                    className={`py-1 pr-4 ${i === 0 ? "font-medium" : "font-mono text-[0.92em] text-paper/70"}
                                ${d.verdict ? `mk mk-${d.verdict}` : ""}`}>
                  {inline(c, r.s.id, onCite)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function Prose({ text, sentences, dress, onCite, onFocus }: ProseProps) {
  if (!sentences.length) {
    return <div className="whitespace-pre-wrap">{stripCites(text, onCite)}</div>;
  }

  const parts: ReactNode[] = [];
  let cursor = 0;
  let i = 0;
  while (i < sentences.length) {
    const s = sentences[i];
    const raw = text.slice(s.start, s.end);

    if (isRow(raw)) {
      const run: { s: SentenceRef; raw: string }[] = [];
      while (i < sentences.length) {
        const r = text.slice(sentences[i].start, sentences[i].end);
        if (!isRow(r)) break;
        run.push({ s: sentences[i], raw: r });
        cursor = Math.max(cursor, sentences[i].end);
        i++;
      }
      parts.push(<Table key={`t${run[0].s.id}`} rows={run} dress={dress} onCite={onCite} />);
      continue;
    }

    const gap = text.slice(cursor, s.start);
    if (gap) {
      const breaks = (gap.match(/\n/g) ?? []).length;
      if (breaks >= 2) parts.push(<div key={`g${i}`} className="h-3" />);
      else if (breaks === 1) parts.push(<br key={`g${i}`} />);
      else parts.push(<Fragment key={`g${i}`}>{gap}</Fragment>);
    }
    parts.push(<Line key={s.id} s={s} raw={raw} d={dress(s)} onCite={onCite} onFocus={onFocus} />);
    cursor = Math.max(cursor, s.end);
    i++;
  }

  return <div className="leading-[1.85]">{parts}</div>;
}

/** Streaming fallback: no offsets yet, but chips should already be clickable. */
function stripCites(text: string, onCite: ProseProps["onCite"]): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0, k = 0;
  for (const m of text.matchAll(CITE)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    const n = Number(m[1]);
    out.push(
      <button key={k++} className="cite" onClick={() => onCite(n, "")}>{n}</button>,
    );
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
