import { useState } from 'react';
import { Settings2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { ModelOption } from '@/app/store/rubricSlice';
import OutputSchemaDialog from '../OutputSchemaDialog';
import { SchemaDefinition } from '@/app/types/schema';
import ModelPicker from '@/components/ModelPicker';

interface SettingsPopoverProps {
  judgeModel: ModelOption;
  availableJudgeModels?: ModelOption[];
  onChange: (jm: ModelOption) => void;
  outputSchema?: SchemaDefinition | null;
  onSchemaChange?: (schema: SchemaDefinition) => void;
  editable?: boolean;
}

export default function SettingsPopover({
  judgeModel,
  availableJudgeModels,
  onChange,
  outputSchema,
  onSchemaChange,
  editable = true,
}: SettingsPopoverProps) {
  const [isSchemaDialogOpen, setIsSchemaDialogOpen] = useState(false);
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
        {judgeModel?.uses_byok && (
          <div className="text-xs text-muted-foreground">
            This model uses your own API key.
          </div>
        )}
        {outputSchema && onSchemaChange && (
          <div className="flex flex-col">
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Output Schema Preview
            </label>
            <div className="text-xs font-mono bg-secondary rounded p-2 text-muted-foreground space-y-0.5 mb-2">
              {outputSchema.properties &&
                Object.entries(outputSchema.properties).map(([key, value]) => {
                  let renderedValue: any = value.type;
                  if ('enum' in value) {
                    renderedValue = 'enum';
                  }

                  return (
                    <div key={key}>
                      {key}: {renderedValue}
                    </div>
                  );
                })}
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => setIsSchemaDialogOpen(true)}
              disabled={!editable}
            >
              Edit Schema
            </Button>
          </div>
        )}
      </PopoverContent>
      {outputSchema && onSchemaChange && (
        <OutputSchemaDialog
          open={isSchemaDialogOpen}
          onOpenChange={setIsSchemaDialogOpen}
          initialSchema={outputSchema}
          onSave={(schema) => {
            onSchemaChange(schema);
            setIsSchemaDialogOpen(false);
          }}
          editable={editable}
        />
      )}
    </Popover>
  );
}
