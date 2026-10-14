import type { ReactNode } from 'react';
import { pageNames, type Page } from '../features/navigation/navigation';

type Props = { page: Page; activePage: Page; children: ReactNode };
export default function WorkbenchPage({ page, activePage, children }: Props) {
  // Keep feature components mounted: changing pages must not lose files or stop polling.
  return <section hidden={activePage !== page} data-testid={'page-' + page}
    className="workbench-page" aria-labelledby={activePage === page ? 'page-title-' + page : undefined}
    aria-label={activePage !== page ? pageNames[page] : undefined}>
    {children}
  </section>;
}
