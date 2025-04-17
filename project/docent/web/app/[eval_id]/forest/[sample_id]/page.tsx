'use client';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import TranscriptGraph from '../components/TranscriptGraph';
import ExperimentGraph from '../components/ExperimentGraph';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export default function ExperimentPage() {
  const params = useParams();
  const sampleId = params.sample_id;
  const [graphType, setGraphType] = useState<'transcript' | 'experiment'>(
    'transcript'
  );

  // Handle tab change
  const handleTabChange = (value: string) => {
    setGraphType(value as 'transcript' | 'experiment');
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Graph type tabs */}
      <div className="bg-white mb-4">
        <Tabs
          defaultValue="transcript"
          value={graphType}
          onValueChange={handleTabChange}
          className="w-full"
        >
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="transcript">Transcript Tree</TabsTrigger>
            <TabsTrigger value="experiment">Experiment Tree</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Graph container */}
      <div className="flex-1 min-h-0">
        {typeof sampleId === 'string' || typeof sampleId === 'number' ? (
          <>
            {graphType === 'transcript' ? (
              <TranscriptGraph sampleId={sampleId} />
            ) : (
              <ExperimentGraph sampleId={sampleId} />
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center min-h-0">
            <p className="text-gray-500">Invalid sample ID</p>
          </div>
        )}
      </div>
    </div>
  );
}
