// import { Card } from '@/components/ui/card';
// import AgentSummary from '../../transcript/components/AgentSummary';
// import { useFrameGrid } from '../../../contexts/FrameGridContext';
// import { useEffect } from 'react';
// import ReactMarkdown from 'react-markdown';

// interface TranscriptCompareProps {
//   datapointId1: string;
//   datapointId2: string;
// }

// export function TranscriptCompare({
//   datapointId1,
//   datapointId2,
// }: TranscriptCompareProps) {
//   const {
//     curDatapoint,
//     diffDatapoint,
//     actionsSummary,
//     actionsSummaryDiff,
//     requestTranscriptDiff,
//     transcriptComparison,
//     sendMessage,
//   } = useFrameGrid();

//   useEffect(() => {
//     if (datapointId1 && datapointId2) {
//       requestTranscriptDiff(datapointId1, datapointId2);
//     }
//   }, [datapointId1, datapointId2]);

//   useEffect(() => {
//     if (datapointId1) {
//       sendMessage('get_datapoint', {
//         datapoint_id: datapointId1,
//       });
//       sendMessage('get_diff_datapoint', {
//         datapoint_id: datapointId2,
//       });
//     }
//   }, [datapointId1, datapointId2]);

//   return (
//     <>
//       <Card className="h-full w-1/4 min-w-0 p-3 text-sm">
//         <div className="text-sm font-semibold">Summary of Differences</div>
//         <div
//           className="prose prose-sm max-w-none text-black
//                   prose-p:my-0.5 prose-p:leading-normal prose-p:text-black
//                   prose-headings:mt-2 prose-headings:mb-1 prose-headings:text-black
//                   prose-ul:my-0.5 prose-ul:pl-4
//                   prose-ol:my-0.5 prose-ol:pl-4
//                   prose-li:my-0 prose-li:leading-normal prose-li:text-black
//                   prose-code:px-1 prose-code:py-0.5 prose-code:bg-slate-50 prose-code:rounded prose-code:text-black
//                   prose-pre:my-1 prose-pre:p-2 prose-pre:bg-slate-50 prose-pre:rounded
//                   prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
//                   prose-hr:my-2
//                   prose-blockquote:my-1 prose-blockquote:pl-2 prose-blockquote:border-l-2 prose-blockquote:border-slate-200 prose-blockquote:italic prose-blockquote:text-black"
//         >
//           {transcriptComparison?.text ? (
//             <ReactMarkdown>{transcriptComparison.text}</ReactMarkdown>
//           ) : (
//             <div className="animate-pulse space-y-1">
//               <div className="h-4 bg-slate-100 rounded w-3/4"></div>
//               <div className="h-4 bg-slate-100 rounded w-2/3"></div>
//               <div className="h-4 bg-slate-100 rounded w-4/5"></div>
//             </div>
//           )}
//         </div>
//       </Card>
//       <Card className="h-full flex-1 min-w-0 p-3">
//         <AgentSummary
//           datapoint={curDatapoint}
//           actionsSummary={actionsSummary}
//         />
//       </Card>
//       <Card className="h-full flex-1 min-w-0 p-3">
//         <AgentSummary
//           datapoint={diffDatapoint}
//           actionsSummary={actionsSummaryDiff}
//         />
//       </Card>
//     </>
//   );
// }
