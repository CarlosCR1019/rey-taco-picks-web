import React from 'react';
import { ReelFrame } from './ReyTacoResultsReel';
import type { ReelInput } from './contracts';

export const ReyTacoTeaserReel: React.FC<ReelInput> = (input) => <ReelFrame input={input} teaser />;
