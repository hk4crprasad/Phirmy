"use client";

import {
  AbsoluteFill,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  AudioLines,
  Globe,
  FileText,
  Braces,
  Wrench,
  Check,
  Phone,
  Code2,
  ArrowRight,
} from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

const card: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 22,
  background: "var(--white)",
  padding: 30,
  width: 730,
  minHeight: 260,
  boxShadow: "0 16px 50px #00000006",
};
const label: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  color: "var(--muted)",
  fontSize: 18,
  marginBottom: 25,
};

function Chapter({
  number,
  title,
  subtitle,
  children,
}: {
  number: number;
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill
      style={{
        alignItems: "center",
        paddingTop: 100,
        opacity: interpolate(
          frame,
          [0, 0.4 * fps, 3.55 * fps, 4 * fps - 1],
          [0, 1, 1, 0],
          { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
        ),
        translate: interpolate(frame, [0, 0.6 * fps], ["0px 12px", "0px 0px"], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      }}
    >
      <div
        style={{
          fontSize: 13,
          color: "var(--muted)",
          letterSpacing: 2,
          marginBottom: 13,
        }}
      >
        0{number} / YOUR FIRST AGENT
      </div>
      <h2
        style={{
          fontSize: 37,
          letterSpacing: -1.4,
          fontWeight: 500,
          margin: "0 0 10px",
        }}
      >
        {title}
      </h2>
      <p style={{ fontSize: 18, color: "var(--muted)", margin: "0 0 30px" }}>
        {subtitle}
      </p>
      {children}
    </AbsoluteFill>
  );
}

function KnowledgeCard() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={card}>
      <div style={label}>
        <Globe size={21} />
        Business knowledge
        <span
          style={{ marginLeft: "auto", fontSize: 13, color: "var(--success)" }}
        >
          Your sources
        </span>
      </div>
      <div style={{ display: "flex", gap: 25, alignItems: "center" }}>
        <div
          style={{
            width: 104,
            height: 118,
            borderRadius: 15,
            display: "grid",
            placeItems: "center",
            background: "var(--surface-soft)",
            color: "var(--secondary)",
          }}
        >
          <FileText size={45} strokeWidth={1.2} />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 22, marginBottom: 20 }}>
            your-business.com
          </div>
          {[96, 75, 86].map((width, index) => (
            <div
              key={width}
              style={{
                height: 8,
                marginTop: 13,
                borderRadius: 8,
                background: "var(--surface-active)",
                width: `${width}%`,
                scale: `${interpolate(frame, [0.3 * fps + index * 4, 1.4 * fps + index * 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} 1`,
                transformOrigin: "left center",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentCard() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={card}>
      <div style={label}>
        <AudioLines size={21} />
        Agent studio
        <span style={{ marginLeft: "auto", fontSize: 13 }}>Draft</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            background: "var(--surface-soft)",
          }}
        >
          <AudioLines size={28} />
        </div>
        <div>
          <strong style={{ fontSize: 23, fontWeight: 500 }}>
            Your assistant
          </strong>
          <p style={{ fontSize: 18, color: "var(--muted)", marginTop: 7 }}>
            {"Hello {{customer_name}}. How can I help?"}
          </p>
        </div>
      </div>
      <div style={{ display: "flex", gap: 13, marginTop: 30 }}>
        {[
          { Icon: FileText, title: "Knowledge" },
          { Icon: Wrench, title: "Tools" },
          { Icon: Braces, title: "Variables" },
        ].map(({ Icon, title }, index) => (
          <div
            key={title}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: "10px 15px",
              fontSize: 16,
              opacity: interpolate(
                frame,
                [0.3 * fps + index * 6, 0.8 * fps + index * 6],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              ),
            }}
          >
            <Icon size={17} />
            {title}
          </div>
        ))}
      </div>
    </div>
  );
}

function ConversationCard() {
  const frame = useCurrentFrame();
  return (
    <div style={card}>
      <div style={label}>
        <AudioLines size={21} />
        Test the conversation
        <span style={{ marginLeft: "auto", fontSize: 13 }}>
          Example preview
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          height: 56,
          justifyContent: "center",
          marginBottom: 20,
        }}
      >
        {Array.from({ length: 31 }, (_, i) => (
          <i
            key={i}
            style={{
              width: 4,
              borderRadius: 5,
              height:
                10 +
                Math.abs(Math.sin(frame * 0.09 + i * 0.7)) *
                  (32 - Math.abs(15 - i)),
              background: i === 15 ? "var(--accent)" : "var(--secondary)",
            }}
          />
        ))}
      </div>
      <div
        style={{
          fontSize: 18,
          background: "var(--surface-soft)",
          borderRadius: 10,
          padding: "15px 18px",
          marginBottom: 9,
        }}
      >
        “Can I book a consultation?”
      </div>
      <div style={{ fontSize: 18, color: "var(--muted)", padding: "5px 18px" }}>
        “Let me check available times.”
      </div>
    </div>
  );
}

function ChannelsCard() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ ...card, minHeight: 260 }}>
      <div style={label}>
        <Check size={21} />
        Publish when you’re ready
      </div>
      <div style={{ display: "flex", gap: 15 }}>
        {[
          { Icon: Globe, title: "Website" },
          { Icon: Phone, title: "Phone" },
          { Icon: Code2, title: "Your API" },
        ].map(({ Icon, title }, index) => (
          <div
            key={title}
            style={{
              flex: 1,
              display: "grid",
              justifyItems: "center",
              gap: 14,
              padding: "28px 15px",
              border: "1px solid var(--line)",
              borderRadius: 13,
              fontSize: 18,
              opacity: interpolate(
                frame,
                [0.2 * fps + index * 5, 0.8 * fps + index * 5],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              ),
              translate: interpolate(
                frame,
                [0.2 * fps + index * 5, 0.8 * fps + index * 5],
                ["0px 10px", "0px 0px"],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
              ),
            }}
          >
            <Icon size={29} strokeWidth={1.4} />
            {title}
          </div>
        ))}
      </div>
    </div>
  );
}

function Progress() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div
      style={{
        position: "absolute",
        top: 37,
        left: 48,
        right: 48,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <AudioLines size={23} />
      <span style={{ fontSize: 17 }}>Phirmy</span>
      <div style={{ display: "flex", marginLeft: "auto", gap: 7 }}>
        {[0, 1, 2, 3].map((index) => (
          <i
            key={index}
            style={{
              width: 30,
              height: 3,
              borderRadius: 5,
              background:
                frame >= index * 4 * fps ? "var(--accent)" : "var(--line)",
            }}
          />
        ))}
      </div>
    </div>
  );
}

/** Illustrative product walkthrough. No network, account data or random frames. */
export default function AgentJourney() {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill
      style={{
        background: "var(--paper)",
        color: "var(--ink)",
        fontFamily: "var(--font-body), sans-serif",
      }}
    >
      <Progress />
      <Sequence from={0} durationInFrames={4 * fps} name="Connect knowledge">
        <Chapter
          number={1}
          title="Start with what you know."
          subtitle="Connect a website or upload your business documents."
        >
          <KnowledgeCard />
        </Chapter>
      </Sequence>
      <Sequence
        from={4 * fps}
        durationInFrames={4 * fps}
        name="Shape the agent"
      >
        <Chapter
          number={2}
          title="Make it sound like you."
          subtitle="Give your agent instructions, tools and a little context."
        >
          <AgentCard />
        </Chapter>
      </Sequence>
      <Sequence
        from={8 * fps}
        durationInFrames={4 * fps}
        name="Test the conversation"
      >
        <Chapter
          number={3}
          title="Try the conversation first."
          subtitle="Test in your browser, review, and make it better."
        >
          <ConversationCard />
        </Chapter>
      </Sequence>
      <Sequence
        from={12 * fps}
        durationInFrames={4 * fps}
        name="Publish to channels"
      >
        <Chapter
          number={4}
          title="Ready for the real world."
          subtitle="Publish, then connect your website or configured platforms."
        >
          <ChannelsCard />
        </Chapter>
      </Sequence>
      <div
        style={{
          position: "absolute",
          bottom: 37,
          left: 48,
          right: 48,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          color: "var(--muted)",
          fontSize: 13,
        }}
      >
        <span>Knowledge → Agent → Test → Publish</span>
        <ArrowRight size={19} />
      </div>
    </AbsoluteFill>
  );
}
