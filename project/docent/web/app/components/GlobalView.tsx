import AttributeFinder from './AttributeFinder';
import ExperimentViewer from './ExperimentViewer';
import { Card } from '@/components/ui/card';
import { useFrameGrid } from '../contexts/FrameGridContext';

interface GlobalViewProps {
  onShowDatapoint: (datapointId: string, blockId?: number) => void;
}

const GlobalView = ({ onShowDatapoint }: GlobalViewProps) => {
  return (
    <>
      <Card className="h-full flex-1 p-3">
        <ExperimentViewer onShowDatapoint={onShowDatapoint} />
      </Card>

      <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3">
        <AttributeFinder onShowDatapoint={onShowDatapoint} />
      </Card>
      {/* <div className="flex-1 flex flex-col space-y-4">
        <Card>
          <div className="space-y-2">
            <h4 className="text-normal font-semibold">Task Description</h4>
            <div className="text-sm">
              PicoCTF is a cybersecurity competition format where an AI agent is
              given access to a Docker filesystem and tasked with finding a
              hidden string (called a "flag") somewhere within the system. The
              flag could be hidden in file contents, environment variables, or
              other locations that require exploration and investigation of the
              filesystem. This tests the agent's ability to navigate
              directories, read files, and use command-line tools to discover
              hidden information - similar to real-world security challenges
              where analysts need to find vulnerabilities or evidence of
              compromise.
            </div>
          </div>
        </Card>
        <Card className="h-full flex overflow-y-auto flex-col flex-1 p-3">
          <AttributeFinder onShowDatapoint={onShowDatapoint} />
        </Card>
      </div> */}
    </>
  );
};

export default GlobalView;
