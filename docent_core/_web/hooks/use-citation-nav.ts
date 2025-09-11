import { useRouter, usePathname } from 'next/navigation';
import { useAppSelector } from '@/app/store/hooks';
import { useCitationHighlight } from '@/lib/citationUtils';
import { useCitationNavigation } from '@/app/dashboard/[collection_id]/rubric/[rubric_id]/NavigateToCitationContext';
import { Citation } from '@/app/types/experimentViewerTypes';
import posthog from 'posthog-js';
import { JudgeResultWithCitations } from '@/app/store/rubricSlice';

export const useCitationNav = (judgeResult: JudgeResultWithCitations) => {
  const router = useRouter();
  const pathname = usePathname();
  const collectionId = useAppSelector((state) => state.collection.collectionId);
  const { highlightCitation } = useCitationHighlight();
  const citationNav = useCitationNavigation();

  const handleNavigateToCitation = ({
    citation,
    newTab,
  }: {
    citation: Citation | null;
    newTab?: boolean;
  }) => {
    const url = `/dashboard/${collectionId}/rubric/${judgeResult.rubric_id}/result/${judgeResult.id}`;

    // Check if we're already on the target result page
    const isOnTargetPage = pathname === url;

    if (newTab) {
      // Always open in new tab when requested
      window.open(url, '_blank');
      if (citation && citationNav?.navigateToCitation) {
        citationNav.navigateToCitation({ citation, newTab });
      }
    } else if (isOnTargetPage) {
      // We're already on the target page, just navigate to the citation
      if (citation && citationNav?.navigateToCitation) {
        citationNav.navigateToCitation({ citation, newTab });
      }
    } else {
      // We need to navigate to a different page
      if (citationNav?.prepareForNavigation) {
        citationNav.prepareForNavigation(); // Clear current handler for navigation
      }
      router.push(url, { scroll: false } as any);
      if (citation && citationNav?.navigateToCitation) {
        citationNav.navigateToCitation({ citation, newTab });
      }
    }

    // Always capture analytics and highlight
    if (citation) {
      posthog.capture('citation_clicked', {
        source: 'judge_result',
        agent_run_id: judgeResult.agent_run_id,
        transcript_idx: citation.transcript_idx,
        block_idx: citation.block_idx,
        start_pattern: citation.start_pattern,
      });
      highlightCitation(citation);
    }
  };

  return {
    handleNavigateToCitation,
  };
};
