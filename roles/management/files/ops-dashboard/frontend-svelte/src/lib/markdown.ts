import DOMPurify from 'dompurify';
import { Marked } from 'marked';

const escape = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const markdown = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    // CLI transcripts contain XML-like context and literal HTML. Show that as
    // text; never interpret it as an embedded page or fetch remote images.
    html: ({ text }) => escape(text),
    image: ({ text }) => escape(`[Image: ${text || 'attachment'}]`),
    code: ({ text, lang }) => `<div class="code-frame"><span class="code-label">${escape(lang?.split(/\s/)[0] || 'code')}</span><pre><code>${escape(text)}</code></pre></div>`,
    table: function ({ header, rows }) {
      const row = (cells: typeof header, tag: string) => `<tr>${cells.map((cell) => `<${tag}>${this.parser.parseInline(cell.tokens)}</${tag}>`).join('')}</tr>`;
      return `<div class="table-frame" tabindex="0" role="region" aria-label="Scrollable table"><table><thead>${row(header, 'th')}</thead><tbody>${rows.map((cells) => row(cells, 'td')).join('')}</tbody></table></div>`;
    },
  },
});

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(markdown.parse(text, { async: false }), {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'a', 'hr', 'div', 'span', 'table',
      'thead', 'tbody', 'tr', 'th', 'td', 'input'],
    ALLOWED_ATTR: ['href', 'title', 'class', 'start', 'type', 'checked', 'disabled', 'tabindex', 'role', 'aria-label'],
  });
}
