import type React from 'react';

export type WordLayer = {
  word_id: string;
  word: string;
  image_public_path: string;
  x: number;
  y: number;
  width: number;
  height: number;
  appear_sec: number;
  appear_frame: number;
  timing_strategy: string;
  confidence?: number | null;
};

export type MediaLayer = {
  asset_id: string;
  candidate_id: string;
  provider: string;
  kind: string;
  role: string;
  title: string;
  media_public_path: string;
  media_type: 'image' | 'gif' | 'video';
  x: number;
  y: number;
  width: number;
  height: number;
};

export type DomLayer = {
  id: string;
  tag: string;
  class_name: string;
  asset_id?: string | null;
  word_id?: string | null;
  text?: string;
  style: React.CSSProperties;
  appear_sec?: number | null;
  appear_frame?: number | null;
  timing_strategy?: string;
  confidence?: number | null;
};

export type RenderScene = {
  scene_id: number;
  fragment_ids: number[];
  raw_start_sec: number;
  raw_end_sec: number;
  raw_duration_sec: number;
  visual_start_sec: number;
  visual_end_sec: number;
  visual_duration_sec: number;
  visual_start_frame: number;
  visual_end_frame: number;
  scene_image_public_path: string;
  base_scene_image_public_path?: string;
  background_color: string;
  asset_status: string;
  media_layers?: MediaLayer[];
  media_by_asset_id?: Record<string, MediaLayer>;
  word_layers?: WordLayer[];
  dom_layers?: DomLayer[];
};

export type RenderItem = {
  post_id: string;
  subreddit: string;
  title: string;
  composition_id: string;
  status: 'pass' | 'fail';
  duration_sec: number;
  duration_frames: number;
  fps: number;
  width: number;
  height: number;
  audio_public_path: string;
  scenes: RenderScene[];
};

export type RenderBundle = {
  items: RenderItem[];
  metadata: {
    fps: number;
    width: number;
    height: number;
  };
};
