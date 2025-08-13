import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Loader2, UploadIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import { apiRestClient } from '../services/apiService';
import { toast } from '@/hooks/use-toast';

const uploadStates = {
  INACTIVE: 'inactive',
  PROCESSING: 'processing',
  REVIEWING: 'reviewing',
  UPLOADING: 'uploading',
} as const;

type UploadState = (typeof uploadStates)[keyof typeof uploadStates];

interface PreviewResult {
  status: string;
  would_import: {
    num_agent_runs: number;
    models: string[];
    task_ids: string[];
    score_types: string[];
  };
  file_info: {
    filename: string;
    task?: string;
    model?: string;
    total_samples: number;
  };
  sample_preview: Array<{
    metadata: Record<string, any>;
    num_messages: number;
  }>;
}

interface UploadRunsDialogProps {
  isOpen: boolean;
  onClose: () => void;
  file: File | null;
  onImportSuccess?: (result: {
    status: string;
    message: string;
    num_runs_imported: number;
    filename: string;
    task_id?: string;
    model?: string;
  }) => void;
}

export default function UploadRunsDialog({
  isOpen,
  onClose,
  file,
  onImportSuccess,
}: UploadRunsDialogProps) {
  const [uploadState, setUploadState] = useState<UploadState>(
    uploadStates.INACTIVE
  );
  const [error, setError] = useState<string>('');
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(
    null
  );
  const [currentSampleIndex, setCurrentSampleIndex] = useState<number>(0);
  const params = useParams();
  const collection_id = params.collection_id as string;

  // Process file when dialog opens with a file
  useEffect(() => {
    if (isOpen && file && uploadState === uploadStates.INACTIVE) {
      processFile(file);
    }
  }, [isOpen, file]);

  const processFile = async (selectedFile: File) => {
    setUploadState(uploadStates.PROCESSING);
    setError('');
    setPreviewResult(null);

    // Validate file extension
    const validExtensions = ['.eval', '.json'];
    const fileExtension = selectedFile.name.toLowerCase();
    const hasValidExtension = validExtensions.some((ext) =>
      fileExtension.endsWith(ext)
    );

    if (!hasValidExtension) {
      setError(
        `Invalid file type. Please upload a file with one of these extensions: ${validExtensions.join(', ')}`
      );
      setUploadState(uploadStates.REVIEWING);
      return;
    }

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await apiRestClient.post(
        `/${collection_id}/preview_import_runs_from_file`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      );

      setUploadState(uploadStates.REVIEWING);
      setPreviewResult(response.data);
      setCurrentSampleIndex(0);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Preview failed');
      setUploadState(uploadStates.REVIEWING);
    }
  };

  const handleImport = async () => {
    if (!file) return;

    setError('');
    setUploadState(uploadStates.UPLOADING);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await apiRestClient.post(
        `/${collection_id}/import_runs_from_file`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      );

      try {
        // await apiRestClient.post(`/${collection_id}/compute_embeddings`);
        toast({
          title: 'Runs Imported',
          description: `${previewResult?.would_import.num_agent_runs ?? 0} runs have been imported successfully.`, // Embeddings computation started.`,
        });
      } catch (embeddingError: any) {
        console.error(
          'Failed to start embeddings computation:',
          embeddingError.response?.data || embeddingError
        );
        toast({
          title: 'Runs Imported',
          description: `${previewResult?.would_import.num_agent_runs ?? 0} runs have been imported successfully. Embeddings computation failed to start - you can manually trigger it later.`,
        });
      }

      if (onImportSuccess) {
        onImportSuccess({
          status: response.data.status || 'success',
          message: response.data.message || 'Import completed successfully',
          num_runs_imported:
            response.data.num_runs_imported ||
            previewResult?.would_import.num_agent_runs ||
            0,
          filename: response.data.filename || file.name,
          task_id: response.data.task_id,
          model: response.data.model,
        });
      }

      handleClose();
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Import failed');
      setUploadState(uploadStates.REVIEWING);
    }
  };

  const handleClose = () => {
    setUploadState(uploadStates.INACTIVE);
    onClose();
  };

  const showTruncationTooltip =
    previewResult &&
    previewResult.would_import.num_agent_runs >
      previewResult.sample_preview.length &&
    currentSampleIndex === previewResult.sample_preview.length - 1;

  return (
    <Dialog open={isOpen} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          {previewResult ? (
            <DialogTitle>
              Upload &quot;{previewResult.file_info.filename}&quot;
            </DialogTitle>
          ) : (
            <DialogTitle>Import Inspect Log</DialogTitle>
          )}
        </DialogHeader>

        {uploadState === uploadStates.PROCESSING && (
          <div className="flex flex-col items-center space-y-2 py-8">
            <Loader2 className="h-10 w-10 animate-spin text-muted-foreground" />
            <div className="text-sm text-muted-foreground">
              Processing file...
            </div>
          </div>
        )}

        {error && <div className="text-sm text-red-600">Error: {error}</div>}
        {previewResult && (
          <div className="space-y-4">
            <div className="space-y-4 border rounded-lg p-4">
              <div className="overflow-x-auto">
                <table className="table-auto w-full text-sm">
                  <tbody>
                    <tr>
                      <td className="font-bold">Agent Runs</td>
                      <td>{previewResult.would_import.num_agent_runs}</td>
                    </tr>
                    <tr>
                      <td className="font-bold">Task</td>
                      <td>{previewResult.file_info.task || 'Unknown'}</td>
                    </tr>
                    <tr>
                      <td className="font-bold">Model</td>
                      <td>{previewResult.file_info.model || 'Unknown'}</td>
                    </tr>
                    {previewResult.would_import.score_types.length > 0 && (
                      <tr>
                        <td className="font-bold">Score Types</td>
                        <td>
                          {previewResult.would_import.score_types.join(', ')}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {previewResult.sample_preview.length > 0 && (
              <div className="text-sm">
                <div className="flex items-center justify-between mb-2">
                  <strong>Run metadata</strong>
                  <div className="flex items-center space-x-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setCurrentSampleIndex(
                          Math.max(0, currentSampleIndex - 1)
                        )
                      }
                      disabled={currentSampleIndex === 0}
                    >
                      <ChevronLeft size={16} />
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      Run {currentSampleIndex + 1} of{' '}
                      {previewResult.would_import.num_agent_runs}
                    </span>
                    <Tooltip open={showTruncationTooltip ?? false}>
                      <TooltipTrigger asChild>
                        <div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setCurrentSampleIndex(
                                Math.min(
                                  previewResult.sample_preview.length - 1,
                                  currentSampleIndex + 1
                                )
                              )
                            }
                            disabled={
                              currentSampleIndex ===
                              previewResult.sample_preview.length - 1
                            }
                          >
                            <ChevronRight size={16} />
                          </Button>
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        Preview only includes the first{' '}
                        {previewResult.sample_preview.length} runs
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>
                {(() => {
                  const currentSample =
                    previewResult.sample_preview[currentSampleIndex];
                  if (!currentSample) return null;

                  return (
                    <div className="space-y-2">
                      <div className="bg-secondary p-3 rounded-md text-xs font-mono h-[500px] overflow-y-auto border">
                        <pre className="whitespace-pre-wrap break-all">
                          {JSON.stringify(currentSample.metadata, null, 2)}
                        </pre>
                      </div>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <div className="flex space-x-2">
            <Button
              onClick={handleImport}
              disabled={!!error || uploadState !== uploadStates.REVIEWING}
            >
              {uploadState === uploadStates.UPLOADING && (
                <Loader2 size={16} className="animate-spin mr-2" />
              )}
              {uploadState !== uploadStates.UPLOADING && (
                <UploadIcon size={16} className="mr-2" />
              )}
              Import {previewResult?.would_import.num_agent_runs ?? ''} Runs
            </Button>
            <Button variant="outline" onClick={handleClose}>
              Cancel
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
