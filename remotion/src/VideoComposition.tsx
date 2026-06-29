import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  Video,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import type {DomLayer, MediaLayer, RenderItem, RenderScene, WordLayer} from './types';

type Props = {
  item: RenderItem;
};

export const VideoComposition: React.FC<Props> = ({item}) => {
  const frame = useCurrentFrame();
  const activeScene =
    item.scenes.find(
      (scene: RenderScene) => frame >= scene.visual_start_frame && frame < scene.visual_end_frame,
    ) || item.scenes[item.scenes.length - 1];

  return (
    <AbsoluteFill style={{backgroundColor: activeScene?.background_color || '#d99caf'}}>
      <GlobalFontFaces />
      {item.scenes.map((scene: RenderScene, index: number) => {
        const isLastScene = index === item.scenes.length - 1;
        const isVisible =
          frame >= scene.visual_start_frame &&
          (frame < scene.visual_end_frame || (isLastScene && frame < item.duration_frames));
        if (!isVisible) {
          return null;
        }
        const localFrame = frame - scene.visual_start_frame;
        const hasDomLayers = (scene.dom_layers || []).length > 0;
        const hasWordLayers = (scene.word_layers || []).length > 0;
        const baseImage =
          hasWordLayers && scene.base_scene_image_public_path
            ? scene.base_scene_image_public_path
            : scene.scene_image_public_path;
        const opacity = hasWordLayers
          ? 1
          : interpolate(localFrame, [0, 5, 13], [0, 0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
        const scale = hasWordLayers
          ? 1
          : interpolate(localFrame, [0, 13], [0.985, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });

        return (
          <AbsoluteFill key={scene.scene_id} style={{backgroundColor: scene.background_color}}>
            {hasDomLayers ? (
              <DomScene scene={scene} frame={frame} localFrame={localFrame} />
            ) : (
              <>
                <Img
                  src={staticFile(baseImage)}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    opacity,
                    transform: `scale(${scale})`,
                  }}
                />
                <Sequence
                  from={scene.visual_start_frame}
                  durationInFrames={Math.max(1, scene.visual_end_frame - scene.visual_start_frame)}
                >
                  {(scene.media_layers || []).map((layer: MediaLayer) => {
                    const mediaOpacity = interpolate(localFrame, [0, 6], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    });
                    const mediaScale = interpolate(localFrame, [0, 10], [0.97, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    });
                    const mediaStyle: React.CSSProperties = {
                      position: 'absolute',
                      left: layer.x,
                      top: layer.y,
                      width: layer.width,
                      height: layer.height,
                      objectFit: 'cover',
                      opacity: mediaOpacity,
                      transform: `scale(${mediaScale})`,
                      borderRadius: 18,
                      pointerEvents: 'none',
                    };

                    return <MediaAsset key={layer.asset_id} layer={layer} style={mediaStyle} />;
                  })}
                </Sequence>
              </>
            )}
            {!hasDomLayers && (scene.word_layers || []).map((layer: WordLayer) => {
              const wordFrame = frame - layer.appear_frame;
              const wordOpacity = interpolate(wordFrame, [0, 4], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              const wordY =
                layer.y +
                interpolate(wordFrame, [0, 4], [8, 0], {
                  extrapolateLeft: 'clamp',
                  extrapolateRight: 'clamp',
                });

              return (
                <Img
                  key={layer.word_id}
                  src={staticFile(layer.image_public_path)}
                  style={{
                    position: 'absolute',
                    left: layer.x,
                    top: wordY,
                    width: layer.width,
                    height: layer.height,
                    objectFit: 'contain',
                    opacity: wordOpacity,
                    pointerEvents: 'none',
                  }}
                />
              );
            })}
          </AbsoluteFill>
        );
      })}
      <Audio src={staticFile(item.audio_public_path)} />
    </AbsoluteFill>
  );
};

const MediaAsset: React.FC<{layer: MediaLayer; style: React.CSSProperties}> = ({layer, style}) => {
  if (layer.media_type === 'video') {
    return <Video src={staticFile(layer.media_public_path)} muted loop style={style} />;
  }

  return <Img src={staticFile(layer.media_public_path)} style={style} />;
};

const DomScene: React.FC<{scene: RenderScene; frame: number; localFrame: number}> = ({
  scene,
  frame,
  localFrame,
}) => {
  const mediaByAssetId = scene.media_by_asset_id || {};
  return (
    <>
      {(scene.dom_layers || []).map((layer: DomLayer) => (
        <DomLayerView
          key={layer.id}
          layer={layer}
          media={layer.asset_id ? mediaByAssetId[layer.asset_id] : undefined}
          frame={frame}
          localFrame={localFrame}
        />
      ))}
    </>
  );
};

const DomLayerView: React.FC<{
  layer: DomLayer;
  media?: MediaLayer;
  frame: number;
  localFrame: number;
}> = ({layer, media, frame, localFrame}) => {
  const rawStyle = layer.style || {};
  const baseOpacity =
    typeof rawStyle.opacity === 'number'
      ? rawStyle.opacity
      : rawStyle.opacity
        ? Number(rawStyle.opacity)
        : 1;
  const style: React.CSSProperties = {
    ...rawStyle,
    opacity: Number.isFinite(baseOpacity) ? baseOpacity : 1,
    pointerEvents: 'none',
  };

  if (media) {
    const mediaOpacity = interpolate(localFrame, [0, 6], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    const mediaScale = interpolate(localFrame, [0, 10], [0.98, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    style.opacity = (Number(style.opacity) || 1) * mediaOpacity;
    style.transform = `${style.transform || ''} scale(${mediaScale})`;
    style.borderStyle = 'none';
    style.backgroundColor = 'transparent';
    style.overflow = 'hidden';
  } else if (layer.word_id && layer.appear_frame !== null && layer.appear_frame !== undefined) {
    const wordFrame = frame - layer.appear_frame;
    const wordOpacity = interpolate(wordFrame, [0, 4], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    const wordLift = interpolate(wordFrame, [0, 4], [8, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    style.opacity = (Number(style.opacity) || 1) * wordOpacity;
    style.transform = `${style.transform || ''} translateY(${wordLift}px)`;
  }

  return (
    <div style={style}>
      {media ? (
        <MediaAsset
          layer={media}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
          }}
        />
      ) : (
        layer.text || null
      )}
    </div>
  );
};

const GlobalFontFaces: React.FC = () => (
  <style>
    {`
      @font-face {
        font-family: "Kalissa";
        src: url("${staticFile('style_packs/static_girly/Fonts/Kalissa/KalissaRegular_0.otf')}") format("opentype");
        font-weight: 400;
        font-style: italic;
        font-display: swap;
      }
      @font-face {
        font-family: "Neo Sans Pro Cyrillic";
        src: url("${staticFile('style_packs/static_girly/Fonts/Neo Sans Pro Cyrillic Bold/neo-sans-pro-cyr-bold.otf')}") format("opentype");
        font-weight: 700;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "TNT Sans Condensed";
        src: url("${staticFile('style_packs/static_girly/Fonts/TNT Sans Condensed/TNTSansCondensed.otf')}") format("opentype");
        font-weight: 400;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "TNT Sans Condensed";
        src: url("${staticFile('style_packs/static_girly/Fonts/TNT Sans Condensed/TNTSansCondensed-Medium.otf')}") format("opentype");
        font-weight: 500;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "TNT Sans Condensed";
        src: url("${staticFile('style_packs/static_girly/Fonts/TNT Sans Condensed/TNTSansCondensed-Demibold.otf')}") format("opentype");
        font-weight: 700;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "PP Object Sans";
        src: url("${staticFile('style_packs/static_girly/Fonts/PP Object Sans/object.ttf')}") format("truetype");
        font-weight: 400 900;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "Helvetica Bold CY";
        src: url("${staticFile('style_packs/static_girly/Fonts/Helvetica-Bold CY [Rus by me]/helvetica_boldcyrusbyme.otf')}") format("opentype");
        font-weight: 700 950;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: "Cormorant Garamond";
        src: url("${staticFile('style_packs/static_girly/Fonts/Cormorant Garamond/CormorantGaramond-BoldItalic.ttf')}") format("truetype");
        font-weight: 700;
        font-style: italic;
        font-display: swap;
      }
    `}
  </style>
);
