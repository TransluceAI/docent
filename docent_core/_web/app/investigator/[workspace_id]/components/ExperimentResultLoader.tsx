'use client';

// This component is no longer needed as result loading is handled locally in CounterfactualExperimentViewer
// Keeping as empty component for backward compatibility
export default function ExperimentResultLoader({
  workspaceId,
  experimentConfigId,
}: {
  workspaceId: string;
  experimentConfigId: string;
}) {
  return null;
}
