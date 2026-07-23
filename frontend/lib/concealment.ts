import type { Concealment } from './api';

/** The shared visual language for a concealment card. The denial is a warning to
 *  keep something OUT (red); the substitution is an instruction to have something
 *  READY (amber). BriefPanel and BriefingScreen render this same mapping in
 *  different layouts, so the colour/label pairing lives here rather than being
 *  copied — and drifting — between the two. */
export interface ConcealmentStyle {
    /** Text and border colour. */
    accent: string;
    background: string;
    label: string;
}

export function concealmentStyle(kind: Concealment['kind']): ConcealmentStyle {
    const denial = kind === 'denial';
    return {
        accent: denial ? 'var(--red-accent)' : 'var(--amber)',
        background: denial ? 'rgba(212, 54, 74, 0.08)' : 'rgba(212, 160, 54, 0.08)',
        label: denial ? 'Do not admit' : 'You must be able to say',
    };
}
