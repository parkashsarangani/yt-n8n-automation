import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { getScheme, Mood } from "../lib/colors";

type TimelineEvent = { date: string; label: string; detail?: string };

interface TimelineVisualProps {
    title: string;
    events: TimelineEvent[];
    mood: Mood;
}

export const TimelineVisual: React.FC<TimelineVisualProps> = ({ title, events = [], mood }) => {
    const frame = useCurrentFrame();
    const scheme = getScheme(mood);
    const rows = events.slice(0, 7);
    const startY = 390;
    const endY = 1490;
    const step = rows.length > 1 ? (endY - startY) / (rows.length - 1) : 0;
    const lineProgress = interpolate(frame, [4, 34], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

    return (
        <AbsoluteFill style={{ background: scheme.backgroundGradient, color: scheme.textPrimary, fontFamily: "Inter, sans-serif" }}>
            <div style={{ position: "absolute", top: 105, left: 72, right: 72, textAlign: "center", fontSize: 68, fontWeight: 900, lineHeight: 1.08 }}>
                {title || "How it unfolded"}
            </div>
            <div style={{ position: "absolute", left: 196, top: startY, width: 10, height: (endY - startY) * lineProgress, borderRadius: 20, background: `linear-gradient(${scheme.primary}, ${scheme.accent})`, boxShadow: `0 0 28px ${scheme.shadow}` }} />

            {rows.map((event, i) => {
                const y = startY + i * step;
                const enter = interpolate(frame, [8 + i * 5, 22 + i * 5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                return (
                    <div key={`${event.date}-${i}`} style={{ position: "absolute", left: 0, right: 0, top: y - 72, height: 144, opacity: enter, transform: `translateX(${(1 - enter) * 70}px)` }}>
                        <div style={{ position: "absolute", left: 171, top: 48, width: 60, height: 60, borderRadius: "50%", background: scheme.primary, border: "6px solid rgba(255,255,255,.92)", boxShadow: `0 0 30px ${scheme.shadow}` }} />
                        <div style={{ position: "absolute", left: 280, top: 2, width: 690, minHeight: 132, padding: "22px 28px", borderRadius: 28, background: "rgba(10,13,24,.72)", border: `2px solid ${scheme.secondary}55`, boxShadow: "0 18px 48px rgba(0,0,0,.28)" }}>
                            <div style={{ fontSize: 31, fontWeight: 900, color: scheme.primary, letterSpacing: 1.2 }}>{event.date}</div>
                            <div style={{ marginTop: 8, fontSize: 43, fontWeight: 900, lineHeight: 1.08 }}>{event.label}</div>
                            {event.detail ? <div style={{ marginTop: 8, fontSize: 27, fontWeight: 650, color: scheme.textSecondary, lineHeight: 1.25 }}>{event.detail}</div> : null}
                        </div>
                    </div>
                );
            })}

            <div style={{ position: "absolute", bottom: 180, left: 100, right: 100, textAlign: "center", color: scheme.textSecondary, fontSize: 29, fontWeight: 700 }}>
                Ordered events, rendered deterministically from the scene contract.
            </div>
        </AbsoluteFill>
    );
};
