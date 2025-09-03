import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { PlusIcon, Upload, BookOpen, Code } from 'lucide-react';
import { useRef, useState } from 'react';
import UploadRunsDialog from './UploadRunsDialog';

interface UploadRunsButtonProps {
  onImportSuccess?: () => void;
  disabled?: boolean;
}

export default function UploadRunsButton({
  onImportSuccess,
  disabled = false,
}: UploadRunsButtonProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    const file = files[0];
    // Reset the file input so we'll get a new event if the user uploads the same file again
    event.target.value = '';

    setSelectedFile(file);
    setDialogOpen(true);
  };

  const handleDialogClose = () => {
    setDialogOpen(false);
    setSelectedFile(null);
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleUseSDKClick = () => {
    // Navigate to docs page - adjust the URL as needed for your docs
    window.open('https://docs.transluce.org/en/latest/quickstart/', '_blank');
  };

  const handleUseTracingClick = () => {
    // Navigate to tracing documentation
    window.open(
      'https://docs.transluce.org/en/latest/tracing/introduction/',
      '_blank'
    );
  };

  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.eval"
        onChange={handleFileSelect}
        style={{ display: 'none' }}
      />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="pr-2 pl-1.5"
            disabled={disabled}
          >
            <PlusIcon size={14} className="mr-1" />
            Add Data
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={handleUploadClick}>
            <Upload className="mr-2 h-4 w-4" />
            Upload Inspect Log
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleUseSDKClick}>
            <BookOpen className="mr-2 h-4 w-4" />
            Use SDK
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleUseTracingClick}>
            <Code className="mr-2 h-4 w-4" />
            Use Tracing
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <UploadRunsDialog
        isOpen={dialogOpen}
        onClose={handleDialogClose}
        file={selectedFile}
        onImportSuccess={onImportSuccess}
      />
    </div>
  );
}
