'use client';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  NodeMouseHandler,
  Viewport,
  OnMove,
  NodeProps,
  Handle,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { useFrameGrid } from '../../../contexts/FrameGridContext';
import { Loader2 } from 'lucide-react';
import { BASE_DOCENT_PATH } from '@/app/constants';

interface TranscriptGraphProps {
  sampleId?: string;
}

// Custom node component for transcript data
function TranscriptNode({ data, id }: NodeProps): JSX.Element {
  // Extract data from node
  const nodeId = id || 'Unknown ID';
  const sampleId = data.sample_id;
  const epochId = data.epoch_id;
  const isCorrect = data.correct;
  const model = data.model;
  const intervention = data.intervention_description;
  const numTranscripts = data.num_transcripts;
  const numCorrect = data.num_correct || 0;

  return (
    <div className="p-2 flex flex-col min-w-0 h-full group hover:bg-gray-50 transition-colors cursor-pointer rounded-lg">
      {/* Title section with ID */}
      <div className="flex flex-col border-b pb-1 mb-1">
        <div className="flex justify-between items-center">
          <div className="font-semibold text-xs truncate">Transcript</div>
          <div
            className="text-[10px] text-gray-500 ml-1 whitespace-nowrap overflow-hidden text-ellipsis max-w-[150px]"
            title={nodeId}
          >
            ID: {nodeId.substring(0, 8)}...
          </div>
        </div>
        <div className="text-[10px] text-gray-500 opacity-70 group-hover:opacity-100 transition-opacity">
          Click to view transcript
        </div>
      </div>

      {/* Main info section */}
      <div className="text-xs space-y-1">
        {/* Key metrics row */}
        <div className="flex flex-wrap gap-1">
          {sampleId !== undefined && (
            <div className="px-1.5 py-0.5">
              <span className="font-medium">Sample:</span> {sampleId}
            </div>
          )}
          {epochId !== undefined && (
            <div className="px-1.5 py-0.5">
              <span className="font-medium">Epoch:</span> {epochId}
            </div>
          )}
          {isCorrect !== undefined && (
            <div className="px-1.5 py-0.5">
              <span className="font-medium">
                {isCorrect ? '✓ Correct' : '✗ Incorrect'}
              </span>
            </div>
          )}
        </div>

        {/* Model info */}
        {model && (
          <div className="px-1.5 py-0.5 inline-block">
            <span className="font-medium">Model:</span> {model}
          </div>
        )}

        {/* Intervention info */}
        {intervention && (
          <div
            className="px-1.5 py-0.5 mt-0.5 text-xs line-clamp-2"
            title={intervention}
          >
            <span className="font-medium">Intervention:</span> {intervention}
          </div>
        )}

        {/* Transcript stats if available */}
        {numTranscripts !== undefined && (
          <div className="px-1.5 py-0.5 flex gap-2">
            <div>
              <span className="font-medium">Transcripts:</span> {numTranscripts}
            </div>
            <div>
              <span className="font-medium">Correct:</span> {numCorrect}
            </div>
          </div>
        )}
      </div>

      <Handle type="target" position={Position.Top} id="top-target" />
      <Handle type="source" position={Position.Bottom} id="bottom-source" />
    </div>
  );
}

export default function TranscriptGraph({ sampleId }: TranscriptGraphProps) {
  const router = useRouter();
  const {
    isConnected,
    transcriptDerivationTree,
    clearTranscriptDerivationTree,
    socketReady,
    requestTranscriptDerivationTree,
    curEvalId,
  } = useFrameGrid();

  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });

  // Request graph data when sampleId changes
  useEffect(() => {
    if (!sampleId || !socketReady) return;
    clearTranscriptDerivationTree();
    requestTranscriptDerivationTree(sampleId);
  }, [sampleId, socketReady]);

  // Process graph data into reactflow nodes and edges
  useEffect(() => {
    if (
      !transcriptDerivationTree ||
      !transcriptDerivationTree.nodes ||
      !transcriptDerivationTree.edges
    ) {
      setNodes([]);
      setEdges([]);
      return;
    }

    // Process nodes
    const processedNodes = Object.values(transcriptDerivationTree.nodes).map(
      (node: any) => {
        // Define node styles based on node data
        const nodeStyle = {
          background: '#ffffff',
          border: '2px solid #86efac', // Default to green border
          borderRadius: '8px',
          padding: '0',
          width: 225,
          minHeight: 100,
          boxShadow: '0 2px 5px rgba(0, 0, 0, 0.1)',
          cursor: 'alias', // Change cursor to indicate node is clickable
        };

        // Determine border color based on correctness
        if (node.data.correct !== undefined) {
          nodeStyle.border = node.data.correct
            ? '2px solid #86efac' // Light green for correct
            : '2px solid #fecaca'; // Light red for incorrect
        } else if (node.data && node.data.num_transcripts !== undefined) {
          const numCorrect = node.data.num_correct || 0;
          const numTranscripts = node.data.num_transcripts;

          if (numTranscripts === 0) {
            nodeStyle.border = '2px solid #d1d5db'; // Gray for no transcripts
          } else if (numCorrect === 0) {
            nodeStyle.border = '2px solid #fecaca'; // Light red for no correct transcripts
          } else if (numCorrect === numTranscripts) {
            nodeStyle.border = '2px solid #86efac'; // Light green for all correct
          } else if (numCorrect / numTranscripts >= 0.5) {
            nodeStyle.border = '2px solid #fef08a'; // Light yellow for more than half correct
          } else {
            nodeStyle.border = '2px solid #fecaca'; // Light red for less than half correct
          }
        }

        return {
          id: node.id,
          type: 'transcript', // Use custom node type
          position: { x: 0, y: 0 }, // Initial position will be replaced by layout
          data: {
            ...node.data,
            nodeId: node.id, // Add the node ID to the data for access in the node component
          },
          style: {
            ...nodeStyle,
          },
        };
      }
    );

    // Process edges
    const processedEdges = Object.values(transcriptDerivationTree.edges).map(
      (edge: any, index: number) => {
        // Define edge styles
        const edgeStyle = {
          stroke: '#555',
          strokeWidth: 2,
        };

        return {
          id: edge.id || `edge-${index}`,
          source: edge.source,
          target: edge.target,
          style: edgeStyle,
          animated: false,
        };
      }
    );

    // Apply automatic layout
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
      processedNodes,
      processedEdges
    );

    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [transcriptDerivationTree]);

  // Define the layout function
  const getLayoutedElements = (
    nodes: Node[],
    edges: Edge[],
    direction = 'TB'
  ) => {
    // Calculate positions for nodes in a tree-like structure
    const nodeWidth = 225; // Match the width used in the node style
    const nodeHeight = 120;
    const horizontalGap = 80;
    const verticalGap = 80;

    // Simple tree layout algorithm
    const nodeMap = new Map();
    nodes.forEach((node) =>
      nodeMap.set(node.id, { ...node, children: [], level: 0 })
    );

    // Build the tree structure
    edges.forEach((edge) => {
      const sourceNode = nodeMap.get(edge.source);
      const targetNode = nodeMap.get(edge.target);
      if (sourceNode && targetNode) {
        sourceNode.children.push(targetNode);
        // Increase the level of the target node and all its descendants
        const updateLevels = (node: any, level: number) => {
          node.level = Math.max(node.level, level);
          node.children.forEach((child: any) => updateLevels(child, level + 1));
        };
        updateLevels(targetNode, sourceNode.level + 1);
      }
    });

    // Find root nodes (nodes with no incoming edges)
    const rootNodes = Array.from(nodeMap.values()).filter((node) => {
      return !edges.some((edge) => edge.target === node.id);
    });

    // Position nodes by level and within level
    const levelNodes = new Map<number, any[]>();
    Array.from(nodeMap.values()).forEach((node) => {
      if (!levelNodes.has(node.level)) {
        levelNodes.set(node.level, []);
      }
      levelNodes.get(node.level)?.push(node);
    });

    // Calculate positions
    const positionedNodes = nodes.map((node) => {
      const nodeWithLevel = nodeMap.get(node.id);
      const level = nodeWithLevel.level;
      const nodesAtLevel = levelNodes.get(level) || [];
      const indexAtLevel = nodesAtLevel.indexOf(nodeWithLevel);

      const xPosition = indexAtLevel * (nodeWidth + horizontalGap);
      const yPosition = level * (nodeHeight + verticalGap);

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

  // Handle node click
  const onNodeClick: NodeMouseHandler = useCallback(
    (event, node) => {
      // Check for various possible ID properties in the node data
      if (node.data.transcript_ids && node.data.transcript_ids.length > 0) {
        // If transcript_ids array is available, use the first one
        router.push(
          `${BASE_DOCENT_PATH}/${curEvalId}/transcript/${node.data.transcript_ids[0]}`
        );
      } else if (node.data.id) {
        router.push(
          `${BASE_DOCENT_PATH}/${curEvalId}/transcript/${node.data.id}`
        );
      }
    },
    [router]
  );

  // Handle viewport changes
  const handleMove: OnMove = useCallback((event, viewport) => {
    setViewport(viewport);
  }, []);

  // Memoize the nodeTypes object to prevent recreation on each render
  const nodeTypes = useMemo(
    () => ({
      transcript: TranscriptNode,
    }),
    []
  );

  if (!isConnected || !sampleId || !transcriptDerivationTree) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodeClick={onNodeClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        zoomOnScroll={true}
        panOnScroll={true}
        preventScrolling={false}
        onMove={handleMove}
        defaultViewport={viewport}
        nodeTypes={nodeTypes}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
