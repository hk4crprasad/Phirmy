"use client";
import { useEffect, useRef, useState } from "react";
import { Player, type PlayerRef } from "@remotion/player";
import AgentJourney from "./agent-journey";

export default function ProductTourPlayer() {
  const player = useRef<PlayerRef>(null);
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => {
      setReduced(media.matches);
      if (media.matches) player.current?.pause();
    };
    const visibility = () => {
      if (document.hidden) player.current?.pause();
    };
    update();
    media.addEventListener("change", update);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      media.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);
  return (
    <>
      <div className="tour-player" aria-label="Product walkthrough animation">
        <Player
          ref={player}
          component={AgentJourney}
          durationInFrames={480}
          fps={30}
          compositionWidth={1000}
          compositionHeight={600}
          initialFrame={30}
          controls
          autoPlay={false}
          loop={false}
          showVolumeControls={false}
          style={{ width: "100%" }}
        />
      </div>
      <div className="tour-chapters" aria-label="Walkthrough chapters">
        {["Knowledge", "Agent", "Test", "Publish"].map((chapter, index) => (
          <button
            key={chapter}
            className="btn small"
            aria-label={"Show " + chapter + " chapter"}
            onClick={() => {
              player.current?.pause();
              player.current?.seekTo(index * 120 + 30);
            }}
          >
            {index + 1}
            <span>{chapter}</span>
          </button>
        ))}
      </div>
      <p className="tour-caption">
        A 16-second illustrated walkthrough. Press play or use the timeline to
        explore.{" "}
        {reduced && "Automatic motion is off for your device preference. "}Phone
        and provider connections require their own activation.
      </p>
      <details className="tour-transcript">
        <summary>Read the walkthrough</summary>
        <ol>
          <li>Connect your website or upload business knowledge.</li>
          <li>
            Create an agent. Add instructions, tools and conversation variables.
          </li>
          <li>Publish a version and test the conversation in your browser.</li>
          <li>
            Connect the published agent to your website or an activated
            platform.
          </li>
        </ol>
      </details>
    </>
  );
}
