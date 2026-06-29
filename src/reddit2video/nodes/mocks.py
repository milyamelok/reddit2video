from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reddit2video.models import (
    ContextBundle,
    DesignKit,
    GeneratedScript,
    HtmlGenerationResult,
    ImageParseResult,
    NodeSpec,
    RedditThread,
    RemotionProjectResult,
    RenderResult,
    VoiceoverResult,
)
from reddit2video.nodes.base import BaseNode


@dataclass(frozen=True)
class HtmlGenerationRequest:
    script: GeneratedScript
    voiceover: VoiceoverResult | None = None
    mode: str = "jinja2_template"


@dataclass(frozen=True)
class ImageParseRequest:
    query: str
    limit: int = 10
    provider: str = "google_images"


@dataclass(frozen=True)
class RemotionTransferRequest:
    html_path: str
    project_dir: str = "outputs/remotion"


@dataclass(frozen=True)
class RemotionRenderRequest:
    project_dir: str
    composition_id: str = "RedditVideo"
    output_path: str = "outputs/video.mp4"


class PrepareContextBundleNode(BaseNode[RedditThread, ContextBundle]):
    spec = NodeSpec(
        step="step-2",
        name="prepare_context_bundle",
        description="Prepare thread and design-kit context bundle.",
        mocked=True,
    )

    def run(self, node_input: RedditThread) -> ContextBundle:
        return ContextBundle(
            thread=node_input,
            design_kit=DesignKit(
                name="mock-default",
                colors=["#111111", "#f5f5f5", "#ff4500"],
                typography={"heading": "Inter", "body": "Inter"},
                motion={"pace": "fast", "caption_style": "karaoke"},
            ),
            notes=["Mock context bundle. Wire real design kit selection here."],
        )


class GeminiScriptNode(BaseNode[ContextBundle, GeneratedScript]):
    spec = NodeSpec(
        step="step-3",
        name="gemini_script",
        description="Generate video script with Gemini.",
        mocked=True,
    )

    def run(self, node_input: ContextBundle) -> GeneratedScript:
        title = node_input.thread.post.title
        beats = [
            f"Hook from Reddit post: {title}",
            "Summarize the conflict or key question.",
            "Bring in top comments as escalating reactions.",
            "End with a short punchline or takeaway.",
        ]
        return GeneratedScript(
            title=title,
            beats=beats,
            narration="\n".join(beats),
            metadata={"mock": True, "source_post": node_input.thread.post.id},
        )


class ElevenLabsVoiceNode(BaseNode[GeneratedScript, VoiceoverResult]):
    spec = NodeSpec(
        step="step-4",
        name="elevenlabs_voice",
        description="Generate voiceover through ElevenLabs API.",
        mocked=True,
    )

    def run(self, node_input: GeneratedScript) -> VoiceoverResult:
        return VoiceoverResult(
            audio_path="outputs/mock_voiceover.mp3",
            duration_seconds=max(8.0, len(node_input.narration.split()) / 2.5),
            voice_id="mock-voice",
            transcript=node_input.narration,
            metadata={"mock": True},
        )


class HtmlGenerationNode(BaseNode[HtmlGenerationRequest, HtmlGenerationResult]):
    spec = NodeSpec(
        step="step-5",
        name="html_generation",
        description="Generate index.html via Jinja2 template or Gemini full HTML.",
        mocked=True,
    )

    def run(self, node_input: HtmlGenerationRequest) -> HtmlGenerationResult:
        safe_mode = "gemini_full_html" if node_input.mode == "gemini_full_html" else "jinja2_template"
        return HtmlGenerationResult(
            mode=safe_mode,
            html_path=f"outputs/{safe_mode}/index.html",
            assets=[],
            metadata={"mock": True, "script_title": node_input.script.title},
        )


class ImageParseNode(BaseNode[ImageParseRequest, ImageParseResult]):
    spec = NodeSpec(
        step="step-6",
        name="image_parse",
        description="Find images/GIFs through Bright Data-backed scrapers.",
        mocked=True,
    )

    def run(self, node_input: ImageParseRequest) -> ImageParseResult:
        images = [
            {
                "url": f"https://example.com/mock-image-{index}.jpg",
                "source": node_input.provider,
                "query": node_input.query,
            }
            for index in range(1, node_input.limit + 1)
        ]
        return ImageParseResult(
            query=node_input.query,
            images=images,
            metadata={"mock": True, "provider": node_input.provider},
        )


class RemotionTransferNode(BaseNode[RemotionTransferRequest, RemotionProjectResult]):
    spec = NodeSpec(
        step="step-7a",
        name="remotion_transfer",
        description="Convert index.html into Remotion-supported TSX files.",
        mocked=True,
    )

    def run(self, node_input: RemotionTransferRequest) -> RemotionProjectResult:
        project_dir = Path(node_input.project_dir)
        return RemotionProjectResult(
            project_dir=str(project_dir),
            tsx_files=[
                str(project_dir / "src" / "Root.tsx"),
                str(project_dir / "src" / "RedditVideo.tsx"),
            ],
            metadata={"mock": True, "source_html": node_input.html_path},
        )


class RemotionRenderNode(BaseNode[RemotionRenderRequest, RenderResult]):
    spec = NodeSpec(
        step="step-7b",
        name="remotion_render",
        description="Render Remotion project into video.",
        mocked=True,
    )

    def run(self, node_input: RemotionRenderRequest) -> RenderResult:
        return RenderResult(
            video_path=node_input.output_path,
            duration_seconds=30.0,
            metadata={
                "mock": True,
                "project_dir": node_input.project_dir,
                "composition_id": node_input.composition_id,
            },
        )

