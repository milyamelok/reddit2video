#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.gemini import GeminiClient  # noqa: E402


class ArtDirectionObservation(BaseModel):
    area: str
    severity: Literal["publication_ready", "minor", "major", "blocker"]
    evidence: str
    why_it_matters: str = ""
    suggested_fix_direction: str = ""


class ArtDirectionVerdict(BaseModel):
    verdict: Literal["pass", "fail"]
    overall_verdict: str
    observations: list[ArtDirectionObservation]
    blocking_design_defects: list[str]
    major_design_issues: list[str]
    minor_polish_issues: list[str]
    pattern_level_problems: list[str]
    three_highest_leverage_fixes: list[str]
    asset_quality_ignored: bool


RUBRIC_PROMPT = """Ты независимый арт-директор и внешний судья для short/reels видео.
Оцени только видимый дизайн финального ролика: композицию, арт-дирекшн, моушн, ритм, иерархию.
Не оценивай качество исходных фото/видео, вкус продукта, тему, маркетинговый текст или техническое разрешение ассетов.

Материалы:
- видео: {video_file}
- дополнительные скриншоты/contact sheets: {screens}

Не выставляй числовые оценки и не считай общий балл.
Это внешний арт-директорский verdict, а не scorecard:
- pass: можно публиковать как дизайнерски законченный reels;
- fail: перед публикацией нужно исправить blocker или major design issue.

Проверь области:
1. Композиция кадра. PASS: ясная сетка, баланс, воздух, объект и текст стоят намеренно. FAIL: случайные позиции, теснота, пустоты без смысла, неосознанные обрезки.
2. Визуальная иерархия. PASS: понятно, что читать/смотреть первым, вторым, третьим. FAIL: все спорит за внимание, заголовки/фото/детали равны по весу.
3. Типографика. PASS: шрифты, размеры, межстрочия и акценты выглядят как система. FAIL: скачущие размеры, нечитабельность, случайные переносы, дешевый шаблон.
4. Ритм монтажа. PASS: кадры сменяются с понятной энергией, нет провисаний, есть темп reels. FAIL: слишком медленно, дергано, монотонно или кадры не держат внимание.
5. Моушн и переходы. PASS: движение помогает смыслу, направляет взгляд, добавляет динамику. FAIL: эффекты ради эффектов, хаотичные зумы/слайды, движение мешает читать.
6. Арт-дирекшн. PASS: палитра, свет, рамки, тени, фактуры и настроение собраны в единый стиль. FAIL: каждый кадр как из разного шаблона, нет общего визуального языка.
7. Работа с пространством. PASS: негативное пространство используется осознанно, кадр дышит. FAIL: белые/пустые зоны выглядят незаполненными или случайными.
8. Кадровое разнообразие. PASS: есть смена масштаба, плотности, фокуса, но без развала стиля. FAIL: все кадры одинаковые или слишком разнородные.
9. Чистота и аккуратность. PASS: выравнивания, отступы, края, наложения и safe zones отполированы. FAIL: кривизны, случайные пересечения, грязные края, небрежные слои.
10. Reels-премиальность. PASS: ощущается сделанным дизайнером, есть вкус, намерение, законченный вид. FAIL: ощущение CapCut-шаблона за $2, сырость, нет дизайн-решения.

Для каждой области верни severity:
- publication_ready;
- minor;
- major;
- blocker.

Если есть blocker или major, verdict должен быть fail.
В evidence ссылайся на видимые признаки кадра/монтажа, timestamps, contact-sheet cells или повторяющийся паттерн, не на качество ассетов.
asset_quality_ignored должен быть true, если ты сознательно исключил качество исходных ассетов из оценки."""


def main() -> int:
    return asyncio.run(_amain(parse_args()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate one vertical video with Gemini against an art direction rubric.")
    parser.add_argument("--video", required=True, help="Path to the MP4 to evaluate.")
    parser.add_argument("--screens", action="append", default=[], help="Screenshot/contact-sheet path. Can be repeated.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--vertex", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        load_env_file(Path(env_file))

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"video does not exist: {video_path}")

    screen_paths = [Path(path).expanduser().resolve() for path in args.screens]
    missing = [str(path) for path in screen_paths if not path.exists()]
    if missing:
        raise SystemExit(f"screenshot does not exist: {missing[0]}")

    client = GeminiClient.from_env(model=str(args.model), vertex=bool(args.vertex))
    try:
        verdict = await client.generate_structured_multimodal(
            prompt=RUBRIC_PROMPT.format(
                video_file=str(video_path),
                screens=", ".join(str(path) for path in screen_paths) or "none",
            ),
            image_paths=[video_path, *screen_paths],
            response_model=ArtDirectionVerdict,
        )
    finally:
        await client.aclose()

    payload = verdict.model_dump()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
