import { FileText } from 'lucide-react';
import React from 'react';

import {
  BaseMetadata,
  BaseAgentRunMetadata,
} from '@/app/types/transcriptTypes';
import { Badge } from '@/components/ui/badge';
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

type MetadataDialogProps = {
  agentRunMetadata?: BaseAgentRunMetadata;
  transcriptMetadata?: BaseMetadata;
  trigger?: React.ReactNode;
};

const MetadataDialog: React.FC<MetadataDialogProps> = ({
  agentRunMetadata = {},
  transcriptMetadata = {},
  trigger,
}) => {
  const hasMetadata =
    !isEmptyObject(agentRunMetadata) || !isEmptyObject(transcriptMetadata);

  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger || (
          <Button
            size="sm"
            variant="outline"
            className="text-xs flex items-center gap-1 h-6 px-1 py-0.5"
            disabled={!hasMetadata}
          >
            <FileText className="h-3 w-3" />
            <span>Metadata</span>
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-6xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-lg font-medium">
            Metadata Details
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-auto custom-scrollbar">
          <div className="space-y-4 pb-2">
            {/* Agent Run Metadata */}
            {!isEmptyObject(agentRunMetadata) && (
              <div className="space-y-2">
                <div className="flex items-center">
                  <h3 className="text-sm font-semibold text-gray-900">
                    Agent Run Metadata
                  </h3>
                  <Badge
                    variant="outline"
                    className="ml-2 text-xs bg-blue-50 text-blue-700 border-blue-200"
                  >
                    {Object.keys(agentRunMetadata).length} fields
                  </Badge>
                </div>
                <div className="bg-gray-50 rounded-md border border-gray-100 overflow-hidden">
                  <div className="divide-y divide-gray-100">
                    {Object.entries(agentRunMetadata)
                      .filter(([key]) => key !== 'run_id')
                      .map(([key, value]) => (
                        <div
                          key={key}
                          className="flex p-2 hover:bg-gray-100 transition-colors"
                        >
                          <div className="w-1/3 font-medium text-sm text-gray-700 break-words pr-4">
                            {key}
                          </div>
                          <div className="w-2/3 text-sm text-gray-600 break-words whitespace-pre-wrap font-mono text-xs">
                            {formatMetadataValue(value)}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            )}

            {/* Transcript Metadata */}
            {!isEmptyObject(transcriptMetadata) && (
              <div className="space-y-2">
                <div className="flex items-center">
                  <h3 className="text-sm font-semibold text-gray-900">
                    Transcript Metadata
                  </h3>
                  <Badge
                    variant="outline"
                    className="ml-2 text-xs bg-green-50 text-green-700 border-green-200"
                  >
                    {Object.keys(transcriptMetadata).length} fields
                  </Badge>
                </div>
                <div className="bg-gray-50 rounded-md border border-gray-100 overflow-hidden">
                  <div className="divide-y divide-gray-100">
                    {Object.entries(transcriptMetadata).map(([key, value]) => (
                      <div
                        key={key}
                        className="flex p-2 hover:bg-gray-100 transition-colors"
                      >
                        <div className="w-1/3 font-medium text-sm text-gray-700 break-words pr-4">
                          {key}
                        </div>
                        <div className="w-2/3 text-sm text-gray-600 break-words whitespace-pre-wrap font-mono text-xs">
                          {formatMetadataValue(value)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* No metadata case */}
            {!hasMetadata && (
              <div className="text-center py-8 text-gray-500">
                No metadata available
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end pt-1">
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
