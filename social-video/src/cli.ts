import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, statSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseReelInput, type ReelKind } from './contracts';

type CliOptions = Readonly<{
  inputPath: string;
  outputPath: string;
  workdir: string;
  pro: boolean;
}>;

function usage(): never {
  throw new Error('usage: render --input <json> --output <mp4> [--workdir <dir>] [--pro]');
}

function inside(child: string, parent: string): boolean {
  const relativePath = relative(parent, child);
  return relativePath === '' || (relativePath !== '..' && !relativePath.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) && !isAbsolute(relativePath));
}

export function parseCliArgs(args: readonly string[]): CliOptions {
  const values = new Map<string, string>();
  let pro = false;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === '--pro') {
      pro = true;
      continue;
    }
    if (!arg.startsWith('--') || index + 1 >= args.length || args[index + 1].startsWith('--')) usage();
    values.set(arg.slice(2), args[index + 1]);
    index += 1;
  }
  if (!values.has('input') || !values.has('output')) usage();
  const outputPath = resolve(values.get('output')!);
  const workdir = resolve(values.get('workdir') ?? dirname(outputPath));
  const inputPath = resolve(values.get('input')!);
  if (!inside(inputPath, workdir) || !inside(outputPath, workdir)) {
    throw new Error('input and output must stay inside workdir');
  }
  return { inputPath, outputPath, workdir, pro };
}

function render(options: CliOptions): void {
  if (!existsSync(options.inputPath) || !statSync(options.inputPath).isFile()) throw new Error('input JSON is missing');
  mkdirSync(options.workdir, { recursive: true });
  const input = parseReelInput(JSON.parse(readFileSync(options.inputPath, 'utf8')));
  const temporaryOutput = `${options.outputPath}.partial`;
  rmSync(temporaryOutput, { force: true });
  const composition = input.kind === 'results' ? 'ReyTacoResultsReel' : 'ReyTacoTeaserReel';
  const frames = '0-299';
  const binary = resolve('node_modules/.bin', process.platform === 'win32' ? 'remotion.cmd' : 'remotion');
  const args = [
    'render', 'src/Root.tsx', composition, temporaryOutput,
    `--props=${options.inputPath}`,
    '--codec=h264', '--pixel-format=yuv420p', `--frames=${frames}`, '--every=1',
  ];
  if (options.pro) args.push('--pro');
  const result = spawnSync(binary, args, { cwd: resolve('.'), stdio: 'inherit' });
  if (result.error || result.status !== 0) {
    rmSync(temporaryOutput, { force: true });
    throw new Error('Remotion render failed');
  }
  const probe = spawnSync('ffprobe', [
    '-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=codec_name,width,height,pix_fmt,duration',
    '-of', 'json', temporaryOutput,
  ], { encoding: 'utf8' });
  let stream: Record<string, unknown> | undefined;
  try {
    const parsed = JSON.parse(probe.stdout ?? '') as { streams?: Record<string, unknown>[] };
    stream = parsed.streams?.[0];
  } catch {
    stream = undefined;
  }
  const duration = Number(stream?.duration);
  if (
    probe.error
    || probe.status !== 0
    || stream?.codec_name !== 'h264'
    || stream?.width !== 1080
    || stream?.height !== 1920
    || stream?.pix_fmt !== 'yuv420p'
    || !Number.isFinite(duration)
    || duration < 8
    || duration > 15
  ) {
    rmSync(temporaryOutput, { force: true });
    throw new Error('FFprobe validation failed');
  }
  renameSync(temporaryOutput, options.outputPath);
}

export function runCli(args: readonly string[]): number {
  try {
    render(parseCliArgs(args));
    return 0;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('invalid reel input')) return 2;
    process.stderr.write(`${error instanceof Error ? error.message : 'render failed'}\n`);
    return 1;
  }
}

if (process.argv[1]?.endsWith('cli.ts')) process.exitCode = runCli(process.argv.slice(2));
