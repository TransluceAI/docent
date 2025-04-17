'use client';

import {
  Datapoint,
  DimState,
  Marginals,
  TranscriptMetadataField,
  LowLevelAction,
  HighLevelAction,
  ActionsSummary,
  ObservationType,
  Citation,
  MetadataFilter,
  TranscriptDiffNode,
  TranscriptDiffEdge,
  TranscriptDiffGraph,
  ExportNode,
  ExportEdge,
  TranscriptDerivationTree,
  ExperimentTree,
  AttributeWithCitation,
  StreamedAttribute,
  AttributeFilter,
  FrameFilter,
  SolutionSummary,
  TranscriptComparison,
} from '@/app/types/docent';
import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
} from 'react';
import { BASE_URL } from '@/app/constants';
import { toast } from '@/hooks/use-toast';
import { v4 as uuid4 } from 'uuid';
import { TaskStats } from '@/app/types/docent';
import posthog from 'posthog-js';

// Organization types
export type OrganizationMethod = 'experiment' | 'sample';

// Eval IDs type
export type EvalId = string;

interface FrameGridContextType {
  // WebSocket functionality
  socket: WebSocket | null;
  isConnected: boolean;
  sendMessage: (action: string, payload: any) => void;
  socketReady: boolean;
  showDisconnectModal: boolean;
  setShowDisconnectModal: React.Dispatch<React.SetStateAction<boolean>>;

  // API keys
  apiKeys: {
    anthropic_key?: string;
    openai_key?: string;
  };
  setApiKeys: React.Dispatch<
    React.SetStateAction<{
      anthropic_key?: string;
      openai_key?: string;
    }>
  >;

  // Diff state
  selectedDiffTranscript: string | null;
  setSelectedDiffTranscript: React.Dispatch<
    React.SetStateAction<string | null>
  >;
  selectedDiffSampleId: string | null;
  setSelectedDiffSampleId: React.Dispatch<React.SetStateAction<string | null>>;
  transcriptDiffViewport: {
    x: number;
    y: number;
    zoom: number;
    transcriptIds: [string, string] | null;
  } | null;
  setTranscriptDiffViewport: React.Dispatch<
    React.SetStateAction<{
      x: number;
      y: number;
      zoom: number;
      transcriptIds: [string, string] | null;
    } | null>
  >;

  // Frame metadata
  baseFilter: FrameFilter[] | null;
  setBaseFilter: React.Dispatch<React.SetStateAction<FrameFilter[] | null>>;
  transcriptMetadataFields: TranscriptMetadataField[];
  setTranscriptMetadataFields: React.Dispatch<
    React.SetStateAction<TranscriptMetadataField[]>
  >;

  // Attribute query
  curAttributeQuery: string | null;
  loadingAttributesFor: string | null;
  numAttributeUpdatesReceived: [number, number];
  setCurAttributeQuery: React.Dispatch<React.SetStateAction<string | null>>;

  // Search history
  searchHistory: string[];
  addToSearchHistory: (query: string) => void;
  clearSearchHistory: () => void;
  setSearchHistory: React.Dispatch<React.SetStateAction<string[]>>;

  // UI State Persistence
  organizationMethod: OrganizationMethod;
  setOrganizationMethod: React.Dispatch<
    React.SetStateAction<OrganizationMethod>
  >;
  expandedOuter: Set<string>;
  setExpandedOuter: React.Dispatch<React.SetStateAction<Set<string>>>;
  expandedInner: Record<string, Set<string>>;
  setExpandedInner: React.Dispatch<
    React.SetStateAction<Record<string, Set<string>>>
  >;
  experimentViewerScrollPosition: number;
  setExperimentViewerScrollPosition: React.Dispatch<
    React.SetStateAction<number>
  >;

  // Global state of experiments
  expStatMarginals: Record<string, TaskStats> | null;
  setExpStatMarginals: React.Dispatch<
    React.SetStateAction<Record<string, TaskStats> | null>
  >;
  perSampleStats: Record<string, TaskStats> | null;
  setPerSampleStats: React.Dispatch<
    React.SetStateAction<Record<string, TaskStats> | null>
  >;
  perExperimentStats: Record<string, TaskStats> | null;
  setPerExperimentStats: React.Dispatch<
    React.SetStateAction<Record<string, TaskStats> | null>
  >;
  interventionDescriptions: Record<string, string[]> | null;
  setInterventionDescriptions: React.Dispatch<
    React.SetStateAction<Record<string, string[]> | null>
  >;
  expIdMarginals: Record<string, [string, number][]> | null;
  setExpIdMarginals: React.Dispatch<
    React.SetStateAction<Record<string, [string, number][]> | null>
  >;
  expBins: { sample_id: string[]; experiment_id: string[] } | null;
  setExpBins: React.Dispatch<
    React.SetStateAction<{
      sample_id: string[];
      experiment_id: string[];
    } | null>
  >;

  // Datapoints and attributes
  curDatapoint: Datapoint | null;
  setCurDatapoint: React.Dispatch<React.SetStateAction<Datapoint | null>>;
  attributeMap: Map<string, Map<string, AttributeWithCitation[]>>;
  setAttributeMap: React.Dispatch<
    React.SetStateAction<Map<string, Map<string, AttributeWithCitation[]>>>
  >;

  // Transcript summaries
  solutionSummary: SolutionSummary | null;
  actionsSummary: ActionsSummary | null;
  clearSolutionSummary: () => void;
  clearActionsSummary: () => void;
  loadingActionsSummaryFor: string | null;
  loadingSolutionSummaryFor: string | null;

  // Transcript assistant
  taSessionId: string | null;
  setTaSessionId: React.Dispatch<React.SetStateAction<string | null>>;
  curTaDatapointId: string | null;
  setCurTaDatapointId: React.Dispatch<React.SetStateAction<string | null>>;
  taMessages: Array<{
    role: 'user' | 'assistant' | 'system';
    content: string;
    citations: Citation[];
  }>;
  setTaMessages: React.Dispatch<
    React.SetStateAction<
      Array<{
        role: 'user' | 'assistant' | 'system';
        content: string;
        citations: Citation[];
      }>
    >
  >;
  clearTaMessages: () => void;
  isReceivingTaResponse: boolean;
  setIsReceivingTaResponse: React.Dispatch<React.SetStateAction<boolean>>;
  sendTaMessage: (message: string) => boolean;
  createTaSession: (datapointId: string) => boolean;

  // FrameGrid data
  frameGridId: string | null;
  setFrameGridId: React.Dispatch<React.SetStateAction<string | null>>;
  dimensions: DimState[];
  setDimensions: React.Dispatch<React.SetStateAction<DimState[]>>;
  marginals: Marginals | null;
  setMarginals: React.Dispatch<React.SetStateAction<Marginals | null>>;

  // Cluster proposals
  clusterProposals: string[][] | null;
  clusterSessionId: string | null;
  setClusterProposals: React.Dispatch<React.SetStateAction<string[][] | null>>;
  setClusterSessionId: React.Dispatch<React.SetStateAction<string | null>>;

  // Transcript metadata
  transcriptMetadata: Record<string, Record<string, any>>;
  setTranscriptMetadata: React.Dispatch<
    React.SetStateAction<Record<string, Record<string, any>>>
  >;

  // Transcript diff results
  transcriptDiffGraph: TranscriptDiffGraph | null;
  transcriptComparison: TranscriptComparison | null;

  // Rate limiting
  isRateLimited: boolean;
  setIsRateLimited: React.Dispatch<React.SetStateAction<boolean>>;

  // API Key Modal
  isApiKeyModalOpen: boolean;
  setIsApiKeyModalOpen: React.Dispatch<React.SetStateAction<boolean>>;

  // Experiment tree
  experimentTree: {
    nodes: Record<string, any>;
    edges: Record<string, any>;
  } | null;
  clearExperimentTree: () => void;

  // Transcript derivation tree
  transcriptDerivationTree: TranscriptDerivationTree | null;
  clearTranscriptDerivationTree: () => void;

  // Compound actions
  onClearDatapoint: () => void;
  onAddFilter: (filter: FrameFilter) => void;
  onRemoveFilter: (filterId: string) => void;
  onClearFilters: () => void;

  // Remote requests
  requestTranscriptDiff: (datapointId1: string, datapointId2: string) => void;
  requestActionsSummary: (datapointId: string) => void;
  requestSolutionSummary: (datapointId: string) => void;
  cancelActionsSummary: () => void;
  cancelSolutionSummary: () => void;
  requestExperimentTree: (sampleId: string | number) => void;
  requestTranscriptDerivationTree: (sampleId: string | number) => void;
  requestTranscriptMetadata: (datapointIds: string[]) => void;
  requestAttributes: (attribute: string) => void;
  requestClusters: (dimensionId: string, feedback?: string) => void;
  requestReclusterDimension: (dimensionId: string) => void;
  cancelReclusterDimension: () => void;
  requestAddDimension: (attribute: string, bins: any) => void;
  cancelAttributeQuery: () => void;
  cancelClustersRequest: () => void;
  handleClearAttribute: (dimId: string | null) => void;
  evalIds: EvalId[];
  fetchEvalIds: () => Promise<EvalId[]>;
  startNewEval: (evalId: EvalId) => void;
  curEvalId: EvalId | null;
  rewriteSearchQuery: (query: string) => Promise<string>;
}

const FrameGridContext = createContext<FrameGridContextType | null>(null);

export function FrameGridProvider({ children }: { children: React.ReactNode }) {
  // Metadata
  const [baseFilters, setBaseFilters] = useState<FrameFilter[] | null>(null);
  const [transcriptMetadataFields, setTranscriptMetadataFields] = useState<
    TranscriptMetadataField[]
  >([]);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);

  // Attribute query
  const [curAttributeQuery, setCurAttributeQuery] = useState<string | null>(
    null
  );
  useEffect(() => {
    if (baseFilters === null) {
      setCurAttributeQuery(null);
    }
  }, [baseFilters]);
  const [loadingAttributesFor, setLoadingAttributesFor] = useState<
    string | null
  >(null);
  const [numAttributeUpdatesReceived, setNumAttributeUpdatesReceived] =
    useState<[number, number]>([0, 0]);
  const handleAttributesUpdate = (data: StreamedAttribute) => {
    const datapointId = data.datapoint_id;
    const attributeId = data.attribute_id;

    // Update the progress counters
    setNumAttributeUpdatesReceived([
      data.num_datapoints_done,
      data.num_datapoints_total,
    ]);

    // If both datapoint_id and attribute_id are null, don't update anything
    if (datapointId === null || attributeId === null) {
      return;
    }

    const attributes = data.attributes || [];

    setAttributeMap((oldMap) => {
      // Get list of attr ids for datapoint
      const attrIds =
        oldMap.get(datapointId) || new Map<string, AttributeWithCitation[]>();
      // Set the attribute list to the new value (not appending)
      attrIds.set(attributeId, attributes);
      oldMap.set(datapointId, attrIds);

      return new Map<string, Map<string, AttributeWithCitation[]>>(oldMap);
    });
  };

  // Per-sample and per-experiment stats
  const [perSampleStats, setPerSampleStats] = useState<Record<
    string,
    TaskStats
  > | null>(null);
  const [perExperimentStats, setPerExperimentStats] = useState<Record<
    string,
    TaskStats
  > | null>(null);
  const [interventionDescriptions, setInterventionDescriptions] =
    useState<Record<string, string[]> | null>(null);

  // Search history
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const addToSearchHistory = useCallback((query: string) => {
    setSearchHistory((prevHistory) => {
      const newHistory = [...prevHistory];
      if (newHistory.includes(query)) {
        newHistory.splice(newHistory.indexOf(query), 1);
      }
      newHistory.unshift(query);
      // Limit to 10 items
      return newHistory.slice(0, 10);
    });
  }, []);
  const clearSearchHistory = useCallback(() => {
    setSearchHistory([]);
  }, []);

  // Diff state
  const [selectedDiffTranscript, setSelectedDiffTranscript] = useState<
    string | null
  >(null);
  const [selectedDiffSampleId, setSelectedDiffSampleId] = useState<
    string | null
  >(null);
  const [transcriptDiffViewport, setTranscriptDiffViewport] = useState<{
    x: number;
    y: number;
    zoom: number;
    transcriptIds: [string, string] | null;
  } | null>(null);

  // UI State Persistence
  const [organizationMethod, setOrganizationMethod] =
    useState<OrganizationMethod>('experiment');
  const [expandedOuter, setExpandedOuter] = useState<Set<string>>(new Set());
  const [expandedInner, setExpandedInner] = useState<
    Record<string, Set<string>>
  >({});
  const [experimentViewerScrollPosition, setExperimentViewerScrollPosition] =
    useState<number>(0);

  // Bins for each dimension in the experiment marginal
  const [expBins, setExpBins] = useState<{
    sample_id: string[];
    experiment_id: string[];
  } | null>(null);
  // Experiment marginal -> datapoint IDs (raw, unfiltered)
  const [rawExpIdMarginals, setRawExpIdMarginals] = useState<Record<
    string,
    [string, number][]
  > | null>(null);
  // Experiment marginal -> performance statistics (raw, unfiltered)
  const [rawExpStatMarginals, setRawExpStatMarginals] = useState<Record<
    string,
    TaskStats
  > | null>(null);

  // Datapoints and attributes
  const [curDatapoint, setCurDatapoint] = useState<Datapoint | null>(null);
  const curDatapointRef = useRef<Datapoint | null>(null);
  useEffect(() => {
    curDatapointRef.current = curDatapoint;
  }, [curDatapoint]);
  const [attributeMap, setAttributeMap] = useState<
    Map<string, Map<string, AttributeWithCitation[]>>
  >(new Map<string, Map<string, AttributeWithCitation[]>>());

  // Derived and filtered versions of expIdMarginals and expStatMarginals
  // These filtered versions only include datapoints that have at least one attribute
  // when curAttributeQuery is not null
  const expIdMarginals = useMemo(() => {
    // If no attribute query or no raw data, return raw data as is
    if (!curAttributeQuery || !rawExpIdMarginals) {
      return rawExpIdMarginals;
    }

    const filtered: Record<string, [string, number][]> = {};

    // Filter each marginal to only include datapoints with attributes
    for (const key in rawExpIdMarginals) {
      const datapointsWithAttributes = rawExpIdMarginals[key].filter(
        ([datapointId]) => {
          // Check if this datapoint has any attributes for the current query
          const hasAttributes =
            attributeMap.has(datapointId) &&
            attributeMap.get(datapointId)?.has(curAttributeQuery) &&
            (attributeMap.get(datapointId)?.get(curAttributeQuery)?.length ??
              0) > 0;

          return hasAttributes;
        }
      );

      // Only include this marginal if it has at least one datapoint with attributes
      if (datapointsWithAttributes.length > 0) {
        filtered[key] = datapointsWithAttributes;
      }
    }

    return filtered;
  }, [rawExpIdMarginals, curAttributeQuery, attributeMap]);

  const expStatMarginals = useMemo(() => {
    // If no attribute query or no raw data, return raw data as is
    if (!curAttributeQuery || !rawExpStatMarginals) {
      return rawExpStatMarginals;
    }

    // FIXME(kevin): this is actually incorrect.
    const filtered: Record<string, any> = {};

    // Filter each marginal based on whether the corresponding expIdMarginals entry exists
    // This ensures we only keep stats for marginals that have datapoints with attributes
    for (const key in rawExpStatMarginals) {
      if (expIdMarginals && key in expIdMarginals) {
        filtered[key] = rawExpStatMarginals[key];
      }
    }

    return filtered;
  }, [rawExpStatMarginals, curAttributeQuery, expIdMarginals]);

  // Transcript summaries
  const [solutionSummary, setSolutionSummary] =
    useState<SolutionSummary | null>(null);
  const [actionsSummary, setActionsSummary] = useState<ActionsSummary | null>(
    null
  );

  // Implement separate methods to clear individual summaries
  const clearSolutionSummary = () => {
    setSolutionSummary(null);
  };

  const clearActionsSummary = () => {
    setActionsSummary(null);
  };

  // Transcript assistant
  const [taSessionId, setTaSessionId] = useState<string | null>(null);
  const [curTaDatapointId, setCurTaDatapointId] = useState<string | null>(null);
  const [taMessages, setTaMessages] = useState<
    Array<{
      role: 'user' | 'assistant' | 'system';
      content: string;
      citations: Citation[];
    }>
  >([]);
  const [isReceivingTaResponse, setIsReceivingTaResponse] = useState(false);

  // Implement clearTaMessages method to clear transcript assistant messages
  const clearTaMessages = useCallback(() => {
    setTaMessages([]);
    setCurTaDatapointId(null);
  }, []);

  // FrameGrid data
  const [frameGridId, setFrameGridId] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState<DimState[]>([]);
  const [marginals, setMarginals] = useState<Marginals | null>(null);

  // Cluster proposals
  const [clusterProposals, setClusterProposals] = useState<string[][] | null>(
    null
  );
  const [clusterSessionId, setClusterSessionId] = useState<string | null>(null);

  // Transcript metadata
  const [transcriptMetadata, setTranscriptMetadata] = useState<
    Record<string, Record<string, any>>
  >({});

  // Transcript diff results
  const [transcriptDiffGraph, setTranscriptDiffGraph] =
    useState<TranscriptDiffGraph | null>(null);
  const [transcriptComparison, setTranscriptComparison] =
    useState<TranscriptComparison | null>(null);

  // Rate limiting
  const [isRateLimited, setIsRateLimited] = useState(false);

  // API Key Modal
  const [isApiKeyModalOpen, setIsApiKeyModalOpen] = useState(false);

  // Experiment tree results
  const [experimentTree, setExperimentTree] = useState<ExperimentTree | null>(
    null
  );
  const experimentTreeRef = useRef<ExperimentTree | null>(null);
  useEffect(() => {
    experimentTreeRef.current = experimentTree;
  }, [experimentTree]);
  const experimentTreeDatapointIds = useMemo(() => {
    if (!experimentTree) {
      return null;
    }

    return new Set(
      experimentTree.nodes.flatMap((node) => node.data.transcript_ids)
    );
  }, [experimentTree]);
  const experimentTreeDatapointIdsRef = useRef<Set<string> | null>(null);
  useEffect(() => {
    experimentTreeDatapointIdsRef.current = experimentTreeDatapointIds;
  }, [experimentTreeDatapointIds]);

  // Transcript derivation tree results
  const [transcriptDerivationTree, setTranscriptDerivationTree] =
    useState<TranscriptDerivationTree | null>(null);
  const transcriptDerivationTreeRef = useRef<TranscriptDerivationTree | null>(
    null
  );
  useEffect(() => {
    transcriptDerivationTreeRef.current = transcriptDerivationTree;
  }, [transcriptDerivationTree]);
  const transcriptDerivationTreeDatapointIds = useMemo(() => {
    if (!transcriptDerivationTree) {
      return null;
    }

    return new Set(transcriptDerivationTree.nodes.map((node) => node.id));
  }, [transcriptDerivationTree]);
  const transcriptDerivationTreeDatapointIdsRef = useRef<Set<string> | null>(
    null
  );
  useEffect(() => {
    transcriptDerivationTreeDatapointIdsRef.current =
      transcriptDerivationTreeDatapointIds;
  }, [transcriptDerivationTreeDatapointIds]);

  // Eval IDs
  const [evalIds, setEvalIds] = useState<EvalId[]>([]);
  const [curEvalId, setCurEvalId] = useState<EvalId | null>(null);

  // WebSocket
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [apiKeys, setApiKeys] = useState<{
    anthropic_key?: string;
    openai_key?: string;
  }>({});

  useEffect(() => {
    const ws = new WebSocket(
      `${BASE_URL ? (BASE_URL.startsWith('https') ? 'wss' : 'ws') : 'ws'}://${(BASE_URL || '').replace(/^https?:\/\//, '')}/ws/framegrid`
    );

    ws.onopen = () => {
      console.log('WebSocket Connected');
      setIsConnected(true);
      setShowDisconnectModal(false);
    };

    ws.onclose = () => {
      console.log('WebSocket Disconnected');
      setIsConnected(false);
    };

    setSocket(ws);

    return () => {
      ws.close();
    };
  }, []);

  const sendMessage = useCallback(
    (action: string, payload: any) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        console.log('ws_send_message', { action, payload });
        socket.send(JSON.stringify({ action, payload }));
        posthog.capture('ws_send_message', { action, payload });
      } else {
        console.error('WebSocket not connected');
        setShowDisconnectModal(true);
      }
    },
    [socket]
  );

  // Compound actions
  const onClearDatapoint = useCallback(() => {
    setCurDatapoint(null);
    setSolutionSummary(null);
    setActionsSummary(null);
  }, []);

  // Function to update backend with current filters
  const updateBackendFilter = useCallback(
    (filters: FrameFilter[] | null) => {
      if (filters === null || filters.length === 0) {
        sendMessage('update_base_filter', {
          filter: null,
        });
      } else {
        sendMessage('update_base_filter', {
          filter: {
            id: '_base_filter',
            type: 'complex',
            filters: filters,
            op: 'and',
          },
        });
      }
    },
    [sendMessage]
  );

  // Filter management
  const onAddFilter = useCallback(
    (filter: FrameFilter) => {
      cancelAttributeQuery();
      setBaseFilters((prev) => {
        const newFilters = prev ? [...prev, filter] : [filter];
        // Update backend with the new filters
        updateBackendFilter(newFilters);
        return newFilters;
      });
    },
    [updateBackendFilter]
  );

  const onRemoveFilter = useCallback(
    (filterId: string) => {
      cancelAttributeQuery();
      setBaseFilters((prev) => {
        if (!prev) return null;

        // Check if the filter being removed is an attribute filter
        const filterToRemove = prev.find((f) => f.id === filterId);
        if (filterToRemove && (filterToRemove.type as any) === 'attribute') {
          setCurAttributeQuery(null);
        }

        const newFilters = prev.filter((f) => f.id !== filterId);
        const result = newFilters.length > 0 ? newFilters : null;

        // Update backend with the new filters
        updateBackendFilter(result);
        return result;
      });
    },
    [setCurAttributeQuery, updateBackendFilter]
  );

  // Remote requests
  const loadingActionsSummaryFor = useRef<string | null>(null);
  const actionsSummaryTaskId = useRef<string | null>(null);
  const [loadingActionsFor, setLoadingActionsFor] = useState<string | null>(
    null
  );

  const loadingSolutionSummaryFor = useRef<string | null>(null);
  const [loadingSolutionFor, setLoadingSolutionFor] = useState<string | null>(
    null
  );

  // Define cancelActionsSummary before it's used
  const cancelActionsSummary = useCallback(() => {
    if (actionsSummaryTaskId.current) {
      sendMessage('cancel_task', {
        _task_id: actionsSummaryTaskId.current,
      });
      actionsSummaryTaskId.current = null;
      loadingActionsSummaryFor.current = null;
      setLoadingActionsFor(null);
    }
  }, [sendMessage]);

  // Define cancelSolutionSummary before it's used
  const solutionSummaryTaskId = useRef<string | null>(null);
  const cancelSolutionSummary = useCallback(() => {
    if (solutionSummaryTaskId.current) {
      sendMessage('cancel_task', {
        _task_id: solutionSummaryTaskId.current,
      });
      solutionSummaryTaskId.current = null;
      loadingSolutionSummaryFor.current = null;
      setLoadingSolutionFor(null);
    }
  }, [sendMessage]);

  // Define cancelAttributeQuery before it's used
  const attributesTaskId = useRef<string | null>(null);
  const cancelAttributeQuery = useCallback(() => {
    if (attributesTaskId.current) {
      sendMessage('cancel_task', {
        _task_id: attributesTaskId.current,
      });
      attributesTaskId.current = null;
      setLoadingAttributesFor(null);
      setNumAttributeUpdatesReceived([0, 0]);
    }
  }, [sendMessage]);

  const onClearFilters = useCallback(() => {
    setBaseFilters(null);
    updateBackendFilter(null);
    cancelAttributeQuery();
  }, [setBaseFilters, updateBackendFilter, cancelAttributeQuery]);

  const requestActionsSummary = useCallback(
    (datapointId: string) => {
      if (loadingActionsSummaryFor.current === datapointId) {
        return;
      } else {
        cancelActionsSummary();
      }

      setActionsSummary(null);
      loadingActionsSummaryFor.current = datapointId;
      setLoadingActionsFor(datapointId);

      // Generate a task_id for cancellation
      const task_id = uuid4();
      actionsSummaryTaskId.current = task_id;

      sendMessage('summarize_transcript', {
        datapoint_id: datapointId,
        summary_type: 'actions',
        _task_id: task_id,
      });
    },
    [sendMessage, setActionsSummary, cancelActionsSummary]
  );

  const requestSolutionSummary = useCallback(
    (datapointId: string) => {
      if (loadingSolutionSummaryFor.current === datapointId) {
        return;
      } else {
        cancelSolutionSummary();
      }

      setSolutionSummary(null);
      loadingSolutionSummaryFor.current = datapointId;
      setLoadingSolutionFor(datapointId);

      // Generate a task_id for cancellation
      const task_id = uuid4();
      solutionSummaryTaskId.current = task_id;

      sendMessage('summarize_transcript', {
        datapoint_id: datapointId,
        summary_type: 'solution',
        _task_id: task_id,
      });
    },
    [sendMessage, setSolutionSummary, cancelSolutionSummary]
  );

  const loadingExperimentTreeFor = useRef<string | number | null>(null);
  const requestExperimentTree = useCallback(
    (sampleId: string | number) => {
      if (loadingExperimentTreeFor.current === sampleId) {
        return;
      }

      loadingExperimentTreeFor.current = sampleId;
      sendMessage('get_merged_experiment_tree', { sample_id: sampleId });
    },
    [sendMessage]
  );

  const loadingTranscriptDerivationTreeFor = useRef<string | number | null>(
    null
  );
  const requestTranscriptDerivationTree = useCallback(
    (sampleId: string | number) => {
      if (loadingTranscriptDerivationTreeFor.current === sampleId) {
        return;
      }

      loadingTranscriptDerivationTreeFor.current = sampleId;
      sendMessage('get_transcript_derivation_tree', { sample_id: sampleId });
    },
    [sendMessage]
  );

  const loadingTranscriptDiffFor = useRef<[string, string] | null>(null);
  const transcriptDiffTaskId = useRef<string | null>(null);
  const requestTranscriptDiff = useCallback(
    (datapointId1: string, datapointId2: string) => {
      if (
        loadingTranscriptDiffFor.current &&
        loadingTranscriptDiffFor.current[0] === datapointId1 &&
        loadingTranscriptDiffFor.current[1] === datapointId2
      ) {
        return;
      }

      loadingTranscriptDiffFor.current = [datapointId1, datapointId2];
      setTranscriptDiffGraph(null);
      setTranscriptComparison(null);

      // Generate a task_id for cancellation
      const task_id = uuid4();
      transcriptDiffTaskId.current = task_id;

      sendMessage('diff_transcripts', {
        datapoint_id_1: datapointId1,
        datapoint_id_2: datapointId2,
        _task_id: task_id,
      });
    },
    [sendMessage]
  );

  const requestTranscriptMetadata = useCallback(
    (datapointIds: string[]) => {
      sendMessage('get_datapoint_metadata', { datapoint_ids: datapointIds });
    },
    [sendMessage]
  );

  // Add the requestAttributes implementation after the other request methods
  const requestAttributes = useCallback(
    (attribute: string) => {
      // Set the current attribute query
      setCurAttributeQuery(attribute);
      setLoadingAttributesFor(attribute);

      // Add to search history
      addToSearchHistory(attribute);

      // Clear only the specific attribute in the attribute map
      setAttributeMap((oldMap) => {
        const newMap = new Map<string, Map<string, AttributeWithCitation[]>>(
          oldMap
        );

        // For each datapoint, remove the specific attribute
        Array.from(newMap.keys()).forEach((datapointId) => {
          const attributesMap = newMap.get(datapointId);
          if (attributesMap && attributesMap.has(attribute)) {
            attributesMap.delete(attribute);
          }
        });

        return newMap;
      });

      // Generate a task_id for cancellation
      const taskId = uuid4();
      attributesTaskId.current = taskId;

      // Send the compute_attributes message to the server
      sendMessage('compute_attributes', {
        attribute: attribute,
        _task_id: taskId,
      });
    },
    [sendMessage, setCurAttributeQuery, addToSearchHistory]
  );

  // Send a message in the TA session
  const taMessageTaskId = useRef<string | null>(null);
  const sendTaMessage = useCallback(
    (message: string) => {
      if (!taSessionId || !isConnected) {
        return false;
      }

      setIsReceivingTaResponse(true);

      // Generate a task_id for cancellation
      const task_id = uuid4();
      taMessageTaskId.current = task_id;

      sendMessage('ta_message', {
        session_id: taSessionId,
        message: message,
        _task_id: task_id,
      });

      return true;
    },
    [taSessionId, isConnected, sendMessage, setIsReceivingTaResponse]
  );

  // Create a new TA session
  const createTaSession = useCallback(
    (datapointId: string) => {
      if (!datapointId || !isConnected) {
        return false;
      }

      sendMessage('create_ta_session', {
        base_filter: {
          id: 'datapoint_id_filter_for_ta_session',
          type: 'datapoint_id',
          value: datapointId,
        },
      });

      setCurTaDatapointId(datapointId);
      return true;
    },
    [sendMessage, isConnected, setCurTaDatapointId]
  );

  // Define cancelClustersRequest
  const clustersTaskId = useRef<string | null>(null);
  const cancelClustersRequest = useCallback(() => {
    if (clustersTaskId.current) {
      sendMessage('cancel_task', {
        _task_id: clustersTaskId.current,
      });
      clustersTaskId.current = null;
    }
  }, [sendMessage]);

  const requestClusters = useCallback(
    (dimensionId: string, feedback?: string) => {
      if (!frameGridId) return;

      // Cancel any existing clusters request
      cancelClustersRequest();

      // Generate a task_id for cancellation
      const taskId = uuid4();
      clustersTaskId.current = taskId;

      // Send the cluster_dimension message to the server
      sendMessage('cluster_dimension', {
        dim_id: dimensionId,
        feedback,
        _task_id: taskId,
      });
    },
    [frameGridId, sendMessage, cancelClustersRequest]
  );

  // Add the rewriteSearchQuery implementation
  const rewriteSearchQuery = useCallback(
    async (query: string): Promise<string> => {
      try {
        const response = await fetch(
          `http://${(BASE_URL || '').replace('http://', '')}/rewrite_search_query`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query }),
          }
        );

        if (!response.ok) {
          throw new Error(`Error: ${response.status}`);
        }

        const data = await response.json();
        return data.rewritten_query;
      } catch (error) {
        console.error('Error rewriting search query:', error);
        toast({
          title: 'Error',
          description: 'Failed to enhance the search query. Please try again.',
          variant: 'destructive',
        });
        return query; // Return the original query if there's an error
      }
    },
    []
  );

  // Fetch eval IDs from the server
  const fetchEvalIds = useCallback(async (): Promise<EvalId[]> => {
    try {
      console.log('Fetching eval IDs...');
      const response = await fetch(`${BASE_URL}/eval_ids`);
      const fetchedEvalIds = await response.json();

      setEvalIds(fetchedEvalIds);

      if (fetchedEvalIds.length === 0) {
        toast({
          title: 'Error',
          description: 'No pre-loaded evaluations found',
          variant: 'destructive',
        });
      }

      return fetchedEvalIds;
    } catch (error) {
      console.error('Error fetching eval IDs:', error);
      toast({
        title: 'Error',
        description: 'Failed to fetch evaluation IDs',
        variant: 'destructive',
      });
      return [];
    }
  }, []);

  // Fetch available eval IDs
  useEffect(() => {
    fetchEvalIds();
  }, [fetchEvalIds]);

  // Start a new evaluation session
  const startNewEval = useCallback(
    (evalId: EvalId) => {
      if (!isConnected) {
        console.error('WebSocket not connected, cannot start new evaluation');
        toast({
          title: 'Error',
          description: 'Cannot start evaluation: WebSocket not connected',
          variant: 'destructive',
        });
        return;
      }

      try {
        console.log(`Starting new evaluation with ID: ${evalId}`);
        sendMessage('create_session', { eval_ids: [evalId] });
        setCurEvalId(evalId);
      } catch (error) {
        console.error('Error starting new evaluation:', error);
        toast({
          title: 'Error',
          description: 'Failed to start new evaluation',
          variant: 'destructive',
        });
      }
    },
    [isConnected, sendMessage]
  );

  // Define the requestAddDimension function
  const requestAddDimension = useCallback(
    (attribute: string, bins: any) => {
      if (!frameGridId) return;

      sendMessage('add_dimension', {
        attribute,
        bins,
      });
    },
    [frameGridId, sendMessage]
  );

  // Implement clearExperimentTree and clearTranscriptDerivationTree
  const clearExperimentTree = useCallback(() => {
    setExperimentTree(null);
  }, []);

  const clearTranscriptDerivationTree = useCallback(() => {
    setTranscriptDerivationTree(null);
  }, []);

  // Define the requestReclusterDimension function and cancelReclusterDimension
  const reclusterDimensionTaskId = useRef<string | null>(null);

  const cancelReclusterDimension = useCallback(() => {
    if (reclusterDimensionTaskId.current) {
      sendMessage('cancel_task', {
        _task_id: reclusterDimensionTaskId.current,
      });
      reclusterDimensionTaskId.current = null;
    }
  }, [sendMessage]);

  const requestReclusterDimension = useCallback(
    (dimensionId: string) => {
      if (!frameGridId) return;

      // Cancel any existing recluster request
      cancelReclusterDimension();

      // Generate a task_id for cancellation
      const taskId = uuid4();
      reclusterDimensionTaskId.current = taskId;

      // Send the recluster_dimension message to the server
      sendMessage('recluster_dimension', {
        dim_id: dimensionId,
        _task_id: taskId,
      });
    },
    [frameGridId, sendMessage, cancelReclusterDimension]
  );

  // Websocket loop
  const transcriptMetadataRef = useRef<Record<string, any>>({});
  useEffect(() => {
    transcriptMetadataRef.current = transcriptMetadata;
  }, [transcriptMetadata]);

  // Handle metadata filter updates from backend
  const socketReady = useMemo(() => {
    return isConnected && socket !== null && frameGridId !== null;
  }, [isConnected, socket, frameGridId]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      console.log('ws_got_message', data);

      if (data.action === 'session_joined') {
        setFrameGridId(data.payload.id);
        sendMessage('get_state', { session_id: data.payload.id });
        sendMessage('get_transcript_metadata_fields', {});
      } else if (data.action === 'transcript_metadata_fields') {
        setTranscriptMetadataFields(data.payload.fields);
      } else if (data.action === 'base_filter') {
        // Update baseFilter from backend response
        if (data.payload.filter && data.payload.filter.filters) {
          setBaseFilters(data.payload.filter.filters);
        } else {
          setBaseFilters(null);
        }
      } else if (data.action === 'datapoint') {
        setCurDatapoint(data.payload.datapoint);
      } else if (data.action === 'datapoint_metadata') {
        setTranscriptMetadata((prev) => {
          const newMetadata = { ...prev, ...data.payload.metadata };
          return newMetadata;
        });
      } else if (data.action === 'datapoints_updated') {
        // Re-request metadata for all updated datapoints
        if (data.payload.datapoint_ids === null) {
          // Request all existing metadata
          requestTranscriptMetadata(Object.keys(transcriptMetadataRef.current));
        } else {
          requestTranscriptMetadata(data.payload.datapoint_ids);
        }

        if (transcriptDerivationTreeRef.current) {
          // Figure out if TranscriptGraph relies on this datapoint
          if (data.payload.datapoint_ids === null) {
            requestTranscriptDerivationTree(
              transcriptDerivationTreeRef.current.sample_id
            );
          } else {
            const matchingNodeIds = data.payload.datapoint_ids.filter(
              (id: string) =>
                transcriptDerivationTreeDatapointIdsRef.current?.has(id)
            );
            if (matchingNodeIds.length > 0) {
              requestTranscriptDerivationTree(
                transcriptDerivationTreeRef.current.sample_id
              );
            }
          }
        }

        // Figure out if ExperimentTree relies on this datapoint
        if (experimentTreeRef.current) {
          if (data.payload.datapoint_ids === null) {
            requestExperimentTree(experimentTreeRef.current.sample_id);
          } else {
            const matchingNodeIds = data.payload.datapoint_ids.filter(
              (id: string) => experimentTreeDatapointIdsRef.current?.has(id)
            );
            if (matchingNodeIds.length > 0) {
              requestExperimentTree(experimentTreeRef.current.sample_id);
            }
          }
        }

        // Request current datapoint
        if (curDatapointRef.current) {
          sendMessage('get_datapoint', {
            datapoint_id: curDatapointRef.current.id,
          });
        }
      } else if (data.action === 'compute_attributes_update') {
        handleAttributesUpdate(data.payload as StreamedAttribute);
      } else if (data.action === 'compute_attributes_complete') {
        setLoadingAttributesFor(null);
        setNumAttributeUpdatesReceived([0, 0]);
        // // Only request clusters if there are at least 10 matching results
        // if (data.payload.num_matching >= 10) {
        //   requestClusters(data.payload.dim_id);
        // }
      } else if (data.action === 'dimensions') {
        setDimensions(data.payload.dimensions);
      } else if (data.action === 'marginals') {
        setMarginals(data.payload.marginals);
      } else if (data.action === 'cluster_proposals') {
        setClusterProposals(data.payload.proposals);
        setClusterSessionId(data.payload.cluster_session_id);
      } else if (data.action === 'specific_marginals') {
        if (data.payload.request_type === 'exp_stats') {
          setRawExpStatMarginals(data.payload.marginals);
        } else if (data.payload.request_type === 'exp_locs') {
          setExpBins(data.payload.bins);
          setRawExpIdMarginals(data.payload.marginals);
        } else if (data.payload.request_type === 'per_sample_stats') {
          setPerSampleStats(data.payload.marginals);
        } else if (data.payload.request_type === 'per_experiment_stats') {
          setPerExperimentStats(data.payload.marginals);
        } else if (data.payload.request_type === 'intervention_descriptions') {
          setInterventionDescriptions(data.payload.marginals);
        }
      } else if (data.action === 'ta_session_created') {
        setTaSessionId(data.payload.session_id);
      } else if (data.action === 'ta_message_chunk') {
        const newMessages = data.payload.messages.filter(
          (msg: any) => msg.role === 'user' || msg.role === 'assistant'
        );
        setTaMessages(newMessages);
      } else if (data.action === 'ta_message_complete') {
        setIsReceivingTaResponse(false);
      } else if (data.action === 'summarize_transcript_update') {
        if (
          data.payload.type === 'solution' &&
          loadingSolutionSummaryFor.current === data.payload.datapoint_id
        ) {
          setSolutionSummary(data.payload);
        } else if (
          data.payload.type === 'actions' &&
          loadingActionsSummaryFor.current === data.payload.datapoint_id
        ) {
          setActionsSummary(data.payload.actions);
        }
      } else if (data.action === 'summarize_transcript_complete') {
        if (
          data.payload.type === 'solution' &&
          loadingSolutionSummaryFor.current === data.payload.datapoint_id
        ) {
          loadingSolutionSummaryFor.current = null;
          setLoadingSolutionFor(null);
          solutionSummaryTaskId.current = null;
        } else if (
          data.payload.type === 'actions' &&
          loadingActionsSummaryFor.current === data.payload.datapoint_id
        ) {
          loadingActionsSummaryFor.current = null;
          setLoadingActionsFor(null);
          actionsSummaryTaskId.current = null;
        }
      } else if (data.action === 'transcript_diff_result') {
        setTranscriptDiffGraph({
          nodes: data.payload.nodes,
          edges: data.payload.edges,
        });
        loadingTranscriptDiffFor.current = null;
      } else if (data.action === 'compare_transcripts_update') {
        setTranscriptComparison(data.payload);
      } else if (data.action === 'get_merged_experiment_tree_result') {
        if (loadingExperimentTreeFor.current === data.payload.sample_id) {
          setExperimentTree(data.payload);
          loadingExperimentTreeFor.current = null;
        }
      } else if (data.action === 'get_transcript_derivation_tree_result') {
        if (
          loadingTranscriptDerivationTreeFor.current === data.payload.sample_id
        ) {
          setTranscriptDerivationTree(data.payload);
          loadingTranscriptDerivationTreeFor.current = null;
        }
      } else if (data.action === 'error') {
        toast({
          title: 'Error',
          description: data.payload.message,
          variant: 'destructive',
        });
      } else if (data.action === 'rate_limit_error') {
        setIsRateLimited(true);
      } else if (data.action === 'api_keys') {
        setApiKeys(data.payload);
      } else if (data.action === 'api_keys_updated') {
        toast({
          title: 'Success',
          description: data.payload.message,
        });
      } else {
        console.error('Unknown message action:', data.action);
      }
    };

    if (socket) {
      socket.addEventListener('message', handleMessage);
      return () => {
        if (socket) {
          socket.removeEventListener('message', handleMessage);
        }
      };
    }
    return undefined;
  }, [
    socket,
    sendMessage,
    setFrameGridId,
    setTranscriptMetadataFields,
    setBaseFilters,
    setCurDatapoint,
    setTranscriptMetadata,
    requestTranscriptMetadata,
    requestTranscriptDerivationTree,
    requestExperimentTree,
    requestClusters,
    setDimensions,
    setMarginals,
    setClusterProposals,
    setClusterSessionId,
    setExpBins,
    setRawExpStatMarginals,
    setRawExpIdMarginals,
    setPerSampleStats,
    setPerExperimentStats,
    setInterventionDescriptions,
    setTaSessionId,
    setTaMessages,
    setIsReceivingTaResponse,
    setSolutionSummary,
    setActionsSummary,
    setTranscriptDiffGraph,
    setExperimentTree,
    setTranscriptDerivationTree,
    setNumAttributeUpdatesReceived,
    setIsRateLimited,
  ]);

  // Define the handleClearAttribute function
  const handleClearAttribute = useCallback(
    (dimId: string | null) => {
      // If there's a dimension ID, we need to delete it
      sendMessage('delete_dimension', {
        dim_id: dimId || curAttributeQuery,
      });

      // Clear the current attribute query
      setCurAttributeQuery(null);
      cancelAttributeQuery();
      cancelClustersRequest();
    },
    [
      setCurAttributeQuery,
      cancelAttributeQuery,
      cancelClustersRequest,
      sendMessage,
    ]
  );

  return (
    <FrameGridContext.Provider
      value={{
        // WebSocket values
        socket,
        isConnected,
        sendMessage,
        socketReady,
        showDisconnectModal,
        setShowDisconnectModal,
        apiKeys,
        setApiKeys,
        selectedDiffTranscript,
        setSelectedDiffTranscript,
        selectedDiffSampleId,
        setSelectedDiffSampleId,
        transcriptDiffViewport,
        setTranscriptDiffViewport,
        baseFilter: baseFilters,
        setBaseFilter: setBaseFilters,
        transcriptMetadataFields,
        setTranscriptMetadataFields,
        curAttributeQuery,
        loadingAttributesFor,
        numAttributeUpdatesReceived,
        setCurAttributeQuery,
        expBins,
        setExpBins,
        expIdMarginals,
        setExpIdMarginals: setRawExpIdMarginals,
        expStatMarginals,
        setExpStatMarginals: setRawExpStatMarginals,
        perSampleStats,
        setPerSampleStats,
        perExperimentStats,
        setPerExperimentStats,
        interventionDescriptions,
        setInterventionDescriptions,
        curDatapoint,
        setCurDatapoint,
        attributeMap,
        setAttributeMap,
        solutionSummary,
        actionsSummary,
        clearSolutionSummary,
        clearActionsSummary,
        loadingActionsSummaryFor: loadingActionsFor,
        loadingSolutionSummaryFor: loadingSolutionFor,
        taSessionId,
        setTaSessionId,
        curTaDatapointId,
        setCurTaDatapointId,
        taMessages,
        setTaMessages,
        clearTaMessages,
        isReceivingTaResponse,
        setIsReceivingTaResponse,
        sendTaMessage,
        createTaSession,
        frameGridId,
        setFrameGridId,
        dimensions,
        setDimensions,
        marginals,
        setMarginals,
        clusterProposals,
        clusterSessionId,
        setClusterProposals,
        setClusterSessionId,
        transcriptMetadata,
        setTranscriptMetadata,
        transcriptDiffGraph,
        transcriptComparison,
        experimentTree,
        clearExperimentTree,
        transcriptDerivationTree,
        clearTranscriptDerivationTree,
        requestTranscriptDiff,
        requestActionsSummary,
        requestSolutionSummary,
        cancelActionsSummary,
        cancelSolutionSummary,
        requestExperimentTree,
        requestTranscriptDerivationTree,
        requestTranscriptMetadata,
        requestAttributes,
        requestClusters,
        requestReclusterDimension,
        cancelReclusterDimension,
        requestAddDimension,
        cancelClustersRequest,
        cancelAttributeQuery,
        handleClearAttribute,
        onClearDatapoint,
        onAddFilter,
        onRemoveFilter,
        onClearFilters,
        organizationMethod,
        setOrganizationMethod,
        expandedOuter,
        setExpandedOuter,
        expandedInner,
        setExpandedInner,
        experimentViewerScrollPosition,
        setExperimentViewerScrollPosition,
        evalIds,
        fetchEvalIds,
        startNewEval,
        curEvalId,
        rewriteSearchQuery,
        searchHistory,
        addToSearchHistory,
        setSearchHistory,
        clearSearchHistory,
        isRateLimited,
        setIsRateLimited,
        isApiKeyModalOpen,
        setIsApiKeyModalOpen,
      }}
    >
      {children}
    </FrameGridContext.Provider>
  );
}

export const useFrameGrid = () => {
  const context = useContext(FrameGridContext);
  if (!context) {
    throw new Error('useFrameGrid must be used within a FrameGridProvider');
  }
  return context;
};
