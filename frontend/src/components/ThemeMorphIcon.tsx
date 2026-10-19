import { MorphIcon } from 'morphicons/react';
import type { ComponentProps } from 'react';
import type { Theme } from '../lib/theme';

type IconData = NonNullable<ComponentProps<typeof MorphIcon>['icon']>;
// Existing local Lucide geometry; its ISC notice remains in public/assets/lucide.LICENSE.txt.
const sun: IconData = [
  ['circle', { cx: '12', cy: '12', r: '4' }],
  ['path', { d: 'M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41' }],
];
const moon: IconData = [['path', { d: 'M12 3a6 6 0 0 0 9 9a9 9 0 1 1-9-9' }]];

export default function ThemeMorphIcon({ theme }: { theme: Theme }) {
  // Keep one mounted SVG. The icon shows the action, matching the existing button label.
  return <MorphIcon className="icon theme-morph-icon" icon={theme === 'dark' ? sun : moon}
    size={18} strokeWidth={2} spring="snappy" reducedMotion="user"
    aria-hidden="true" focusable="false" data-icon={theme === 'dark' ? 'lucide:sun' : 'lucide:moon'} />;
}
