import AttributeFinder from './AttributeFinder';
import ExperimentViewer from './ExperimentViewer';
import { Card } from '@/components/ui/card';
import { useState } from 'react';

interface GlobalViewProps {
  onShowDatapoint: (datapointId: string, blockId?: number) => void;
}

const GlobalView = ({ onShowDatapoint }: GlobalViewProps) => {
  const [rewrittenQuery, setRewrittenQuery] = useState<string | undefined>();

  return (
    <>
      <Card className="h-full flex-1 p-3">
        <ExperimentViewer onShowDatapoint={onShowDatapoint} />
      </Card>

      <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3">
        <AttributeFinder onShowDatapoint={onShowDatapoint} />
      </Card>
    </>
  );
};

export default GlobalView;
