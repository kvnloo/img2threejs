#!/usr/bin/env node
/** Package the already-tested Hinge Lab into one portable offline HTML file.
 * Preserves photo attribution and both source/library license notices.
 */
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const output = resolve(process.env.HINGE_LAB_OUTPUT || 'hinge-lab-dist');
const read = path => readFileSync(join(output, path), 'utf8');
for (const path of ['index.html', 'bundle.js', 'reference.jpg',
  'THREE_LICENSE.txt', 'IMG2THREEJS_LICENSE.txt', 'manifest.json']) {
  if (!existsSync(join(output, path))) throw new Error('missing package input ' + path);
}
const manifest = JSON.parse(read('manifest.json'));
const photo = readFileSync(join(output, 'reference.jpg'));
const sha = createHash('sha256').update(photo).digest('hex');
if (sha !== manifest.reference.sha256) {
  throw new Error('reference image failed manifest SHA-256 verification');
}
const photo64 = photo.toString('base64');
const bundle = read('bundle.js');
const html = read('index.html');
const externalImage = 'src="reference.jpg"';
const externalScript = '<script src="bundle.js" defer></script>';
if (html.split(externalImage).length !== 2 ||
    html.split(externalScript).length !== 2) {
  throw new Error('unexpected lab HTML template');
}
const escapedBundle = bundle.replace(/<\/script/gi, '<\\/script');
const escaped = text => text.replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const notices = ['THREE_LICENSE.txt','IMG2THREEJS_LICENSE.txt'].map(name =>
  name + '\n' + read(name)).join('\n\n');
const noticeSection =
  '<details style="padding:12px 20px;max-height:180px;overflow:auto">' +
  '<summary>Bundled library and repository license notices</summary>' +
  '<pre style="white-space:pre-wrap;font-size:11px">' +
  escaped(notices) + '</pre></details>';
// Use a replacement callback so minified bundle text is copied literally.
const single = html.replace(externalImage,
    () => 'src="data:image/jpeg;base64,' + photo64 + '"')
  .replace(externalScript, () => '<script>\n' + escapedBundle + '\n</script>')
  .replace('</body>', () => noticeSection + '\n</body>');
if (single.includes(externalImage) ||
    single.includes(externalScript) ||
    !single.includes('data:image/jpeg;base64,') ||
    single.includes('src="bundle.js"')) {
  throw new Error('single HTML still has unresolved local runtime assets');
}
const path = join(output,'Hinge-Lab-Standalone.html');
writeFileSync(path,single);
const finalHash = createHash('sha256').update(single).digest('hex');
console.log('HINGE_SINGLE_FILE_PASS:',JSON.stringify({
  bytes:Buffer.byteLength(single), sha256:finalHash,
  referenceSha256:sha, embedsBundle:true,
  embedsReference:true, embedsLicenses:true,
  output:path,
}));
