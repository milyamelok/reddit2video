import React from 'react';
import {Composition} from 'remotion';
import {HtmlLayoutComposition, htmlLayoutCompositions} from './HtmlLayoutComposition';
import bundlePayload from './render-bundle.generated.json';
import {VideoComposition} from './VideoComposition';
import type {RenderBundle, RenderItem} from './types';

const bundle = bundlePayload as unknown as RenderBundle;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {bundle.items
        .filter((item: RenderItem) => item.status === 'pass')
        .map((item: RenderItem) => (
          <Composition
            key={item.composition_id}
            id={item.composition_id}
            component={VideoComposition}
            durationInFrames={Math.max(1, item.duration_frames)}
            fps={item.fps}
            width={item.width}
            height={item.height}
            defaultProps={{item}}
          />
        ))}
      {htmlLayoutCompositions.map((item) => (
        <Composition
          key={item.composition_id}
          id={item.composition_id}
          component={HtmlLayoutComposition}
          durationInFrames={Math.max(1, item.duration_frames)}
          fps={item.fps}
          width={item.width}
          height={item.height}
        />
      ))}
    </>
  );
};
