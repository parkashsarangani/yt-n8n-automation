import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { getScheme, Mood } from "../lib/colors";

type DiagramNode = { id: string; label: string; detail?: string };
type DiagramEdge = { from: string; to: string; label?: string };

interface DiagramVisualProps {
    title: string;
    nodes: DiagramNode[];
    edges?: DiagramEdge[];
    mood: Mood;
}

function layout(nodes: DiagramNode[]) {
    const out = new Map<string, { x: number; y: number }>();
    const items = nodes.slice(0, 8);
    const cols = items.length <= 4 ? 1 : 2;
    const rows = Math.ceil(items.length / cols);
    items.forEach((n, i) => {
        const col = cols === 1 ? 0 : i % 2;
        const row = cols === 1 ? i : Math.floor(i / 2);
        const x = cols === 1 ? 540 : (col === 0 ? 300 : 780);
        const y = 410 + (rows <= 1 ? 0 : row * (1030 / Math.max(1, rows - 1)));
        out.set(String(n.id), { x, y });
    });
    return out;
}

export const DiagramVisual: React.FC<DiagramVisualProps> = ({ title, nodes = [], edges = [], mood }) => {
    const frame = useCurrentFrame();
    const scheme = getScheme(mood);
    const items = nodes.slice(0, 8);
    const positions = layout(items);

    return (
        <AbsoluteFill style={{ background: scheme.backgroundGradient, color: scheme.textPrimary, fontFamily: "Inter, sans-serif" }}>
            <div style={{ position: "absolute", top: 100, left: 72, right: 72, textAlign: "center", fontWeight: 900, fontSize: 66, lineHeight: 1.08 }}>
                {title || "How it connects"}
            </div>
            <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{ position: "absolute", inset: 0 }}>
                <defs>
                    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto"><path d="M0,0 L12,6 L0,12 z" fill={scheme.accent}/></marker>
                </defs>
                {edges.slice(0, 12).map((e, i) => {
                    const a = positions.get(String(e.from)); const b = positions.get(String(e.to));
                    if (!a || !b) return null;
                    const progress = interpolate(frame, [7 + i * 3, 27 + i * 3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                    const len = Math.hypot(b.x - a.x, b.y - a.y);
                    return (
                        <g key={`${e.from}-${e.to}-${i}`}>
                            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={scheme.accent} strokeWidth="7" strokeLinecap="round" markerEnd="url(#arrow)" strokeDasharray={len} strokeDashoffset={len * (1 - progress)} opacity="0.9" />
                            {e.label ? <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 18} textAnchor="middle" fill={scheme.textSecondary} fontSize="28" fontWeight="800" stroke="rgba(0,0,0,.8)" strokeWidth="7" paintOrder="stroke">{e.label}</text> : null}
                        </g>
                    );
                })}
            </svg>

            {items.map((node, i) => {
                const p = positions.get(String(node.id))!;
                const enter = interpolate(frame, [5 + i * 4, 19 + i * 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                return (
                    <div key={String(node.id)} style={{ position: "absolute", left: p.x - 205, top: p.y - 86, width: 410, minHeight: 172, padding: "28px 28px", borderRadius: 30, background: "rgba(10,13,24,.86)", border: `3px solid ${scheme.primary}88`, boxShadow: `0 20px 55px rgba(0,0,0,.35), 0 0 32px ${scheme.shadow}`, opacity: enter, transform: `scale(${0.84 + enter * 0.16})` }}>
                        <div style={{ fontSize: 40, fontWeight: 900, lineHeight: 1.08, textAlign: "center" }}>{node.label}</div>
                        {node.detail ? <div style={{ marginTop: 12, fontSize: 26, lineHeight: 1.22, fontWeight: 650, textAlign: "center", color: scheme.textSecondary }}>{node.detail}</div> : null}
                    </div>
                );
            })}

            <div style={{ position: "absolute", bottom: 160, left: 100, right: 100, textAlign: "center", color: scheme.textSecondary, fontSize: 29, fontWeight: 700 }}>
                Nodes and relationships are rendered from structured template data, not symbolic stock footage.
            </div>
        </AbsoluteFill>
    );
};
