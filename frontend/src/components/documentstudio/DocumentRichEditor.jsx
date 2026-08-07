import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { $generateHtmlFromNodes, $generateNodesFromDOM } from '@lexical/html';
import { AutoLinkNode, LinkNode } from '@lexical/link';
import { ListItemNode, ListNode, INSERT_ORDERED_LIST_COMMAND, INSERT_UNORDERED_LIST_COMMAND, REMOVE_LIST_COMMAND } from '@lexical/list';
import { $createHeadingNode, HeadingNode, QuoteNode } from '@lexical/rich-text';
import { $patchStyleText, $setBlocksType } from '@lexical/selection';
import { mergeRegister } from '@lexical/utils';
import { LexicalComposer } from '@lexical/react/LexicalComposer.js';
import { ContentEditable } from '@lexical/react/LexicalContentEditable.js';
import { LexicalErrorBoundary } from '@lexical/react/LexicalErrorBoundary.js';
import { HistoryPlugin } from '@lexical/react/LexicalHistoryPlugin.js';
import { LinkPlugin } from '@lexical/react/LexicalLinkPlugin.js';
import { ListPlugin } from '@lexical/react/LexicalListPlugin.js';
import { OnChangePlugin } from '@lexical/react/LexicalOnChangePlugin.js';
import { RichTextPlugin } from '@lexical/react/LexicalRichTextPlugin.js';
import { useLexicalComposerContext } from '@lexical/react/LexicalComposerContext.js';
import {
  $getRoot,
  $getSelection,
  $insertNodes,
  $isRangeSelection,
  COMMAND_PRIORITY_HIGH,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  INDENT_CONTENT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  PASTE_COMMAND,
  REDO_COMMAND,
  UNDO_COMMAND,
  createCommand,
} from 'lexical';
import { createPageBreakNode, PageBreakNode, sanitizeEditorHtml } from './editorModel';

export const INSERT_CLEAN_HTML_COMMAND = createCommand('INSERT_CLEAN_HTML_COMMAND');
export const INSERT_PAGE_BREAK_COMMAND = createCommand('INSERT_PAGE_BREAK_COMMAND');
export const SET_EDITOR_HTML_COMMAND = createCommand('SET_EDITOR_HTML_COMMAND');

function Placeholder() {
  return <div className="pointer-events-none absolute left-0 top-0 text-neutral-400">Start typing your document…</div>;
}

function EditorBridge({ html, onHtmlChange, editorApiRef, onEditorReady }) {
  const [editor] = useLexicalComposerContext();
  const lastExternalHtml = useRef(html || '');

  useEffect(() => {
    onEditorReady?.(editor);
  }, [editor, onEditorReady]);

  useImperativeHandle(editorApiRef, () => ({
    formatText: (format) => editor.dispatchCommand(FORMAT_TEXT_COMMAND, format),
    formatElement: (format) => editor.dispatchCommand(FORMAT_ELEMENT_COMMAND, format),
    undo: () => editor.dispatchCommand(UNDO_COMMAND, undefined),
    redo: () => editor.dispatchCommand(REDO_COMMAND, undefined),
    indent: () => editor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined),
    outdent: () => editor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined),
    insertList: (ordered = false) => editor.dispatchCommand(ordered ? INSERT_ORDERED_LIST_COMMAND : INSERT_UNORDERED_LIST_COMMAND, undefined),
    removeList: () => editor.dispatchCommand(REMOVE_LIST_COMMAND, undefined),
    insertHtml: (markup) => editor.dispatchCommand(INSERT_CLEAN_HTML_COMMAND, markup),
    insertPageBreak: () => editor.dispatchCommand(INSERT_PAGE_BREAK_COMMAND, undefined),
    setHtml: (markup) => editor.dispatchCommand(SET_EDITOR_HTML_COMMAND, markup),
    setHeading: (tag = 'h2') => editor.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        $setBlocksType(selection, () => $createHeadingNode(tag));
      }
    }),
    setInlineStyle: (styles) => editor.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        $patchStyleText(selection, styles);
      }
    }),
    getHtml: () => {
      let value = '';
      editor.getEditorState().read(() => {
        value = $generateHtmlFromNodes(editor, null);
      });
      return sanitizeEditorHtml(value);
    },
  }), [editor]);

  useEffect(() => {
    if ((html || '') !== lastExternalHtml.current) {
      lastExternalHtml.current = html || '';
      editor.dispatchCommand(SET_EDITOR_HTML_COMMAND, html || '');
    }
  }, [editor, html]);

  useEffect(() => mergeRegister(
    editor.registerCommand(SET_EDITOR_HTML_COMMAND, (markup) => {
      editor.update(() => {
        const parser = new DOMParser();
        const dom = parser.parseFromString(sanitizeEditorHtml(markup || '<p></p>'), 'text/html');
        const nodes = $generateNodesFromDOM(editor, dom);
        const root = $getRoot();
        root.clear();
        root.append(...nodes);
      });
      return true;
    }, COMMAND_PRIORITY_HIGH),
    editor.registerCommand(INSERT_CLEAN_HTML_COMMAND, (markup) => {
      editor.update(() => {
        const parser = new DOMParser();
        const dom = parser.parseFromString(sanitizeEditorHtml(markup), 'text/html');
        const nodes = $generateNodesFromDOM(editor, dom);
        $insertNodes(nodes);
      });
      return true;
    }, COMMAND_PRIORITY_HIGH),
    editor.registerCommand(INSERT_PAGE_BREAK_COMMAND, () => {
      editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
          selection.insertNodes([createPageBreakNode()]);
        }
      });
      return true;
    }, COMMAND_PRIORITY_HIGH),
    editor.registerCommand(PASTE_COMMAND, (event) => {
      const clipboard = event.clipboardData;
      const html = clipboard?.getData('text/html');
      const text = clipboard?.getData('text/plain');
      if (!html && !text) return false;
      event.preventDefault();
      editor.dispatchCommand(INSERT_CLEAN_HTML_COMMAND, html || `<p>${String(text).replace(/\n/g, '<br/>')}</p>`);
      return true;
    }, COMMAND_PRIORITY_HIGH),
  ), [editor]);

  return <OnChangePlugin onChange={(editorState) => {
    editorState.read(() => {
      const nextHtml = sanitizeEditorHtml($generateHtmlFromNodes(editor, null));
      lastExternalHtml.current = nextHtml;
      onHtmlChange(nextHtml);
    });
  }} />;
}

const DocumentRichEditor = forwardRef(function DocumentRichEditor({ html, onHtmlChange, disabled, className = '', onEditorReady, onSelectionContextChange }, ref) {
  const editorApiRef = useRef(null);
  const initialConfig = useMemo(() => ({
    namespace: 'LuminaDocumentStudioEditor',
    editable: !disabled,
    nodes: [HeadingNode, QuoteNode, ListNode, ListItemNode, LinkNode, AutoLinkNode, PageBreakNode],
    onError(error) {
      throw error;
    },
    editorState: null,
    theme: {
      text: { bold: 'font-bold', italic: 'italic', underline: 'underline' },
      paragraph: 'my-3',
      heading: { h1: 'text-4xl font-display mb-5', h2: 'text-2xl font-display mt-6 mb-3', h3: 'text-xl font-display mt-5 mb-2' },
      list: { ul: 'list-disc pl-6 my-3', ol: 'list-decimal pl-6 my-3', listitem: 'my-1' },
      link: 'text-blue-700 underline',
    },
  }), [disabled]);

  return (
    <LexicalComposer initialConfig={initialConfig}>
      <div className="relative" onMouseUp={() => reportSelectionContext(onSelectionContextChange)} onKeyUp={() => reportSelectionContext(onSelectionContextChange)}>
        <RichTextPlugin
          contentEditable={<ContentEditable className={`prose prose-neutral max-w-none outline-none ${className}`} />}
          placeholder={<Placeholder />}
          ErrorBoundary={LexicalErrorBoundary}
        />
        <HistoryPlugin />
        <ListPlugin />
        <LinkPlugin />
        <EditorBridge html={html} onHtmlChange={onHtmlChange} editorApiRef={ref || editorApiRef} onEditorReady={onEditorReady} />
      </div>
    </LexicalComposer>
  );
});

export default DocumentRichEditor;

function reportSelectionContext(callback) {
  if (!callback || typeof window === 'undefined') return;
  const node = window.getSelection?.()?.anchorNode;
  const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
  if (element?.closest?.('img, figure')) return callback('image');
  if (element?.closest?.('table, th, td')) return callback('table');
  if (element?.closest?.('header, footer, [data-document-region]')) return callback('header-footer');
  callback(window.getSelection?.()?.toString() ? 'text' : 'document');
}
