import { AbsoluteFill, Sequence, staticFile, useCurrentFrame, useVideoConfig, interpolate, spring, Easing } from 'remotion';
import {Audio} from '@remotion/media';
import {useWindowedAudioData, visualizeAudio} from '@remotion/media-utils';
import {loadFont} from '@remotion/fonts';
import {AudioLines, Check, CalendarDays, MessageCircle, ArrowUpRight, FileText, ShieldCheck, Users} from 'lucide-react';
import type {CSSProperties, ReactNode} from 'react';
import {scenarios, type ScenarioId} from './scenarios';
import narration from './narration-manifest.json';
import {SceneCaptions} from './SceneCaptions';

void loadFont({family:'Manrope',url:staticFile('fonts/manrope.woff2'),weight:'200 800'});
void loadFont({family:'DM Sans',url:staticFile('fonts/dm-sans.woff2'),weight:'100 1000'});
const ease={extrapolateLeft:'clamp',extrapolateRight:'clamp',easing:Easing.bezier(.16,1,.3,1)} as const;
const ink='#173b2b', mint='#c8efcf';
const answers = {
 support: 'Yes! Team day passes include workspace, Wi-Fi, and meeting-room access. How many people are joining?',
 voice: 'Visitor parking is beside the main entrance. Reception will welcome you for your tour.',
 leads: 'When are you moving in? May our team follow up about available spaces?',
 booking: 'There’s a tour at 10:00 AM. Shall I book that time for you?',
};
const panel:CSSProperties={background:'#fff',border:'1px solid #bfd3c4',borderRadius:22,padding:26,boxShadow:'0 20px 60px #0e302310'};

function Reveal({children,delay=0,style={}}:{children:ReactNode;delay?:number;style?:CSSProperties}) {
 const frame=useCurrentFrame(); const {fps}=useVideoConfig();
 return <div style={{...style,opacity:interpolate(frame-delay,[0,.4*fps],[0,1],ease),translate:`0 ${interpolate(frame-delay,[0,.7*fps],[28,0],ease)}px`}}>{children}</div>;
}
function Title({stage}:{stage:number}) {
 const frame=useCurrentFrame();const {fps,width}=useVideoConfig();
 const title=['Start with a hello.','Make it personal.','Move forward.'][stage];
 return <h2 style={{fontFamily:'Manrope',fontSize:width<700?43:60,lineHeight:1.08,letterSpacing:-2.8,fontWeight:700,margin:0}}>{title.split(' ').map((word,i)=><span key={word} style={{color:ink,display:'inline-block',marginRight:'.22em',opacity:interpolate(frame-i*3,[0,.35*fps],[0,1],ease),translate:`0 ${interpolate(frame-i*3,[0,.5*fps],[25,0],ease)}px`}}>{word}</span>)}</h2>;
}
function Spectrum({src}:{src:string}) {
 const frame=useCurrentFrame();const {fps}=useVideoConfig();
 const {audioData,dataOffsetInSeconds}=useWindowedAudioData({src:staticFile(src),frame,fps,windowInSeconds:10});
 const values=audioData?visualizeAudio({fps,frame,audioData,numberOfSamples:32,optimizeFor:'speed',dataOffsetInSeconds}):Array(32).fill(0);
 return <div style={{display:'flex',alignItems:'center',gap:5,height:70,justifyContent:'center'}}>{values.map((value,i)=><div key={i} style={{width:7,height:Math.max(4,Math.min(65,value*230)),background:ink,borderRadius:5}}/>)}</div>;
}
function QuestionScene({scenario}:{scenario:ScenarioId}) {
 const s=scenarios[scenario];const {width,fps}=useVideoConfig();const mobile=width<700;
 return <div style={{display:'grid',gap:20}}>
  <Reveal style={{...panel,background:ink,color:'#fff',maxWidth:mobile?'100%':'86%',marginLeft:'auto'}} delay={fps*.5}>
   <div style={{fontSize:16,color:mint,marginBottom:15,display:'flex',gap:10,alignItems:'center'}}><MessageCircle size={20}/> A VISITOR ASKS</div>
   <p style={{fontSize:mobile?29:32,lineHeight:1.35,margin:0}}>{s.question}</p>
  </Reveal>
  <Reveal delay={fps*1.6} style={{display:'flex',alignItems:'center',gap:14,paddingLeft:16}}><div style={{width:48,height:48,borderRadius:16,background:mint,display:'grid',placeItems:'center'}}><AudioLines/></div><div style={{fontSize:18}}>Your Phirmy agent<div style={{fontSize:14,color:'#476750',marginTop:5}}>Listening. Finding the right context.</div></div></Reveal>
 </div>;
}
function AnswerScene({scenario,src}:{scenario:ScenarioId;src:string}) {
 const s=scenarios[scenario];const {fps,width}=useVideoConfig();const mobile=width<700;
 return <div style={{display:'grid',gap:16}}>
  <Reveal style={{...panel}} delay={fps*.25}>
   <div style={{display:'flex',gap:10,alignItems:'center',color:'#3b684b',fontSize:16,marginBottom:16}}><ShieldCheck size={22}/>{scenario==='booking'?'CHECKED AGAINST YOUR CALENDAR':'GROUNDED IN YOUR KNOWLEDGE'}</div>
   {scenario==='voice' && <Spectrum src={src}/>}
   <p style={{fontSize:mobile?30:34,lineHeight:1.42,margin:0}}>{answers[scenario]}</p>
  </Reveal>
  <Reveal delay={fps*1.2} style={{display:'flex',gap:12,alignItems:'center',fontSize:16,color:'#3b684b'}}><FileText size={20}/>{s.source}<Check size={18}/></Reveal>
  {scenario==='booking' && <Reveal delay={fps*2} style={{display:'flex',gap:10}}>{['9:00 AM','10:00 AM','11:00 AM'].map((time,i)=><div key={time} style={{padding:'12px 18px',borderRadius:12,background:i===1?ink:'#e2ece3',color:i===1?'white':'#4b6252',fontSize:18}}>{time}</div>)}</Reveal>}
 </div>;
}
function OutcomeScene({scenario}:{scenario:ScenarioId}) {
 const s=scenarios[scenario];const frame=useCurrentFrame();const {fps,width}=useVideoConfig();
 const Icon=scenario==='booking'?CalendarDays:scenario==='leads'?Users:Check;
 return <div>
  <div style={{...panel,background:ink,color:'white',position:'relative'}}>
   <div style={{width:58,height:58,display:'grid',placeItems:'center',background:mint,color:ink,borderRadius:18,marginBottom:18,scale:spring({fps,frame,config:{damping:18,stiffness:130}})}}><Icon size={30}/></div>
   <Reveal delay={fps*.3}><h3 style={{fontSize:width<700?32:36,lineHeight:1.25,margin:'0 0 18px',fontWeight:600}}>{s.result}</h3></Reveal>
   <Reveal delay={fps*1} style={{fontSize:18,lineHeight:1.5,color:mint}}>{s.detail}</Reveal>
  </div>
  <Reveal delay={fps*2} style={{fontSize:18,display:'flex',alignItems:'center',gap:10,marginTop:22}}><ArrowUpRight size={22}/>Built by you. Made for people.</Reveal>
 </div>;
}
function Scene({scenario,stage}:{scenario:ScenarioId;stage:number}) {
 const {width,fps}=useVideoConfig();const mobile=width<700;const clip=narration[scenario].clips[stage];
 return <AbsoluteFill style={{background:stage===1?'#f5f7ee':'#edf5ee',padding:mobile?32:42,color:ink,fontFamily:'DM Sans',overflow:'hidden'}}>
  <Audio src={staticFile(clip.src)}/>
  <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',fontSize:mobile?15:16,letterSpacing:2,fontWeight:600}}><span>PHIRMY / {scenarios[scenario].label.toUpperCase()}</span><span>0{stage+1}</span></div>
  <div style={{display:'grid',gridTemplateColumns:mobile?'1fr':'.82fr 1.3fr',gap:mobile?28:40,alignItems:'center',flex:1,paddingBottom:mobile?110:100,paddingTop:28}}>
   <div><Title stage={stage}/>{!mobile && <Reveal delay={fps*.8} style={{fontSize:17,lineHeight:1.6,marginTop:24,color:'#42664e'}}>A small conversation.<br/>A new possibility.</Reveal>}</div>
   {stage===0?<QuestionScene scenario={scenario}/>:stage===1?<AnswerScene scenario={scenario} src={clip.src}/>:<OutcomeScene scenario={scenario}/>}
  </div>
  <SceneCaptions scenario={scenario} stage={stage}/>
  <div style={{position:'absolute',bottom:18,left:32,right:32,display:'flex',justifyContent:'space-between',fontSize:12,letterSpacing:1,color:'#476750'}}><span>ILLUSTRATED DEMO · AI NARRATION</span><span>BUILD. SCALE. TOGETHER.</span></div>
 </AbsoluteFill>;
}
export function ConversationFilm({scenario='support'}:{scenario?:ScenarioId}) {
 const {fps}=useVideoConfig(); const clips=narration[scenario].clips;
 return <AbsoluteFill>
  <Sequence name="01 — A visitor connects" from={0} durationInFrames={Math.round(clips[0].duration/30*fps)}><Scene scenario={scenario} stage={0}/></Sequence>
  <Sequence name="02 — Knowledge becomes conversation" from={Math.round(clips[1].from/30*fps)} durationInFrames={Math.round(clips[1].duration/30*fps)}><Scene scenario={scenario} stage={1}/></Sequence>
  <Sequence name="03 — A useful next step" from={Math.round(clips[2].from/30*fps)} durationInFrames={Math.round(clips[2].duration/30*fps)}><Scene scenario={scenario} stage={2}/></Sequence>
 </AbsoluteFill>;
}
