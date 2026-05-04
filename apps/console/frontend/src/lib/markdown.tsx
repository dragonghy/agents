/**
 * Tiny markdown renderer for ticket descriptions + comment bodies.
 *
 * Uses react-markdown + remark-gfm (tables, task lists, autolinks) +
 * rehype-sanitize (XSS safety on raw HTML — though we don't allow raw
 * HTML in markdown source anyway). Custom components rewrite ticket
 * references like ``#123`` into router links so an operator can
 * cross-navigate without leaving the page.
 *
 * Used by: TicketDetail (description + comment bodies).
 */
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';

interface Props {
  source: string;
  /** Visual variant: 'block' for full description, 'inline' for comments. */
  variant?: 'block' | 'inline';
}

/** Components: minimal styling; relies on .md-block CSS. */
const COMPONENTS: Components = {
  // Auto-link ticket references like "#123" or "ticket #123" inside text
  // nodes. We intercept paragraphs / list items so the link rewrite runs
  // on every leaf text segment.
  p: ({ children, ...rest }) => <p {...rest}>{rewriteTicketRefs(children)}</p>,
  li: ({ children, ...rest }) => <li {...rest}>{rewriteTicketRefs(children)}</li>,
  // Collapsed external links open in new tab.
  a: ({ href, children, ...rest }) => (
    <a href={href} target="_blank" rel="noreferrer noopener" {...rest}>
      {children}
    </a>
  ),
  // Code blocks render with our existing .tool-pre styling.
  code: ({ className, children, ...rest }) => {
    const inline = !className;
    return inline ? (
      <code className="md-inline-code" {...rest}>
        {children}
      </code>
    ) : (
      <code className={`md-code ${className || ''}`} {...rest}>
        {children}
      </code>
    );
  },
};

export default function Markdown({ source, variant = 'block' }: Props) {
  if (!source) return null;
  return (
    <div className={variant === 'block' ? 'md-block' : 'md-inline'}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={COMPONENTS}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

// ── Ticket-ref auto-linker ────────────────────────────────────────────

const TICKET_REF_RE = /(#\d{2,5})\b/g;

/** Walk children; for any string segment, replace ``#NNN`` with a router Link. */
function rewriteTicketRefs(children: React.ReactNode): React.ReactNode {
  if (typeof children === 'string') {
    return rewriteString(children);
  }
  if (Array.isArray(children)) {
    return children.map((c, i) => (
      <span key={i}>{rewriteTicketRefs(c)}</span>
    ));
  }
  return children;
}

function rewriteString(s: string): React.ReactNode {
  if (!TICKET_REF_RE.test(s)) {
    TICKET_REF_RE.lastIndex = 0;
    return s;
  }
  TICKET_REF_RE.lastIndex = 0;
  const parts: React.ReactNode[] = [];
  let lastEnd = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = TICKET_REF_RE.exec(s)) !== null) {
    if (m.index > lastEnd) parts.push(s.slice(lastEnd, m.index));
    const id = m[0].slice(1); // drop "#"
    parts.push(
      <Link key={`tr-${key++}`} to={`/tickets/${id}`} className="md-ticket-ref">
        {m[0]}
      </Link>
    );
    lastEnd = m.index + m[0].length;
  }
  if (lastEnd < s.length) parts.push(s.slice(lastEnd));
  return parts;
}
