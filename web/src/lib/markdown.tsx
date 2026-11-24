/**
 * A small, safe Markdown renderer for reports.
 *
 * It produces React elements only: raw HTML in the source is shown as text (React escapes it), and
 * links are kept only for http(s), mailto, in-page (#) and app-relative (/) targets. Supports the subset
 * the Reporter emits: headings, paragraphs, lists, tables, block quotes, fenced code, rules, and inline
 * code / bold / italic / links.
 */
import { Fragment, type ReactNode } from "react";

export function safeHref(url: string): string | null {
  const u = url.trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (u.startsWith("#") || (u.startsWith("/") && !u.startsWith("//"))) return u;
  return null;
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\s][^*]*\*)|(\b_[^_\s][^_]*_\b)|(\[[^\]]+\]\([^)\s]+\))/;

export function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      out.push(rest);
      break;
    }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${k++}`;
    if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={key}>{renderInline(tok.slice(2, -2), key)}</strong>);
    else if (tok.startsWith("*") || tok.startsWith("_")) out.push(<em key={key}>{renderInline(tok.slice(1, -1), key)}</em>);
    else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok)!;
      const href = safeHref(lm[2]);
      out.push(
        href ? (
          <a key={key} href={href} {...(/^https?:/i.test(href) ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
            {renderInline(lm[1], key)}
          </a>
        ) : (
          <Fragment key={key}>{lm[1]}</Fragment>
        ),
      );
    }
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  const isTableSep = (l: string | undefined) => !!l && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);

  while (i < lines.length) {
    const line = lines[i];
    const k = `b${key++}`;
    if (!line.trim()) {
      i++;
      continue;
    }
    const fence = /^```(.*)$/.exec(line.trim());
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) body.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={k} className="md-code">
          <code>{body.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = Math.min(h[1].length + 1, 6); // the page owns h1
      const Tag = `h${level}` as "h2";
      blocks.push(<Tag key={k}>{renderInline(h[2].replace(/\s+#+\s*$/, ""), k)}</Tag>);
      i++;
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(<hr key={k} />);
      i++;
      continue;
    }
    if (line.includes("|") && isTableSep(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      blocks.push(
        <div key={k} className="table-scroll">
          <table className="data-table md-table">
            <thead>
              <tr>{head.map((c, j) => <th key={j} scope="col">{renderInline(c, `${k}h${j}`)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>{head.map((_, j) => <td key={j}>{renderInline(r[j] ?? "", `${k}r${ri}c${j}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push(
        <blockquote key={k}>
          <Markdown source={body.join("\n")} />
        </blockquote>,
      );
      continue;
    }
    const ul = /^\s*[-*+]\s+/;
    const ol = /^\s*\d+[.)]\s+/;
    if (ul.test(line) || ol.test(line)) {
      const ordered = ol.test(line);
      const re = ordered ? ol : ul;
      const items: string[] = [];
      while (i < lines.length && (re.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (re.test(lines[i])) items.push(lines[i].replace(re, ""));
        else items[items.length - 1] += ` ${lines[i].trim()}`;
        i++;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={k}>{items.map((it, j) => <li key={j}>{renderInline(it, `${k}-${j}`)}</li>)}</List>);
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s/.test(lines[i]) &&
      !/^```/.test(lines[i].trim()) &&
      !ul.test(lines[i]) &&
      !ol.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) &&
      !(lines[i].includes("|") && isTableSep(lines[i + 1]))
    ) {
      para.push(lines[i++].trim());
    }
    blocks.push(<p key={k}>{renderInline(para.join(" "), k)}</p>);
  }
  return <div className="markdown">{blocks}</div>;
}
