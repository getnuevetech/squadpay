/**
 * adminApi/landingPage.ts — Public landing-page visual config
 * (random phone-frame colours, avatars, hashtags, background shades).
 */
import { _aRequest } from './_core';

export type LandingPageConfig = {
  phone_frame_colors: string[];
  bg_purple_shades: string[];
  hashtags: string[];
  avatars: {
    slot_left: string[];
    slot_right_man: string[];
    slot_right_woman: string[];
  };
  updated_at?: string;
  updated_by?: string;
};

export const landingPageConfigApi = {
  get: () => _aRequest<LandingPageConfig>('/admin/landing-page'),
  set: (cfg: Partial<Omit<LandingPageConfig, 'updated_at' | 'updated_by'>>) =>
    _aRequest<{ ok: boolean } & LandingPageConfig>('/admin/landing-page', {
      method: 'PUT',
      body: JSON.stringify(cfg),
    }),
};
