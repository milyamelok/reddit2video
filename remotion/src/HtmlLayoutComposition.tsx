import React from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import htmlPayload from './html-layout.generated.json';

type HtmlScene = {
  scene_id: number;
  start_frame: number;
  duration_frames: number;
  asset_timings?: Record<string, AssetTiming>;
  vfx_timings?: VfxTiming[];
  word_timings?: WordTiming[];
  bridge_media_assets?: MediaAsset[];
  final_choice_media?: MediaAsset[];
  final_choice_labels?: string[];
  semantic_visual?: SemanticVisual;
  html: string;
};

type AssetTiming = {
  appear_frame: number;
  appears_on_word?: string;
  global_sec?: number;
  confidence?: string;
};

type VfxTiming = {
  target: string;
  appear_frame: number;
  cue_word?: string;
  role?: string;
  confidence?: string;
};

type WordTiming = {
  index: number;
  word_index?: number;
  word?: string;
  text?: string;
  appear_frame: number;
  appear_sec?: number;
  start_sec?: number;
  end_sec?: number;
  confidence?: string | number;
  timing_strategy?: string;
};

type MediaAsset = {
  id: string;
  kind: 'image' | 'video';
  role: string;
  src: string;
  fit: React.CSSProperties['objectFit'];
  focusX: string;
  focusY: string;
};

type SemanticVisual = {
  id: string;
  kind: 'semantic_motion';
  quality?: string;
  source?: string;
  topic?: string;
  layout?: string;
  motifs?: string[];
};

type ProofCue = {
  kicker: string;
  value: string;
  detail?: string;
};

type SceneTopic = 'food' | 'thermal' | 'supplements' | 'recovery' | 'general';

type DesignFamily = 'video' | 'feature' | 'duel' | 'hero' | 'slam' | 'stack' | 'final' | 'default';

type SceneDesign = {
  family: DesignFamily;
  accent: string;
  secondary: string;
  paper: string;
  dark: string;
  proof?: ProofCue;
};

type HtmlLayoutPayload = {
  composition_id: string;
  layout_mode?: string;
  metadata?: Record<string, unknown>;
  fps: number;
  width: number;
  height: number;
  duration_frames: number;
  audio_public_path?: string;
  post_id?: string;
  subreddit?: string;
  story_title?: string;
  css: string;
  scenes: HtmlScene[];
};

const payload = htmlPayload as unknown as HtmlLayoutPayload;

export const htmlLayoutCompositions = [payload];

const isBLayoutStagedVfxPayload = (): boolean =>
  payload.layout_mode === 'b_layout_staged_vfx' ||
  payload.layout_mode === 'b_layout_staged_vfx_clean' ||
  payload.layout_mode === 'b_layout_staged_vfx_no_labels';

const isCleanOrnamentLayout = (): boolean => payload.layout_mode === 'b_layout_staged_vfx_clean';

const isNoChromeTextLayout = (): boolean => payload.layout_mode === 'b_layout_staged_vfx_no_labels';

const palettes = [
  {accent: '#e94f37', secondary: '#0f6f6a', paper: '#fff8ee', dark: '#17120f'},
  {accent: '#2e6dd8', secondary: '#d49b2f', paper: '#f8faf3', dark: '#101622'},
  {accent: '#bf3f5a', secondary: '#547a39', paper: '#fff6f6', dark: '#1b1215'},
  {accent: '#0b7c86', secondary: '#db5f42', paper: '#f8f2e6', dark: '#111617'},
  {accent: '#8b4fd1', secondary: '#e2b13b', paper: '#f9f6ff', dark: '#18111f'},
];

export const HtmlLayoutComposition: React.FC = () => {
  const frame = useCurrentFrame();
  const activeIndex = Math.max(
    0,
    payload.scenes.findIndex(
      (scene) => frame >= scene.start_frame && frame < scene.start_frame + scene.duration_frames,
    ),
  );
  const activeScene = payload.scenes[activeIndex] || payload.scenes[payload.scenes.length - 1];
  const localFrame = Math.max(0, frame - activeScene.start_frame);
  const design = getSceneDesign(activeScene, activeIndex === payload.scenes.length - 1);
  const stagedVfxLayout = isBLayoutStagedVfxPayload();
  const sceneMotionCss = buildSceneMotionCss(activeScene, localFrame, payload.fps, design, stagedVfxLayout);
  const sceneProgress = clamp(localFrame / Math.max(1, activeScene.duration_frames - 1), 0, 1);
  const reveal = stagedVfxLayout ? 1 : easeOutCubic(progress(localFrame, 0, 14));
  const scale = stagedVfxLayout ? 1 : round(1.012 + sceneProgress * 0.018);
  const lift = stagedVfxLayout ? 0 : round((1 - reveal) * 18);
  const opacity = stagedVfxLayout ? 1 : round(0.35 + reveal * 0.65);
  const sceneHtml = prepareSceneHtml(activeScene, false);

  return (
    <AbsoluteFill style={{backgroundColor: design.paper}}>
      <style>{payload.css}</style>
      <style>{sceneMotionCss}</style>
      <div
        id="remotion-html-stage"
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          ['--scene-accent' as string]: design.accent,
          ['--scene-secondary' as string]: design.secondary,
          ['--scene-paper' as string]: design.paper,
          ['--scene-dark' as string]: design.dark,
        }}
      >
        <SceneColorField scene={activeScene} localFrame={localFrame} design={design} />
        <div
          className="quality-scene-frame"
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            zIndex: 2,
            opacity,
            overflow: 'hidden',
            transform: stagedVfxLayout ? 'translate3d(0, 0, 0) scale(1)' : `translateY(${lift}px) scale(${scale})`,
            transformOrigin: 'center center',
          }}
        >
          <Sequence from={activeScene.start_frame} durationInFrames={activeScene.duration_frames}>
            <SceneMediaBackdrop scene={activeScene} localFrame={localFrame} design={design} />
            <SceneImageComposition scene={activeScene} localFrame={localFrame} design={design} />
            <SceneGraphicLayer scene={activeScene} localFrame={localFrame} design={design} />
            <SceneCaptionCard scene={activeScene} localFrame={localFrame} design={design} />
            <div
              className="quality-scene-html"
              style={{position: 'absolute', inset: 0, zIndex: 34}}
              dangerouslySetInnerHTML={{__html: sceneHtml}}
            />
          </Sequence>
        </div>
      </div>
      <SceneContrast />
      {payload.audio_public_path ? <Audio src={staticFile(payload.audio_public_path)} /> : null}
    </AbsoluteFill>
  );
};

const IntroSourceCard: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  if (scene.scene_id !== 1) {
    return null;
  }
  const reveal = easeOutBack(progress(localFrame, 5, 18));
  const exit = 1 - easeOutCubic(progress(localFrame, Math.max(70, scene.duration_frames - 36), 28));
  const opacity = round(clamp(reveal, 0, 1) * clamp(exit, 0, 1));
  const label = payload.subreddit ? `r/${payload.subreddit}` : 'reddit';
  const caseTitle = sourceCaseTitle(scene);
  return (
    <div
      style={{
        position: 'absolute',
        left: 44,
        top: 958,
        width: 272,
        zIndex: 120,
        opacity,
        transform: `translateY(${round((1 - clamp(reveal, 0, 1)) * 18)}px) rotate(-2deg)`,
        color: design.dark,
        fontFamily: '"TNT Sans Condensed", "Neo Sans Pro Cyrillic", Arial, sans-serif',
        letterSpacing: 0,
        pointerEvents: 'none',
        background: 'rgba(255, 250, 240, 0.92)',
        border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
        boxShadow: `0 20px 50px ${hexToRgba(design.dark, 0.18)}`,
        padding: '14px 16px 13px',
      }}
    >
      <div style={{fontSize: 15, fontWeight: 800, textTransform: 'uppercase'}}>{label}</div>
      <div
        style={{
          marginTop: 8,
          width: 56,
          height: 5,
          background: design.accent,
        }}
      />
      <div style={{marginTop: 11, fontSize: 28, fontWeight: 900, lineHeight: 0.88, textTransform: 'uppercase'}}>
        {caseTitle}
      </div>
      <div style={{marginTop: 8, fontSize: 12, fontWeight: 700, opacity: 0.68, textTransform: 'uppercase'}}>
        case file 01
      </div>
    </div>
  );
};

const SceneContrast: React.FC = () => (
  <>
    <AbsoluteFill
      style={{
        zIndex: 80,
        pointerEvents: 'none',
        background:
          'linear-gradient(180deg, rgba(248, 243, 234, 0.42) 0%, rgba(248, 243, 234, 0) 21%, rgba(20, 15, 13, 0) 58%, rgba(20, 15, 13, 0.28) 100%)',
      }}
    />
    <AbsoluteFill
      style={{
        zIndex: 81,
        pointerEvents: 'none',
        boxShadow: 'inset 0 0 0 1px rgba(23, 18, 15, 0.08), inset 0 0 90px rgba(23, 18, 15, 0.14)',
      }}
    />
  </>
);

const SceneColorField: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const sceneProgress = clamp(localFrame / Math.max(1, scene.duration_frames - 1), 0, 1);
  const mode = scene.scene_id % 5;
  const isPoster = design.family === 'slam';
  const skew = scene.scene_id % 2 === 0 ? -8 : 7;
  const stripeShift = round(sceneProgress * 28);
  const baseWash = isPoster
    ? `linear-gradient(180deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(
        design.dark,
        0.055,
      )} 100%), radial-gradient(circle at 18% 22%, ${hexToRgba(design.accent, 0.11)}, transparent 34%), radial-gradient(circle at 86% 70%, ${hexToRgba(
        design.secondary,
        0.12,
      )}, transparent 32%)`
    : mode === 0
      ? `linear-gradient(180deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(design.secondary, 0.11)} 100%)`
      : mode === 1
        ? `linear-gradient(118deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(
            design.paper,
            1,
          )} 55%, ${hexToRgba(design.secondary, 0.16)} 55.3%, ${hexToRgba(
            design.secondary,
            0.16,
          )} 72%, ${hexToRgba(design.accent, 0.12)} 72.3%, ${hexToRgba(design.accent, 0.12)} 100%)`
        : mode === 2
          ? `linear-gradient(90deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(
              design.paper,
              1,
            )} 42%, ${hexToRgba(design.dark, 0.08)} 42.2%, ${hexToRgba(
              design.dark,
              0.08,
            )} 44%, ${hexToRgba(design.paper, 1)} 44.2%, ${hexToRgba(design.paper, 1)} 100%)`
          : mode === 3
            ? `linear-gradient(180deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(
                design.paper,
                1,
              )} 62%, ${hexToRgba(design.accent, 0.13)} 62.3%, ${hexToRgba(design.accent, 0.13)} 100%)`
            : `linear-gradient(130deg, ${hexToRgba(design.paper, 1)} 0%, ${hexToRgba(
                design.paper,
                1,
              )} 38%, ${hexToRgba(design.secondary, 0.13)} 38.3%, ${hexToRgba(
                design.secondary,
                0.13,
              )} 100%)`;
  return (
    <AbsoluteFill style={{zIndex: 0, pointerEvents: 'none', overflow: 'hidden', background: design.paper}}>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: baseWash,
        }}
      />
      {!isPoster && (mode === 1 || mode === 4) ? (
        <div
          style={{
            position: 'absolute',
            left: scene.scene_id % 3 === 0 ? -38 : 594,
            top: -80,
            width: mode === 1 ? 82 : 58,
            height: 1480,
            background: design.accent,
            opacity: mode === 1 ? 0.72 : 0.48,
            transform: `translateY(${stripeShift}px) rotate(${skew}deg)`,
          }}
        />
      ) : null}
      {!isPoster && mode === 0 ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: 44,
              top: 142,
              width: 612,
              height: 4,
              background: hexToRgba(design.dark, 0.16),
            }}
          />
          <div
            style={{
              position: 'absolute',
              right: 52,
              top: 188,
              width: 5,
              height: 760,
              background: hexToRgba(design.secondary, 0.44),
            }}
          />
        </>
      ) : null}
      {!isPoster && mode === 2 ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: -40,
              top: 690,
              width: 780,
              height: 118,
              background: hexToRgba(design.secondary, 0.18),
              transform: 'rotate(-3deg)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 56,
              top: 78,
              width: 590,
              height: 930,
              border: `2px solid ${hexToRgba(design.dark, 0.1)}`,
            }}
          />
        </>
      ) : null}
      {!isPoster && mode === 3 ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: -26,
              top: 132,
              width: 196,
              height: 820,
              background: hexToRgba(design.accent, 0.14),
              transform: 'rotate(4deg)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              right: -42,
              bottom: 86,
              width: 266,
              height: 382,
              border: `14px solid ${hexToRgba(design.secondary, 0.28)}`,
              transform: 'rotate(-5deg)',
            }}
          />
        </>
      ) : null}
      {!isPoster ? (
        <div
          style={{
            position: 'absolute',
            left: -16,
            right: -16,
            top: 438 + (scene.scene_id % 4) * 16,
            height: 84,
            background: hexToRgba(design.dark, 0.08),
            transform: `rotate(${scene.scene_id % 2 === 0 ? 2.3 : -2.1}deg)`,
            opacity: mode === 1 ? 1 : 0.62,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          opacity: 0.2,
          mixBlendMode: 'multiply',
          backgroundImage:
            'repeating-linear-gradient(0deg, rgba(20, 18, 16, 0.16) 0, rgba(20, 18, 16, 0.16) 1px, transparent 1px, transparent 7px), repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.32) 0, rgba(255, 255, 255, 0.32) 1px, transparent 1px, transparent 11px)',
        }}
      />
    </AbsoluteFill>
  );
};

const SceneMediaBackdrop: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  if (shouldSuppressSceneMedia(scene)) {
    return null;
  }
  const media = sceneBackdropMedia(scene);
  if (!media) {
    return null;
  }
  const hasPrimaryMedia = !isBLayoutStagedVfxPayload() && sceneMediaAssets(scene).length > 0;
  const sceneProgress = clamp(localFrame / Math.max(1, scene.duration_frames - 1), 0, 1);
  const scale = hasPrimaryMedia ? round(1.02 + sceneProgress * 0.055) : round(1.08 + sceneProgress * 0.035);
  const isVideo = media.kind === 'video';
  const commonStyle: React.CSSProperties = {
    position: 'absolute',
    inset: hasPrimaryMedia ? 0 : -42,
    width: hasPrimaryMedia ? '100%' : 'calc(100% + 84px)',
    height: hasPrimaryMedia ? '100%' : 'calc(100% + 84px)',
    objectFit: 'cover',
    opacity: hasPrimaryMedia ? (isVideo ? 0.82 : 0.78) : isVideo ? 0.3 : 0.24,
    filter: hasPrimaryMedia
      ? 'saturate(0.96) contrast(1.04)'
      : `blur(${isVideo ? 15 : 22}px) saturate(1.1) contrast(1.02)`,
    transform: `scale(${scale})`,
    transformOrigin: 'center center',
  };
  return (
    <div style={{position: 'absolute', inset: 0, zIndex: 0, overflow: 'hidden', background: design.paper}}>
      {media.kind === 'video' ? (
        <OffthreadVideo
          src={media.src}
          muted
          pauseWhenBuffering
          delayRenderRetries={2}
          delayRenderTimeoutInMilliseconds={120000}
          acceptableTimeShiftInSeconds={0.08}
          style={commonStyle}
        />
      ) : (
        <Img src={media.src} style={commonStyle} />
      )}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: hasPrimaryMedia
            ? `linear-gradient(180deg, ${hexToRgba(design.dark, 0.1)}, ${hexToRgba(
                design.paper,
                0.1,
              )} 44%, ${hexToRgba(design.dark, 0.2)})`
            : `linear-gradient(180deg, ${hexToRgba(design.paper, 0.46)}, ${hexToRgba(
                design.paper,
                0.28,
              )} 44%, ${hexToRgba(design.paper, 0.68)})`,
        }}
      />
    </div>
  );
};

const SceneImageComposition: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const assets = sceneMediaAssets(scene);
  if (design.family === 'final') {
    return <FinalChoiceCards scene={scene} assets={assets} localFrame={localFrame} design={design} />;
  }
  if (assets.length && !isBLayoutStagedVfxPayload()) {
    return null;
  }
  if (!assets.length) {
    if (isBLayoutStagedVfxPayload()) {
      return null;
    }
    const semantic = sceneSemanticVisual(scene);
    return semantic ? (
      <SemanticVisualComposition scene={scene} visual={semantic} localFrame={localFrame} design={design} />
    ) : null;
  }
  if (design.family === 'stack') {
    return <StackCards scene={scene} assets={assets} localFrame={localFrame} design={design} />;
  }
  if (design.family === 'feature') {
    return <FeatureCards scene={scene} assets={assets} localFrame={localFrame} design={design} />;
  }
  if (assets.length >= 2) {
    return <DuelCards scene={scene} assets={assets.slice(0, 2)} localFrame={localFrame} design={design} />;
  }
  return <HeroCard scene={scene} asset={assets[0]} localFrame={localFrame} design={design} />;
};

const SemanticVisualComposition: React.FC<{
  scene: HtmlScene;
  visual: SemanticVisual;
  localFrame: number;
  design: SceneDesign;
}> = ({scene, visual, localFrame, design}) => {
  const topic = sceneTopic(scene);
  const labels = semanticVisualLabels[topic];
  const revealStart = scene.scene_id === 1 ? 4 : 1;
  const sweepStart = scene.scene_id === 1 ? 16 : 10;
  const reveal = easeOutBack(progress(localFrame, revealStart, 16));
  const visible = clamp(reveal, 0, 1);
  const sweep = easeOutCubic(progress(localFrame, sweepStart, Math.max(22, Math.floor(scene.duration_frames * 0.38))));
  const variant = scene.scene_id % 4;
  const panelX = variant === 1 ? 52 : variant === 2 ? 96 : 40;
  const panelY = variant === 2 ? 286 : 316;
  const panelW = variant === 2 ? 572 : 618;
  const panelH = variant === 0 ? 612 : 660;
  const rotation = variant === 1 ? -2.2 : variant === 2 ? 1.4 : variant === 3 ? -1.2 : 2.0;
  const showStamp = false;
  return (
    <>
      <div
        data-semantic-visual-id={visual.id}
        style={{
          position: 'absolute',
          left: panelX,
          top: panelY,
          width: panelW,
          height: panelH,
          zIndex: 13,
          opacity: round(visible),
          transform: `translateY(${round((1 - visible) * 42)}px) rotate(${rotation}deg) scale(${round(
            0.94 + visible * 0.06,
          )})`,
          transformOrigin: 'center center',
          background: `linear-gradient(145deg, ${hexToRgba(design.paper, 0.96)}, ${hexToRgba(
            design.secondary,
            0.2,
          )}), repeating-linear-gradient(0deg, ${hexToRgba(design.dark, 0.055)} 0, ${hexToRgba(
            design.dark,
            0.055,
          )} 1px, transparent 1px, transparent 15px)`,
          border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
          boxShadow: `14px 20px 0 ${hexToRgba(design.dark, 0.12)}, 24px 38px 54px ${hexToRgba(
            design.dark,
            0.18,
          )}`,
          overflow: 'hidden',
        }}
      >
        <SemanticTopicObject scene={scene} visual={visual} topic={topic} localFrame={localFrame} design={design} sweep={sweep} />
        <div
          style={{
            position: 'absolute',
            left: 30,
            bottom: 28,
            display: 'flex',
            gap: 10,
            alignItems: 'center',
          }}
        >
          {(visual.motifs || []).slice(0, 4).map((motif, index) => (
            <div
              key={`${visual.id}-${motif}-${index}`}
              style={{
                width: index === 0 ? 88 : 58,
                height: 9,
                background: index % 2 === 0 ? design.accent : design.secondary,
                opacity: 0.86 - index * 0.1,
              }}
            />
          ))}
        </div>
      </div>
      {showStamp ? (
        <GraphicStamp
          x={variant === 2 ? 58 : 392}
          y={variant === 2 ? 784 : 274}
          w={variant === 2 ? 220 : 238}
          h={86}
          rot={variant === 2 ? -4.4 : 3.2}
          localFrame={localFrame}
          delay={7}
          design={design}
          kicker={labels.kicker}
          value={labels.value}
          detail={undefined}
          z={26}
          quiet
        />
      ) : null}
    </>
  );
};

const SemanticTopicObject: React.FC<{
  scene: HtmlScene;
  visual: SemanticVisual;
  topic: SceneTopic;
  localFrame: number;
  design: SceneDesign;
  sweep: number;
}> = ({scene, visual, topic, localFrame, design, sweep}) => {
  const pulse = round(0.94 + Math.sin((localFrame + scene.scene_id * 5) / 12) * 0.035);
  const variant = semanticVisualVariant(scene, visual);
  if (topic === 'food') {
    if (variant === 1) {
      return <FoodCheckoutScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 2) {
      return <FoodKitchenScaleScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 3) {
      return <FoodSplitPlateScene design={design} sweep={sweep} pulse={pulse} />;
    }
    return (
      <>
        <div
          style={{
            position: 'absolute',
            left: 64,
            top: 148,
            width: 300,
            height: 300,
            borderRadius: '50%',
            background: hexToRgba(design.paper, 0.92),
            border: `24px solid ${hexToRgba(design.accent, 0.5)}`,
            boxShadow: `0 0 0 2px ${hexToRgba(design.dark, 0.14)}, 22px 24px 38px ${hexToRgba(
              design.dark,
              0.16,
            )}`,
            transform: `scale(${pulse})`,
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 398,
            top: 118,
            width: 118,
            height: 194,
            borderRadius: '18px 18px 42px 42px',
            background: `linear-gradient(180deg, ${hexToRgba(design.secondary, 0.88)}, ${hexToRgba(
              design.dark,
              0.72,
            )})`,
            boxShadow: `14px 20px 26px ${hexToRgba(design.dark, 0.18)}`,
          }}
        />
        <ReceiptStrip x={356} y={356} w={154} h={218} design={design} sweep={sweep} />
      </>
    );
  }
  if (topic === 'thermal') {
    if (variant === 1) {
      return <ThermalBathScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 2) {
      return <ThermalThermometerScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 3) {
      return <ThermalCompressScene design={design} sweep={sweep} pulse={pulse} />;
    }
    return (
      <>
        <div style={{position: 'absolute', left: 58, top: 134, width: 224, height: 390, background: design.accent}} />
        <div style={{position: 'absolute', right: 58, top: 134, width: 224, height: 390, background: design.secondary}} />
        <div
          style={{
            position: 'absolute',
            left: 310,
            top: 118,
            width: 24,
            height: 430,
            background: hexToRgba(design.dark, 0.82),
            transform: `scaleY(${round(0.72 + sweep * 0.28)})`,
            transformOrigin: 'bottom center',
          }}
        />
        <PulseLine x={94} y={592} w={440} design={design} sweep={sweep} />
      </>
    );
  }
  if (topic === 'supplements') {
    if (variant === 1) {
      return <SupplementBlisterScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 2) {
      return <SupplementShelfScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 3) {
      return <SupplementTrackerScene design={design} sweep={sweep} pulse={pulse} />;
    }
    return (
      <>
        {[0, 1, 2, 3].map((index) => (
          <div
            key={`bottle-${index}`}
            style={{
              position: 'absolute',
              left: 82 + index * 116,
              top: 166 + (index % 2) * 44,
              width: 82,
              height: 272,
              borderRadius: '18px 18px 12px 12px',
              background: index % 2 === 0 ? design.dark : design.secondary,
              boxShadow: `12px 18px 26px ${hexToRgba(design.dark, 0.16)}`,
              transform: `translateY(${round(Math.sin((localFrame + index * 8) / 18) * 8)}px)`,
            }}
          >
            <div style={{position: 'absolute', left: 18, right: 18, top: -24, height: 34, background: design.accent}} />
            <div style={{position: 'absolute', left: 12, right: 12, top: 92, height: 72, background: design.paper}} />
          </div>
        ))}
        <DoseGrid x={102} y={508} design={design} sweep={sweep} />
      </>
    );
  }
  if (topic === 'recovery') {
    if (variant === 1) {
      return <RecoveryBedScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 2) {
      return <RecoveryStepsScene design={design} sweep={sweep} pulse={pulse} />;
    }
    if (variant === 3) {
      return <RecoveryBatteryScene design={design} sweep={sweep} pulse={pulse} />;
    }
    return (
      <>
        <div
          style={{
            position: 'absolute',
            left: 96,
            top: 170,
            width: 430,
            height: 234,
            borderRadius: '120px 120px 30px 30px',
            border: `22px solid ${hexToRgba(design.secondary, 0.72)}`,
            borderBottom: 0,
            transform: `scaleX(${round(0.92 + sweep * 0.08)})`,
            transformOrigin: 'left center',
          }}
        />
        {[0, 1, 2, 3, 4].map((index) => (
          <div
            key={`energy-${index}`}
            style={{
              position: 'absolute',
              left: 116 + index * 78,
              bottom: 116,
              width: 48,
              height: 92 + index * 34,
              background: index < Math.round(2 + sweep * 3) ? design.accent : hexToRgba(design.dark, 0.12),
            }}
          />
        ))}
      </>
    );
  }
  if (variant === 1) {
    return <GeneralBalanceScene design={design} sweep={sweep} pulse={pulse} />;
  }
  if (variant === 2) {
    return <GeneralMapScene design={design} sweep={sweep} pulse={pulse} />;
  }
  if (variant === 3) {
    return <GeneralNotebookScene design={design} sweep={sweep} pulse={pulse} />;
  }
  return (
    <>
      {[0, 1, 2].map((index) => (
        <div
          key={`evidence-${index}`}
          style={{
            position: 'absolute',
            left: 72 + index * 134,
            top: 148 + index * 72,
            width: 276,
            height: 154,
            background: index % 2 === 0 ? design.paper : hexToRgba(design.secondary, 0.3),
            border: `1px solid ${hexToRgba(design.dark, 0.2)}`,
            boxShadow: `10px 16px 28px ${hexToRgba(design.dark, 0.14)}`,
            transform: `rotate(${index % 2 === 0 ? -3 : 3}deg)`,
          }}
        >
          <div style={{position: 'absolute', left: 22, top: 28, width: 170, height: 12, background: design.accent}} />
          <div style={{position: 'absolute', left: 22, top: 62, width: 220, height: 8, background: hexToRgba(design.dark, 0.22)}} />
          <div style={{position: 'absolute', left: 22, top: 88, width: 132, height: 8, background: hexToRgba(design.dark, 0.18)}} />
        </div>
      ))}
      <PulseLine x={76} y={558} w={468} design={design} sweep={sweep} />
    </>
  );
};

const semanticVisualVariant = (scene: HtmlScene, visual: SemanticVisual): number => {
  const layoutSeed: Record<string, number> = {meter: 0, split: 1, stack: 2, tableau: 3};
  const seed = layoutSeed[String(visual.layout || '')] ?? 0;
  return (scene.scene_id + seed) % 4;
};

const FoodCheckoutScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 70,
        top: 180,
        width: 438,
        height: 96,
        borderRadius: 18,
        background: `linear-gradient(90deg, ${hexToRgba(design.dark, 0.12)}, ${hexToRgba(design.dark, 0.04)})`,
        border: `1px solid ${hexToRgba(design.dark, 0.16)}`,
      }}
    />
    {[0, 1, 2].map((index) => (
      <div
        key={`checkout-item-${index}`}
        style={{
          position: 'absolute',
          left: 98 + index * 138 + round(sweep * 18),
          top: 132 + (index % 2) * 18,
          width: 96,
          height: 148,
          borderRadius: index === 1 ? '48px 48px 22px 22px' : 22,
          background: index === 1 ? design.secondary : index === 2 ? design.accent : hexToRgba(design.paper, 0.96),
          border: `2px solid ${hexToRgba(design.dark, 0.16)}`,
          boxShadow: `10px 18px 28px ${hexToRgba(design.dark, 0.13)}`,
          transform: `scale(${pulse})`,
        }}
      />
    ))}
    <ReceiptStrip x={342} y={342} w={160} h={226} design={design} sweep={sweep} />
    <PulseLine x={86} y={548} w={404} design={design} sweep={sweep} />
  </>
);

const FoodKitchenScaleScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 150,
        top: 124,
        width: 324,
        height: 324,
        borderRadius: '50%',
        background: hexToRgba(design.paper, 0.94),
        border: `18px solid ${hexToRgba(design.secondary, 0.58)}`,
        boxShadow: `18px 26px 44px ${hexToRgba(design.dark, 0.16)}`,
        transform: `scale(${pulse})`,
      }}
    />
    {[0, 1, 2, 3, 4].map((index) => {
      const angle = -54 + index * 27;
      return (
        <div
          key={`scale-tick-${index}`}
          style={{
            position: 'absolute',
            left: 304,
            top: 178,
            width: 7,
            height: 54,
            background: index === Math.floor(sweep * 5) ? design.accent : hexToRgba(design.dark, 0.25),
            transform: `rotate(${angle}deg) translateY(-116px)`,
            transformOrigin: 'center 150px',
          }}
        />
      );
    })}
    <div
      style={{
        position: 'absolute',
        left: 304,
        top: 274,
        width: 12,
        height: 126,
        background: design.dark,
        transform: `rotate(${round(-35 + sweep * 58)}deg)`,
        transformOrigin: 'center 8px',
      }}
    />
    <VisualNoteLines x={96} y={498} w={420} design={design} sweep={sweep} rows={4} />
  </>
);

const FoodSplitPlateScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 88,
        top: 126,
        width: 394,
        height: 394,
        borderRadius: '50%',
        background: `conic-gradient(${design.accent} 0 36%, ${design.secondary} 36% 66%, ${hexToRgba(
          design.dark,
          0.16,
        )} 66% 100%)`,
        boxShadow: `20px 26px 42px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse}) rotate(${round(sweep * 8)}deg)`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 144,
        top: 182,
        width: 282,
        height: 282,
        borderRadius: '50%',
        background: design.paper,
      }}
    />
    <div style={{position: 'absolute', right: 82, top: 142, width: 20, height: 392, background: design.dark}} />
    <ReceiptStrip x={82} y={522} w={192} h={82} design={design} sweep={sweep} />
  </>
);

const ThermalBathScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 74,
        top: 260,
        width: 474,
        height: 260,
        borderRadius: '40px 40px 120px 120px',
        background: `linear-gradient(180deg, ${hexToRgba(design.paper, 0.9)}, ${hexToRgba(design.secondary, 0.45)})`,
        border: `18px solid ${hexToRgba(design.dark, 0.2)}`,
        boxShadow: `20px 30px 44px ${hexToRgba(design.dark, 0.15)}`,
        transform: `scale(${pulse})`,
      }}
    />
    {[0, 1, 2].map((index) => (
      <div
        key={`steam-${index}`}
        style={{
          position: 'absolute',
          left: 170 + index * 84,
          top: 128 + index * 16,
          width: 58,
          height: 160,
          borderRadius: 999,
          border: `10px solid ${hexToRgba(index % 2 === 0 ? design.accent : design.secondary, 0.55)}`,
          borderBottomColor: 'transparent',
          opacity: 0.78,
          transform: `translateY(${round(-sweep * (16 + index * 8))}px)`,
        }}
      />
    ))}
    <PulseLine x={96} y={572} w={420} design={design} sweep={sweep} />
  </>
);

const ThermalThermometerScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({
  design,
  sweep,
  pulse,
}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 238,
        top: 118,
        width: 116,
        height: 410,
        borderRadius: 999,
        background: hexToRgba(design.paper, 0.95),
        border: `14px solid ${hexToRgba(design.dark, 0.18)}`,
        boxShadow: `18px 28px 46px ${hexToRgba(design.dark, 0.15)}`,
        transform: `scale(${pulse})`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 273,
        bottom: 114,
        width: 46,
        height: 110 + sweep * 224,
        borderRadius: 999,
        background: `linear-gradient(180deg, ${design.accent}, ${design.secondary})`,
        transformOrigin: 'bottom center',
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 218,
        top: 448,
        width: 158,
        height: 158,
        borderRadius: '50%',
        background: design.accent,
        boxShadow: `0 0 0 18px ${hexToRgba(design.accent, 0.18)}`,
      }}
    />
    <VisualNoteLines x={410} y={170} w={112} design={design} sweep={sweep} rows={6} />
  </>
);

const ThermalCompressScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    {[0, 1].map((index) => (
      <div
        key={`compress-${index}`}
        style={{
          position: 'absolute',
          left: 92 + index * 246,
          top: 154 + index * 46,
          width: 198,
          height: 292,
          borderRadius: 34,
          background: index === 0 ? design.accent : design.secondary,
          boxShadow: `16px 24px 40px ${hexToRgba(design.dark, 0.14)}`,
          transform: `scale(${pulse}) rotate(${index === 0 ? -3 : 4}deg)`,
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 18,
            border: `2px solid ${hexToRgba(design.paper, 0.42)}`,
            borderRadius: 22,
          }}
        />
      </div>
    ))}
    <div
      style={{
        position: 'absolute',
        left: 308,
        top: 120,
        width: 22,
        height: 452,
        background: design.dark,
        transform: `scaleY(${round(0.72 + sweep * 0.28)})`,
        transformOrigin: 'bottom center',
      }}
    />
  </>
);

const SupplementBlisterScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({
  design,
  sweep,
  pulse,
}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 102,
        top: 142,
        width: 390,
        height: 398,
        borderRadius: 30,
        background: `linear-gradient(145deg, ${hexToRgba(design.paper, 0.98)}, ${hexToRgba(design.secondary, 0.2)})`,
        border: `1px solid ${hexToRgba(design.dark, 0.16)}`,
        boxShadow: `20px 28px 44px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse})`,
      }}
    />
    {Array.from({length: 12}).map((_, index) => {
      const row = Math.floor(index / 4);
      const col = index % 4;
      return (
        <div
          key={`blister-${index}`}
          style={{
            position: 'absolute',
            left: 146 + col * 82,
            top: 188 + row * 96,
            width: 50,
            height: 50,
            borderRadius: '50%',
            background: index <= Math.floor(sweep * 11) ? design.accent : hexToRgba(design.dark, 0.12),
            boxShadow: `inset 0 6px 12px ${hexToRgba(design.paper, 0.68)}, 5px 8px 16px ${hexToRgba(
              design.dark,
              0.12,
            )}`,
          }}
        />
      );
    })}
    <VisualNoteLines x={82} y={560} w={430} design={design} sweep={sweep} rows={3} />
  </>
);

const SupplementShelfScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    {[0, 1, 2].map((shelf) => (
      <div
        key={`shelf-line-${shelf}`}
        style={{
          position: 'absolute',
          left: 70,
          top: 216 + shelf * 122,
          width: 470,
          height: 14,
          background: hexToRgba(design.dark, 0.2),
        }}
      />
    ))}
    {Array.from({length: 9}).map((_, index) => {
      const shelf = Math.floor(index / 3);
      const col = index % 3;
      return (
        <div
          key={`shelf-bottle-${index}`}
          style={{
            position: 'absolute',
            left: 102 + col * 138 + (shelf % 2) * 24,
            top: 116 + shelf * 122 + (col % 2) * 10,
            width: 68,
            height: 100,
            borderRadius: '16px 16px 8px 8px',
            background: index % 2 === 0 ? design.dark : index % 3 === 0 ? design.accent : design.secondary,
            boxShadow: `8px 14px 20px ${hexToRgba(design.dark, 0.14)}`,
            transform: `translateY(${round(Math.sin(index + sweep * 2) * 5)}px) scale(${pulse})`,
          }}
        >
          <div style={{position: 'absolute', left: 12, right: 12, top: 34, height: 30, background: design.paper}} />
        </div>
      );
    })}
  </>
);

const SupplementTrackerScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 90,
        top: 132,
        width: 430,
        height: 430,
        background: hexToRgba(design.paper, 0.95),
        border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
        boxShadow: `20px 28px 42px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse}) rotate(-1deg)`,
      }}
    />
    {Array.from({length: 16}).map((_, index) => {
      const row = Math.floor(index / 4);
      const col = index % 4;
      return (
        <div
          key={`tracker-${index}`}
          style={{
            position: 'absolute',
            left: 132 + col * 82,
            top: 178 + row * 74,
            width: 44,
            height: 44,
            borderRadius: 8,
            background: index < Math.floor(4 + sweep * 12) ? design.secondary : hexToRgba(design.dark, 0.08),
            border: `2px solid ${hexToRgba(design.dark, 0.16)}`,
          }}
        >
          {index < Math.floor(4 + sweep * 12) ? (
            <div
              style={{
                position: 'absolute',
                left: 10,
                top: 18,
                width: 22,
                height: 10,
                borderLeft: `5px solid ${design.paper}`,
                borderBottom: `5px solid ${design.paper}`,
                transform: 'rotate(-45deg)',
              }}
            />
          ) : null}
        </div>
      );
    })}
    <DoseGrid x={168} y={538} design={design} sweep={sweep} />
  </>
);

const RecoveryBedScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 86,
        top: 250,
        width: 460,
        height: 232,
        borderRadius: '42px 42px 24px 24px',
        background: hexToRgba(design.paper, 0.96),
        border: `16px solid ${hexToRgba(design.secondary, 0.55)}`,
        boxShadow: `20px 30px 42px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse})`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        left: 126,
        top: 202,
        width: 136,
        height: 82,
        borderRadius: 24,
        background: design.paper,
        border: `2px solid ${hexToRgba(design.dark, 0.16)}`,
      }}
    />
    <div
      style={{
        position: 'absolute',
        right: 116,
        top: 124,
        width: 112,
        height: 112,
        borderRadius: '50%',
        background: design.accent,
        boxShadow: `-26px 0 0 ${design.paper}`,
      }}
    />
    <PulseLine x={100} y={544} w={420} design={design} sweep={sweep} />
  </>
);

const RecoveryStepsScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    {Array.from({length: 8}).map((_, index) => (
      <div
        key={`step-dot-${index}`}
        style={{
          position: 'absolute',
          left: 96 + index * 54,
          top: 428 - Math.sin(index / 1.4) * 132,
          width: 38,
          height: 38,
          borderRadius: '50%',
          background: index <= Math.floor(sweep * 7) ? design.accent : hexToRgba(design.dark, 0.14),
          boxShadow: `6px 10px 16px ${hexToRgba(design.dark, 0.12)}`,
          transform: `scale(${pulse})`,
        }}
      />
    ))}
    <div
      style={{
        position: 'absolute',
        left: 356,
        top: 158,
        width: 136,
        height: 246,
        borderRadius: 28,
        background: design.dark,
        boxShadow: `14px 20px 30px ${hexToRgba(design.dark, 0.16)}`,
      }}
    >
      <div style={{position: 'absolute', left: 18, right: 18, top: 28, height: 148, background: design.paper}} />
      <div style={{position: 'absolute', left: 48, bottom: 24, width: 42, height: 10, background: design.secondary}} />
    </div>
    <VisualNoteLines x={92} y={522} w={410} design={design} sweep={sweep} rows={3} />
  </>
);

const RecoveryBatteryScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 92,
        top: 156,
        width: 388,
        height: 202,
        borderRadius: 28,
        border: `16px solid ${hexToRgba(design.dark, 0.42)}`,
        background: hexToRgba(design.paper, 0.96),
        boxShadow: `20px 28px 42px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse})`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 18,
          top: 18,
          bottom: 18,
          width: `${round(28 + sweep * 62)}%`,
          borderRadius: 12,
          background: `linear-gradient(90deg, ${design.accent}, ${design.secondary})`,
        }}
      />
    </div>
    <div style={{position: 'absolute', left: 486, top: 216, width: 42, height: 82, background: hexToRgba(design.dark, 0.42)}} />
    <MiniBarSet x={108} y={440} design={design} sweep={sweep} count={6} />
  </>
);

const GeneralBalanceScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div style={{position: 'absolute', left: 304, top: 130, width: 18, height: 404, background: design.dark}} />
    <div
      style={{
        position: 'absolute',
        left: 158,
        top: 204,
        width: 310,
        height: 14,
        background: design.dark,
        transform: `rotate(${round(-8 + sweep * 16)}deg) scale(${pulse})`,
      }}
    />
    {[0, 1].map((index) => (
      <div
        key={`scale-pan-${index}`}
        style={{
          position: 'absolute',
          left: index === 0 ? 92 : 394,
          top: 314 + (index === 0 ? 18 : -8),
          width: 150,
          height: 92,
          borderRadius: '0 0 76px 76px',
          border: `12px solid ${index === 0 ? design.accent : design.secondary}`,
          borderTop: 0,
          background: hexToRgba(design.paper, 0.7),
        }}
      />
    ))}
    <VisualNoteLines x={110} y={512} w={408} design={design} sweep={sweep} rows={3} />
  </>
);

const GeneralMapScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    {[0, 1, 2, 3].map((index) => (
      <div
        key={`map-node-${index}`}
        style={{
          position: 'absolute',
          left: [96, 372, 158, 430][index],
          top: [158, 194, 392, 462][index],
          width: index === 0 ? 110 : 86,
          height: index === 0 ? 110 : 86,
          borderRadius: '50%',
          background: index % 2 === 0 ? design.accent : design.secondary,
          boxShadow: `12px 18px 26px ${hexToRgba(design.dark, 0.14)}`,
          transform: `scale(${pulse})`,
        }}
      />
    ))}
    <svg
      viewBox="0 0 620 620"
      style={{position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', overflow: 'visible'}}
    >
      <path
        d="M150 210 C260 120 350 240 420 236 C512 232 510 410 462 504 C358 464 280 424 202 428"
        fill="none"
        stroke={design.dark}
        strokeWidth="16"
        strokeLinecap="round"
        strokeDasharray={`${round(60 + sweep * 420)} 520`}
        opacity="0.5"
      />
    </svg>
    <VisualNoteLines x={90} y={536} w={420} design={design} sweep={sweep} rows={2} />
  </>
);

const GeneralNotebookScene: React.FC<{design: SceneDesign; sweep: number; pulse: number}> = ({design, sweep, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: 98,
        top: 126,
        width: 418,
        height: 430,
        background: hexToRgba(design.paper, 0.96),
        border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
        boxShadow: `18px 28px 42px ${hexToRgba(design.dark, 0.14)}`,
        transform: `scale(${pulse}) rotate(1.2deg)`,
      }}
    />
    {Array.from({length: 5}).map((_, index) => (
      <div
        key={`notebook-row-${index}`}
        style={{
          position: 'absolute',
          left: 142,
          top: 188 + index * 62,
          width: 310 - index * 16,
          height: 14,
          background: index <= Math.floor(sweep * 4) ? design.accent : hexToRgba(design.dark, 0.18),
        }}
      />
    ))}
    {[0, 1, 2].map((index) => (
      <div
        key={`notebook-tab-${index}`}
        style={{
          position: 'absolute',
          right: 86,
          top: 170 + index * 86,
          width: 58,
          height: 42,
          background: index % 2 === 0 ? design.secondary : design.accent,
        }}
      />
    ))}
  </>
);

const VisualNoteLines: React.FC<{
  x: number;
  y: number;
  w: number;
  design: SceneDesign;
  sweep: number;
  rows: number;
}> = ({x, y, w, design, sweep, rows}) => (
  <>
    {Array.from({length: rows}).map((_, index) => (
      <div
        key={`note-line-${x}-${y}-${index}`}
        style={{
          position: 'absolute',
          left: x,
          top: y + index * 24,
          width: round(w * (0.52 + ((index + 2) % 4) * 0.11)),
          height: index === 0 ? 10 : 7,
          background: index <= Math.floor(sweep * rows) ? design.accent : hexToRgba(design.dark, 0.2),
        }}
      />
    ))}
  </>
);

const MiniBarSet: React.FC<{x: number; y: number; design: SceneDesign; sweep: number; count: number}> = ({
  x,
  y,
  design,
  sweep,
  count,
}) => (
  <>
    {Array.from({length: count}).map((_, index) => (
      <div
        key={`mini-bar-${index}`}
        style={{
          position: 'absolute',
          left: x + index * 66,
          top: y + 120 - index * 18,
          width: 42,
          height: 70 + index * 18,
          background: index <= Math.floor(sweep * (count - 1)) ? design.secondary : hexToRgba(design.dark, 0.12),
        }}
      />
    ))}
  </>
);

const ReceiptStrip: React.FC<{x: number; y: number; w: number; h: number; design: SceneDesign; sweep: number}> = ({
  x,
  y,
  w,
  h,
  design,
  sweep,
}) => (
  <div
    style={{
      position: 'absolute',
      left: x,
      top: y,
      width: w,
      height: h,
      background: design.paper,
      border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
      boxShadow: `10px 18px 28px ${hexToRgba(design.dark, 0.14)}`,
      overflow: 'hidden',
    }}
  >
    {[0, 1, 2, 3, 4].map((index) => (
      <div
        key={`receipt-${index}`}
        style={{
          position: 'absolute',
          left: 18,
          top: 24 + index * 34,
          width: index === 4 ? 86 : 112,
          height: 7,
          background: index === Math.floor(sweep * 5) ? design.accent : hexToRgba(design.dark, 0.2),
        }}
      />
    ))}
  </div>
);

const PulseLine: React.FC<{x: number; y: number; w: number; design: SceneDesign; sweep: number}> = ({
  x,
  y,
  w,
  design,
  sweep,
}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w, height: 58, overflow: 'hidden'}}>
    <div
      style={{
        position: 'absolute',
        left: round(-80 + sweep * 120),
        top: 24,
        width: w + 120,
        height: 10,
        background: `linear-gradient(90deg, ${design.accent}, ${design.secondary})`,
        clipPath: 'polygon(0 50%, 12% 50%, 17% 5%, 24% 95%, 32% 50%, 48% 50%, 54% 20%, 60% 80%, 68% 50%, 100% 50%)',
      }}
    />
  </div>
);

const DoseGrid: React.FC<{x: number; y: number; design: SceneDesign; sweep: number}> = ({x, y, design, sweep}) => (
  <div style={{position: 'absolute', left: x, top: y, display: 'grid', gridTemplateColumns: 'repeat(6, 42px)', gap: 16}}>
    {Array.from({length: 12}).map((_, index) => (
      <div
        key={`dose-${index}`}
        style={{
          width: 42,
          height: 24,
          borderRadius: 999,
          background: index <= Math.floor(sweep * 11) ? design.accent : hexToRgba(design.dark, 0.16),
          transform: `rotate(${index % 2 === 0 ? -14 : 14}deg)`,
        }}
      />
    ))}
  </div>
);

const semanticVisualLabels: Record<SceneTopic, ProofCue> = {
  food: {kicker: 'визуальная сцена', value: 'ПОРЦИЯ', detail: 'чек + стол + выбор'},
  thermal: {kicker: 'визуальная сцена', value: 'ТЕПЛО', detail: 'контраст без клише'},
  supplements: {kicker: 'визуальная сцена', value: 'ДОЗА', detail: 'банки под контролем'},
  recovery: {kicker: 'визуальная сцена', value: 'БАЗА', detail: 'сон, шаги, энергия'},
  general: {kicker: 'визуальная сцена', value: 'ФАКТ', detail: 'карточки доказательств'},
};

const assetRevealDelay = (scene: HtmlScene, asset: MediaAsset | undefined, fallback: number): number => {
  if (!asset) {
    return fallback;
  }
  const frame = (isBLayoutStagedVfxPayload() ? vfxTimingForAsset(scene, asset.id)?.appear_frame : undefined) ??
    scene.asset_timings?.[asset.id]?.appear_frame;
  return Number.isFinite(frame) ? Math.max(0, Number(frame)) : fallback;
};

const DuelCards: React.FC<{scene: HtmlScene; assets: MediaAsset[]; localFrame: number; design: SceneDesign}> = ({
  scene,
  assets,
  localFrame,
  design,
}) => {
  const layouts = duelLayouts[scene.scene_id % duelLayouts.length];
  return (
    <>
      {assets.map((asset, index) => {
        const layout = layouts[index] || layouts[0];
        return (
          <MediaCard
            key={asset.id}
            asset={asset}
            caption={captionFor(scene, index)}
            localFrame={localFrame}
            design={design}
            delay={assetRevealDelay(scene, asset, 1 + index * 4)}
            {...layout}
          />
        );
      })}
    </>
  );
};

const HeroCard: React.FC<{scene: HtmlScene; asset: MediaAsset; localFrame: number; design: SceneDesign}> = ({
  scene,
  asset,
  localFrame,
  design,
}) => {
  const layout = heroLayouts[scene.scene_id] || {
    x: 42,
    y: 432,
    w: 626,
    h: 706,
    rot: scene.scene_id % 2 === 0 ? 2.6 : -2.8,
    z: 14,
  };
  return (
    <MediaCard
      asset={asset}
      caption={captionFor(scene, 0)}
      localFrame={localFrame}
      design={design}
      delay={assetRevealDelay(scene, asset, 1)}
      {...layout}
    />
  );
};

const FeatureCards: React.FC<{scene: HtmlScene; assets: MediaAsset[]; localFrame: number; design: SceneDesign}> = ({
  scene,
  assets,
  localFrame,
  design,
}) => {
  const primary = assets[0];
  const secondary = assets[1];
  const flip = scene.scene_id % 2 === 0;
  return (
    <>
      <MediaCard
        asset={primary}
        caption={captionFor(scene, 0)}
        localFrame={localFrame}
        design={design}
        delay={assetRevealDelay(scene, primary, 1)}
        x={flip ? 34 : -24}
        y={flip ? 390 : 420}
        w={flip ? 652 : 628}
        h={flip ? 694 : 736}
        rot={flip ? 1.6 : -2.4}
        z={12}
      />
      {secondary ? (
        <MediaCard
          asset={secondary}
          caption={captionFor(scene, 1)}
          localFrame={localFrame}
          design={design}
          delay={assetRevealDelay(scene, secondary, 6)}
          x={flip ? 392 : 418}
          y={flip ? 720 : 604}
          w={flip ? 294 : 276}
          h={flip ? 354 : 414}
          rot={flip ? -5.2 : 5.6}
          z={18}
        />
      ) : null}
      {!isCleanOrnamentLayout() ? <FeatureRule scene={scene} localFrame={localFrame} design={design} /> : null}
    </>
  );
};

const FeatureRule: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const reveal = easeOutCubic(progress(localFrame, 8, 14));
  const visible = clamp(reveal, 0, 1);
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: scene.scene_id % 2 === 0 ? 42 : 510,
          top: 288,
          width: 126,
          height: 690,
          zIndex: 10,
          opacity: round(visible * 0.72),
          transform: `translateY(${round((1 - visible) * 30)}px) rotate(${scene.scene_id % 2 === 0 ? -3 : 4}deg)`,
          background: hexToRgba(design.accent, 0.34),
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: scene.scene_id % 2 === 0 ? 488 : 46,
          top: 1002,
          width: 184,
          height: 10,
          zIndex: 20,
          opacity: round(visible),
          background: design.secondary,
        }}
      />
    </>
  );
};

const StackCards: React.FC<{scene: HtmlScene; assets: MediaAsset[]; localFrame: number; design: SceneDesign}> = ({
  scene,
  assets,
  localFrame,
  design,
}) => (
  <>
    {assets.slice(0, 3).map((asset, index) => {
      const layout = stackLayouts[index] || stackLayouts[0];
      return (
        <MediaCard
          key={asset.id}
          asset={asset}
          caption={captionFor(scene, index)}
          localFrame={localFrame}
          design={design}
          delay={assetRevealDelay(scene, asset, 1 + index * 4)}
          {...layout}
        />
      );
    })}
  </>
);

const FinalChoiceCards: React.FC<{scene: HtmlScene; assets: MediaAsset[]; localFrame: number; design: SceneDesign}> = ({
  scene,
  assets,
  localFrame,
  design,
}) => {
  const choiceAssets = finalChoiceAssets(scene, assets);
  const labels = finalChoiceLabels(scene);
  return (
  <>
    <FinalCtaPoster localFrame={localFrame} design={design} />
    <FinalSplitChoice
      asset={choiceAssets[0]}
      label={labels[0]}
      index={0}
      localFrame={localFrame}
      delay={assetRevealDelay(scene, choiceAssets[0], 3)}
      design={design}
    />
    <FinalSplitChoice
      asset={choiceAssets[1]}
      label={labels[1]}
      index={1}
      localFrame={localFrame}
      delay={assetRevealDelay(scene, choiceAssets[1], 8)}
      design={design}
    />
  </>
  );
};

const finalChoiceAssets = (scene: HtmlScene, assets: MediaAsset[]): MediaAsset[] => {
  if (assets.length >= 2) {
    return assets;
  }
  const payloadAssets = Array.isArray(scene.final_choice_media) ? scene.final_choice_media : [];
  const validPayloadAssets = payloadAssets.filter(
    (asset) => asset && asset.id && asset.src && (asset.kind === 'image' || asset.kind === 'video'),
  );
  return validPayloadAssets.length
    ? validPayloadAssets.map((asset) => ({
        ...asset,
        src: videoSrc(asset.src),
        fit: asset.fit || 'cover',
        focusX: asset.focusX || '50%',
        focusY: asset.focusY || '50%',
      }))
    : assets;
};

const FinalSplitChoice: React.FC<{
  asset?: MediaAsset;
  label: string;
  index: number;
  localFrame: number;
  delay: number;
  design: SceneDesign;
}> = ({asset, label, index, localFrame, delay, design}) => {
  const reveal = easeOutBack(progress(localFrame, delay, 14));
  const visible = clamp(reveal, 0, 1);
  const x = index === 0 ? 22 : 368;
  const rot = index === 0 ? -1.8 : 1.8;
  const mediaStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    objectPosition: asset ? `${asset.focusX} ${asset.focusY}` : '50% 50%',
    filter: 'saturate(0.82) contrast(1.16) sepia(0.08)',
    transform: 'scale(1.05)',
  };
  return (
    <div
        style={{
          position: 'absolute',
          left: x,
          top: 392,
          width: 334,
          height: 612,
        zIndex: 19 + index,
        overflow: 'hidden',
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 42)}px) rotate(${rot}deg) scale(${round(
          0.92 + visible * 0.08,
        )})`,
        transformOrigin: 'center center',
        background: index === 0 ? design.dark : paperTexture(design.paper, design.dark),
        border: `2px solid ${hexToRgba(index === 0 ? design.paper : design.dark, 0.24)}`,
        boxShadow: `11px 14px 0 ${hexToRgba(design.dark, 0.18)}, 18px 30px 34px ${hexToRgba(
          design.dark,
          0.18,
        )}`,
      }}
    >
      {asset?.kind === 'video' ? (
        <OffthreadVideo
          src={asset.src}
          muted
          pauseWhenBuffering
          delayRenderRetries={2}
          delayRenderTimeoutInMilliseconds={120000}
          acceptableTimeShiftInSeconds={0.08}
          playbackRate={1}
          style={mediaStyle}
        />
      ) : asset ? (
        <Img src={asset.src} style={mediaStyle} />
      ) : (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              index === 0
                ? `linear-gradient(145deg, ${hexToRgba(design.dark, 1)}, ${hexToRgba(design.accent, 0.55)})`
                : `linear-gradient(145deg, ${hexToRgba(design.paper, 1)}, ${hexToRgba(design.secondary, 0.34)})`,
          }}
        />
      )}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            index === 0
              ? `linear-gradient(180deg, ${hexToRgba(design.dark, 0.22)}, ${hexToRgba(design.dark, 0.76)})`
              : `linear-gradient(180deg, ${hexToRgba(design.paper, 0.08)}, ${hexToRgba(design.dark, 0.64)})`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 24,
          top: 26,
          fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
          fontSize: 14,
          lineHeight: 1,
          fontWeight: 900,
          textTransform: 'uppercase',
          color: index === 0 ? design.secondary : design.paper,
        }}
      >
        вариант {index + 1 < 10 ? `0${index + 1}` : index + 1}
      </div>
      <div
      style={{
        position: 'absolute',
        left: 22,
        right: 20,
          bottom: 28,
          minHeight: 118,
          padding: '20px 18px 18px',
          boxSizing: 'border-box',
          display: 'flex',
          alignItems: 'center',
          background: index === 0 ? hexToRgba(design.dark, 0.93) : hexToRgba(design.dark, 0.86),
          border: `1px solid ${hexToRgba(design.paper, 0.28)}`,
          color: design.paper,
          fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
          fontSize: label.length > 8 ? 50 : label.length > 6 ? 58 : 70,
          lineHeight: 0.84,
          fontWeight: 900,
          textTransform: 'uppercase',
          overflowWrap: 'normal',
          wordBreak: 'normal',
          hyphens: 'none',
          textShadow: `0 8px 22px ${hexToRgba(design.dark, 0.5)}`,
        }}
      >
        {label}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 42,
          bottom: 26,
          width: 138,
          height: 9,
          background: index === 0 ? design.accent : design.secondary,
          zIndex: 2,
        }}
      />
    </div>
  );
};

const FinalCtaPoster: React.FC<{localFrame: number; design: SceneDesign}> = ({localFrame, design}) => {
  const reveal = easeOutBack(progress(localFrame, 0, 14));
  const visible = clamp(reveal, 0, 1);
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: 42,
          top: 82,
          width: 634,
          height: 258,
          zIndex: 20,
          opacity: round(visible),
          transform: `translateY(${round((1 - visible) * 30)}px) rotate(-1.4deg)`,
          background: hexToRgba(design.dark, 0.93),
          border: `1px solid ${hexToRgba(design.paper, 0.2)}`,
          boxShadow: `16px 28px 46px ${hexToRgba(design.dark, 0.22)}`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 78,
          top: 116,
          width: 548,
          zIndex: 21,
          opacity: round(visible),
          transform: `translateY(${round((1 - visible) * 22)}px) rotate(-1.4deg)`,
          color: design.paper,
          fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
          textTransform: 'uppercase',
        }}
      >
        <div
          style={{
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 15,
            lineHeight: 1,
            fontWeight: 900,
            color: design.secondary,
          }}
        >
          финальный вопрос
        </div>
        <div style={{marginTop: 15, fontSize: 88, lineHeight: 0.82, fontWeight: 900}}>А ТЫ</div>
        <div style={{fontSize: 80, lineHeight: 0.82, fontWeight: 900}}>ЧТО</div>
        <div style={{fontSize: 86, lineHeight: 0.82, fontWeight: 900, color: design.accent}}>ВЫБЕРЕШЬ?</div>
      </div>
      <div
        style={{
          position: 'absolute',
          left: 80,
          top: 64,
          width: 220,
          height: 34,
          zIndex: 22,
          opacity: round(visible * 0.95),
          transform: 'rotate(-4deg)',
          background: tapeTexture(design.secondary, design.dark),
        }}
      />
    </>
  );
};

type MediaCaptionMode = 'featureCard' | 'lowerThird' | 'sideNote';

type CaptionToken = {
  text: string;
  word?: WordTiming;
  fallbackFrame: number;
};

type CaptionLine = CaptionToken[];

const mediaCaptionMode = (
  scene: HtmlScene,
  text: string,
  lines: CaptionLine[],
  assets: MediaAsset[],
  design: SceneDesign,
): MediaCaptionMode => {
  if (isBLayoutStagedVfxPayload()) {
    return 'featureCard';
  }
  const longest = captionLongestLine(lines);
  const longestWord = captionLongestWord(lines);
  const tooDenseForCompact = text.length > 108 || lines.length > 6 || longest > 24 || longestWord > 14;
  if (sceneSemanticVisual(scene)) {
    return text.length > 138 || lines.length > 7 || longestWord > 16 ? 'sideNote' : 'lowerThird';
  }
  if (tooDenseForCompact) {
    return 'featureCard';
  }
  if (assets.length >= 2 || design.family === 'duel' || design.family === 'stack') {
    return 'sideNote';
  }
  if (design.family === 'video' || design.family === 'feature') {
    return 'lowerThird';
  }
  if (design.family === 'hero' && (text.length > 78 || lines.length > 4) && scene.scene_id % 3 === 0) {
    return 'featureCard';
  }
  return scene.scene_id % 2 === 0 ? 'sideNote' : 'lowerThird';
};

const compactCaptionFontSize = (lines: CaptionLine[], mode: Exclude<MediaCaptionMode, 'featureCard'>): number => {
  const longest = captionLongestLine(lines);
  const longestWord = captionLongestWord(lines);
  const base = mode === 'sideNote' ? 32 : 34;
  if (lines.length > 5 || longestWord > 12 || longest > 22) {
    return mode === 'sideNote' ? 24 : 25;
  }
  if (lines.length > 4 || longest > 19) {
    return mode === 'sideNote' ? 27 : 28;
  }
  return base;
};

const TimedCaptionLine: React.FC<{
  line: CaptionLine;
  lineIndex: number;
  localFrame: number;
  fontSize: number;
  lineHeight: number;
  translateX: number;
  maxWidth?: number;
}> = ({line, lineIndex, localFrame, fontSize, lineHeight, translateX, maxWidth}) => {
  const lineStartFrame = captionLineStartFrame(line, lineIndex * 2);
  const lineHasStarted = localFrame >= lineStartFrame;
  const lineReveal = lineHasStarted ? easeOutCubic(progress(localFrame, lineStartFrame, 7)) : 0;
  const lineVisible = lineHasStarted ? clamp(lineReveal, 0, 1) : 0.64;
  return (
    <div
      style={{
        display: 'block',
        opacity: round(lineVisible),
        transform: `translateX(${round((lineHasStarted ? 1 - lineVisible : 0) * translateX)}px)`,
        fontSize,
        lineHeight,
        fontWeight: 900,
        whiteSpace: 'normal',
        overflowWrap: 'normal',
        wordBreak: 'normal',
        hyphens: 'none',
        maxWidth,
      }}
    >
      {line.map((token, tokenIndex) => {
        const startFrame = captionTokenAppearFrame(token);
        const tokenHasStarted = localFrame >= startFrame;
        const visible = tokenHasStarted ? clamp(easeOutCubic(progress(localFrame, startFrame, 6)), 0, 1) : 0;
        const tokenOpacity = tokenHasStarted ? 0.58 + visible * 0.42 : 0.48;
        return (
          <span
            key={`${tokenIndex}-${token.word?.index ?? token.word?.word_index ?? token.fallbackFrame}-${token.text}`}
            style={{
              display: 'inline-block',
              marginRight: tokenIndex === line.length - 1 ? 0 : '0.14em',
              opacity: round(tokenOpacity),
              transform: `translateY(${round((tokenHasStarted ? 1 - visible : 0) * 8)}px)`,
              filter: `blur(${round((tokenHasStarted ? 1 - visible : 0) * 1.8)}px)`,
              willChange: 'opacity, transform, filter',
            }}
          >
            {token.text}
          </span>
        );
      })}
    </div>
  );
};

const MediaFirstCaptionCard: React.FC<{
  scene: HtmlScene;
  lines: CaptionLine[];
  localFrame: number;
  design: SceneDesign;
  mode: Exclude<MediaCaptionMode, 'featureCard'>;
}> = ({scene, lines, localFrame, design, mode}) => {
  const cleanOrnaments = isCleanOrnamentLayout();
  const reveal = easeOutBack(progress(localFrame, Math.max(0, captionStartFrame(lines) - 2), 13));
  const visible = clamp(reveal, 0, 1);
  const isSideNote = mode === 'sideNote';
  const hasSemanticVisual = Boolean(sceneSemanticVisual(scene));
  const variant = scene.scene_id % 4;
  const fontSize = compactCaptionFontSize(lines, mode);
  const darkPanel = isSideNote || variant === 1;
  const left = isSideNote ? (variant === 2 ? 218 : variant === 3 ? 52 : 42) : 44;
  const top = isSideNote ? (variant === 1 ? 76 : variant === 2 ? 94 : 112) : undefined;
  const right = isSideNote ? undefined : 44;
  const bottom = isSideNote ? undefined : hasSemanticVisual ? 48 : 68 + (variant % 2) * 12;
  const width = isSideNote ? (variant === 2 ? 448 : 488) : undefined;
  const rotation = isSideNote
    ? variant === 2
      ? -1.2
      : variant === 3
        ? 1.4
        : scene.scene_id % 2 === 0
          ? 0.9
          : -0.8
    : scene.scene_id % 2 === 0
      ? -0.6
      : 0.7;
  const background = darkPanel
    ? hexToRgba(design.dark, hasSemanticVisual ? 0.72 : 0.82)
    : hexToRgba(design.paper, hasSemanticVisual ? 0.78 : 0.9);
  const foreground = darkPanel ? design.paper : design.dark;
  return (
    <div
      style={{
        position: 'absolute',
        left,
        right,
        top,
        bottom,
        width,
        zIndex: 38,
        padding: isSideNote ? '17px 20px 19px' : hasSemanticVisual ? '15px 22px 17px' : '18px 24px 22px',
        boxSizing: 'border-box',
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 26)}px) rotate(${rotation}deg) scale(${round(
          0.97 + visible * 0.03,
        )})`,
        transformOrigin: isSideNote ? 'left center' : 'center center',
        background,
        border: `1px solid ${hexToRgba(darkPanel ? design.paper : design.dark, darkPanel ? 0.22 : 0.18)}`,
        boxShadow: `0 14px 34px ${hexToRgba(design.dark, hasSemanticVisual ? 0.16 : 0.2)}, -5px 5px 0 ${hexToRgba(
          design.accent,
          hasSemanticVisual ? 0.34 : darkPanel ? 0.68 : 0.5,
        )}`,
        color: foreground,
        fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
        textTransform: 'uppercase',
        letterSpacing: 0,
        overflow: 'hidden',
      }}
    >
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 8,
            background: design.accent,
          }}
        />
      ) : null}
      <div>
        {lines.map((line, index) => {
          return (
            <TimedCaptionLine
              key={`${scene.scene_id}-media-${index}-${captionLineKey(line)}`}
              line={line}
              lineIndex={index}
              localFrame={localFrame}
              fontSize={fontSize}
              lineHeight={isSideNote ? 0.94 : 0.9}
              translateX={-14}
            />
          );
        })}
      </div>
      {!cleanOrnaments ? (
        <div
          style={{
            marginTop: 12,
            width: isSideNote ? 168 : 232,
            height: 6,
            background: darkPanel ? design.secondary : design.accent,
          }}
        />
      ) : null}
    </div>
  );
};

const SceneCaptionCard: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  if (isFinalCtaScene(scene)) {
    return null;
  }
  const lines = buildCaptionTokenLines(scene);
  const text = captionPlainText(lines);
  if (!text) {
    return null;
  }
  const mediaAssets = sceneMediaAssets(scene);
  const hasMedia = mediaAssets.length > 0;
  const hasSemanticVisual = Boolean(sceneSemanticVisual(scene));
  const reveal = easeOutBack(progress(localFrame, Math.max(0, captionStartFrame(lines) - 2), 14));
  const visible = clamp(reveal, 0, 1);
  const isPoster = design.family === 'slam' || (!hasMedia && !hasSemanticVisual);
  if (isPoster) {
    return <TextWallScene scene={scene} lines={lines} localFrame={localFrame} design={design} />;
  }
  const longCaption = text.length > 64 || lines.length > 4;
  const compactMode = mediaCaptionMode(scene, text, lines, mediaAssets, design);
  if (compactMode !== 'featureCard') {
    return <MediaFirstCaptionCard scene={scene} lines={lines} localFrame={localFrame} design={design} mode={compactMode} />;
  }
  const posterTone = isPoster ? scene.scene_id % 3 : -1;
  const posterIsDark = isPoster && posterTone !== 1;
  const mediaVariant = !isPoster ? scene.scene_id % 3 : 0;
  const top = isPoster
    ? 76
    : mediaVariant === 1
      ? longCaption
        ? 72
        : 92
      : mediaVariant === 2
        ? longCaption
          ? 92
          : 118
        : longCaption
          ? 46
          : 58;
  const height = isPoster
    ? longCaption
      ? 830
      : 760
    : mediaVariant === 1
      ? longCaption
        ? 338
        : 292
      : longCaption
        ? 348
        : 302;
  const fontSize = captionFontSize(lines, isPoster);
  const left = isPoster
    ? posterTone === 2
      ? 58
      : 42
    : mediaVariant === 2
      ? 70
      : mediaVariant === 1
        ? 62
        : 42;
  const width = isPoster
    ? posterTone === 2
      ? 604
      : 636
    : mediaVariant === 2
      ? 520
      : mediaVariant === 1
        ? 596
        : 636;
  const rotation = isPoster
    ? posterTone === 1
      ? -1
      : 1
    : mediaVariant === 1
      ? scene.scene_id % 2 === 0
        ? 1.2
        : -1.2
      : mediaVariant === 2
        ? scene.scene_id % 2 === 0
          ? -2.2
          : 2.1
        : scene.scene_id % 2 === 0
          ? -1.4
          : 1.2;
  const cardColor = isPoster
    ? posterIsDark
      ? hexToRgba(design.dark, 0.94)
      : paperTexture(design.paper, design.dark)
    : hexToRgba(design.paper, 0.95);
  const textColor = posterIsDark ? design.paper : design.dark;
  const cleanOrnaments = isCleanOrnamentLayout();
  const hideChromeText = cleanOrnaments || isNoChromeTextLayout();
  const showCaptionChrome = !hideChromeText && (isPoster || isBLayoutStagedVfxPayload());
  const showAccentBars = !cleanOrnaments;
  return (
    <div
      style={{
        position: 'absolute',
        left,
        top,
        width,
        height,
        zIndex: 36,
        padding: isPoster ? '54px 52px 68px' : longCaption ? '34px 40px 66px' : '32px 40px 58px',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: isPoster && !longCaption ? 'center' : 'flex-start',
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 38)}px) rotate(${rotation}deg) scale(${round(
          0.94 + visible * 0.06,
        )})`,
        transformOrigin: 'center center',
        background: cardColor,
        border: `1px solid ${hexToRgba(posterIsDark ? design.paper : design.dark, isPoster ? 0.2 : 0.16)}`,
        boxShadow: `13px 17px 0 ${hexToRgba(design.dark, 0.13)}, 16px 22px 18px ${hexToRgba(design.dark, 0.1)}, -5px 8px 0 ${hexToRgba(
          posterTone === 1 ? design.secondary : design.accent,
          isPoster ? 0.7 : 0.36,
        )}`,
        color: textColor,
        fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
        textTransform: 'uppercase',
        letterSpacing: 0,
        overflow: 'hidden',
      }}
    >
      {showAccentBars ? (
        <div
          style={{
            position: 'absolute',
            left: isPoster ? 44 : 32,
            top: -14,
            width: isPoster ? 246 : 176,
            height: 32,
            background: tapeTexture(design.secondary, design.dark),
            transform: 'rotate(-3.4deg)',
            opacity: round(visible * 0.96),
          }}
        />
      ) : null}
      {showCaptionChrome ? (
        <div
          style={{
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 16,
            lineHeight: 1,
            fontWeight: 900,
            color: posterIsDark ? design.secondary : design.accent,
          }}
        >
          {captionHeader(scene, isPoster)}
        </div>
      ) : null}
      <div style={{marginTop: showCaptionChrome ? 34 : 0}}>
        {lines.map((line, index) => {
          return (
            <TimedCaptionLine
              key={`${scene.scene_id}-${index}-${captionLineKey(line)}`}
              line={line}
              lineIndex={index}
              localFrame={localFrame}
              fontSize={fontSize}
              lineHeight={isPoster ? 0.8 : 0.86}
              translateX={-18}
            />
          );
        })}
      </div>
      {showAccentBars ? (
        <div
          style={{
            position: 'absolute',
            left: isPoster ? 44 : 32,
            bottom: isPoster ? 42 : 24,
            width: isPoster ? 340 : longCaption ? 286 : 222,
            height: isPoster ? 14 : 8,
            background: design.accent,
          }}
        />
      ) : null}
      {showCaptionChrome ? (
        <div
          style={{
            position: 'absolute',
            right: 44,
            bottom: 38,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 12,
            lineHeight: 1,
            fontWeight: 900,
            opacity: 0.62,
          }}
        >
          {captionFooter(scene)}
        </div>
      ) : null}
    </div>
  );
};

const isFinalCtaScene = (scene: HtmlScene): boolean => {
  const lastSceneId = payload.scenes[payload.scenes.length - 1]?.scene_id;
  if (scene.scene_id !== lastSceneId) {
    return false;
  }
  const text = extractSyncCaptionText(scene.html).toLowerCase();
  return /лагере|оставля(?:ешь|ть)|доеда(?:ешь|ть)/i.test(text);
};

const TextWallScene: React.FC<{
  scene: HtmlScene;
  lines: CaptionLine[];
  localFrame: number;
  design: SceneDesign;
}> = ({scene, lines, localFrame, design}) => {
  const cleanOrnaments = isCleanOrnamentLayout();
  const hideChromeText = cleanOrnaments || isNoChromeTextLayout();
  const reveal = easeOutBack(progress(localFrame, Math.max(0, captionStartFrame(lines) - 2), 14));
  const visible = clamp(reveal, 0, 1);
  const dark = scene.scene_id % 4 === 1 || scene.scene_id % 4 === 2;
  const textColor = dark ? design.paper : design.dark;
  const mutedColor = dark ? hexToRgba(design.paper, 0.62) : hexToRgba(design.dark, 0.58);
  const longest = captionLongestLine(lines);
  const longestWord = captionLongestWord(lines);
  const fontSize =
    longestWord > 12 || longest > 22
      ? lines.length > 6
        ? 52
        : 62
      : lines.length <= 2
        ? 116
        : lines.length <= 4
          ? 94
          : lines.length <= 6
          ? 78
            : 64;
  const align = lines.length <= 4 || scene.scene_id % 3 === 0 ? 'center' : 'left';
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 36,
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 32)}px) scale(${round(0.96 + visible * 0.04)})`,
        transformOrigin: 'center center',
        color: textColor,
        fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
        textTransform: 'uppercase',
        letterSpacing: 0,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: dark
            ? `linear-gradient(180deg, ${hexToRgba(design.dark, 0.96)}, ${hexToRgba(
                design.dark,
                0.88,
              )}), radial-gradient(circle at 12% 18%, ${hexToRgba(design.accent, 0.22)}, transparent 28%)`
            : `linear-gradient(180deg, ${hexToRgba(design.paper, 0.96)}, ${hexToRgba(
                design.paper,
                0.82,
              )}), radial-gradient(circle at 86% 24%, ${hexToRgba(design.secondary, 0.2)}, transparent 30%)`,
        }}
      />
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            left: scene.scene_id % 2 === 0 ? 42 : 620,
            top: 0,
            width: 14,
            height: 1280,
            background: design.accent,
            opacity: 0.44,
            transform: `rotate(${scene.scene_id % 2 === 0 ? 3 : -3}deg)`,
            zIndex: 0,
          }}
        />
      ) : null}
      {!hideChromeText ? (
        <div
          style={{
            position: 'absolute',
            left: 54,
            top: 72,
            zIndex: 2,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 15,
            lineHeight: 1,
            fontWeight: 900,
            color: dark ? design.secondary : design.accent,
          }}
        >
          {captionHeader(scene, true)}
        </div>
      ) : null}
      <div
        style={{
          position: 'absolute',
          left: 54,
          right: 150,
          top: 152,
          bottom: 168,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: align === 'center' ? 'center' : 'flex-start',
          textAlign: align,
          zIndex: 2,
        }}
      >
        {lines.map((line, index) => {
          return (
            <TimedCaptionLine
              key={`${scene.scene_id}-wall-${index}-${captionLineKey(line)}`}
              line={line}
              lineIndex={index}
              localFrame={localFrame}
              fontSize={fontSize}
              lineHeight={0.82}
              translateX={-20}
              maxWidth={align === 'center' ? 516 : 500}
            />
          );
        })}
      </div>
      {!hideChromeText ? (
        <div
          style={{
            position: 'absolute',
            left: 54,
            bottom: 92,
            width: 250,
            height: 12,
            background: design.accent,
            zIndex: 2,
          }}
        />
      ) : null}
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            right: 54,
            bottom: 86,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 13,
            lineHeight: 1,
            fontWeight: 900,
            color: mutedColor,
            zIndex: 2,
          }}
        >
          {captionFooter(scene)}
        </div>
      ) : null}
    </div>
  );
};

const MediaCard: React.FC<{
  asset: MediaAsset;
  caption?: string;
  localFrame: number;
  design: SceneDesign;
  x: number;
  y: number;
  w: number;
  h: number;
  rot: number;
  z: number;
  delay: number;
}> = ({asset, caption, localFrame, design, x, y, w, h, rot, z, delay}) => {
  const cleanOrnaments = isCleanOrnamentLayout();
  const reveal = easeOutBack(progress(localFrame, delay, 14));
  const drift = clamp(localFrame / 120, 0, 1);
  const visible = clamp(reveal, 0, 1);
  const visibleCaption = cleanOrnaments ? undefined : caption;
  const mediaHeight = visibleCaption ? 'calc(100% - 40px)' : '100%';
  const mediaTreatment: React.CSSProperties = {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    objectPosition: `${asset.focusX} ${asset.focusY}`,
    display: 'block',
    filter: 'saturate(0.86) contrast(1.12) sepia(0.08)',
    transform: `scale(${asset.kind === 'video' ? 1.1 : 1.035})`,
    transformOrigin: 'center center',
    background: '#f7efe7',
  };
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: w,
        height: h,
        zIndex: z,
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 42)}px) rotate(${round(rot + drift * 0.85)}deg) scale(${round(
          0.92 + visible * 0.08 + drift * 0.012,
        )})`,
        transformOrigin: 'center center',
        padding: 14,
        boxSizing: 'border-box',
        background: paperTexture(design.paper, design.dark),
        border: `1px solid ${hexToRgba(design.dark, 0.16)}`,
        boxShadow: `10px 13px 0 ${hexToRgba(design.dark, 0.12)}, 16px 24px 28px ${hexToRgba(
          design.dark,
          0.1,
        )}, 0 2px 0 rgba(255,255,255,0.82) inset`,
      }}
    >
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            left: Math.max(24, w * 0.24),
            top: -13,
            width: Math.min(156, w * 0.48),
            height: 28,
            background: tapeTexture(design.secondary, design.dark),
            border: `1px solid ${hexToRgba(design.dark, 0.08)}`,
            transform: `rotate(${rot > 0 ? -2.5 : 2.5}deg)`,
            boxShadow: `3px 7px 14px ${hexToRgba(design.dark, 0.08)}`,
            clipPath: 'polygon(0 12%, 96% 0, 100% 78%, 4% 100%)',
          }}
        />
      ) : null}
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: mediaHeight,
          overflow: 'hidden',
          background: '#f7efe7',
        }}
      >
        {asset.kind === 'video' ? (
          <OffthreadVideo
            src={asset.src}
            muted
            pauseWhenBuffering
            delayRenderRetries={2}
            delayRenderTimeoutInMilliseconds={120000}
            acceptableTimeShiftInSeconds={0.08}
            playbackRate={1}
            style={mediaTreatment}
          />
        ) : (
          <Img src={asset.src} style={mediaTreatment} />
        )}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: `linear-gradient(180deg, ${hexToRgba(design.paper, 0.05)}, ${hexToRgba(
              design.dark,
              0.08,
            )})`,
          }}
        />
      </div>
      {visibleCaption ? (
        <div
          style={{
            position: 'absolute',
            left: 14,
            right: 14,
            bottom: 11,
            height: 31,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            color: design.dark,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 13,
            fontWeight: 800,
            letterSpacing: 0,
            textTransform: 'uppercase',
          }}
        >
          <span>{visibleCaption}</span>
          <span style={{width: 32, height: 4, background: design.accent}} />
        </div>
      ) : null}
    </div>
  );
};

const SceneGraphicLayer: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const cue = design.proof;
  const isSlam = design.family === 'slam';
  const isVideo = design.family === 'video' || design.family === 'feature';
  const isFinal = design.family === 'final';
  const hasMedia = sceneMediaAssets(scene).length > 0;
  const showProofStamp = false;
  return (
    <div style={{position: 'absolute', inset: 0, zIndex: 24, pointerEvents: 'none'}}>
      {isSlam ? <SlamMarks scene={scene} localFrame={localFrame} design={design} /> : null}
      {isVideo && !hasMedia ? <VideoEditorialMatte scene={scene} localFrame={localFrame} design={design} /> : null}
      {isVideo && !hasMedia && scene.scene_id !== 1 ? (
        <VideoStoryAnchor scene={scene} localFrame={localFrame} design={design} />
      ) : null}
      {showProofStamp && cue ? (
        <GraphicStamp
          x={proofPosition(scene.scene_id).x}
          y={proofPosition(scene.scene_id).y}
          w={proofPosition(scene.scene_id).w}
          h={proofPosition(scene.scene_id).h}
          rot={proofPosition(scene.scene_id).rot}
          localFrame={localFrame}
          delay={proofPosition(scene.scene_id).delay}
          design={design}
          kicker={cue.kicker}
          value={cue.value}
          detail={cue.detail}
        />
      ) : null}
      {isFinal ? <ChoiceMeter localFrame={localFrame} design={design} /> : null}
    </div>
  );
};

const SlamMarks: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const reveal = easeOutBack(progress(localFrame, 0, 12));
  const visible = clamp(reveal, 0, 1);
  const label = slamLabel(scene);
  const keywords = posterKeywords(scene);
  const showStamps = false;
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: -54,
          top: 604,
          width: 820,
          zIndex: 8,
          opacity: round(visible * 0.12),
          transform: `translateX(${round((1 - visible) * -36)}px) rotate(${scene.scene_id % 2 === 0 ? -4.5 : 3.6}deg)`,
          color: design.dark,
          fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
          fontSize: keywords[0].length > 8 ? 136 : 164,
          lineHeight: 0.72,
          fontWeight: 900,
          textTransform: 'uppercase',
          letterSpacing: 0,
          overflowWrap: 'break-word',
        }}
      >
        {keywords[0]}
      </div>
      <div
        style={{
          position: 'absolute',
          right: -42,
          top: 760,
          width: 560,
          zIndex: 9,
          opacity: round(visible * 0.1),
          transform: `translateX(${round((1 - visible) * 36)}px) rotate(${scene.scene_id % 2 === 0 ? 4.8 : -4.2}deg)`,
          color: design.accent,
          fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
          fontSize: keywords[1].length > 8 ? 118 : 148,
          lineHeight: 0.74,
          fontWeight: 900,
          textTransform: 'uppercase',
          letterSpacing: 0,
          textAlign: 'right',
        }}
      >
        {keywords[1]}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 44,
          right: 44,
          top: 846,
          height: 246,
          zIndex: 7,
          opacity: round(visible * 0.5),
          transform: `translateY(${round((1 - visible) * 26)}px) rotate(${scene.scene_id % 2 === 0 ? 1.7 : -1.4}deg)`,
          background: `linear-gradient(135deg, ${hexToRgba(design.paper, 0.72)}, ${hexToRgba(
            design.paper,
            0.42,
          )}), repeating-linear-gradient(0deg, ${hexToRgba(design.dark, 0.055)} 0, ${hexToRgba(
            design.dark,
            0.055,
          )} 1px, transparent 1px, transparent 18px)`,
          borderTop: `1px solid ${hexToRgba(design.dark, 0.13)}`,
          borderBottom: `1px solid ${hexToRgba(design.dark, 0.13)}`,
          boxShadow: `0 22px 42px ${hexToRgba(design.dark, 0.1)}`,
          clipPath: 'polygon(0 7%, 96% 0, 100% 88%, 3% 100%)',
        }}
      />
      {showStamps ? (
        <>
          <GraphicStamp
            x={72}
            y={952}
            w={292}
            h={132}
            rot={scene.scene_id % 2 === 0 ? -4 : 4}
            localFrame={localFrame}
            delay={4}
            design={design}
            kicker={label.kicker}
            value={label.value}
            detail={label.detail}
          />
          <GraphicStamp
            x={386}
            y={902}
            w={270}
            h={126}
            rot={scene.scene_id % 2 === 0 ? 3.2 : -3.4}
            localFrame={localFrame}
            delay={7}
            design={design}
            kicker="ключ"
            value={keywords[1]}
            z={21}
          />
        </>
      ) : null}
    </>
  );
};

const VideoEditorialMatte: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const cleanOrnaments = isCleanOrnamentLayout();
  const reveal = easeOutCubic(progress(localFrame, 2, 14));
  const visible = clamp(reveal, 0, 1);
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: 34,
          right: 34,
          bottom: 104,
          height: 96,
          opacity: round(visible * 0.72),
          transform: `translateY(${round((1 - visible) * 24)}px) rotate(${scene.scene_id % 2 === 0 ? 1.1 : -1.1}deg)`,
          background: paperTexture(design.paper, design.dark),
          border: `1px solid ${hexToRgba(design.dark, 0.14)}`,
          boxShadow: `7px 16px 30px ${hexToRgba(design.dark, 0.13)}`,
        }}
      />
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            left: 48,
            bottom: 154,
            width: 108,
            height: 8,
            background: design.accent,
            opacity: round(visible),
          }}
        />
      ) : null}
      {!cleanOrnaments ? (
        <div
          style={{
            position: 'absolute',
            right: 42,
            top: 114,
            width: 120,
            height: 520,
            borderRight: `10px solid ${hexToRgba(design.accent, 0.62)}`,
            borderTop: `10px solid ${hexToRgba(design.accent, 0.62)}`,
            opacity: round(visible * 0.86),
            transform: `translateX(${round((1 - visible) * 28)}px)`,
          }}
        />
      ) : null}
    </>
  );
};

const VideoStoryAnchor: React.FC<{scene: HtmlScene; localFrame: number; design: SceneDesign}> = ({
  scene,
  localFrame,
  design,
}) => {
  const cue = videoAnchorCue(scene);
  if (!cue) {
    return null;
  }
  const reveal = easeOutBack(progress(localFrame, cue.delay, 14));
  const visible = clamp(reveal, 0, 1);
  const compact = sceneMediaAssets(scene).length > 0;
  const anchorX = compact ? (scene.scene_id % 4 === 1 ? 62 : 352) : cue.x;
  const anchorY = compact ? 86 : cue.y;
  const anchorW = compact ? 306 : cue.w;
  const anchorH = compact ? 116 : cue.h;
  const anchorRot = compact ? (scene.scene_id % 2 === 0 ? -0.8 : 0.9) : cue.rot;
  const valueSize = compact ? (cue.value.length > 8 ? 38 : 50) : cue.value.length > 11 ? 68 : 82;
  return (
    <>
      <div
        style={{
          position: 'absolute',
          left: anchorX - (compact ? 10 : 20),
          top: anchorY + (compact ? 12 : 26),
          width: anchorW + (compact ? 20 : 44),
          height: anchorH + (compact ? 18 : 24),
          zIndex: 16,
          background: hexToRgba(design.secondary, 0.18),
          border: `2px solid ${hexToRgba(design.secondary, 0.5)}`,
          transform: `translateY(${round((1 - visible) * 22)}px) rotate(${anchorRot + 2.1}deg)`,
          opacity: round(visible * (compact ? 0.54 : 0.86)),
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: anchorX,
          top: anchorY,
          width: anchorW,
          minHeight: anchorH,
          zIndex: 18,
          padding: compact ? '14px 16px 15px' : '22px 24px 24px',
          boxSizing: 'border-box',
          background: compact ? hexToRgba(design.paper, 0.9) : paperTexture(design.paper, design.dark),
          border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
          boxShadow: compact
            ? `0 16px 34px ${hexToRgba(design.dark, 0.14)}, -4px 4px 0 ${hexToRgba(design.secondary, 0.42)}`
            : `10px 22px 36px ${hexToRgba(design.dark, 0.18)}, 0 1px 0 rgba(255,255,255,0.7) inset`,
          color: design.dark,
          fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
          opacity: round(visible),
          transform: `translateY(${round((1 - visible) * 34)}px) rotate(${anchorRot}deg) scale(${round(
            0.94 + visible * 0.06,
          )})`,
          transformOrigin: 'center center',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: compact ? 18 : 26,
            top: compact ? -10 : -14,
            width: compact ? 116 : 174,
            height: compact ? 20 : 30,
            background: tapeTexture(design.secondary, design.dark),
            transform: 'rotate(-2.5deg)',
            opacity: 0.94,
          }}
        />
        <div
          style={{
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: compact ? 11 : 13,
            lineHeight: 1,
            fontWeight: 900,
            textTransform: 'uppercase',
            color: design.accent,
          }}
        >
          {cue.kicker}
        </div>
        <div style={{marginTop: compact ? 9 : 12, fontSize: valueSize, lineHeight: 0.82, fontWeight: 900}}>
          {cue.value}
        </div>
        <div
          style={{
            marginTop: compact ? 8 : 16,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: compact ? 12 : 18,
            lineHeight: 1.08,
            fontWeight: 800,
            textTransform: 'uppercase',
          }}
        >
          {cue.detail}
        </div>
        <div
          style={{
            marginTop: compact ? 9 : 18,
            height: compact ? 5 : 9,
            width: compact ? Math.min(142, cue.lineWidth) : cue.lineWidth,
            background: design.accent,
          }}
        />
      </div>
    </>
  );
};

const ChoiceMeter: React.FC<{localFrame: number; design: SceneDesign}> = ({localFrame, design}) => {
  const reveal = easeOutCubic(progress(localFrame, 8, 14));
  const visible = clamp(reveal, 0, 1);
  return (
    <div
      style={{
        position: 'absolute',
        left: 92,
        top: 1016,
        width: 520,
        height: 64,
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 18)}px)`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
        fontSize: 14,
        fontWeight: 900,
        textTransform: 'uppercase',
        letterSpacing: 0,
        color: design.dark,
      }}
    >
      <div
        style={{
          padding: '17px 22px 15px',
          background: paperTexture(design.paper, design.dark),
          border: `1px solid ${hexToRgba(design.dark, 0.18)}`,
          boxShadow: `6px 12px 22px ${hexToRgba(design.dark, 0.12)}`,
          transform: 'rotate(-1.2deg)',
        }}
      >
        напиши в комменты, какой лагерь твой
      </div>
    </div>
  );
};

const GraphicStamp: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  rot: number;
  localFrame: number;
  delay: number;
  design: SceneDesign;
  kicker: string;
  value: string;
  detail?: string;
  z?: number;
  quiet?: boolean;
}> = ({x, y, w, h, rot, localFrame, delay, design, kicker, value, detail, z = 22, quiet = false}) => {
  const reveal = easeOutBack(progress(localFrame, delay, 13));
  const visible = clamp(reveal, 0, 1);
  const valueSize = quiet ? (value.length > 10 ? 30 : value.length > 7 ? 34 : 40) : w < 170 ? 66 : value.length > 10 ? 48 : value.length > 7 ? 60 : 72;
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width: w,
        minHeight: h,
        zIndex: z,
        padding: quiet ? '12px 14px 13px' : '17px 19px 18px',
        boxSizing: 'border-box',
        opacity: round(visible),
        transform: `translateY(${round((1 - visible) * 30)}px) rotate(${rot}deg) scale(${round(0.9 + visible * 0.1)})`,
        transformOrigin: 'center center',
        background: paperTexture(design.paper, design.dark),
        border: `1px solid ${hexToRgba(design.dark, 0.2)}`,
        boxShadow: `7px 9px 0 ${hexToRgba(design.dark, 0.12)}, 12px 18px 22px ${hexToRgba(
          design.dark,
          0.1,
        )}, 0 1px 0 rgba(255,255,255,0.72) inset`,
        color: design.dark,
        fontFamily: '"TNT Sans Condensed", "Arial Narrow", Arial, sans-serif',
        letterSpacing: 0,
      }}
    >
      <div
        style={{
          fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
          fontSize: 13,
          lineHeight: 1,
          fontWeight: 900,
          textTransform: 'uppercase',
          color: design.accent,
          letterSpacing: 0,
        }}
      >
        {kicker}
      </div>
      <div style={{marginTop: 9, fontSize: valueSize, lineHeight: 0.82, fontWeight: 900}}>
        {value}
      </div>
      {detail && !quiet ? (
        <div
          style={{
            marginTop: 9,
            fontFamily: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
            fontSize: 13,
            lineHeight: 1.05,
            fontWeight: 800,
            textTransform: 'uppercase',
            opacity: 0.74,
          }}
        >
          {detail}
        </div>
      ) : null}
    </div>
  );
};

const duelLayouts = [
  [
    {x: -18, y: 424, w: 470, h: 646, rot: -4.2, z: 12},
    {x: 328, y: 552, w: 430, h: 564, rot: 4.0, z: 15},
  ],
  [
    {x: 18, y: 592, w: 416, h: 536, rot: -4.8, z: 14},
    {x: 278, y: 402, w: 462, h: 628, rot: 2.9, z: 12},
  ],
  [
    {x: 40, y: 432, w: 448, h: 604, rot: 3.1, z: 13},
    {x: 368, y: 686, w: 358, h: 450, rot: -4.6, z: 16},
  ],
];

const heroLayouts: Record<number, {x: number; y: number; w: number; h: number; rot: number; z: number}> = {
  3: {x: 34, y: 410, w: 638, h: 724, rot: -2.4, z: 13},
  8: {x: 92, y: 404, w: 558, h: 716, rot: 3.2, z: 13},
  11: {x: 40, y: 482, w: 642, h: 610, rot: -1.6, z: 13},
  15: {x: 42, y: 450, w: 622, h: 660, rot: 2.1, z: 13},
  17: {x: 24, y: 448, w: 662, h: 684, rot: -3.8, z: 13},
};

const stackLayouts = [
  {x: -20, y: 430, w: 384, h: 560, rot: -5.4, z: 11},
  {x: 202, y: 560, w: 458, h: 590, rot: 2.5, z: 15},
  {x: 410, y: 382, w: 318, h: 456, rot: 5.2, z: 13},
];

const finalLayouts = [
  {x: 22, y: 412, w: 338, h: 514, rot: -2.5, z: 12},
  {x: 360, y: 420, w: 338, h: 514, rot: 2.2, z: 13},
];

const getSceneDesign = (scene: HtmlScene, isLastScene = false): SceneDesign => {
  const palette = palettes[(scene.scene_id - 1) % palettes.length];
  const images = sceneMediaAssets(scene);
  const hasVideo = images.some((asset) => asset.kind === 'video');
  const hasSemanticVisual = !isBLayoutStagedVfxPayload() && Boolean(sceneSemanticVisual(scene));
  const isTextOnly = /\btextonly\b/.test(scene.html) || (!images.length && !hasVideo && !hasSemanticVisual);
  const family: DesignFamily =
    isLastScene
      ? 'final'
      : isTextOnly
        ? 'slam'
        : hasSemanticVisual && !images.length
          ? scene.scene_id % 3 === 0
            ? 'feature'
            : 'video'
        : hasVideo
          ? scene.scene_id % 3 === 1
            ? 'feature'
            : 'video'
          : images.length >= 3
            ? 'stack'
            : images.length >= 2
              ? 'duel'
              : images.length === 1
                ? 'hero'
                : 'default';
  return {
    ...palette,
    family,
    proof: proofCue(scene),
  };
};

const proofCue = (scene: HtmlScene): ProofCue | undefined => {
  const topic = sceneTopic(scene);
  const cuesByTopic: Record<SceneTopic, ProofCue[]> = {
    food: [
      {kicker: 'проверка', value: 'ПОРЦИЯ', detail: 'не магия'},
      {kicker: 'счет', value: 'БАЛАНС', detail: 'контекст важнее'},
      {kicker: 'выбор', value: 'ДОСТАТОЧНО', detail: 'без героизма'},
    ],
    thermal: [
      {kicker: 'режим', value: 'ТЕПЛО', detail: 'мягкий стресс'},
      {kicker: 'реакция', value: 'ПУЛЬС', detail: 'телу не все равно'},
      {kicker: 'смысл', value: 'ВОССТАНОВЛЕНИЕ', detail: 'не шоу'},
    ],
    supplements: [
      {kicker: 'аптечка', value: 'БАЗА', detail: 'сначала рутина'},
      {kicker: 'проверка', value: 'ДОЗА', detail: 'без фанатизма'},
      {kicker: 'риск', value: 'НЕ ДОБАВКА', detail: 'если база пустая'},
    ],
    recovery: [
      {kicker: 'биохак', value: 'СОН', detail: 'самый скучный'},
      {kicker: 'энергия', value: 'ШАГИ', detail: 'без таблетки'},
      {kicker: 'стресс', value: 'ПАУЗА', detail: 'телу нужна база'},
    ],
    general: [
      {kicker: 'вывод', value: 'БАЗА', detail: 'скучно, но держит'},
      {kicker: 'факт', value: 'ПРИЧИНА', detail: 'а не легенда'},
    ],
  };
  const cues = cuesByTopic[topic];
  return cues[scene.scene_id % cues.length];
};

const videoAnchorCue = (
  scene: HtmlScene,
): {kicker: string; value: string; detail: string; x: number; y: number; w: number; h: number; rot: number; delay: number; lineWidth: number} | null => {
  const topic = sceneTopic(scene);
  const contextual: Record<SceneTopic, {kicker: string; value: string; detail: string}> = {
    food: {kicker: 'счет без драмы', value: 'БАЛАНС', detail: 'порция решает больше, чем зависть'},
    thermal: {kicker: 'тепловая логика', value: 'ТЕПЛО', detail: 'восстановление без героизма'},
    supplements: {kicker: 'аптечка под контролем', value: 'БАЗА', detail: 'сначала сон, еда и анализы'},
    recovery: {kicker: 'скучный биохак', value: 'СОН', detail: 'энергия начинается не с банки'},
    general: {kicker: 'проверка', value: 'ФАКТ', detail: 'смотрим на механизм'},
  };
  const cues: Record<
    number,
    {x: number; y: number; w: number; h: number; rot: number; delay: number; lineWidth: number}
  > = {
    1: {
      x: 78,
      y: 424,
      w: 500,
      h: 246,
      rot: -2.2,
      delay: 2,
      lineWidth: 248,
    },
    5: {
      x: 74,
      y: 470,
      w: 520,
      h: 268,
      rot: 2.3,
      delay: 2,
      lineWidth: 306,
    },
    12: {
      x: 58,
      y: 430,
      w: 570,
      h: 304,
      rot: -1.7,
      delay: 1,
      lineWidth: 356,
    },
    16: {
      x: 82,
      y: 456,
      w: 520,
      h: 292,
      rot: 2.2,
      delay: 2,
      lineWidth: 302,
    },
  };
  const layout = cues[scene.scene_id];
  if (!layout || (scene.scene_id !== 1 && scene.scene_id % 2 === 0)) {
    return null;
  }
  return {...contextual[topic], ...layout};
};

const proofPosition = (
  sceneId: number,
): {x: number; y: number; w: number; h: number; rot: number; delay: number} => {
  const positions: Record<number, {x: number; y: number; w: number; h: number; rot: number; delay: number}> = {
    4: {x: 48, y: 778, w: 354, h: 164, rot: -4, delay: 10},
    5: {x: 360, y: 818, w: 310, h: 154, rot: 3, delay: 18},
    8: {x: 42, y: 720, w: 348, h: 178, rot: -5, delay: 12},
    9: {x: 48, y: 796, w: 322, h: 154, rot: 4, delay: 10},
    11: {x: 382, y: 620, w: 278, h: 148, rot: 4, delay: 14},
    13: {x: 44, y: 786, w: 356, h: 160, rot: -3, delay: 10},
    15: {x: 386, y: 650, w: 286, h: 150, rot: -4, delay: 15},
    17: {x: 390, y: 666, w: 288, h: 150, rot: 5, delay: 15},
    19: {x: 46, y: 800, w: 356, h: 156, rot: 3, delay: 10},
  };
  return positions[sceneId] || {x: 382, y: 822, w: 286, h: 150, rot: sceneId % 2 === 0 ? 4 : -4, delay: 16};
};

const captionFor = (scene: HtmlScene, index: number): string | undefined => {
  if (index > 1 || scene.scene_id % 4 !== 2) {
    return undefined;
  }
  const labels: Record<SceneTopic, string[]> = {
    food: ['ПОРЦИЯ', 'КОНТЕКСТ'],
    thermal: ['ТЕПЛО', 'ХОЛОД'],
    supplements: ['БАНКА', 'БАЗА'],
    recovery: ['СОН', 'ЭНЕРГИЯ'],
    general: ['ФАКТ', 'ВЫВОД'],
  };
  return labels[sceneTopic(scene)][index];
};

const slamLabel = (scene: HtmlScene): ProofCue => {
  const fallbacks: Record<SceneTopic, ProofCue[]> = {
    food: [
      {kicker: 'рамка', value: 'ПОРЦИЯ', detail: 'а не воля'},
      {kicker: 'итог', value: 'БАЛАНС', detail: 'скучный ответ'},
    ],
    thermal: [
      {kicker: 'режим', value: 'ТЕПЛО', detail: 'без подвига'},
      {kicker: 'пауза', value: 'СТРЕСС', detail: 'тоже дозировка'},
    ],
    supplements: [
      {kicker: 'проверка', value: 'БАЗА', detail: 'до банок'},
      {kicker: 'заметка', value: 'РИСК', detail: 'если мешать всё'},
    ],
    recovery: [
      {kicker: 'биохак', value: 'СОН', detail: 'не модный'},
      {kicker: 'вывод', value: 'ШАГИ', detail: 'без волшебства'},
    ],
    general: [
      {kicker: 'вывод', value: 'ФАКТ', detail: 'без легенды'},
      {kicker: 'рамка', value: 'БАЗА', detail: 'держит сюжет'},
    ],
  };
  const cues = fallbacks[sceneTopic(scene)];
  return cues[scene.scene_id % cues.length];
};

const finalChoiceLabels = (scene: HtmlScene): [string, string] => {
  const payloadLabels = Array.isArray(scene.final_choice_labels)
    ? scene.final_choice_labels.map((label) => String(label || '').trim()).filter(Boolean)
    : [];
  if (payloadLabels.length >= 2) {
    return [payloadLabels[0].toUpperCase(), payloadLabels[1].toUpperCase()];
  }
  const labels: Record<SceneTopic, [string, string]> = {
    food: ['ОСТАВЛЯЮ', 'ДОЕДАЮ'],
    thermal: ['ПРОРУБЬ', 'БАНЯ'],
    supplements: ['БАНКИ', 'БАЗА'],
    recovery: ['ТАБЛЕТКА', 'СОН'],
    general: ['СТАРОЕ', 'НОВОЕ'],
  };
  return labels[sceneTopic(scene)];
};

const sourceCaseTitle = (scene: HtmlScene): string => {
  const titles: Record<SceneTopic, string> = {
    food: 'РАЗБОР ПОРЦИИ',
    thermal: 'ТЕПЛО-ПРОВЕРКА',
    supplements: 'СТЕК БЕЗ ХАОСА',
    recovery: 'ЭНЕРГИЯ И БАЗА',
    general: 'ЗАМЕТКИ КЕЙСА',
  };
  return titles[sceneTopic(scene)];
};

const posterKeywords = (scene: HtmlScene): [string, string] => {
  const topicFallbacks: Record<SceneTopic, [string, string]> = {
    food: ['ПОРЦИЯ', 'БАЛАНС'],
    thermal: ['ТЕПЛО', 'СТРЕСС'],
    supplements: ['БАЗА', 'РИСК'],
    recovery: ['СОН', 'ШАГИ'],
    general: ['ФАКТ', 'БАЗА'],
  };
  const stopWords = new Set([
    'МЕНЯ',
    'ТЕБЯ',
    'ЭТО',
    'ЧТО',
    'КАК',
    'ТАК',
    'ЕСЛИ',
    'ПОТОМУ',
    'ПОЭТОМУ',
    'КОТОРЫЙ',
    'КОТОРАЯ',
    'КОТОРЫЕ',
    'ПРОСТО',
    'ОЧЕНЬ',
    'ВСЕГДА',
    'МОЖЕТ',
    'НУЖНА',
    'НУЖЕН',
    'ПОСЛЕ',
    'ПЕРЕД',
  ]);
  const words = extractSyncCaptionText(scene.html)
    .toUpperCase()
    .replace(/Ё/g, 'Е')
    .replace(/[^A-ZА-Я0-9\s-]/g, ' ')
    .split(/\s+/)
    .map((word) => word.replace(/^-+|-+$/g, ''))
    .filter((word) => word.length >= 4 && !stopWords.has(word));
  const unique = Array.from(new Set(words));
  const fallback = topicFallbacks[sceneTopic(scene)];
  return [unique[0] || fallback[0], unique[1] || fallback[1]];
};

const sceneTopic = (scene: HtmlScene): SceneTopic => {
  const text = scenePlainText(scene);
  if (/(баня|баню|бане|саун|тепл|холод|лед|ледян|проруб|сосуд|пульс|температур|cold|sauna|plunge)/i.test(text)) {
    return 'thermal';
  }
  if (/(бад|бадов|витамин|омег|желез|цинк|аптеч|добавк|коллаген|таблет|банки|банка|stack|supplement|vitamin)/i.test(text)) {
    return 'supplements';
  }
  if (/(сон|спишь|спит|высып|кортизол|энерг|прогул|шаг|активност|биохак|biohack|sleep|energy)/i.test(text)) {
    return 'recovery';
  }
  if (/(латте|кофе|круас|выпеч|еда|сахар|тарел|обед|завтрак|калори|порци|перекус|доеда|lattes|pastries|coffee)/i.test(text)) {
    return 'food';
  }
  return 'general';
};

const scenePlainText = (scene: HtmlScene): string => {
  const htmlText = decodeHtmlEntities(scene.html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' '));
  const semantic = sceneSemanticVisual(scene);
  const semanticText = semantic ? `${semantic.topic || ''} ${(semantic.motifs || []).join(' ')}` : '';
  return `${payload.story_title || ''} ${extractSyncCaptionText(scene.html)} ${htmlText} ${semanticText}`.toLowerCase();
};

const sceneOwnMediaAssets = (scene: HtmlScene): MediaAsset[] => {
  if (shouldSuppressSceneMedia(scene)) {
    return [];
  }
  const assets: MediaAsset[] = [];
  const seen = new Set<string>();
  for (const asset of [...extractMediaAssets(scene.html), ...sceneBridgeMediaAssets(scene)]) {
    if (!asset.id || !asset.src || seen.has(asset.id)) {
      continue;
    }
    seen.add(asset.id);
    assets.push(asset);
  }
  return assets;
};

const sceneMediaAssets = (scene: HtmlScene): MediaAsset[] => {
  const ownAssets = sceneOwnMediaAssets(scene);
  if (ownAssets.length) {
    return ownAssets;
  }
  if (isBLayoutStagedVfxPayload()) {
    return [];
  }
  return sceneSemanticVisual(scene) ? sceneFallbackMediaAssets(scene) : [];
};

const sceneFallbackMediaAssets = (scene: HtmlScene): MediaAsset[] => {
  const sceneIndex = payload.scenes.findIndex((candidate) => candidate.scene_id === scene.scene_id);
  if (sceneIndex < 0) {
    return [];
  }
  for (let offset = 1; offset < payload.scenes.length; offset += 1) {
    const candidates = [sceneIndex - offset, sceneIndex + offset];
    for (const candidateIndex of candidates) {
      const candidate = payload.scenes[candidateIndex];
      if (!candidate) {
        continue;
      }
      const assets = sceneOwnMediaAssets(candidate);
      if (!assets.length) {
        continue;
      }
      return assets.slice(0, 1).map((asset) => ({
        ...asset,
        id: `${asset.id}-fallback-s${scene.scene_id}`,
        role: `${asset.role || 'semantic_bridge'} fallback_visual`,
      }));
    }
  }
  return [];
};

const shouldSuppressSceneMedia = (_scene: HtmlScene): boolean => false;

const sceneSemanticVisual = (scene: HtmlScene): SemanticVisual | null => {
  const visual = scene.semantic_visual;
  if (!visual || visual.kind !== 'semantic_motion' || visual.quality !== 'publishable_visual') {
    return null;
  }
  if (!Array.isArray(visual.motifs) || visual.motifs.length < 2 || !String(visual.id || '').trim()) {
    return null;
  }
  return visual;
};

const sceneBridgeMediaAssets = (scene: HtmlScene): MediaAsset[] => {
  return (scene.bridge_media_assets || [])
    .map((asset): MediaAsset => {
      const kind: MediaAsset['kind'] = asset.kind === 'video' ? 'video' : 'image';
      return {
        id: String(asset.id || ''),
        kind,
        role: String(asset.role || 'semantic_bridge'),
        src: videoSrc(String(asset.src || '')),
        fit: asset.fit || 'cover',
        focusX: String(asset.focusX || '50%'),
        focusY: String(asset.focusY || '50%'),
      };
    })
    .filter((asset) => asset.id && asset.src);
};

type HtmlVideoTarget = {
  id: string;
  src: string;
  className: string;
  dataAttrs: Record<string, string>;
  styleText: string;
  assetFit: React.CSSProperties['objectFit'];
};

const resolveStaticUrls = (html: string): string => {
  return html.replace(/__STATIC_FILE__([^"')\s<>]+)/g, (_match, assetPath: string) =>
    staticFile(assetPath),
  );
};

const stripHtmlVideoPlaceholders = (html: string): string => {
  return html.replace(videoWrapperPattern(), '').replace(directVideoPattern(), '');
};

const stripSyncCaptionLayer = (html: string): string => {
  return html.replace(/<div\b(?=[^>]*\bdata-girly-sync-caption=(["'])true\1)[^>]*>[\s\S]*?<\/div>/gi, '');
};

const stripGirlyDesignTextSlots = (html: string): string => {
  return html.replace(
    /<([a-z0-9]+)\b(?=[^>]*\bdata-girly-(?:filled|hidden)-text=)[^>]*>[\s\S]*?<\/\1>/gi,
    '',
  );
};

const prepareSceneHtml = (scene: HtmlScene, preserveBLayout: boolean): string => {
  let html = preserveBLayout ? scene.html : stripEmptyBridgePlaceholders(stripHtmlVideoPlaceholders(scene.html), scene);
  if (!preserveBLayout) {
    if (scene.scene_id === 1) {
      html = stripGirlyDesignTextSlots(html);
    }
    html = stripSyncCaptionLayer(html);
  }
  return resolveStaticUrls(html);
};

const stripEmptyBridgePlaceholders = (html: string, scene: HtmlScene): string => {
  if (!sceneBridgeMediaAssets(scene).length) {
    return html;
  }
  return html.replace(emptyScenePlaceholderPattern(), '');
};

const emptyScenePlaceholderPattern = (): RegExp =>
  /<div\b(?=[^>]*\bclass=(["'])(?=[^"']*\bscene-placeholder\b)[^"']*\1)(?![^>]*\bdata-girly-filled-media=)(?![^>]*\bdata-asset-id=)[^>]*>\s*<\/div>/gi;

const VideoOverlays: React.FC<{scene: HtmlScene}> = ({scene}) => {
  const targets = extractHtmlVideoTargets(scene.html);
  if (!targets.length) {
    return null;
  }
  const rootClassName = extractSceneRootClass(scene.html);
  return (
    <div
      className={rootClassName}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'none',
      }}
    >
      {targets.map((target) => (
        <div
          key={target.id}
          className={`${target.className} remotion-controlled-video`}
          {...target.dataAttrs}
          data-asset-id={target.id}
          style={parseInlineStyle(target.styleText)}
        >
          <OffthreadVideo
            src={videoSrc(target.src)}
            muted
            pauseWhenBuffering
            delayRenderRetries={2}
            delayRenderTimeoutInMilliseconds={120000}
            acceptableTimeShiftInSeconds={0.08}
            playbackRate={1}
            style={{
              width: '100%',
              height: '100%',
              display: 'block',
              objectFit: target.assetFit || 'cover',
              background: '#17101D',
            }}
          />
        </div>
      ))}
    </div>
  );
};

const extractSceneRootClass = (html: string): string => {
  const rootMatch = html.match(
    /<(?:div|section)\b([^>]*(?:\bdata-scene-root=["'][^"']+["']|\bdata-preview15=["'][^"']+["']|\bdata-scene-id=["'][^"']+["'])[^>]*)>/i,
  );
  if (!rootMatch) {
    return '';
  }
  return attrValue(rootMatch[1] || '', 'class');
};

const extractHtmlVideoTargets = (html: string): HtmlVideoTarget[] => {
  const targets: HtmlVideoTarget[] = [];
  const seen = new Set<string>();
  const pattern = videoWrapperPattern();
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html))) {
    const attrs = match[1] || '';
    const id = match[2] || '';
    const inner = match[3] || '';
    const src = inner.match(/\bsrc="([^"]+)"/i)?.[1] || '';
    if (!id || !src) {
      continue;
    }
    const styleText = attrValue(attrs, 'style');
    if (seen.has(id)) {
      continue;
    }
    seen.add(id);
    targets.push({
      id,
      src,
      className: attrValue(attrs, 'class') || 'asset-placeholder',
      dataAttrs: dataAttrs(attrs),
      styleText,
      assetFit: extractAssetFit(styleText),
    });
  }
  const directPattern = directVideoPattern();
  while ((match = directPattern.exec(html))) {
    const attrs = match[1] || '';
    const id = match[2] || '';
    const src = attrValue(attrs, 'src');
    if (!id || !src || seen.has(id)) {
      continue;
    }
    seen.add(id);
    const styleText = attrValue(attrs, 'style');
    targets.push({
      id,
      src,
      className: attrValue(attrs, 'class') || 'asset-placeholder',
      dataAttrs: dataAttrs(attrs),
      styleText,
      assetFit: extractAssetFit(styleText),
    });
  }
  return targets;
};

const videoWrapperPattern = (): RegExp =>
  /<div\b([^>]*\bdata-asset-id="([^"]+)"[^>]*)>\s*(<video\b[^>]*>[\s\S]*?<\/video>)\s*<\/div>/gi;

const directVideoPattern = (): RegExp =>
  /<video\b([^>]*\bdata-asset-id="([^"]+)"[^>]*)>[\s\S]*?<\/video>/gi;

const attrValue = (attrs: string, name: string): string => {
  const match = attrs.match(new RegExp(`\\b${name}="([^"]*)"`, 'i'));
  return match?.[1] || '';
};

const dataAttrs = (attrs: string): Record<string, string> => {
  const result: Record<string, string> = {};
  const pattern = /\b(data-[\w:-]+)=["']([^"']*)["']/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(attrs))) {
    const name = match[1] || '';
    if (name && name !== 'data-asset-id') {
      result[name] = match[2] || '';
    }
  }
  return result;
};

const videoSrc = (src: string): string => {
  const staticMatch = src.match(/^__STATIC_FILE__(.+)$/);
  if (staticMatch) {
    return staticFile(staticMatch[1]);
  }
  return src;
};

const extractBackdropMedia = (html: string): {src: string; kind: 'image' | 'video'} | null => {
  const candidates: {src: string; kind: 'image' | 'video'}[] = [];
  const staticPattern = /__STATIC_FILE__([^"')\s<>]+)/g;
  let match: RegExpExecArray | null;
  while ((match = staticPattern.exec(html))) {
    const assetPath = match[1] || '';
    const kind = /\.(mp4|webm|mov)(?:[?#].*)?$/i.test(assetPath) ? 'video' : 'image';
    candidates.push({src: staticFile(assetPath), kind});
  }
  if (!candidates.length) {
    return null;
  }
  return candidates.find((candidate) => candidate.kind === 'image') || candidates[0];
};

const sceneBackdropMedia = (scene: HtmlScene): {src: string; kind: 'image' | 'video'} | null => {
  const htmlMedia = extractBackdropMedia(scene.html);
  if (htmlMedia) {
    return htmlMedia;
  }
  const bridgeAssets = sceneBridgeMediaAssets(scene);
  const asset = bridgeAssets.find((candidate) => candidate.kind === 'image') || bridgeAssets[0];
  if (asset) {
    return {src: asset.src, kind: asset.kind};
  }
  if (isBLayoutStagedVfxPayload()) {
    return null;
  }
  const fallbackAssets = sceneFallbackMediaAssets(scene);
  const fallback = fallbackAssets.find((candidate) => candidate.kind === 'video') || fallbackAssets[0];
  return fallback ? {src: fallback.src, kind: fallback.kind} : null;
};

const extractSyncCaptionText = (html: string): string => {
  const match = html.match(/<div\b[^>]*\bdata-girly-sync-caption="true"[^>]*>([\s\S]*?)<\/div>/i);
  const source = match?.[1] || '';
  return decodeHtmlEntities(
    source
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim(),
  );
};

const buildCaptionTokenLines = (scene: HtmlScene): CaptionLine[] => {
  const timedTokens = (scene.word_timings || [])
    .map((word, index): CaptionToken | null => {
      const text = captionDisplayText(word.text || word.word || '');
      if (!text) {
        return null;
      }
      return {text, word, fallbackFrame: index * 2};
    })
    .filter((token): token is CaptionToken => Boolean(token));
  if (timedTokens.length) {
    return splitCaptionTokens(timedTokens);
  }

  const fallbackTokens = extractSyncCaptionText(scene.html)
    .replace(/\s+—\s+/g, ' — ')
    .split(/\s+/)
    .filter(Boolean)
    .map((word, index): CaptionToken => ({text: captionDisplayText(word), fallbackFrame: index * 2}));
  return splitCaptionTokens(fallbackTokens);
};

const splitCaptionTokens = (tokens: CaptionToken[]): CaptionLine[] => {
  const text = captionPlainText([tokens]);
  const maxChars = text.length > 98 ? 14 : text.length > 68 ? 15 : 17;
  const lines: CaptionLine[] = [];
  let current: CaptionLine = [];
  for (const token of tokens) {
    const next = [...current, token];
    if (current.length && captionLineText(next).length > maxChars) {
      if (/—\s*$/.test(captionLineText(current))) {
        current = next;
      } else {
        lines.push(current);
        current = [token];
      }
    } else {
      current = next;
    }
  }
  if (current.length) {
    lines.push(current);
  }
  const maxLines = 7;
  return lines.length <= maxLines ? lines : [...lines.slice(0, maxLines - 1), lines.slice(maxLines - 1).flat()];
};

const captionDisplayText = (value: string): string =>
  value
    .trim()
    .replace(/семьсот/gi, '700')
    .toUpperCase();

const captionLineText = (line: CaptionLine): string => line.map((token) => token.text).join(' ');

const captionPlainText = (lines: CaptionLine[]): string => lines.map(captionLineText).join(' ');

const captionLineKey = (line: CaptionLine): string =>
  line.map((token) => `${token.word?.index ?? token.word?.word_index ?? token.fallbackFrame}:${token.text}`).join('|');

const captionTokenAppearFrame = (token: CaptionToken): number => {
  const rawFrame = Number(token.word?.appear_frame);
  return Number.isFinite(rawFrame) ? Math.max(0, rawFrame) : Math.max(0, token.fallbackFrame);
};

const captionLineStartFrame = (line: CaptionLine, fallbackFrame: number): number => {
  if (!line.length) {
    return Math.max(0, fallbackFrame);
  }
  return Math.min(...line.map(captionTokenAppearFrame));
};

const captionLongestLine = (lines: CaptionLine[]): number => Math.max(1, ...lines.map((line) => captionLineText(line).length));

const captionLongestWord = (lines: CaptionLine[]): number =>
  Math.max(
    1,
    ...lines.flatMap((line) =>
      line.flatMap((token) => token.text.split(/\s+/)).map((word) => word.replace(/[^\p{L}\p{N}-]/gu, '').length),
    ),
  );

const captionStartFrame = (lines: CaptionLine[]): number => {
  const frames = lines
    .flatMap((line, index) => (line.length ? [captionLineStartFrame(line, index * 2)] : []))
    .filter((frame) => Number.isFinite(frame));
  return frames.length ? Math.min(...frames) : 0;
};

const captionHeader = (scene: HtmlScene, isPoster: boolean): string => {
  const headers: Record<SceneTopic, string[]> = {
    food: ['разбор порции', 'проверка мифа', 'контекст еды'],
    thermal: ['тепловой режим', 'проверка стресса', 'восстановление'],
    supplements: ['разбор рутины', 'проверка базы', 'аптечка без хаоса'],
    recovery: ['скучный биохак', 'проверка энергии', 'режим тела'],
    general: ['проверка мифа', 'сдвиг логики', 'что на самом деле'],
  };
  const options = headers[sceneTopic(scene)];
  return options[(scene.scene_id + (isPoster ? 2 : 0)) % options.length];
};

const captionFooter = (scene: HtmlScene): string => {
  const footers: Record<SceneTopic, string[]> = {
    food: ['контекст, не магия', 'порция решает', 'обычный день'],
    thermal: ['дозируем стресс', 'тепло без подвига', 'смотрим на тело'],
    supplements: ['база до банок', 'не мешать вслепую', 'сначала рутина'],
    recovery: ['сон до моды', 'шаги вместо шоу', 'энергия без трюка'],
    general: ['контекст, не магия', 'смотрим на детали', 'без героизма'],
  };
  const options = footers[sceneTopic(scene)];
  return options[scene.scene_id % options.length];
};

const captionFontSize = (lines: CaptionLine[], isPoster: boolean): number => {
  const longest = captionLongestLine(lines);
  const longestWord = captionLongestWord(lines);
  if (isPoster) {
    if (lines.length <= 2 && longestWord <= 10 && longest <= 15) {
      return 108;
    }
    if (lines.length <= 4 && longestWord <= 10 && longest <= 16) {
      return 88;
    }
    if (longestWord > 11 || longest > 19) {
      return lines.length > 5 ? 50 : 58;
    }
    return lines.length > 6 ? 50 : lines.length > 5 ? 56 : longest > 16 ? 64 : 78;
  }
  if (longestWord > 11 || longest > 20) {
    return lines.length > 5 ? 32 : 38;
  }
  return lines.length > 6 ? 32 : lines.length > 5 ? 36 : longest > 16 ? 42 : 50;
};

const decodeHtmlEntities = (value: string): string =>
  value
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');

const extractMediaAssets = (html: string): MediaAsset[] => {
  const assets: MediaAsset[] = [];
  const seen = new Set<string>();
  const addAsset = (asset: MediaAsset) => {
    if (!asset.id || !asset.src || seen.has(asset.id)) {
      return;
    }
    seen.add(asset.id);
    assets.push(asset);
  };

  for (const target of extractHtmlVideoTargets(html)) {
    addAsset({
      id: target.id,
      kind: 'video',
      role: target.dataAttrs['data-girly-role'] || '',
      src: videoSrc(target.src),
      fit: target.assetFit || 'cover',
      focusX: target.styleText.match(/--focus-x\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%',
      focusY: target.styleText.match(/--focus-y\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%',
    });
  }

  const pattern = /<div\b([^>]*\bdata-asset-id="([^"]+)"[^>]*)>\s*<img\b([^>]*)>/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html))) {
    const attrs = match[1] || '';
    const id = match[2] || '';
    const imgAttrs = match[3] || '';
    const src = attrValue(imgAttrs, 'src');
    if (!id || !src) {
      continue;
    }
    const styleText = attrValue(attrs, 'style');
    const focusX = styleText.match(/--focus-x\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%';
    const focusY = styleText.match(/--focus-y\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%';
    const fit = (attrValue(attrs, 'data-fit') || extractAssetFit(styleText)) as React.CSSProperties['objectFit'];
    addAsset({
      id,
      kind: 'image',
      role: attrValue(attrs, 'data-role') || '',
      src: videoSrc(src),
      fit: fit || 'cover',
      focusX,
      focusY,
    });
  }

  const divPattern = /<div\b([^>]*\bdata-asset-id="([^"]+)"[^>]*)>/gi;
  while ((match = divPattern.exec(html))) {
    const attrs = match[1] || '';
    const id = match[2] || '';
    if (!id || seen.has(id)) {
      continue;
    }
    const styleText = attrValue(attrs, 'style');
    const src = extractBackgroundImageSrc(styleText);
    if (!src) {
      continue;
    }
    addAsset({
      id,
      kind: 'image',
      role: attrValue(attrs, 'data-girly-role') || attrValue(attrs, 'data-role') || '',
      src: videoSrc(src),
      fit: extractAssetFit(styleText) || 'cover',
      focusX: styleText.match(/--focus-x\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%',
      focusY: styleText.match(/--focus-y\s*:\s*([^;]+)/i)?.[1]?.trim() || '50%',
    });
  }

  return assets;
};

const extractBackgroundImageSrc = (styleText: string): string => {
  const match = styleText.match(/background-image\s*:\s*url\(([^)]+)\)/i);
  return (match?.[1] || '').trim().replace(/^['"]|['"]$/g, '');
};

const extractAssetFit = (styleText: string): React.CSSProperties['objectFit'] => {
  const match = styleText.match(/(?:--asset-fit|object-fit)\s*:\s*([^;]+)/i);
  return (match?.[1]?.trim() || 'cover') as React.CSSProperties['objectFit'];
};

const parseInlineStyle = (styleText: string): React.CSSProperties => {
  const style: Record<string, string> = {};
  for (const part of styleText.split(';')) {
    const index = part.indexOf(':');
    if (index < 0) {
      continue;
    }
    const rawKey = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (!rawKey || !value) {
      continue;
    }
    const key = rawKey.startsWith('--') ? rawKey : rawKey.replace(/-([a-z])/g, (_m, char) => char.toUpperCase());
    style[key] = value;
  }
  return style as React.CSSProperties;
};

type AssetMotionTarget = {
  id: string;
  baseOpacity: number;
  isBackground: boolean;
  index: number;
};

const buildSceneMotionCss = (
  scene: HtmlScene,
  localFrame: number,
  fps: number,
  design: SceneDesign,
  rawHtmlLayout = false,
): string => {
  const hasVideoTargets = extractHtmlVideoTargets(scene.html).length > 0;
  const sceneProgress = clamp(localFrame / Math.max(1, scene.duration_frames - 1), 0, 1);
  const textReveal = easeOutCubic(progress(localFrame, 0, Math.min(18, Math.max(10, fps * 0.55))));
  const cardReveal = easeOutBack(progress(localFrame, 1, Math.min(14, Math.max(9, fps * 0.45))));
  const speakerReveal = easeOutBack(progress(localFrame, 2, Math.min(14, Math.max(8, fps * 0.4))));
  const wordRules = buildWordRevealCss(scene, localFrame);
  const finalSceneCss =
    design.family === 'final'
      ? `
#remotion-html-stage .quality-scene-html .typo,
#remotion-html-stage .quality-scene-html .subtitle-bottom {
  opacity: 0 !important;
  visibility: hidden !important;
}
`
      : '';
  const lines = Array.from({length: 6}, (_value, index) => {
    const lineProgress = easeOutCubic(progress(localFrame, index * 2, 12));
    return `
#remotion-html-stage .poster-type span:nth-child(${index + 1}) {
  opacity: ${round(lineProgress)} !important;
  clip-path: inset(0 ${round((1 - lineProgress) * 100)}% 0 0) !important;
  translate: 0 ${round((1 - lineProgress) * 26)}px !important;
}`;
  }).join('\n');

  const assetRules = extractAssetMotionTargets(scene.html)
    .map((target) => {
      const vfxTiming = vfxTimingForAsset(scene, target.id);
      if (target.isBackground && !vfxTiming) {
        const bgScale = round(1 + sceneProgress * 0.035);
        return `
#remotion-html-stage [data-asset-id="${cssAttr(target.id)}"] {
  opacity: ${target.baseOpacity} !important;
  scale: ${bgScale} !important;
}`;
      }
      const timing = vfxTiming || scene.asset_timings?.[target.id];
      const appearFrame = timing ? timing.appear_frame : 8 + target.index * 7;
      const assetProgress = rawHtmlLayout
        ? easeOutCubic(progress(localFrame, appearFrame, target.isBackground ? 24 : 20))
        : easeOutBack(progress(localFrame, appearFrame, 17));
      const opacity = round(target.baseOpacity * clamp(assetProgress, 0, 1));
      const startScale = rawHtmlLayout ? (target.isBackground ? 1.01 : 0.96) : 0.78;
      const scale = round(startScale + assetProgress * (1 - startScale));
      const y = round((1 - clamp(assetProgress, 0, 1)) * (rawHtmlLayout ? (target.isBackground ? 14 : 28) : 44));
      const blur = round((1 - clamp(assetProgress, 0, 1)) * (rawHtmlLayout ? 3 : 5));
      return `
#remotion-html-stage [data-asset-id="${cssAttr(target.id)}"] {
  opacity: ${opacity} !important;
  scale: ${scale} !important;
  translate: 0 ${y}px !important;
  filter: blur(${blur}px) !important;
}`;
    })
    .join('\n');
  const vfxRules = rawHtmlLayout ? buildVfxTimingCss(scene, localFrame) : '';

  return `
#remotion-html-stage .quality-scene-frame {
  will-change: opacity, transform;
  z-index: 2 !important;
}
#remotion-html-stage [data-preview15="true"],
#remotion-html-stage [data-scene-root] {
  width: ${payload.width}px !important;
  height: ${payload.height}px !important;
  position: absolute !important;
  inset: 0 !important;
  overflow: hidden !important;
}
#remotion-html-stage .voiceoverSyncText {
  display: none !important;
}
#remotion-html-stage .quality-scene-html {
  opacity: 0 !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
#remotion-html-stage .quality-scene-html .mediaBox {
  opacity: 0 !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
#remotion-html-stage .quality-scene-html .scene,
#remotion-html-stage .quality-scene-html [data-preview15="true"],
#remotion-html-stage .quality-scene-html [data-scene-root] {
  background: transparent !important;
}
#remotion-html-stage .quality-scene-html .scene::before {
  opacity: 0 !important;
}
#remotion-html-stage .quality-scene-html .typo {
  max-width: calc(100% - 88px) !important;
}
#remotion-html-stage .quality-scene-html .typoInner {
  display: inline-block !important;
  box-sizing: border-box !important;
  max-width: 100% !important;
  padding: 16px 18px 18px !important;
  background: ${hexToRgba(design.paper, 0.86)} !important;
  border: 1px solid ${hexToRgba(design.dark, 0.13)} !important;
  box-shadow: 0 18px 48px ${hexToRgba(design.dark, 0.14)} !important;
}
#remotion-html-stage .quality-scene-html .textonly .typoInner {
  padding: 0 !important;
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}
#remotion-html-stage .quality-scene-html .avatar .typoInner {
  background: ${hexToRgba(design.paper, 0.78)} !important;
}
#remotion-html-stage .quality-scene-html .textonly .heroLine,
#remotion-html-stage .quality-scene-html .textonly .body,
#remotion-html-stage .quality-scene-html .textonly .timedWord {
  color: ${design.paper} !important;
}
#remotion-html-stage .body,
#remotion-html-stage .heroLine,
#remotion-html-stage .accent,
#remotion-html-stage .label {
  letter-spacing: 0 !important;
}
#remotion-html-stage .heroLine {
  transform: scaleX(.84) !important;
  width: 119% !important;
}
#remotion-html-stage .quality-scene-html .avatar .typo {
  top: 78px !important;
}
#remotion-html-stage .quality-scene-html #scene-08 .heroLine {
  font-size: 76px !important;
  line-height: .82 !important;
}
#remotion-html-stage .quality-scene-html #scene-11 .heroLine,
#remotion-html-stage .quality-scene-html #scene-17 .heroLine {
  font-size: 92px !important;
}
#remotion-html-stage .quality-scene-html #scene-20 .typo {
  left: 46px !important;
  top: 48px !important;
  width: 640px !important;
}
#remotion-html-stage .quality-scene-html #scene-20 .typoInner {
  padding: 14px 16px 16px !important;
}
#remotion-html-stage .quality-scene-html #scene-20 .heroLine {
  font-size: 78px !important;
  line-height: .78 !important;
}
#remotion-html-stage .quality-scene-html #scene-20 .body {
  font-size: 27px !important;
}
#remotion-html-stage .quality-scene-html #scene-20 .accent {
  font-size: 38px !important;
}
${finalSceneCss}
#remotion-html-stage .poster-type,
#remotion-html-stage .editorial-serif,
#remotion-html-stage .script-accent,
#remotion-html-stage .pill,
#remotion-html-stage .timedWord,
#remotion-html-stage .heroLine,
#remotion-html-stage .body {
  will-change: opacity, clip-path, translate, scale, filter;
}
#remotion-html-stage .poster-type span {
  display: block;
}
#remotion-html-stage .sync-text {
  opacity: 1 !important;
  clip-path: none !important;
}
#remotion-html-stage .sync-word {
  display: inline !important;
  white-space: pre-wrap !important;
  opacity: 0 !important;
}
#remotion-html-stage .timedWord {
  display: inline-block !important;
  opacity: 0 !important;
}
#remotion-html-stage .remotion-controlled-video video {
  width: 100% !important;
  height: 100% !important;
  display: block !important;
  filter: saturate(1.05) contrast(1.02) !important;
}
#remotion-html-stage .asset-video-bg.bg-layer,
#remotion-html-stage .remotion-controlled-video.asset-video-bg.bg-layer {
  position: absolute !important;
  inset: 0 !important;
  z-index: 0 !important;
  pointer-events: none !important;
  filter: saturate(1.04) contrast(1.02) !important;
  opacity: .86 !important;
}
#remotion-html-stage > div:first-child {
  position: absolute !important;
  inset: 0 !important;
  z-index: 0 !important;
}
${hasVideoTargets ? `
#remotion-html-stage > div:first-child [data-scene-root] {
  background: transparent !important;
}` : ''}
#remotion-html-stage .avatar.scene {
  background: transparent !important;
}
#remotion-html-stage .avatar.scene::before {
  opacity: 0 !important;
}
#remotion-html-stage .typo {
  position: absolute !important;
  z-index: 30 !important;
}
#remotion-html-stage .typoInner {
  position: relative !important;
  z-index: 30 !important;
}
#remotion-html-stage .timedWord {
  position: relative !important;
  z-index: 31 !important;
}
${lines}
#remotion-html-stage .editorial-serif:not(.sync-text),
#remotion-html-stage .script-accent:not(.sync-text) {
  opacity: ${round(textReveal)} !important;
  clip-path: inset(0 ${round((1 - textReveal) * 100)}% 0 0) !important;
}
#remotion-html-stage .editorial-card,
#remotion-html-stage .subtitle-bottom {
  opacity: ${round(clamp(cardReveal, 0, 1))} !important;
  scale: ${round(0.94 + cardReveal * 0.06)} !important;
  translate: 0 ${round((1 - clamp(cardReveal, 0, 1)) * 28)}px !important;
}
#remotion-html-stage .speaker-placeholder {
  opacity: ${round(clamp(speakerReveal, 0, 1))} !important;
  scale: ${round(0.82 + speakerReveal * 0.18)} !important;
  translate: 0 ${round((1 - clamp(speakerReveal, 0, 1)) * 34)}px !important;
}
#remotion-html-stage .pill:nth-child(1) {
  opacity: ${round(easeOutCubic(progress(localFrame, 18, 14)))} !important;
}
#remotion-html-stage .pill:nth-child(2) {
  opacity: ${round(easeOutCubic(progress(localFrame, 28, 14)))} !important;
}
${assetRules}
#remotion-html-stage .quality-scene-html .mediaBox,
#remotion-html-stage .quality-scene-html .mediaBox[data-asset-id] {
  opacity: 0 !important;
  visibility: hidden !important;
  pointer-events: none !important;
}
${wordRules}
`;
};

const buildWordRevealCss = (scene: HtmlScene, localFrame: number): string => {
  const isTextOnly = /\btextonly\b/.test(scene.html);
  return (scene.word_timings || [])
    .map((word) => {
      const originalAppearFrame = Number.isFinite(word.appear_frame) ? word.appear_frame : 0;
      const appearFrame = isTextOnly ? Math.min(originalAppearFrame, word.index * 2) : originalAppearFrame;
      const wordProgress = easeOutCubic(progress(localFrame, appearFrame, isTextOnly ? 4 : 6));
      const visible = localFrame >= appearFrame ? 1 : 0;
      const opacity = round(visible * clamp(wordProgress, 0, 1));
      const y = round((1 - clamp(wordProgress, 0, 1)) * 8);
      const blur = round((1 - clamp(wordProgress, 0, 1)) * 2);
      return `
#remotion-html-stage [data-word-index="${word.index}"] {
  opacity: ${opacity} !important;
  clip-path: none !important;
  translate: 0 ${y}px !important;
  filter: blur(${blur}px) !important;
}`;
    })
    .join('\n');
};

const buildVfxTimingCss = (scene: HtmlScene, localFrame: number): string => {
  return (scene.vfx_timings || [])
    .filter((timing) => timing.target && !isAssetVfxTarget(timing.target) && isSafeVfxSelector(timing.target))
    .map((timing) => {
      const appearFrame = clamp(Math.round(timing.appear_frame || 0), 0, Math.max(0, scene.duration_frames - 1));
      const role = timing.role || 'decoration';
      const revealDuration = role === 'decoration' ? 14 : role === 'label' ? 16 : 20;
      const reveal = easeOutCubic(progress(localFrame, appearFrame, revealDuration));
      const visible = clamp(reveal, 0, 1);
      const travel = role === 'decoration' ? 14 : role === 'label' ? 18 : 28;
      const startScale = role === 'decoration' ? 0.985 : role === 'label' ? 0.975 : 0.96;
      const opacity = round(visible);
      const y = round((1 - visible) * travel);
      const scale = round(startScale + visible * (1 - startScale));
      const blur = round((1 - visible) * (role === 'decoration' ? 2 : 3));
      return `
#remotion-html-stage .quality-scene-html ${timing.target}:not(.girly-sync-caption):not(.sync-word) {
  opacity: ${opacity} !important;
  translate: 0 ${y}px !important;
  scale: ${scale} !important;
  filter: blur(${blur}px) !important;
  will-change: opacity, translate, scale, filter !important;
}`;
    })
    .join('\n');
};

const vfxTimingForAsset = (scene: HtmlScene, assetId: string): VfxTiming | undefined => {
  const target = `[data-asset-id="${cssAttr(assetId)}"]`;
  return (scene.vfx_timings || []).find((timing) => timing.target === target || timing.target === assetId);
};

const isAssetVfxTarget = (target: string): boolean => /^\[data-asset-id=/.test(target) || !/[\[.#: ]/.test(target);

const isSafeVfxSelector = (target: string): boolean => {
  if (/(girly-sync-caption|sync-word|voiceoverSyncText)/i.test(target)) {
    return false;
  }
  if (!/^(\[[\w:-]+="[^"]+"\]|\.[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*)$/.test(target)) {
    return false;
  }
  return true;
};

const extractAssetMotionTargets = (html: string): AssetMotionTarget[] => {
  const result: AssetMotionTarget[] = [];
  const seen = new Set<string>();
  const pattern = /<(?:div|img|video)\b([^>]*\bdata-asset-id="([^"]+)"[^>]*)>/gi;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html))) {
    const attrs = match[1] || '';
    const id = match[2];
    if (seen.has(id)) {
      continue;
    }
    seen.add(id);
    const isBackground = /\b(?:asset-video-bg|bg-layer)\b/.test(attrs);
    result.push({
      id,
      baseOpacity: extractInlineOpacity(attrs),
      isBackground,
      index: result.filter((target) => !target.isBackground).length,
    });
  }
  return result;
};

const extractInlineOpacity = (attrs: string): number => {
  const style = attrs.match(/\bstyle="([^"]*)"/i)?.[1] || '';
  const opacity = style.match(/(?:^|;)\s*opacity\s*:\s*([0-9.]+)/i)?.[1];
  if (!opacity) {
    return 1;
  }
  const parsed = Number(opacity);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return clamp(parsed, 0, 1);
};

const cssAttr = (value: string): string => value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');

const progress = (frame: number, start: number, duration: number): number =>
  clamp((frame - start) / Math.max(1, duration), 0, 1);

const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

const easeOutCubic = (value: number): number => 1 - Math.pow(1 - clamp(value, 0, 1), 3);

const easeOutBack = (value: number): number => {
  const x = clamp(value, 0, 1);
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
};

const hexToRgba = (hex: string, alpha: number): string => {
  const clean = hex.replace('#', '').trim();
  const normalized =
    clean.length === 3
      ? clean
          .split('')
          .map((char) => `${char}${char}`)
          .join('')
      : clean;
  if (!/^[0-9a-f]{6}$/i.test(normalized)) {
    return `rgba(23, 18, 15, ${clamp(alpha, 0, 1)})`;
  }
  const r = parseInt(normalized.slice(0, 2), 16);
  const g = parseInt(normalized.slice(2, 4), 16);
  const b = parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`;
};

const paperTexture = (paper: string, dark: string): string =>
  `linear-gradient(180deg, ${hexToRgba(paper, 0.98)}, ${hexToRgba(
    paper,
    0.92,
  )}), repeating-linear-gradient(0deg, ${hexToRgba(dark, 0.035)} 0, ${hexToRgba(
    dark,
    0.035,
  )} 1px, transparent 1px, transparent 9px), repeating-linear-gradient(90deg, rgba(255,255,255,0.28) 0, rgba(255,255,255,0.28) 1px, transparent 1px, transparent 13px)`;

const tapeTexture = (color: string, dark: string): string =>
  `linear-gradient(90deg, ${hexToRgba(color, 0.2)}, ${hexToRgba(color, 0.34)} 48%, ${hexToRgba(
    color,
    0.18,
  )}), repeating-linear-gradient(90deg, ${hexToRgba(dark, 0.055)} 0, ${hexToRgba(
    dark,
    0.055,
  )} 1px, transparent 1px, transparent 8px)`;

const round = (value: number): number => Math.round(value * 1000) / 1000;
