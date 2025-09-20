import { Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { ModelOption } from '@/app/store/rubricSlice';
import ModelPicker from '@/components/ModelPicker';

interface SettingsPopoverProps {
  judgeModel: ModelOption;
  availableJudgeModels?: ModelOption[];
  onChange: (jm: ModelOption) => void;
  editable?: boolean;
}

export default function SettingsPopover({
  judgeModel,
  availableJudgeModels,
  onChange,
  editable = true,
}: SettingsPopoverProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 hover:bg-accent transition-all duration-200 text-muted-foreground hover:text-primary"
          title="Settings"
          disabled={!editable}
        >
          <Settings2 className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="center"
        sideOffset={6}
        className="max-w-60 p-3 space-y-3"
      >
        <div className="flex flex-col">
          <label className="block text-xs font-medium text-muted-foreground mb-1">
            Judge Model
          </label>
          <ModelPicker
            selectedModel={judgeModel}
            availableModels={availableJudgeModels}
            onChange={onChange}
            disabled={!editable}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
