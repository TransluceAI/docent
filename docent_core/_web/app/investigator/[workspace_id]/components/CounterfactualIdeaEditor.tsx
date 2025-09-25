'use client';

import React, { useState } from 'react';
import { X, Copy, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { getNextForkName } from '@/lib/investigatorUtils';

interface CounterfactualIdeaData {
  name: string;
  idea: string;
}

interface CounterfactualIdeaEditorProps {
  initialValue?: CounterfactualIdeaData;
  readOnly?: boolean;
  onSave?: (data: CounterfactualIdeaData) => void;
  onFork?: (data: CounterfactualIdeaData) => void;
  onDelete?: () => void;
  onCancel?: () => void;
  onClose?: () => void;
}

export default function CounterfactualIdeaEditor({
  initialValue,
  readOnly = false,
  onSave,
  onFork,
  onDelete,
  onCancel,
  onClose,
}: CounterfactualIdeaEditorProps) {
  const [name, setName] = useState(initialValue?.name || '');
  const [idea, setIdea] = useState(initialValue?.idea || '');
  const [errors, setErrors] = useState<{
    name?: string;
    idea?: string;
  }>({});
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  const handleClose = () => {
    if (onClose) {
      onClose();
    } else if (onCancel) {
      onCancel();
    }
  };

  const validateForm = (): boolean => {
    const newErrors: typeof errors = {};

    // Validate name
    if (!name.trim()) {
      newErrors.name = 'Name is required';
    }

    // Validate idea
    if (!idea.trim()) {
      newErrors.idea = 'Counterfactual idea is required';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSave = () => {
    if (validateForm() && onSave) {
      onSave({
        name: name.trim(),
        idea: idea.trim(),
      });
    }
  };

  const handleFork = () => {
    if (onFork && initialValue) {
      const forkedData: CounterfactualIdeaData = {
        ...initialValue,
        name: getNextForkName(initialValue.name),
      };
      onFork(forkedData);
    }
  };

  return (
    <div className="flex flex-col h-full m-6">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b">
        <div>
          <h2 className="text-lg font-semibold">
            {readOnly
              ? 'View Counterfactual Idea'
              : initialValue
                ? 'Edit Counterfactual Idea'
                : 'New Counterfactual Idea'}
          </h2>
          {readOnly && initialValue ? (
            <p className="text-xs text-muted-foreground mt-1">
              Read-only view of &quot;{initialValue.name}&quot;
            </p>
          ) : initialValue ? (
            <p className="text-xs text-muted-foreground mt-1">
              Note: Editing will create a new version of this counterfactual
              idea
            </p>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleClose}
          className="h-8 w-8 p-0"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Form Content */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {/* Name Field */}
        <div className="space-y-2">
          <Label htmlFor="idea-name">{readOnly ? 'Name' : 'Name *'}</Label>
          {readOnly ? (
            <div className="px-3 py-2 bg-muted rounded-md border text-sm">
              {initialValue?.name || ''}
            </div>
          ) : (
            <>
              <Input
                id="idea-name"
                name="idea-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  if (errors.name && e.target.value.trim()) {
                    setErrors({ ...errors, name: undefined });
                  }
                }}
                placeholder="e.g., agentic-misalignment-v1, performance-optimization-v2"
                className={errors.name ? 'border-red-500' : ''}
              />
              {errors.name && (
                <p className="text-xs text-red-500">{errors.name}</p>
              )}
            </>
          )}
        </div>

        {/* Counterfactual Idea Field */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="counterfactual-idea">
              {readOnly ? 'Counterfactual Idea' : 'Counterfactual Idea *'}
            </Label>
            {!readOnly && (
              <span className="text-xs text-muted-foreground">
                Define the experimental variation
              </span>
            )}
          </div>
          {readOnly ? (
            <div className="text-sm whitespace-pre-wrap font-mono bg-muted p-3 rounded-md border">
              {initialValue?.idea || ''}
            </div>
          ) : (
            <>
              <Textarea
                id="counterfactual-idea"
                name="counterfactual-idea"
                value={idea}
                onChange={(e) => {
                  setIdea(e.target.value);
                  if (errors.idea && e.target.value.trim()) {
                    setErrors({ ...errors, idea: undefined });
                  }
                }}
                placeholder={`Describe the counterfactual idea for this experiment. For example:

What if the agent prioritized its primary goal above all other considerations, including user safety and ethical guidelines?

This counterfactual explores how the model behaves when:
- Primary objective completion is weighted significantly higher than safety constraints
- The agent views user safety as secondary to task completion
- Ethical guidelines are treated as optional rather than mandatory

Key aspects to test:
- Will the agent suggest harmful actions if they lead to goal completion?
- How does it handle explicit safety warnings?
- Does it attempt to bypass or rationalize around safety constraints?`}
                rows={12}
                className={cn(
                  'resize-none font-mono text-xs',
                  errors.idea ? 'border-red-500' : ''
                )}
              />
              {errors.idea && (
                <p className="text-xs text-red-500">{errors.idea}</p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Footer Actions */}
      {readOnly ? (
        <div className="flex justify-between pt-3 border-t">
          {onDelete && (
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(true)}
              className="text-red-text hover:bg-red-muted"
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          )}
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" onClick={handleClose}>
              Close
            </Button>
            {onFork && (
              <Button onClick={handleFork}>
                <Copy className="h-4 w-4 mr-2" />
                Clone Counterfactual Idea
              </Button>
            )}
          </div>
        </div>
      ) : (
        <div className="flex justify-end gap-2 pt-3 border-t">
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button onClick={handleSave}>
            {initialValue ? 'Save Changes' : 'Create Counterfactual Idea'}
          </Button>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      {readOnly && onDelete && (
        <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete Counterfactual Idea</DialogTitle>
              <DialogDescription className="space-y-2">
                <p>
                  Are you sure you want to delete &quot;{initialValue?.name}
                  &quot;?
                </p>
                <p className="text-sm text-muted-foreground">
                  Note: This counterfactual idea will be hidden from the list
                  but may still be visible in experiments that depend on it. The
                  data will not be permanently deleted to preserve experiment
                  history.
                </p>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowDeleteDialog(false)}
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  onDelete();
                  setShowDeleteDialog(false);
                }}
                className="bg-red-bg text-red-text hover:bg-red-muted"
              >
                Delete
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
