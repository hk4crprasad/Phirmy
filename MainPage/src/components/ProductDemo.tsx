import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Player, type PlayerRef } from "@remotion/player";
import {
  AudioLines,
  CalendarDays,
  LockKeyhole,
  MessageCircle,
  Pause,
  Play,
  RotateCcw,
  Users,
  Volume2,
  VolumeX,
} from "lucide-react";
import { ConversationFilm } from "../motion/ConversationFilm";
import { scenarios, type ScenarioId } from "../motion/scenarios";

const FPS = 30;
import narration from "../motion/narration-manifest.json";
const tabs = [
  { id: "support", icon: MessageCircle },
  { id: "voice", icon: AudioLines },
  { id: "leads", icon: Users },
  { id: "booking", icon: CalendarDays },
] as const;

export default function ProductDemo({
  requested,
  ambientPaused,
}: {
  requested: number;
  ambientPaused: boolean;
}) {
  const [scenario, setScenario] = useState<ScenarioId>("support");
  const [compact, setCompact] = useState(false);
  const [muted, setMuted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState(0);
  const player = useRef<PlayerRef>(null);
  const container = useRef<HTMLDivElement>(null);
  const previousRequest = useRef(0);
  const pendingPlay = useRef(false);
  const visible = useRef(false);
  const data = scenarios[scenario];
  const track = narration[scenario];
  const DURATION = track.duration;
  const seconds = Math.ceil(DURATION / FPS);
  const activeClip = track.clips.find(c => frame >= c.from && frame < c.from + c.duration) || track.clips[0];
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(([entry]) => setCompact(entry.contentRect.width < 650));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const p = player.current;
    if (!p) return;
    const update = ({ detail }: { detail: { frame: number } }) =>
      setFrame(detail.frame);
    const play = () => setPlaying(true);
    const pause = () => setPlaying(false);
    p.addEventListener("frameupdate", update);
    p.addEventListener("play", play);
    p.addEventListener("pause", pause);
    p.addEventListener("ended", pause);
    const hidden = () => {
      if (document.hidden) p.pause();
    };
    document.addEventListener("visibilitychange", hidden);
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible.current =
          entry.isIntersecting && entry.intersectionRatio >= 0.1;
        if (!visible.current) p.pause();
        else if (pendingPlay.current && !document.hidden) {
          pendingPlay.current = false;
          p.play();
        }
      },
      { threshold: 0.1 },
    );
    if (container.current) observer.observe(container.current);
    return () => {
      p.removeEventListener("frameupdate", update);
      p.removeEventListener("play", play);
      p.removeEventListener("pause", pause);
      p.removeEventListener("ended", pause);
      document.removeEventListener("visibilitychange", hidden);
      observer.disconnect();
    };
  }, []);
  useEffect(() => {
    if (ambientPaused) player.current?.pause();
  }, [ambientPaused]);
  useEffect(() => {
    if (requested > previousRequest.current) {
      previousRequest.current = requested;
      player.current?.seekTo(0);
      // A deliberate Watch action may play even when ambient/reduced motion is off.
      pendingPlay.current = true;
      if (visible.current && !document.hidden) {
        pendingPlay.current = false;
        player.current?.play();
      }
    }
  }, [requested]);
  function choose(id: ScenarioId) {
    pendingPlay.current = false;
    player.current?.pause();
    setScenario(id);
    player.current?.seekTo(0);
    setFrame(0);
  }
  function keyTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft")
      next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    choose(tabs[next].id);
    document.getElementById(`tab-${tabs[next].id}`)?.focus();
  }
  function toggle() {
    pendingPlay.current = false;
    if (playing) player.current?.pause();
    else {
      if (frame >= DURATION - 1) player.current?.seekTo(0);
      player.current?.play();
    }
  }
  return (
    <div ref={container}>
      <div
        className="demo-tabs"
        role="tablist"
        aria-label="Product walkthrough scenarios"
      >
        {tabs.map(({ id, icon: Icon }, i) => (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            tabIndex={id === scenario ? 0 : -1}
            aria-selected={id === scenario}
            aria-controls="demo-panel"
            onClick={() => choose(id)}
            onKeyDown={(event) => keyTabs(event, i)}
          >
            <Icon size={15} />
            {scenarios[id].label}
          </button>
        ))}
      </div>
      <div id="demo-panel" role="tabpanel" aria-labelledby={`tab-${scenario}`}>
        <div className="demo-shell">
          <div className="demo-browser-bar">
            <div className="window-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <span>
              <LockKeyhole size={9} /> your-business.com
            </span>
            <span className="demo-sample">A PHIRMY POSSIBILITY</span>
          </div>
          <div className="demo-screen" aria-hidden="true" style={{aspectRatio: compact ? "600 / 900" : "1000 / 640"}}>
            {frame === 0 && !playing && <div className="demo-cover"><span className="eyebrow">PHIRMY · ILLUSTRATED WALKTHROUGH</span><div className="demo-cover-icon"><MessageCircle size={30} strokeWidth={1.3}/></div><h3>A customer has a question.<br/><em>Let’s see what happens next.</em></h3><p>Press play to explore {data.label.toLowerCase()}.</p><span className="demo-cover-note">Sample conversations · no live call</span></div>}
            <Player
              ref={player}
              component={ConversationFilm}
              inputProps={{ scenario }}
              durationInFrames={DURATION}
              compositionWidth={compact ? 600 : 1000}
              compositionHeight={compact ? 900 : 640}
              fps={FPS}
              controls={false}
              initiallyMuted={false}
              clickToPlay={false}
              doubleClickToFullscreen={false}
              spaceKeyToPlayOrPause={false}
              style={{ width: "100%" }}
            />
          </div>
          <div className="spoken-caption sr-only" aria-label="Narration caption">{activeClip.text}</div>
          <div className="player-controls">
            <button
              onClick={toggle}
              aria-label={playing ? "Pause walkthrough" : "Play walkthrough"}
            >
              {playing ? (
                <Pause size={16} />
              ) : (
                <Play size={16} fill="currentColor" />
              )}
            </button>
            <button
              onClick={() => {
                player.current?.seekTo(0);
                setFrame(0);
              }}
              aria-label="Restart walkthrough"
            >
              <RotateCcw size={15} />
            </button>
            <span className="player-time">
              0:{String(Math.floor(frame / FPS)).padStart(2, "0")}
            </span>
            <input
              type="range"
              min={0}
              max={DURATION - 1}
              value={frame}
              aria-label="Walkthrough timeline"
              aria-valuetext={`${(frame / FPS).toFixed(1)} of ${seconds} seconds`}
              onChange={(event) => {
                const next = Number(event.target.value);
                player.current?.seekTo(next);
                setFrame(next);
              }}
            />
            <span className="player-time">0:{String(seconds).padStart(2, "0")}</span>
            <button aria-label={muted ? "Unmute narration" : "Mute narration"} onClick={() => { if (muted) player.current?.unmute(); else player.current?.mute(); setMuted(!muted); }}>{muted ? <VolumeX size={18} /> : <Volume2 size={18} />}</button>
          </div>
        </div>
        <div className="demo-caption">
          <div>
            <h3>{data.headline}</h3>
            <p>{data.description}</p>
          </div>
          <span>{data.outcome}</span>
        </div>
        <details className="tour-transcript">
          <summary>Read the walkthrough</summary>
          <ol>
            {data.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <p className="narration-transcript">{track.clips.map(c => c.text).join(" ")}</p>
        </details>
      </div>
    </div>
  );
}
