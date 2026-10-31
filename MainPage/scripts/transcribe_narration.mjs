import {canUseWhisperWebGpu, downloadWhisperModel, loadWhisperModel, transcribe, toCaptions} from '@remotion/whisper-webgpu';
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
const support = await canUseWhisperWebGpu();
if (!support.supported) throw new Error(support.detailedReason);
const model = 'small.en';
await downloadWhisperModel({model});
const handle = await loadWhisperModel({model});
const manifest = JSON.parse(readFileSync('src/motion/narration-manifest.json','utf8'));
const result = {};
try {
for (const [scenario, tour] of Object.entries(manifest)) {
  result[scenario] = [];
  for (const clip of tour.clips) {
    const pcm = execFileSync('ffmpeg',['-v','error','-i','public/'+clip.src,'-f','f32le','-ar','16000','-ac','1','pipe:1']);
    const channelWaveform = new Float32Array(pcm.buffer.slice(pcm.byteOffset,pcm.byteOffset+pcm.byteLength));
    const output = await transcribe({channelWaveform,model});
    const {captions} = toCaptions({whisperWebGpuOutput:output});
    result[scenario].push(captions);
    console.log(scenario, clip.src, captions.map(c=>c.text).join(''));
  }
}
writeFileSync('src/motion/captions.json',JSON.stringify(result,null,2)+'\n');
} finally { await handle[Symbol.asyncDispose](); }
