"""Inline source-relative Caption JSON for Remotion's editable caption nodes."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
captions = json.loads((root/'src/motion/captions.json').read_text())
source = """// Generated from locally transcribed source audio. Regenerate with scripts/build_caption_scenes.py.
import {useVideoConfig} from 'remotion';
import {BasicCaptions} from './basic-captions';
import type {ScenarioId} from './scenarios';
export function SceneCaptions({scenario,stage}:{scenario:ScenarioId;stage:number}) {
 const {width}=useVideoConfig();
 const style={position:'absolute' as const,bottom:52,left:32,scale:.5,transformOrigin:'bottom left'};
"""
for scenario, clips in captions.items():
    for i, clip in enumerate(clips):
        source += f' if (scenario === "{scenario}" && stage === {i}) return <BasicCaptions name="{scenario} beat {i+1} captions" width={{(width-64)*2}} style={{style}} combineTokensWithinMilliseconds={{1600}} captions={{{json.dumps(clip)}}}/>;\n'
source += ' return null;\n}\n'
(root/'src/motion/SceneCaptions.tsx').write_text(source)
