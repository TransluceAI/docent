import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useFrameGrid } from '../contexts/FrameGridContext';

interface ClusterProposalDialogProps {
  isOpen: boolean;
  onClose: () => void;
  proposals: string[][];
  clusterSessionId: string;
}

export default function ClusterProposalDialog({
  isOpen,
  onClose,
  proposals,
  clusterSessionId,
}: ClusterProposalDialogProps) {
  const fg = useFrameGrid();
  const { sendMessage } = fg;
  const [selectedProposal, setSelectedProposal] = useState<number | null>(null);
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);

  const handleSubmit = () => {
    if (showFeedback) {
      sendMessage('cluster_response', {
        cluster_id: clusterSessionId,
        feedback: feedback,
      });
    } else if (selectedProposal !== null) {
      sendMessage('cluster_response', {
        cluster_id: clusterSessionId,
        choice: selectedProposal,
      });
    }
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Choose Cluster Proposal</DialogTitle>
        </DialogHeader>

        <ScrollArea className="h-full">
          <div className="space-y-3">
            {!showFeedback && (
              <RadioGroup
                value={selectedProposal?.toString()}
                onValueChange={(value) => setSelectedProposal(parseInt(value))}
                className="space-y-2"
              >
                {proposals.map((proposal, idx) => (
                  <div
                    key={idx}
                    className="flex items-start space-x-2 p-2 border rounded-lg hover:bg-gray-50"
                  >
                    <RadioGroupItem
                      value={idx.toString()}
                      id={`proposal-${idx}`}
                      className="mt-0.5"
                    />
                    <Label
                      htmlFor={`proposal-${idx}`}
                      className="text-sm leading-relaxed flex-1"
                    >
                      <div className="font-medium text-xs mb-1">
                        Proposal {idx + 1}
                      </div>
                      <div className="space-y-1">
                        {proposal.map((centroid, i) => (
                          <div
                            key={i}
                            className="text-gray-600 text-xs p-1 bg-gray-100 rounded"
                          >
                            {centroid}
                          </div>
                        ))}
                      </div>
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            )}

            {showFeedback && (
              <div className="space-y-1.5">
                <Label htmlFor="feedback" className="text-sm">
                  Feedback
                </Label>
                <Input
                  id="feedback"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Enter your feedback..."
                  className="w-full text-xs"
                />
              </div>
            )}
          </div>
        </ScrollArea>

        <div className="flex justify-between border-t pt-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowFeedback(!showFeedback)}
          >
            {showFeedback ? 'Show Proposals' : 'Give Feedback Instead'}
          </Button>
          <div className="space-x-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSubmit}
              disabled={
                (!showFeedback && selectedProposal === null) ||
                (showFeedback && !feedback.trim())
              }
            >
              Submit
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
