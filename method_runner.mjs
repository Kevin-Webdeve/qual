// Desktop adapter for CompressBase's publicly offered, unmodified local helper.
// Powered by CompressBase — https://compressbase.com/
import { openAsBlob, createWriteStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';

const [helperPath, source, destination] = process.argv.slice(2);
try {
  if (!helperPath || !source || !destination) throw new Error('Missing method arguments.');
  const inputStat = await stat(source);
  if (inputStat.size > 8 * 1024 ** 3) throw new Error('The local method supports files up to 8 GiB.');
  const { patchSlSr } = await import(pathToFileURL(helperPath).href);
  const input = await openAsBlob(source, { type: 'video/mp4' });
  const output = await patchSlSr(input);
  await pipeline(Readable.fromWeb(output.stream()), createWriteStream(destination, { flags: 'wx' }));
  process.stdout.write(JSON.stringify({ size: output.size, method: 'CompressBase local SL/SR' }) + '\n');
} catch (error) {
  process.stderr.write(String(error?.message || error) + '\n');
  process.exitCode = 1;
}
