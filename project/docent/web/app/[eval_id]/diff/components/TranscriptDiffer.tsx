'use client';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  NodeMouseHandler,
  EdgeMouseHandler,
  Viewport,
  OnMove,
  ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useState, useCallback, useEffect, useMemo } from 'react';
import { useFrameGrid } from '../../../contexts/FrameGridContext';
import { useRouter } from 'next/navigation';
import dagre from '@dagrejs/dagre';

import { Handle, NodeProps, Position } from 'reactflow';
import { Card } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import ReactMarkdown from 'react-markdown';
import { Loader2 } from 'lucide-react';
import { BASE_DOCENT_PATH } from '@/app/constants';

// TranscriptTable component for displaying transcript steps
interface TranscriptTableProps {
  title: string;
  nodes: Node[];
  selectedNodeId: string | null;
  onNodeClick: (nodeId: string) => void;
  className?: string;
}

function TranscriptTable({
  title,
  nodes,
  selectedNodeId,
  onNodeClick,
  className = '',
}: TranscriptTableProps) {
  if (nodes.length === 0) return null;

  // Helper function to determine match type color
  const getMatchTypeColor = (node: Node) => {
    // Check connected edges in the node data if available
    if (node.data.matchType) {
      return node.data.matchType;
    }

    // Fallback to style border color if available
    if (node.style?.border) {
      const borderStr = String(node.style.border); // Convert to string to safely use includes
      if (borderStr.includes('#86efac')) return 'exact'; // exact match - green
      if (borderStr.includes('#fef08a')) return 'near'; // near match - yellow
      if (borderStr.includes('#fecaca')) return 'none'; // no match - red
    }

    return 'none'; // default
  };

  // Get border color based on match type
  const getMatchTypeBorderColor = (matchType: string) => {
    switch (matchType) {
      case 'exact':
        return 'border-l-4 border-l-green-300'; // exact match
      case 'near':
        return 'border-l-4 border-l-yellow-300'; // near match
      case 'none':
        return 'border-l-4 border-l-red-300'; // no match
      default:
        return '';
    }
  };

  return (
    <div className={className}>
      <div className="bg-gray-50 px-3 py-1.5 text-sm font-semibold border-y">
        {title}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b">
            <th className="font-medium text-left px-3 py-1.5 w-16">Step</th>
            <th className="font-medium text-left px-3 py-1.5">Title</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => {
            const stepNumber =
              node.data.action_unit_idx !== undefined
                ? node.data.action_unit_idx
                : node.data.starting_block_idx;

            const matchType = getMatchTypeColor(node);
            const matchTypeBorder = getMatchTypeBorderColor(matchType);

            return (
              <tr
                key={node.id}
                onClick={() => onNodeClick(node.id)}
                className={`
                  text-xs border-b cursor-pointer ${matchTypeBorder}
                  ${
                    selectedNodeId === node.id
                      ? 'bg-blue-50'
                      : 'hover:bg-gray-50'
                  }
                `}
              >
                <td className="px-3 py-1.5 font-medium">{stepNumber}</td>
                <td className="px-3 py-1.5 truncate max-w-[180px]">
                  {node.data.title || '-'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DiffNode({ data }: NodeProps): JSX.Element {
  // Extract data from node
  const actionUnitIdx = data.action_unit_idx;
  const title = data.title ?? 'Action';
  const summary = data.summary;

  // Create a title that includes the action unit index if available
  const displayTitle =
    actionUnitIdx !== undefined ? `Step ${actionUnitIdx}: ${title}` : title;

  return (
    <div className="p-2 flex-1 min-h-0 flex flex-col min-w-0 overflow-hidden group hover:bg-gray-50 transition-colors cursor-pointer rounded-lg">
      {/* Title section */}
      <div className="border-b pb-1 mb-1">
        <div className="font-semibold text-xs">{displayTitle}</div>
        <div className="text-[10px] text-gray-500 opacity-70 group-hover:opacity-100 transition-opacity">
          Click to view step in transcript
        </div>
      </div>

      {/* Summary section */}
      {summary && (
        <div className="flex-1 text-xs leading-snug overflow-auto mt-1">
          {summary}
        </div>
      )}

      {/* Add handles: top/bottom for chain, left/right for near/exact */}
      <Handle type="target" position={Position.Top} id="top-target" />
      <Handle type="source" position={Position.Bottom} id="bottom-source" />
      <Handle type="target" position={Position.Left} id="left-target" />
      <Handle type="source" position={Position.Right} id="right-source" />
    </div>
  );
}

interface TranscriptDifferProps {
  datapointId1: string;
  datapointId2: string;
}

function TranscriptDiffer({
  datapointId1,
  datapointId2,
}: TranscriptDifferProps) {
  const router = useRouter();
  const {
    requestTranscriptDiff,
    transcriptDiffGraph,
    transcriptDiffViewport,
    setTranscriptDiffViewport,
    transcriptComparison,
    socketReady,
    curEvalId,
  } = useFrameGrid();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [sortedDatapoint1Nodes, setSortedDatapoint1Nodes] = useState<Node[]>(
    []
  );
  const [sortedDatapoint2Nodes, setSortedDatapoint2Nodes] = useState<Node[]>(
    []
  );
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [reactFlowInstance, setReactFlowInstance] =
    useState<ReactFlowInstance | null>(null);
  const [tooltipData, setTooltipData] = useState<{
    explanation: string | null;
    position: { x: number; y: number } | null;
  }>({
    explanation: null,
    position: null,
  });

  useEffect(() => {
    if (socketReady && datapointId1 && datapointId2) {
      requestTranscriptDiff(datapointId1, datapointId2);
    }
  }, [datapointId1, datapointId2, socketReady]);

  // Define the layout function using dagre
  const getLayoutedElements = (
    nodes: Node[],
    edges: Edge[],
    direction = 'TB'
  ) => {
    // For a side-by-side top-to-bottom line arrangement, we'll manually position the nodes
    // Identify nodes from each datapoint
    const datapoint1Nodes = nodes.filter(
      (node) => node.data.datapoint_id === datapointId1
    );

    const datapoint2Nodes = nodes.filter(
      (node) => node.data.datapoint_id === datapointId2
    );

    // Sort nodes by their action_unit_idx or starting_block_idx to maintain order
    const sortNodes = (nodeArray: Node[]) => {
      return [...nodeArray].sort((a, b) => {
        // First try to sort by action_unit_idx if available
        if (
          a.data.action_unit_idx !== undefined &&
          b.data.action_unit_idx !== undefined
        ) {
          return a.data.action_unit_idx - b.data.action_unit_idx;
        }
        // Fall back to starting_block_idx
        return a.data.starting_block_idx - b.data.starting_block_idx;
      });
    };

    const sortedDatapoint1Nodes = sortNodes(datapoint1Nodes);
    const sortedDatapoint2Nodes = sortNodes(datapoint2Nodes);

    // Calculate the maximum number of nodes in either column
    const maxNodesInColumn = Math.max(
      sortedDatapoint1Nodes.length,
      sortedDatapoint2Nodes.length
    );

    // Define spacing
    const nodeWidth = 400;
    const nodeHeight = 150;
    const horizontalGap = 100; // Gap between the two columns
    const verticalGap = 50; // Gap between nodes in the same column

    // Position the nodes in two columns
    const positionedNodes = nodes.map((node) => {
      // Determine if node belongs to first or second datapoint
      const isDatapoint1 = node.data.datapoint_id === datapointId1;
      const relevantArray = isDatapoint1
        ? sortedDatapoint1Nodes
        : sortedDatapoint2Nodes;

      // Find the index of this node in its sorted array
      const nodeIndex = relevantArray.findIndex((n) => n.id === node.id);

      // Calculate position
      const xPosition = isDatapoint1 ? 50 : 50 + nodeWidth + horizontalGap;
      const yPosition = nodeIndex * (nodeHeight + verticalGap) + 50;

      return {
        ...node,
        position: {
          x: xPosition,
          y: yPosition,
        },
      };
    });

    return { nodes: positionedNodes, edges };
  };

  // Transform the transcriptDiffGraph data into ReactFlow nodes and edges
  useEffect(() => {
    if (!transcriptDiffGraph) {
      setNodes([]);
      setEdges([]);
      setSortedDatapoint1Nodes([]);
      setSortedDatapoint2Nodes([]);
      return;
    }

    // Process nodes from transcriptDiffGraph
    const processedNodes = transcriptDiffGraph.nodes.map((node) => {
      // Determine node match status by analyzing connected edges
      const connectedEdges = transcriptDiffGraph.edges.filter(
        (edge) => edge.source === node.id || edge.target === node.id
      );

      const hasExactMatch = connectedEdges.some(
        (edge) => edge.type === 'exact_match'
      );
      const hasNearMatch = connectedEdges.some(
        (edge) => edge.type !== 'exact_match' && edge.type !== 'chain'
      );

      // Define match type for use in the table
      const matchType = hasExactMatch
        ? 'exact'
        : hasNearMatch
          ? 'near'
          : 'none';

      // Define border color based on match status
      const borderColor = hasExactMatch
        ? '#86efac' // light green
        : hasNearMatch
          ? '#fef08a' // light yellow
          : '#fecaca'; // light red

      // Define node styles based on node data
      const nodeStyle = {
        background: '#ffffff',
        border: `2px solid ${borderColor}`,
        borderRadius: '8px',
        width: 400,
        minHeight: 100,
        maxHeight: 175,
        boxShadow: `0 2px 5px ${borderColor}40`,
        display: 'flex',
        padding: 0,
        cursor: 'pointer',
      };

      // We'll use dagre for positioning instead of manual positioning
      return {
        id: node.id,
        type: 'custom',
        // Initial position will be replaced by dagre
        position: { x: 0, y: 0 },
        data: {
          ...node.data,
          datapoint_id: node.datapoint_id,
          starting_block_idx: node.starting_block_idx,
          action_unit_idx: node.action_unit_idx,
          matchType: matchType, // Add match type to node data
        },
        style: {
          ...nodeStyle,
        },
      };
    });

    // Process edges from transcriptDiffGraph
    const processedEdges = transcriptDiffGraph.edges.map((edge) => {
      // Define edge styles based on edge type
      const edgeStyle =
        edge.type === 'chain'
          ? { stroke: '#555', strokeWidth: 3 }
          : edge.type === 'exact_match'
            ? { strokeDasharray: '5 5', stroke: '#22c55e', strokeWidth: 3 }
            : { strokeDasharray: '3 3', stroke: '#eab308', strokeWidth: 3 };

      // Set edge connection points based on type
      const isChain = edge.type === 'chain';

      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        style: edgeStyle,
        animated: !isChain,
        sourceHandle: isChain ? 'bottom-source' : 'right-source',
        targetHandle: isChain ? 'top-target' : 'left-target',
        data: {
          explanation: edge.explanation || 'No explanation available',
          type: edge.type,
        },
      };
    });

    // Apply the layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      processedNodes,
      processedEdges
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);

    // Store sorted nodes for the sidebar
    const dp1Nodes = layoutedNodes.filter(
      (node) => node.data.datapoint_id === datapointId1
    );
    const dp2Nodes = layoutedNodes.filter(
      (node) => node.data.datapoint_id === datapointId2
    );

    // Sort nodes by their action_unit_idx or starting_block_idx
    const sortNodes = (nodeArray: Node[]) => {
      return [...nodeArray].sort((a, b) => {
        // First try to sort by action_unit_idx if available
        if (
          a.data.action_unit_idx !== undefined &&
          b.data.action_unit_idx !== undefined
        ) {
          return a.data.action_unit_idx - b.data.action_unit_idx;
        }
        // Fall back to starting_block_idx
        return a.data.starting_block_idx - b.data.starting_block_idx;
      });
    };

    setSortedDatapoint1Nodes(sortNodes(dp1Nodes));
    setSortedDatapoint2Nodes(sortNodes(dp2Nodes));
  }, [transcriptDiffGraph]);

  // Handle node click
  const onNodeClick: NodeMouseHandler = useCallback(
    (event, node) => {
      setSelectedNodeId(node.id);
      router.push(
        `${BASE_DOCENT_PATH}/${curEvalId}/transcript/${node.data.datapoint_id}?block_id=${node.data.starting_block_idx}`
      );
    },
    [router]
  );

  // Function to pan to a specific node
  const panToNode = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      if (node && reactFlowInstance) {
        setSelectedNodeId(nodeId);
        reactFlowInstance.setCenter(
          node.position.x + 200,
          node.position.y + 75,
          {
            zoom: 1.5,
            duration: 800,
          }
        );
      }
    },
    [nodes, reactFlowInstance]
  );

  // Handle edge mouse enter
  const onEdgeMouseEnter: EdgeMouseHandler = useCallback((event, edge) => {
    if (edge.data?.explanation) {
      // Set tooltip data with the explanation and mouse position
      // Use clientX/Y for fixed positioning relative to viewport
      setTooltipData({
        explanation: edge.data.explanation,
        position: {
          x: event.clientX,
          y: event.clientY,
        },
      });
    }
  }, []);

  // Handle edge mouse leave
  const onEdgeMouseLeave: EdgeMouseHandler = useCallback(() => {
    // Clear the tooltip data when mouse leaves the edge
    setTooltipData({
      explanation: null,
      position: null,
    });
  }, []);

  const handleMove: OnMove = useCallback(
    (event, viewport) => {
      setTranscriptDiffViewport({
        x: viewport.x,
        y: viewport.y,
        zoom: viewport.zoom,
        transcriptIds: [datapointId1, datapointId2],
      });
    },
    [setTranscriptDiffViewport, datapointId1, datapointId2]
  );

  // Memoize the nodeTypes object to prevent recreation on each render
  const nodeTypes = useMemo(
    () => ({
      custom: DiffNode,
    }),
    []
  );

  // ExplanationTooltip component for displaying edge explanations
  interface ExplanationTooltipProps {
    explanation: string | null;
    position: { x: number; y: number } | null;
  }

  function ExplanationTooltip({
    explanation,
    position,
  }: ExplanationTooltipProps) {
    if (!explanation || !position) return null;

    return (
      <div
        className="fixed z-50 bg-white border border-gray-200 rounded-md shadow-lg p-2 max-w-md"
        style={{
          left: position.x,
          top: position.y,
          transform: 'translate(10px, 10px)',
          transition: 'opacity 0.2s ease-in-out',
          pointerEvents: 'none', // Prevent the tooltip from interfering with mouse events
        }}
      >
        <div className="text-sm text-gray-800">{explanation}</div>
      </div>
    );
  }

  // Use the stored viewport if available, otherwise use default
  const initialViewport =
    transcriptDiffViewport &&
    transcriptDiffViewport.transcriptIds?.[0] === datapointId1 &&
    transcriptDiffViewport.transcriptIds?.[1] === datapointId2
      ? {
          x: transcriptDiffViewport.x,
          y: transcriptDiffViewport.y,
          zoom: transcriptDiffViewport.zoom,
        }
      : { x: 0, y: 0, zoom: 1 };

  return (
    <>
      <Card className="h-full w-1/3 overflow-auto flex flex-col space-y-2 p-3">
        <div className="space-y-2">
          <div>
            <div className="text-sm font-semibold text-gray-800">
              Transcript Diffing
            </div>
            <div className="text-xs">
              Compare steps between two transcripts.
            </div>
          </div>
          <div className="text-xs px-3 py-2 bg-gray-50 border rounded-md">
            <div className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 bg-green-300 rounded-full"></div>
              <span>Green: Exact match between steps</span>
            </div>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-3 h-3 bg-yellow-300 rounded-full"></div>
              <span>Yellow: Near match with some differences</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-red-300 rounded-full"></div>
              <span>Red: No match found</span>
            </div>
          </div>
        </div>

        <ScrollArea className="flex-1">
          {/* <TranscriptTable
            title="Transcript 1"
            nodes={sortedDatapoint1Nodes}
            selectedNodeId={selectedNodeId}
            onNodeClick={panToNode}
          />

          <TranscriptTable
            title="Transcript 2"
            nodes={sortedDatapoint2Nodes}
            selectedNodeId={selectedNodeId}
            onNodeClick={panToNode}
            className="mt-4"
          />

          {sortedDatapoint1Nodes.length === 0 &&
            sortedDatapoint2Nodes.length === 0 && (
              <div className="flex items-center justify-center h-full">
                <p className="text-sm">Loading transcript steps...</p>
              </div>
            )} */}
          <div
            className="prose prose-sm max-w-none text-black
                  prose-p:my-0.5 prose-p:leading-normal prose-p:text-black
                  prose-headings:mt-2 prose-headings:mb-1 prose-headings:text-black
                  prose-ul:my-0.5 prose-ul:pl-4
                  prose-ol:my-0.5 prose-ol:pl-4
                  prose-li:my-0 prose-li:leading-normal prose-li:text-black
                  prose-code:px-1 prose-code:py-0.5 prose-code:bg-slate-50 prose-code:rounded prose-code:text-black
                  prose-pre:my-1 prose-pre:p-2 prose-pre:bg-slate-50 prose-pre:rounded
                  prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
                  prose-hr:my-2
                  prose-blockquote:my-1 prose-blockquote:pl-2 prose-blockquote:border-l-2 prose-blockquote:border-slate-200 prose-blockquote:italic prose-blockquote:text-black"
          >
            {transcriptComparison?.text ? (
              <ReactMarkdown>{transcriptComparison.text}</ReactMarkdown>
            ) : (
              <div className="animate-pulse space-y-1">
                <div className="h-4 bg-slate-100 rounded w-3/4"></div>
                <div className="h-4 bg-slate-100 rounded w-2/3"></div>
                <div className="h-4 bg-slate-100 rounded w-4/5"></div>
              </div>
            )}
          </div>
        </ScrollArea>
      </Card>
      <Card className="h-full flex-1 min-w-0 p-2 overflow-hidden">
        <div className="h-full w-full">
          {transcriptDiffGraph ? (
            <>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodeClick={onNodeClick}
                onEdgeMouseEnter={onEdgeMouseEnter}
                onEdgeMouseLeave={onEdgeMouseLeave}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={true}
                zoomOnScroll={true}
                panOnScroll={true}
                preventScrolling={false}
                onMove={handleMove}
                defaultViewport={initialViewport}
                nodeTypes={nodeTypes}
                proOptions={{ hideAttribution: true }}
                onInit={setReactFlowInstance}
              >
                <Background />
                <Controls />
                <MiniMap />
              </ReactFlow>
              <ExplanationTooltip
                explanation={tooltipData.explanation}
                position={tooltipData.position}
              />
            </>
          ) : (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
            </div>
          )}
        </div>
      </Card>
    </>
  );
}

export default TranscriptDiffer;
