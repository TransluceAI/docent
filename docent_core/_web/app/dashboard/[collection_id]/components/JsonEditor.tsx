import { cn, getSchemaPreview } from '@/lib/utils';
import { ChevronLeft } from 'lucide-react';
import CodeMirror, { EditorView } from '@uiw/react-codemirror';
import { json as jsonLanguage } from '@codemirror/lang-json';
import { useTheme } from 'next-themes';
import { useMemo, useState } from 'react';

interface JsonEditorProps {
  schemaText: string;
  setSchemaText: (text: string) => void;
  schemaError: string | null;
  editable: boolean;
  forceOpenSchema: boolean;
  showPreview?: boolean;
}

export default function JsonEditor({
  schemaText,
  setSchemaText,
  schemaError,
  editable,
  forceOpenSchema,
  showPreview = true,
}: JsonEditorProps) {
  const [schemaOpen, setSchemaOpen] = useState(false);

  const { resolvedTheme } = useTheme();
  const extensions = useMemo(
    () => [jsonLanguage(), EditorView.lineWrapping],
    []
  );

  const preview = useMemo(() => {
    try {
      return getSchemaPreview(JSON.parse(schemaText || '{}'));
    } catch (error) {
      // If JSON parsing fails, return null to show "No preview available"
      return null;
    }
  }, [schemaText]);

  return (
    <div className="rounded-md border bg-background shadow-sm">
      {/* Dropdown button */}
      <button
        type="button"
        className={cn(
          'w-full flex items-center justify-between transition-colors duration-200 rounded-md h-9 px-2 py-1.5 disabled:opacity-80',
          !editable || forceOpenSchema ? '' : 'hover:bg-accent',
          schemaOpen ? 'rounded-b-none' : ''
        )}
        onClick={() => setSchemaOpen(!schemaOpen)}
        disabled={forceOpenSchema}
        aria-expanded={schemaOpen || forceOpenSchema ? true : false}
        aria-controls="schema-content"
      >
        <div className="flex items-center gap-2 min-w-0">
          {showPreview &&
            (preview ? (
              <span className="text-xs text-muted-foreground truncate">
                {preview}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground truncate">
                No preview available
              </span>
            ))}
        </div>
        <ChevronLeft
          className={
            'h-3 w-3 transition-transform ' +
            (schemaOpen || forceOpenSchema ? '-rotate-90' : '')
          }
        />
      </button>

      {/* Schema, always mounted */}
      <div
        id="schema-content"
        className={cn(
          'px-0 space-y-2 overflow-hidden transition-all duration-200',
          schemaOpen || forceOpenSchema
            ? 'max-h-[40vh] opacity-100'
            : '!max-h-0  opacity-0 pointer-events-none'
        )}
      >
        <div className=" rounded-b max-h-[30vh] overflow-y-auto custom-scrollbar">
          <CodeMirror
            value={schemaText}
            height="auto"
            // maxHeight="30vh"
            theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
            extensions={extensions}
            onChange={(value) => setSchemaText(value)}
            basicSetup={{
              lineNumbers: false,
              highlightActiveLine: true,
              foldGutter: false,
            }}
            readOnly={!editable}
          />
        </div>
        {schemaError && (
          <div className="text-xs text-red-text">{schemaError}</div>
        )}
      </div>
    </div>
  );
}
