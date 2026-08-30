import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { getScheme, Mood } from "../lib/colors";

type MapLocation = { label: string; lat: number; lon: number };
type MapConnection = { from: string; to: string; label?: string };

interface MapVisualProps {
    title: string;
    locations: MapLocation[];
    connections?: MapConnection[];
    mood: Mood;
}

const MAP_X = 90;
const MAP_Y = 360;
const MAP_W = 900;
const MAP_H = 1120;

function project(latRaw: number, lonRaw: number) {
    const lat = Math.max(-85, Math.min(85, Number(latRaw) || 0));
    const lon = Math.max(-180, Math.min(180, Number(lonRaw) || 0));
    return {
        x: MAP_X + ((lon + 180) / 360) * MAP_W,
        y: MAP_Y + ((85 - lat) / 170) * MAP_H,
    };
}

// Deliberately simplified continent silhouettes. Geographic claims come from
// the lat/lon points and connections, while these shapes provide immediate map
// orientation without a runtime tile/network dependency.
const LAND_PATHS = [
    "M135 610 L175 505 L260 445 L355 470 L405 560 L345 625 L285 650 L230 735 L165 705 Z",
    "M300 760 L355 790 L390 910 L355 1080 L310 1170 L275 1020 L260 865 Z",
    "M520 545 L585 500 L665 515 L710 555 L785 525 L930 575 L965 690 L865 740 L805 700 L730 765 L665 730 L620 655 L555 650 Z",
    "M555 700 L640 700 L700 790 L675 945 L610 1050 L555 925 L520 805 Z",
    "M825 1050 L910 1035 L965 1095 L930 1170 L845 1185 L800 1125 Z",
    "M470 520 L505 485 L540 515 L520 560 Z",
];

export const MapVisual: React.FC<MapVisualProps> = ({ title, locations = [], connections = [], mood }) => {
    const frame = useCurrentFrame();
    const scheme = getScheme(mood);
    const locs = locations.slice(0, 8);
    const byLabel = new Map(locs.map((l) => [String(l.label).toLowerCase(), l]));
    const reveal = interpolate(frame, [0, 18], [0, 1], { extrapolateRight: "clamp" });

    return (
        <AbsoluteFill style={{ background: scheme.backgroundGradient, color: scheme.textPrimary, fontFamily: "Inter, sans-serif" }}>
            <div style={{ position: "absolute", top: 110, left: 72, right: 72, textAlign: "center", fontWeight: 900, fontSize: 68, lineHeight: 1.08 }}>
                {title || "Where it happens"}
            </div>
            <div style={{ position: "absolute", top: MAP_Y - 40, left: MAP_X - 24, width: MAP_W + 48, height: MAP_H + 80, borderRadius: 38, background: "rgba(5,8,18,.54)", border: `2px solid ${scheme.secondary}55`, boxShadow: `0 24px 80px ${scheme.shadow}` }} />

            <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{ position: "absolute", inset: 0 }}>
                <defs>
                    <filter id="mapGlow"><feGaussianBlur stdDeviation="8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
                </defs>
                {[ -120, -60, 0, 60, 120 ].map((lon) => {
                    const p = project(0, lon);
                    return <line key={`lon-${lon}`} x1={p.x} y1={MAP_Y} x2={p.x} y2={MAP_Y + MAP_H} stroke="rgba(255,255,255,.08)" strokeWidth="2" />;
                })}
                {[ -60, -30, 0, 30, 60 ].map((lat) => {
                    const p = project(lat, 0);
                    return <line key={`lat-${lat}`} x1={MAP_X} y1={p.y} x2={MAP_X + MAP_W} y2={p.y} stroke="rgba(255,255,255,.08)" strokeWidth="2" />;
                })}
                <g opacity={0.34 + reveal * 0.16} fill={scheme.secondary} stroke={`${scheme.primary}66`} strokeWidth="2">
                    {LAND_PATHS.map((d, i) => <path key={i} d={d} />)}
                </g>

                {connections.slice(0, 8).map((c, i) => {
                    const a = byLabel.get(String(c.from).toLowerCase());
                    const b = byLabel.get(String(c.to).toLowerCase());
                    if (!a || !b) return null;
                    const p1 = project(a.lat, a.lon); const p2 = project(b.lat, b.lon);
                    const progress = interpolate(frame, [10 + i * 4, 30 + i * 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                    const len = Math.hypot(p2.x - p1.x, p2.y - p1.y);
                    return (
                        <g key={`${c.from}-${c.to}-${i}`}>
                            <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={scheme.accent} strokeWidth="7" strokeLinecap="round" strokeDasharray={len} strokeDashoffset={len * (1 - progress)} opacity={0.9} />
                            {c.label ? <text x={(p1.x + p2.x) / 2} y={(p1.y + p2.y) / 2 - 16} fill={scheme.textPrimary} fontSize="30" fontWeight="800" textAnchor="middle" stroke="rgba(0,0,0,.7)" strokeWidth="6" paintOrder="stroke">{c.label}</text> : null}
                        </g>
                    );
                })}

                {locs.map((l, i) => {
                    const p = project(l.lat, l.lon);
                    const scale = interpolate(frame, [8 + i * 3, 18 + i * 3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
                    return (
                        <g key={`${l.label}-${i}`} transform={`translate(${p.x} ${p.y}) scale(${scale})`} filter="url(#mapGlow)">
                            <circle r="19" fill={scheme.primary} stroke="#fff" strokeWidth="5" />
                            <circle r="38" fill="none" stroke={`${scheme.primary}77`} strokeWidth="5" />
                            <text x="0" y="-48" fill={scheme.textPrimary} fontSize="34" fontWeight="900" textAnchor="middle" stroke="rgba(0,0,0,.8)" strokeWidth="8" paintOrder="stroke">{l.label}</text>
                        </g>
                    );
                })}
            </svg>
            <div style={{ position: "absolute", bottom: 210, left: 120, right: 120, textAlign: "center", fontSize: 28, fontWeight: 700, color: scheme.textSecondary }}>
                Positions are rendered from latitude/longitude supplied by the visual plan.
            </div>
        </AbsoluteFill>
    );
};
