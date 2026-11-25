import React, { useState } from 'react';

/**
 * Lightweight, safe Markdown renderer for chat messages.
 * Handles code blocks (with copy button), inline code, bold, italics,
 * headings, blockquotes, lists, and line breaks.
 */
export default function MarkdownRenderer({ content }) {
  if (!content) return null;

  // Split by code blocks first
  const parts = [];
  const codeBlockRegex = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({
        type: 'text',
        value: content.slice(lastIndex, match.index),
      });
    }
    parts.push({
      type: 'code',
      language: match[1] || 'plaintext',
      value: match[2].trimEnd(),
    });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < content.length) {
    parts.push({
      type: 'text',
      value: content.slice(lastIndex),
    });
  }

  return (
    <div className="rendered-markdown">
      {parts.map((part, idx) => {
        if (part.type === 'code') {
          return <CodeBlock key={idx} language={part.language} code={part.value} />;
        }
        return <FormattedTextBlock key={idx} text={part.value} />;
      })}
    </div>
  );
}

function CodeBlock({ language, code }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  };

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-lang">{language || 'code'}</span>
        <button
          type="button"
          className="btn-copy-code"
          onClick={handleCopy}
          title="Copy code to clipboard"
        >
          {copied ? (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span>Copied!</span>
            </>
          ) : (
            <>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <span>Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="code-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function FormattedTextBlock({ text }) {
  // Split into lines/blocks
  const lines = text.split('\n');
  const elements = [];
  let currentList = null;
  let listType = null; // 'ul' or 'ol'
  let tableRows = [];

  const flushList = () => {
    if (currentList && currentList.length > 0) {
      if (listType === 'ol') {
        elements.push(<ol key={`ol-${elements.length}`} className="md-ol">{currentList}</ol>);
      } else {
        elements.push(<ul key={`ul-${elements.length}`} className="md-ul">{currentList}</ul>);
      }
      currentList = null;
      listType = null;
    }
  };

  const flushTable = () => {
    if (tableRows.length === 0) return;
    const isSeparator = (row) => row.every((cell) => /^:?-{2,}:?$/.test(cell.trim()));
    const headerRow = tableRows[0];
    const bodyStart = tableRows.length > 1 && isSeparator(tableRows[1]) ? 2 : 1;
    const bodyRows = tableRows.slice(bodyStart);

    elements.push(
      <div key={`tbl-${elements.length}`} className="md-table-wrap">
        <table className="md-table">
          <thead>
            <tr>
              {headerRow.map((cell, ci) => (
                <th key={ci}>{renderInline(cell.trim())}</th>
              ))}
            </tr>
          </thead>
          {bodyRows.length > 0 && (
            <tbody>
              {bodyRows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td key={ci}>{renderInline(cell.trim())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          )}
        </table>
      </div>
    );
    tableRows = [];
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    // Check for markdown table row
    if (trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.includes('|')) {
      flushList();
      const cells = trimmed.slice(1, -1).split('|');
      tableRows.push(cells);
      return;
    } else {
      flushTable();
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushList();
      elements.push(<hr key={`hr-${index}`} className="md-hr" />);
      return;
    }

    // Check for unordered list
    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (ulMatch) {
      if (listType !== 'ul') flushList();
      listType = 'ul';
      if (!currentList) currentList = [];
      currentList.push(
        <li key={`li-${index}`} className="md-li">
          {renderInline(ulMatch[2])}
        </li>
      );
      return;
    }

    // Check for ordered list
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (olMatch) {
      if (listType !== 'ol') flushList();
      listType = 'ol';
      if (!currentList) currentList = [];
      currentList.push(
        <li key={`li-${index}`} className="md-li">
          {renderInline(olMatch[2])}
        </li>
      );
      return;
    }

    // Not a list item
    flushList();

    if (!trimmed) {
      elements.push(<div key={`empty-${index}`} className="md-space" />);
      return;
    }

    // Headings
    if (trimmed.startsWith('### ')) {
      elements.push(<h3 key={index} className="md-h3">{renderInline(trimmed.slice(4))}</h3>);
    } else if (trimmed.startsWith('## ')) {
      elements.push(<h2 key={index} className="md-h2">{renderInline(trimmed.slice(3))}</h2>);
    } else if (trimmed.startsWith('# ')) {
      elements.push(<h1 key={index} className="md-h1">{renderInline(trimmed.slice(2))}</h1>);
    } else if (trimmed.startsWith('> ')) {
      elements.push(
        <blockquote key={index} className="md-blockquote">
          {renderInline(trimmed.slice(2))}
        </blockquote>
      );
    } else {
      elements.push(
        <p key={index} className="md-p">
          {renderInline(line)}
        </p>
      );
    }
  });

  flushList();
  flushTable();

  return <>{elements}</>;
}

function renderInline(str) {
  if (!str) return '';

  // Regex to match inline code, bold, italic
  const tokens = [];
  const inlineRegex = /(`([^`]+)`)|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)/g;
  let lastIdx = 0;
  let m;

  while ((m = inlineRegex.exec(str)) !== null) {
    if (m.index > lastIdx) {
      tokens.push(str.slice(lastIdx, m.index));
    }

    if (m[1]) {
      // Inline code
      tokens.push(<code key={m.index} className="inline-code">{m[2]}</code>);
    } else if (m[3]) {
      // Bold
      tokens.push(<strong key={m.index} className="inline-bold">{m[4]}</strong>);
    } else if (m[5]) {
      // Italic
      tokens.push(<em key={m.index} className="inline-italic">{m[6]}</em>);
    }

    lastIdx = m.index + m[0].length;
  }

  if (lastIdx < str.length) {
    tokens.push(str.slice(lastIdx));
  }

  return tokens.length > 0 ? tokens : str;
}
