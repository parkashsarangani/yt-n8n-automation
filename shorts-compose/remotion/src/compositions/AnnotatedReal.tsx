import { AbsoluteFill, Img } from "remotion";
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
    annotations?: Annotation[];
    mood: Mood;
}

/**
 * Render a vision-verified real image as a clean evidence frame.
 *
 * `title` and `annotations` deliberately remain in the public props contract for
 * backwards compatibility with already-produced workflow payloads. They are not
 * rendered: the previous implementation exposed internal VLM verification data
 * as large bounding boxes, labels, connector lines and a diagnostic footer.
 * Those diagnostics are useful to the resolver, but they are not audience-facing
 * editorial graphics and must never leak into the final Short.
 */
export const AnnotatedReal: React.FC<AnnotatedRealProps> = ({
    imageUrl,
    imageWidth = 1080,
    imageHeight = 1920,
    mood,
}) => {
    const scheme = getScheme(mood);
    const iw = Math.max(1, Number(imageWidth) || 1080);
    const ih = Math.max(1, Number(imageHeight) || 1920);

    // Preserve the complete verified image instead of cropping away the very
    // detail the resolver selected it for. The blurred copy behind it fills the
    // 9:16 canvas without introducing black bars.
    const maxW = 1030;
    const maxH = 1760;
    const scale = Math.min(maxW / iw, maxH / ih);
    const displayW = iw * scale;
    const displayH = ih * scale;
    const left = (1080 - displayW) / 2;
    const top = (1920 - displayH) / 2;

    return (
        <AbsoluteFill style={{ background: scheme.background }}>
            <Img
                src={imageUrl}
                style={{
                    position: "absolute",
                    inset: -40,
                    width: 1160,
                    height: 2000,
                    objectFit: "cover",
                    filter: "blur(38px) brightness(.46) saturate(.86)",
                    transform: "scale(1.08)",
                }}
            />
            <div
                style={{
                    position: "absolute",
                    inset: 0,
                    background: "linear-gradient(to bottom, rgba(5,7,15,.34), rgba(5,7,15,.08) 42%, rgba(5,7,15,.52))",
                }}
            />

            <div
                style={{
                    position: "absolute",
                    left,
                    top,
                    width: displayW,
                    height: displayH,
                    borderRadius: 26,
                    overflow: "hidden",
                    boxShadow: "0 26px 88px rgba(0,0,0,.44)",
                    border: "2px solid rgba(255,255,255,.16)",
                    background: scheme.background,
                }}
            >
                <Img
                    src={imageUrl}
                    style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}
                />
            </div>
        </AbsoluteFill>
    );
};
