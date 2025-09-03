import { FileText, Copy, Check } from 'lucide-react';
import React, { useState } from 'react';

import { BaseMetadata } from '@/app/types/transcriptTypes';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from '@/components/ui/dialog';

// Helper function to format different types of metadata values
const formatMetadataValue = (value: any): string => {
  if (value === null || value === undefined) return 'N/A';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
};

// Helper to determine if an object is empty
const isEmptyObject = (obj: BaseMetadata) => {
  return Object.keys(obj).length === 0;
};

// Helper function to copy text to clipboard
const copyToClipboard = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    console.error('Failed to copy to clipboard:', err);
    return false;
  }
};

type MetadataDialogProps = {
  metadata: BaseMetadata;
  title?: string;
  trigger?: React.ReactNode;
};

// Component for copy button with success feedback
const CopyButton: React.FC<{ value: any }> = ({ value }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const textToCopy = formatMetadataValue(value);
    const success = await copyToClipboard(textToCopy);

    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000); // Reset after 2 seconds
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="ml-2 p-1 rounded hover:bg-muted transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <Check className="h-3 w-3 text-green-text" />
      ) : (
        <Copy className="h-3 w-3 text-muted-foreground hover:text-primary" />
      )}
    </button>
  );
};

const MetadataDialog: React.FC<MetadataDialogProps> = ({
  metadata = {},
  title = 'Metadata Details',
  trigger,
}) => {
  const hasMetadata = !isEmptyObject(metadata);

  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger || (
          <Button
            size="sm"
            variant="outline"
            className="text-xs flex items-center gap-1 h-6 px-1 py-0.5 shadow-none"
            disabled={!hasMetadata}
          >
            <FileText className="h-3 w-3" />
            <span>Metadata</span>
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-4xl max-h-[80vh] flex flex-col p-3">
        <DialogHeader>
          <DialogTitle className="text-base font-medium">{title}</DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-auto custom-scrollbar">
          <div className="space-y-3">
            {hasMetadata ? (
              <div className="bg-secondary rounded-lg border border-border overflow-hidden">
                <div className="divide-y divide-border">
                  {Object.entries(metadata).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex p-2 hover:bg-muted transition-colors"
                    >
                      <div className="w-1/3 font-medium text-sm text-primary break-words pr-4">
                        {key}
                      </div>
                      <div className="w-2/3 text-sm text-muted-foreground break-words whitespace-pre-wrap font-mono text-xs flex items-start justify-between">
                        <span className="flex-1">
                          {formatMetadataValue(value)}
                        </span>
                        <CopyButton value={value} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No metadata available
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <DialogClose asChild>
            <Button variant="outline" size="sm">
              Close
            </Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default MetadataDialog;
