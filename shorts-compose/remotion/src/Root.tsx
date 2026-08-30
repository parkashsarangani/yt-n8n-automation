import { Composition } from "remotion";
import { StatReveal } from "./compositions/StatReveal";
import { Comparison } from "./compositions/Comparison";
import { KineticText } from "./compositions/KineticText";
import { MapVisual } from "./compositions/MapVisual";
import { TimelineVisual } from "./compositions/TimelineVisual";
import { DiagramVisual } from "./compositions/DiagramVisual";
import { AnnotatedReal } from "./compositions/AnnotatedReal";
import { CaptionOverlay } from "./compositions/CaptionOverlay";
import { SceneTransition } from "./compositions/SceneTransition";

export const RemotionRoot: React.FC = () => {
    return (
        <>
            <Composition
                id="StatReveal"
                component={StatReveal}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    statValue: "3.5x",
                    label: "MORE VIEWS",
                    icon: "activity",
                    mood: "upbeat" as const,
                }}
            />
            <Composition
                id="Comparison"
                component={Comparison}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    leftLabel: "BEFORE",
                    leftValue: "$100",
                    rightLabel: "AFTER",
                    rightValue: "$10,000",
                    mood: "upbeat" as const,
                }}
            />
            <Composition
                id="KineticText"
                component={KineticText}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    line: "This changes everything",
                    mood: "serious" as const,
                }}
            />
            <Composition
                id="MapVisual"
                component={MapVisual}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    title: "Where it happens",
                    locations: [
                        { label: "A", lat: 30, lon: -20 },
                        { label: "B", lat: 10, lon: 70 },
                    ],
                    connections: [{ from: "A", to: "B" }],
                    mood: "serious" as const,
                }}
            />
            <Composition
                id="TimelineVisual"
                component={TimelineVisual}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    title: "How it unfolded",
                    events: [
                        { date: "1900", label: "First event" },
                        { date: "2000", label: "Second event" },
                    ],
                    mood: "serious" as const,
                }}
            />
            <Composition
                id="DiagramVisual"
                component={DiagramVisual}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    title: "How it connects",
                    nodes: [
                        { id: "a", label: "Cause" },
                        { id: "b", label: "Effect" },
                    ],
                    edges: [{ from: "a", to: "b" }],
                    mood: "neutral" as const,
                }}
            />
            <Composition
                id="AnnotatedReal"
                component={AnnotatedReal}
                durationInFrames={120}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    imageUrl: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1080' height='1920'%3E%3Crect width='100%25' height='100%25' fill='%23141428'/%3E%3C/svg%3E",
                    imageWidth: 1080,
                    imageHeight: 1920,
                    title: "Look here",
                    annotations: [{ label: "Key detail", x_pct: 50, y_pct: 50, w_pct: 22, h_pct: 16 }],
                    mood: "neutral" as const,
                }}
            />
            <Composition
                id="CaptionOverlay"
                component={CaptionOverlay}
                durationInFrames={900}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    words: [] as Array<{ text: string; start: number; end: number }>,
                    commentHook: "",
                    totalDuration: 30,
                }}
            />
            <Composition
                id="SceneTransition"
                component={SceneTransition}
                durationInFrames={12}
                fps={30}
                width={1080}
                height={1920}
                defaultProps={{
                    type: "crossfade" as const,
                }}
            />
        </>
    );
};
