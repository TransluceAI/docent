'use client';

import {
  Pencil,
  Trash,
  Square,
  Check,
  ArrowDown,
  ArrowUp,
  Plus,
  Save,
} from 'lucide-react';
import { useState, useEffect } from 'react';

import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';

import { type Rubric } from '@/app/store/rubricSlice';

import { useHasCollectionWritePermission } from '@/lib/permissions/hooks';

interface RubricEditorProps {
  initRubric: Rubric;
  onSave: (rubric: Rubric) => void;
  onCloseWithoutSave?: () => void;
  readOnly?: boolean;
}

export default function RubricEditor({
  initRubric,
  onSave,
  onCloseWithoutSave,
  readOnly = false,
}: RubricEditorProps) {
  const hasWritePermission = useHasCollectionWritePermission();
  const isDisabled = readOnly || !hasWritePermission;

  // Deep copy the initial rubric into local state
  const [rubric, setRubric] = useState<Rubric>(() => {
    return JSON.parse(JSON.stringify(initRubric));
  });

  // When the initRubric changes, update the local state
  useEffect(() => {
    setRubric(JSON.parse(JSON.stringify(initRubric)));
  }, [initRubric]);

  // Inline editing state
  const [editingInclusionRule, setEditingInclusionRule] = useState<
    number | null
  >(null);
  const [editingExclusionRule, setEditingExclusionRule] = useState<
    number | null
  >(null);
  const [editingText, setEditingText] = useState<string>('');

  // Helper function to create a new rubric with updates
  const updateRubric = (updates: Partial<Rubric>) => {
    setRubric((prev) => ({
      ...prev,
      ...updates,
    }));
  };

  // Handler functions for rubric editing
  const handleDescriptionChange = (
    e: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    if (readOnly) return;
    updateRubric({ high_level_description: e.target.value });
  };

  const handleEditInclusionRule = (index: number) => {
    if (readOnly) return;
    // Cancel any existing edit
    setEditingExclusionRule(null);
    setEditingInclusionRule(index);
    setEditingText(rubric.inclusion_rules[index] || '');
  };

  const handleEditExclusionRule = (index: number) => {
    if (readOnly) return;
    // Cancel any existing edit
    setEditingInclusionRule(null);
    setEditingExclusionRule(index);
    setEditingText(rubric.exclusion_rules[index] || '');
  };

  const handleSaveEdit = () => {
    if (editingInclusionRule !== null) {
      const newInclusionRules = [...rubric.inclusion_rules];
      newInclusionRules[editingInclusionRule] = editingText;
      updateRubric({ inclusion_rules: newInclusionRules });
      setEditingInclusionRule(null);
    } else if (editingExclusionRule !== null) {
      const newExclusionRules = [...rubric.exclusion_rules];
      newExclusionRules[editingExclusionRule] = editingText;
      updateRubric({ exclusion_rules: newExclusionRules });
      setEditingExclusionRule(null);
    }
    setEditingText('');
  };

  const handleCancelEdit = () => {
    setEditingInclusionRule(null);
    setEditingExclusionRule(null);
    setEditingText('');
  };

  const handleDeleteInclusionRule = (index: number) => {
    if (readOnly) return;
    const newInclusionRules = rubric.inclusion_rules.filter(
      (_: string, i: number) => i !== index
    );
    updateRubric({ inclusion_rules: newInclusionRules });
  };

  const handleDeleteExclusionRule = (index: number) => {
    if (readOnly) return;
    const newExclusionRules = rubric.exclusion_rules.filter(
      (_: string, i: number) => i !== index
    );
    updateRubric({ exclusion_rules: newExclusionRules });
  };

  const handleMoveInclusionToExclusion = (index: number) => {
    if (readOnly) return;
    const rule = rubric.inclusion_rules[index];
    const newInclusionRules = rubric.inclusion_rules.filter(
      (_: string, i: number) => i !== index
    );
    const newExclusionRules = [...rubric.exclusion_rules, rule];
    updateRubric({
      inclusion_rules: newInclusionRules,
      exclusion_rules: newExclusionRules,
    });
  };

  const handleMoveExclusionToInclusion = (index: number) => {
    if (readOnly) return;
    const rule = rubric.exclusion_rules[index];
    const newExclusionRules = rubric.exclusion_rules.filter(
      (_: string, i: number) => i !== index
    );
    const newInclusionRules = [...rubric.inclusion_rules, rule];
    updateRubric({
      inclusion_rules: newInclusionRules,
      exclusion_rules: newExclusionRules,
    });
  };

  const handleAddInclusionRule = () => {
    if (readOnly) return;
    // Cancel any existing edit
    setEditingExclusionRule(null);
    const newInclusionRules = [...rubric.inclusion_rules, ''];
    updateRubric({ inclusion_rules: newInclusionRules });
    const newIndex = newInclusionRules.length - 1;
    setEditingInclusionRule(newIndex);
    setEditingText('');
  };

  const handleAddExclusionRule = () => {
    if (readOnly) return;
    // Cancel any existing edit
    setEditingInclusionRule(null);
    const newExclusionRules = [...rubric.exclusion_rules, ''];
    updateRubric({ exclusion_rules: newExclusionRules });
    const newIndex = newExclusionRules.length - 1;
    setEditingExclusionRule(newIndex);
    setEditingText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSaveEdit();
    } else if (e.key === 'Escape') {
      handleCancelEdit();
    }
  };

  const handleSave = () => {
    onSave(rubric);
  };

  return (
    <div className="border rounded-sm bg-secondary p-2 space-y-2 relative">
      {/* High-level Description */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-primary">
          High-level Description
        </div>
        <div className="relative overflow-hidden rounded-md border bg-background focus-within:ring-1 focus-within:ring-ring">
          <Textarea
            className="h-[6rem] resize-none border-0 p-2 shadow-none focus-visible:ring-0 text-xs font-mono"
            placeholder="Enter a high-level description of what this rubric evaluates..."
            value={rubric.high_level_description || ''}
            onChange={handleDescriptionChange}
            disabled={isDisabled}
          />
        </div>
      </div>

      {/* Inclusion Rules */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-primary">
          Inclusion Rules
        </div>
        <div className="space-y-0.5">
          {rubric.inclusion_rules.map((rule: string, index: number) => (
            <div
              key={index}
              className={`group flex items-center gap-2 py-1.5 px-2 rounded border transition-all duration-200 ${
                editingInclusionRule === index
                  ? 'border-green-border bg-green-bg/60 shadow-md'
                  : 'border-green-border bg-green-bg/30 hover:bg-green-bg/50 hover:shadow-sm'
              }`}
            >
              <div className="w-1.5 h-1.5 rounded-full bg-green-text flex-shrink-0"></div>
              {editingInclusionRule === index ? (
                <div className="flex-1 flex items-center gap-2">
                  <Input
                    className="text-xs font-mono bg-transparent border-0 shadow-none focus-visible:ring-0 p-0 h-auto rounded-none"
                    value={editingText}
                    onChange={(e) => setEditingText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={handleSaveEdit}
                    autoFocus
                  />
                  <div className="flex items-center gap-1">
                    <button
                      className="hover:bg-green-bg/60 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors"
                      onClick={handleSaveEdit}
                      title="Save"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                    <button
                      className="hover:bg-green-bg/60 rounded p-0.5 text-muted-foreground hover:text-red-text transition-colors"
                      onClick={handleCancelEdit}
                      title="Cancel"
                    >
                      <Square className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex-1 text-xs text-primary font-mono">
                    {rule}
                  </div>
                  {!readOnly && (
                    <div className="flex items-center gap-1">
                      <button
                        className="hover:bg-green-bg/60 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleEditInclusionRule(index)}
                        title="Edit rule"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        className="hover:bg-green-bg/60 rounded p-0.5 text-muted-foreground hover:text-red-text transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleMoveInclusionToExclusion(index)}
                        title="Move to exclusion rules"
                      >
                        <ArrowDown className="h-3 w-3" />
                      </button>
                      <button
                        className="hover:bg-green-bg/60 rounded p-0.5 text-muted-foreground hover:text-red-text transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleDeleteInclusionRule(index)}
                        title="Delete rule"
                      >
                        <Trash className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {!readOnly && (
            <button
              className="flex items-center gap-1 py-1 px-2 text-[11px] text-muted-foreground hover:text-green-text transition-colors"
              disabled={isDisabled}
              onClick={handleAddInclusionRule}
              title="Add inclusion rule"
            >
              <Plus className="h-3 w-3" />
              <span>Add rule</span>
            </button>
          )}
        </div>
      </div>

      {/* Exclusion Rules */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-primary">
          Exclusion Rules
        </div>
        <div className="space-y-0.5">
          {rubric.exclusion_rules.map((rule: string, index: number) => (
            <div
              key={index}
              className={`group flex items-center gap-2 py-1.5 px-2 rounded border transition-all duration-200 ${
                editingExclusionRule === index
                  ? 'border-red-border bg-red-bg/60 shadow-md'
                  : 'border-red-border bg-red-bg/30 hover:bg-red-bg/50 hover:shadow-sm'
              }`}
            >
              <div className="w-1.5 h-1.5 rounded-full bg-red-text flex-shrink-0"></div>
              {editingExclusionRule === index ? (
                <div className="flex-1 flex items-center gap-2">
                  <Input
                    className="text-xs font-mono bg-transparent border-0 shadow-none focus-visible:ring-0 p-0 h-auto rounded-none"
                    value={editingText}
                    onChange={(e) => setEditingText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={handleSaveEdit}
                    autoFocus
                  />
                  <div className="flex items-center gap-1">
                    <button
                      className="hover:bg-red-bg/60 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors"
                      onClick={handleSaveEdit}
                      title="Save"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                    <button
                      className="hover:bg-red-bg/60 rounded p-0.5 text-muted-foreground hover:text-red-text transition-colors"
                      onClick={handleCancelEdit}
                      title="Cancel"
                    >
                      <Square className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex-1 text-xs text-primary font-mono">
                    {rule}
                  </div>
                  {!readOnly && (
                    <div className="flex items-center gap-1">
                      <button
                        className="hover:bg-red-bg/60 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleEditExclusionRule(index)}
                        title="Edit rule"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        className="hover:bg-red-bg/60 rounded p-0.5 text-muted-foreground hover:text-green-text transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleMoveExclusionToInclusion(index)}
                        title="Move to inclusion rules"
                      >
                        <ArrowUp className="h-3 w-3" />
                      </button>
                      <button
                        className="hover:bg-red-bg/60 rounded p-0.5 text-muted-foreground hover:text-red-text transition-colors"
                        disabled={isDisabled}
                        onClick={() => handleDeleteExclusionRule(index)}
                        title="Delete rule"
                      >
                        <Trash className="h-3 w-3" />
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
          {!readOnly && (
            <button
              className="flex items-center gap-1 py-1 px-2 text-[11px] text-muted-foreground hover:text-red-text transition-colors"
              disabled={isDisabled}
              onClick={handleAddExclusionRule}
              title="Add exclusion rule"
            >
              <Plus className="h-3 w-3" />
              <span>Add rule</span>
            </button>
          )}
        </div>
      </div>

      {/* Save Button */}
      {!readOnly && (
        <div className="flex justify-end pt-2 gap-2">
          {onCloseWithoutSave && (
            <Button size="sm" variant="outline" onClick={onCloseWithoutSave}>
              Cancel
            </Button>
          )}
          <Button
            size="sm"
            disabled={isDisabled}
            onClick={handleSave}
            className="gap-1.5"
          >
            <Save className="h-4 w-4" />
            Save
          </Button>
        </div>
      )}
    </div>
  );
}
