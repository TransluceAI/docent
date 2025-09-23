import { KeyRound } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipPortal,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ModelOption } from '@/app/store/rubricSlice';
import { cn } from '@/lib/utils';
import { useMemo } from 'react';

function nameModel(model: ModelOption, shortenName = false) {
  if (shortenName) {
    // TODO: more general/clean way to shorten names like this
    if (model.model_name.startsWith('claude-sonnet-4-')) {
      return 'claude-sonnet-4';
    }
    return `${model.model_name}`;
  }

  if (model.reasoning_effort) {
    return `${model.provider}/${model.model_name} (${model.reasoning_effort} reasoning effort)`;
  }
  return `${model.provider}/${model.model_name}`;
}

interface ModelPickerProps {
  selectedModel: ModelOption;
  availableModels?: ModelOption[];
  onChange: (model: ModelOption) => void;
  disabled?: boolean;
  className?: string;
  borderless?: boolean;
  shortenName?: boolean;
}

export default function ModelPicker({
  selectedModel,
  availableModels,
  onChange,
  disabled = false,
  className = 'w-full h-7 text-xs border bg-background px-2 font-normal',
  borderless = false,
  shortenName = false,
}: ModelPickerProps) {
  // availableModels may have info (e.g. uses_byok) that is not stored in the database.
  // So when selectedModel comes from the database we need to get that info from availableModels
  const selectedModelWithInfo = useMemo(() => {
    const availableSelectedModel = availableModels?.find(
      (m) =>
        m.model_name === selectedModel.model_name &&
        m.provider === selectedModel.provider &&
        m.reasoning_effort === selectedModel.reasoning_effort
    );
    return availableSelectedModel ?? selectedModel;
  }, [selectedModel, availableModels]);

  return (
    <TooltipProvider>
      <Select
        value={nameModel(selectedModel)}
        onValueChange={(value) => {
          const selected = availableModels?.find(
            (model) => nameModel(model) === value
          );
          if (!selected) return;
          onChange(selected);
        }}
        disabled={disabled}
      >
        <SelectTrigger
          className={cn(
            className,
            borderless &&
              'border-none shadow-none text-muted-foreground hover:text-foreground focus:ring-0 focus:border-none'
          )}
        >
          <div className="flex flex-row items-center gap-1 w-full">
            <span className="flex-1 truncate">
              {nameModel(selectedModel, shortenName)}
            </span>
            {selectedModelWithInfo?.uses_byok && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <KeyRound className="h-3 w-3 flex-shrink-0" />
                </TooltipTrigger>
                <TooltipPortal>
                  <TooltipContent side="top">
                    <p>This model uses your own API key</p>
                  </TooltipContent>
                </TooltipPortal>
              </Tooltip>
            )}
          </div>
        </SelectTrigger>
        <SelectContent>
          {availableModels?.map((model) => (
            <SelectItem
              key={nameModel(model)}
              value={nameModel(model)}
              className="text-xs"
            >
              <span className="flex flex-row items-center gap-1">
                <span className="flex-1">{nameModel(model)}</span>
                {model.uses_byok && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <KeyRound className="h-3 w-3 flex-shrink-0" />
                    </TooltipTrigger>
                    <TooltipPortal>
                      <TooltipContent>
                        <p>This model uses your own API key</p>
                      </TooltipContent>
                    </TooltipPortal>
                  </Tooltip>
                )}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TooltipProvider>
  );
}
