import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import TaPanel from './TaPanel';
import TranscriptViewer from './TranscriptViewer';
import { ScrollArea } from '@/components/ui/scroll-area';
import TaskSummary from './TaskSummary';
import AgentSummary from './AgentSummary';
import { Datapoint, ActionsSummary, SolutionSummary } from '@/app/types/docent';
import { useFrameGrid } from '../../../contexts/FrameGridContext';
interface TranscriptViewProps {
  datapoint: Datapoint | null;
  solutionSummary: SolutionSummary | null;
  actionsSummary: ActionsSummary | null;
  transcriptViewerRef: React.RefObject<{
    scrollToBlock: (blockIndex: number) => void;
  }>;
  onShowDatapoint: (datapointId: string, blockId?: number) => void;
}

const TranscriptView = ({
  datapoint,
  solutionSummary,
  actionsSummary,
  transcriptViewerRef,
  onShowDatapoint,
}: TranscriptViewProps) => {
  const { loadingActionsSummaryFor } = useFrameGrid();

  return (
    <>
      <Card className="h-full overflow-y-auto flex-1 p-3">
        <TranscriptViewer
          ref={transcriptViewerRef}
          datapoint={datapoint}
          attributes={datapoint?.attributes || {}}
        />
      </Card>
      <Card className="h-full overflow-y-auto flex-1 p-3">
        <Tabs defaultValue="agent" className="h-full flex flex-col">
          <TabsList className="grid w-full grid-cols-3 h-8">
            <TabsTrigger value="agent" className="text-xs">
              Agent Summary
            </TabsTrigger>
            <TabsTrigger value="task" className="text-xs">
              Task Summary
            </TabsTrigger>
            <TabsTrigger value="chat" className="text-xs">
              Chat
            </TabsTrigger>
          </TabsList>

          <TabsContent value="task" className="flex-1 mt-0">
            <ScrollArea className="h-full px-1 py-2">
              <TaskSummary
                datapoint={datapoint}
                solutionSummary={solutionSummary}
              />
            </ScrollArea>
          </TabsContent>

          <TabsContent value="agent" className="flex-1 mt-0">
            <ScrollArea className="h-full px-1 py-2">
              <AgentSummary
                datapoint={datapoint}
                actionsSummary={actionsSummary}
                onCitationClick={onShowDatapoint}
              />
            </ScrollArea>
          </TabsContent>

          <TabsContent value="chat" className="flex-1 mt-0">
            <div className="h-full px-1 py-2">
              <TaPanel onShowDatapoint={onShowDatapoint} />
            </div>
          </TabsContent>
        </Tabs>
      </Card>
    </>
  );
};

export default TranscriptView;
