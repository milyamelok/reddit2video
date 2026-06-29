import {spawnSync} from 'node:child_process';
import {existsSync, mkdirSync, readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const projectDir = dirname(here);
const repoRoot = dirname(projectDir);
const bundle = JSON.parse(readFileSync(join(projectDir, 'src/render-bundle.generated.json'), 'utf8'));
const outDir = process.env.REMOTION_OUT_DIR || join(repoRoot, 'outputs/videos');
const only = process.env.POST_ID || '';
const limit = Number(process.env.LIMIT || '0');
const force = process.env.FORCE === '1';
const renderConcurrency = process.env.REMOTION_RENDER_CONCURRENCY || '2';

mkdirSync(outDir, {recursive: true});

const items = bundle.items
  .filter((item) => item.status === 'pass')
  .filter((item) => !only || item.post_id === only)
  .slice(0, limit > 0 ? limit : undefined);

for (const [index, item] of items.entries()) {
  const output = join(outDir, `${String(index + 1).padStart(2, '0')}_${item.post_id}.mp4`);
  if (!force && existsSync(output)) {
    console.log(`Skipping existing ${output}`);
    continue;
  }
  console.log(`Rendering ${item.composition_id} -> ${output}`);
  const result = spawnSync(
    process.platform === 'win32' ? 'npx.cmd' : 'npx',
    ['remotion', 'render', 'src/index.ts', item.composition_id, output, `--concurrency=${renderConcurrency}`],
    {cwd: projectDir, stdio: 'inherit', env: process.env},
  );
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}
