import { KeyRound } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ModelOption } from '@/app/store/rubricSlice';
import { cn } from '@/lib/utils';
import { useMemo } from 'react';
import { Combobox, type ComboboxOption } from '@/app/components/Combobox';

function nameModel(model: ModelOption, shortenName = false) {
  if (shortenName) {
    let shortName = model.model_name;

    // TODO: more general/clean way to shorten names like this
    if (model.model_name.startsWith('claude-sonnet-4-')) {
      shortName = 'claude-sonnet-4';
    }

    // Add reasoning effort if it exists
    if (model.reasoning_effort) {
      const effort =
        model.reasoning_effort === 'medium' ? 'med' : model.reasoning_effort;
      return `${shortName} (${effort})`;
    }

    return shortName;
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
  className = '',
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

  const modelOptions = useMemo(() => {
    type ModelOptionWithValue = ComboboxOption & { model: ModelOption };

    // Stable identifier used by the combobox; reasoning effort distinguishes variants.
    const toValue = (model: ModelOption) =>
      `${model.provider}::${model.model_name}::${model.reasoning_effort ?? '__no_reasoning__'}`;

    const modelsForOptions: ModelOption[] = [];

    // Load the remote list first so we pick up BYOK metadata, quotas, etc.
    if (availableModels && availableModels.length > 0) {
      modelsForOptions.push(...availableModels);
    }

    // Ensure the currently-selected model is always present, even if it was loaded earlier
    // or removed from the latest available list.
    if (selectedModelWithInfo) {
      const hasSelected = modelsForOptions.some(
        (model) => toValue(model) === toValue(selectedModelWithInfo)
      );
      if (!hasSelected) {
        modelsForOptions.push(selectedModelWithInfo);
      }
    }

    // Fallback: if everything is empty but we still have a selected model, surface it alone.
    if (modelsForOptions.length === 0 && selectedModelWithInfo) {
      modelsForOptions.push(selectedModelWithInfo);
    }

    const valueToModel = new Map<string, ModelOption>();
    // Transform into combobox options while keeping a reverse lookup for onChange.
    const options: ModelOptionWithValue[] = modelsForOptions.map((model) => {
      const value = toValue(model);
      valueToModel.set(value, model);
      return {
        value,
        label: nameModel(model),
        keywords: [
          model.provider,
          model.model_name,
          model.reasoning_effort ?? '',
        ].filter(Boolean) as string[],
        model,
      };
    });

    return {
      options,
      valueToModel,
      toValue,
    };
  }, [availableModels, selectedModelWithInfo]);

  const { options, valueToModel, toValue } = modelOptions;

  const selectedValue = selectedModelWithInfo
    ? toValue(selectedModelWithInfo)
    : null;

  return (
    <TooltipProvider>
      <Combobox
        value={selectedValue}
        onChange={(value) => {
          const selected = valueToModel.get(value);
          if (!selected) return;
          onChange(selected);
        }}
        options={options}
        popoverAlign="start"
        placeholder="Select model"
        searchPlaceholder="Search models..."
        emptyMessage="No models found"
        triggerProps={{ disabled, variant: borderless ? 'ghost' : 'outline' }}
        triggerClassName={cn(
          'h-7 text-xs font-normal',
          className,
          borderless &&
            'border-none shadow-none text-muted-foreground hover:text-foreground hover:bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0'
        )}
        optionClassName="text-xs"
        renderValue={(selectedOption) => {
          const model = selectedOption
            ? valueToModel.get(selectedOption.value)
            : selectedModelWithInfo;
          if (!model) {
            return 'Select model';
          }
          return (
            <span className="flex items-center gap-1">
              <span className="flex-1 truncate">
                {nameModel(model, shortenName)}
              </span>
              {model.uses_byok && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <KeyRound className="h-3 w-3 flex-shrink-0" />
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>This model uses your own API key</p>
                  </TooltipContent>
                </Tooltip>
              )}
            </span>
          );
        }}
        renderOptionLabel={(option) => {
          const model = valueToModel.get(option.value);
          if (!model) {
            return option.label;
          }
          return (
            <span className="flex items-center gap-1 w-full">
              <span className="flex-1">{nameModel(model)}</span>
              {model.uses_byok && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <KeyRound className="h-3 w-3 flex-shrink-0" />
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>This model uses your own API key</p>
                  </TooltipContent>
                </Tooltip>
              )}
            </span>
          );
        }}
      />
    </TooltipProvider>
  );
}
