import { AbsoluteFill, Img, interpolate, useCurrentFrame } from "remotion";
import { getScheme, Mood } from "../lib/colors";

type Annotation = {
    label: string;
    x_pct: number;
    y_pct: number;
    w_pct?: number;
    h_pct?: number;
};

interface AnnotatedRealProps {
    imageUrl: string;
    imageWidth?: number;
    imageHeight?: number;
    title?: string;
    annotations: Annotation[];
    mood: Mood;
}

const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, Number(n) || 0));

export const AnnotatedReal: React.FC<AnnotatedRealProps> = ({ imageUrl, imageWidth = 1080, imageHeight = 1920, title = "", annotations = [], mood }) => {
    const frame = useCurrentFrame();
    const scheme = getScheme(mood);
    const iw = Math.max(1, Number(imageWidth) || 1080);
    const ih = Math.max(1, Number(imageHeight) || 1920);
    const maxW = 980;
    const maxH = title ? 1450 : 1580;
    const scale = Math.min(maxW / iw, maxH / ih);
    const displayW = iw * scale;
    const displayH = ih * scale;
    const left = (1080 - displayW) / 2;
    const top = (title ? 280 : 170) + Math.max(0, (maxH - displayH) / 2);
    const visible = annotations.slice(0, 6);

    return (
        <AbsoluteFill style={{ background: scheme.background, fontFamily: "Inter, sans-serif", color: scheme.textPrimary }}>
            <Img src={imageUrl} style={{ position: "absolute", inset: -30, width: 1140, height: 1980, objectFit: "cover", filter: "blur(34px) brightness(.42) saturate(.85)", transform: "scale(1.08)" }} />
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to bottom, rgba(5,7,15,.5), rgba(5,7,15,.16) 42%, rgba(5,7,15,.68))" }} />

            {title ? <div style={{ position: "absolute", top: 92, left: 60, right: 60, textAlign: "center", fontSize: 58, fontWeight: 900, lineHeight: 1.08, textShadow: "0 4px 18px rgba(0,0,0,.75)" }}>{title}</div> : null}

            <div style={{ position: "absolute", left, top, width: displayW, height: displayH, borderRadius: 28, overflow: "hidden", boxShadow: "0 28px 90px rgba(0,0,0,.48)", border: "2px solid rgba(255,255,255,.18)" }}>
                <Img src={imageUrl} style={{ width: "100%", height: "100%", objectFit: "fill" }} />
            </div>

            {visible.map((a, i) => {
                const xPct = clamp(a.x_pct, 0, 100);
                const yPct = clamp(a.y_pct, 0, 100);
                const wPct = clamp(a.w_pct ?? 16, 3, 55);
                const hPct = clamp(a.h_pct ?? 12, 3, 55);
                const cx = left + (xPct / 100) * displayW;
                const cy = top + (yPct / 100) * displayH;
                const bw = (wPct / 100) * displayW;
                const bh = (hPct / 100) * displayH;
                const enter = interpolate(frame, [8 + i * 5, 20 + i * 5], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                const labelLeft = clamp(cx - 180, 34, 686);
                const labelTop = clamp(cy - bh / 2 - 92, 220, 1680);
                return (
                    <div key={`${a.label}-${i}`} style={{ opacity: enter }}>
                        <div style={{ position: "absolute", left: cx - bw / 2, top: cy - bh / 2, width: bw, height: bh, border: `6px solid ${scheme.primary}`, borderRadius: 22, boxShadow: `0 0 0 4px rgba(0,0,0,.48), 0 0 34px ${scheme.shadow}`, transform: `scale(${0.9 + enter * 0.1})` }} />
                        <div style={{ position: "absolute", left: labelLeft, top: labelTop, maxWidth: 360, padding: "13px 20px", borderRadius: 18, background: "rgba(4,6,12,.88)", border: `2px solid ${scheme.primary}aa`, fontSize: 30, lineHeight: 1.08, fontWeight: 900, boxShadow: "0 10px 28px rgba(0,0,0,.42)" }}>{a.label}</div>
                        <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
                            <line x1={labelLeft + 180} y1={labelTop + 58} x2={cx} y2={cy - bh / 2} stroke={scheme.primary} strokeWidth="5" strokeLinecap="round" />
                            <circle cx={cx} cy={cy} r="9" fill={scheme.primary} />
                        </svg>
                    </div>
                );
            })}

            <div style={{ position: "absolute", bottom: 90, left: 70, right: 70, textAlign: "center", fontSize: 25, fontWeight: 700, color: "rgba(255,255,255,.74)" }}>
                Callouts are positioned from visual verification of this exact image.
            </div>
        </AbsoluteFill>
    );
};
