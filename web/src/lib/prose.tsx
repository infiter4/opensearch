import katex from "katex";
import "katex/dist/katex.min.css";
import { Fragment, type ReactNode } from "react";
import type { SentenceRef, Verdict } from "./protocol";
import { MARK } from "./protocol";

/** Render TeX to HTML. Bundled locally, never a CDN — the demo has to survive a bad network.
 *  throwOnError:false means a malformed formula renders in red rather than taking out the answer
 *  around it; `$` also appears in prose about money, so a false positive must be harmless. */
function tex(src: string, display: boolean): string {
  try {
    return katex.renderToString(src, { displayMode: display, throwOnError: false, output: "html" });
  } catch {
    return "";
  }
}

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
  struck?: boolean;             // false when rewound: at iteration 0 it had not been withdrawn yet
  note?: string;                // tooltip: why the mark landed
}

interface ProseProps {
  text: string;
  sentences: SentenceRef[];
  dress: (s: SentenceRef) => SentenceDress;
  onCite: (sourceId: number, sentenceId: string) => void;
  onFocus?: (sentenceId: string) => void;
}

// Math is $$…$$ or \(…\) ONLY — never single $…$.
//
// A single-dollar rule cannot be made safe here. "Pay-As-You-Go ($0.008/credit, cancel anytime)
// or plans from $30 to $500" contains two dollar signs on one line, so $…$ swallowed the prose
// between them and rendered "0.008/credit, cancel anytime) or plans ranging from" as a formula.
// This app's own demo question is about pricing: dollars are money here far more often than math.
const INLINE = /(\$\$[^$]+\$\$|\\\([\s\S]*?\\\)|\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[\d+\])/g;

/** Un-marked text: streaming copy has no verdicts yet, so it wears no mark. */
const NO_MARK = (): SentenceDress => ({
  verdict: null, repairing: false, healed: false, focused: false,
});

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
    } else if (tok.startsWith("$$") || tok.startsWith("\\(")) {
      const display = tok.startsWith("$$");
      const body = display ? tok.slice(2, -2) : tok.slice(2, -2);
      const html = tex(body, display);
      out.push(
        html
          ? <span key={`m${k++}`} className="katex-host" dangerouslySetInnerHTML={{ __html: html }} />
          : <span key={`m${k++}`}>{tok}</span>,
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
  // A withdrawn sentence stays on the page, struck through — redlined copy, not a deletion. It is
  // still prose, so it takes the same markdown path as live text: rendering it raw printed literal
  // `**bold**` and leading `- ` bullets in the one place a reader is looking hardest.
  const withdrawn = !raw && !!d.retractedText;
  let body = withdrawn ? d.retractedText! : raw;
  if (!body) return null;

  let prefix: ReactNode = null;
  // Struck only in the shipped copy. Rewound to the first draft, a withdrawn sentence was still
  // live prose wearing whatever mark it had actually earned — showing it struck there would claim
  // the desk had already acted when it hadn't.
  let cls = withdrawn && d.struck !== false ? "mk mk-retracted" : markClass(d);

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
        data-note={withdrawn ? d.note ?? MARK.retracted.word : d.note}
        onClick={onFocus ? () => onFocus(s.id) : undefined}
        style={onFocus && (d.verdict || withdrawn) ? { cursor: "pointer" } : undefined}
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
  // No offsets yet — the answer is still streaming, or it never got segmented. It is still
  // markdown, and dumping it raw is why a finished-looking answer showed `## Paid plans`, `- ` and
  // `| Plan | Credits |` as literal text. Synthesize one pseudo-sentence per line and run the very
  // same block pipeline: headings, bullets, tables, bold, code and chips all render, nothing is
  // marked (there are no verdicts yet), and the two paths cannot drift apart.
  if (!sentences.length) {
    if (!text) return null;
    const lines: SentenceRef[] = [];
    let pos = 0;
    for (const raw of text.split("\n")) {
      lines.push({ id: `l${lines.length}`, start: pos, end: pos + raw.length, cited: [] });
      pos += raw.length + 1;
    }
    return (
      <Prose
        text={text}
        sentences={lines}
        dress={NO_MARK}
        onCite={onCite}
      />
    );
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

// The old `stripCites` streaming fallback is gone: it rendered chips but dumped every other bit of
// markdown as literal text. The no-offset path now runs the same block pipeline as the final copy,
// so there is exactly one renderer to keep honest.
