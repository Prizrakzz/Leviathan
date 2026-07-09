import type { PdfTabParams } from '@/store/tabs';
import { PdfViewer } from '@/views/pdf/PdfViewer';

/** A workspace pdf tab (P1.5-T3): the full-surface PdfViewer inside the document area. This module is
 *  lazy-loaded via the registry, so pdf.js (which PdfViewer pulls) stays off the first-paint bundle.
 *  Known v1 limit: a tab left idle past the presign TTL (~15 min) page-loads from an expired url → blank
 *  canvas; re-presign-on-403 is a follow-up. */
export default function PdfTab({ params }: { params: PdfTabParams }) {
  return (
    <div className="h-full" data-testid="pdf-tab">
      <PdfViewer
        sourceKey={params.sourceKey}
        snippet={params.snippet}
        charStart={params.charStart}
        offsetKind={params.offsetKind}
      />
    </div>
  );
}
