'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

import CodeMirror from '@uiw/react-codemirror';
import { json as jsonLanguage } from '@codemirror/lang-json';
import { EditorView } from '@codemirror/view';

interface OutputSchemaDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSchema: Record<string, any> | null | undefined;
  onSave: (schema: Record<string, any>) => void;
  editable: boolean;
}

export default function OutputSchemaDialog({
  open,
  onOpenChange,
  initialSchema,
  onSave,
  editable,
}: OutputSchemaDialogProps) {
  const [schemaText, setSchemaText] = useState<string>('');
  const [schemaError, setSchemaError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setSchemaText(JSON.stringify(initialSchema ?? {}, null, 2));
      setSchemaError(null);
    }
  }, [open, initialSchema]);

  const extensions = useMemo(
    () => [jsonLanguage(), EditorView.lineWrapping],
    []
  );

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setSchemaError(null);
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit output schema</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            Enter a JSON Schema for the judge output to follow.{' '}
            <a
              href="https://json-schema.org/learn/getting-started-step-by-step"
              target="_blank"
              className="text-primary underline"
            >
              Learn more about JSON Schema
            </a>
          </div>
          <div className="border rounded-sm">
            <CodeMirror
              value={schemaText}
              height="50vh"
              theme={undefined}
              extensions={extensions}
              onChange={(value) => {
                setSchemaText(value);
                if (schemaError) setSchemaError(null);
              }}
              basicSetup={{ lineNumbers: true, highlightActiveLine: true }}
              readOnly={!editable}
            />
          </div>
          {schemaError && (
            <div className="text-xs text-red-text">{schemaError}</div>
          )}
        </div>
        <DialogFooter>
          <div className="flex space-x-2">
            <Button
              size="sm"
              disabled={!editable}
              onClick={() => {
                try {
                  const parsed = JSON.parse(schemaText);
                  if (typeof parsed !== 'object' || parsed === null) {
                    setSchemaError('Schema must be a JSON object');
                    return;
                  }
                  onSave(parsed as Record<string, any>);
                } catch (err: any) {
                  setSchemaError(err?.message || 'Invalid JSON');
                }
              }}
            >
              Save
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
