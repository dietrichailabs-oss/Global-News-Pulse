// Presentation only: the provider creates and controls the original player.
// No URL, iframe source, request header, media source, or account state changes.
(() => {
    "use strict";

    if (window.top !== window) return { applied: false, reason: "child_frame" };
    const documents = new Map([
        ["https://widget.coastalcoms.com/video/005972b5-8290-420c-8527-9ce69bbcd2ec", "coastalcoms"],
        ["https://widget.coastalcoms.com/video/e53407e0-915b-4964-b60a-638e1bd32d6d", "coastalcoms"],
        // Use the working public page, not the unavailable standalone embed.
        ["https://www.ipcamlive.com/bsyc1080", "ipcam_public"],
    ]);
    const documentUrl = new URL(window.location.href);
    documentUrl.hash = "";
    const view = documents.get(documentUrl.href);
    if (!view) return { applied: false, reason: "unapproved_document" };

    const styleId = "global-pulse-camera-player-view";
    const coastalStyles = `
        html, body {
            box-sizing: border-box !important;
            width: 100% !important; height: 100% !important; min-height: 0 !important;
            margin: 0 !important; padding: 0 !important; background: #000 !important;
        }
        body { display: flex !important; flex-direction: column !important; overflow: auto !important; }
        #page-content {
            box-sizing: border-box !important;
            display: flex !important; flex-direction: column !important;
            flex: 1 1 0% !important; min-height: 0 !important;
            width: 100% !important; max-width: none !important;
            margin: 0 !important; padding: 0 !important;
        }
        #page-content > #player-area {
            box-sizing: border-box !important;
            flex: 1 1 0% !important; min-height: 0 !important;
            width: 100% !important; height: auto !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important; padding: 0 !important; background: #000 !important;
        }
        #player-area #video {
            box-sizing: border-box !important;
            width: 100% !important; height: 100% !important;
            min-height: 0 !important; max-height: none !important;
            margin: 0 !important; padding: 0 !important; object-fit: contain !important;
        }
        #player-area #video .vjs-tech { object-fit: contain !important; }
        /* Keep the provider's availability notice in the layout and readable. */
        #page-content > .alert {
            box-sizing: border-box !important; flex: 0 0 auto !important;
            max-width: 100% !important; margin: 0 !important; padding: 6px 10px !important;
            background: #13212e !important; color: #e6edf3 !important;
            font-size: 12px !important; line-height: 1.35 !important;
            overflow-wrap: anywhere !important;
        }
    `;
    const publicPageStyles = `
        html, body {
            box-sizing: border-box !important;
            width: 100% !important; height: 100% !important;
            margin: 0 !important; padding: 0 !important;
            overflow: hidden !important; background: #000 !important;
        }
        /* These are the observed navigation/header/footer, never generic dialogs. */
        body.page--player > .wrap.wrap--black,
        body.page--player > .wrap--footer { display: none !important; }
        /* The provider uses this header's width when it constructs its iframe. */
        body.page--player > .section-content > .wrap.wrap--gray-lightest { visibility: hidden !important; }
        #playerdiv {
            box-sizing: border-box !important;
            position: fixed !important; inset: 0 !important; z-index: 1 !important;
            width: 100vw !important; height: 100vh !important;
            min-width: 0 !important; min-height: 0 !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important; padding: 0 !important; background: #000 !important;
        }
        /* It may be created later or resized by provider code; keep that DOM intact. */
        #playerdiv #playeriframe {
            box-sizing: border-box !important; display: block !important;
            width: 100% !important; height: 100% !important;
            max-width: none !important; max-height: none !important;
            margin: 0 !important; padding: 0 !important; border: 0 !important;
        }
    `;

    function apply() {
        const currentUrl = new URL(window.location.href);
        currentUrl.hash = "";
        if (window.top !== window || documents.get(currentUrl.href) !== view)
            return { applied: false, reason: "unapproved_document" };
        // A changed provider layout falls back to its untouched original page.
        const target = view === "coastalcoms"
            ? document.querySelector("#page-content > #player-area #video")
            : document.querySelector("body.page--player > .section-content > section.section--live > #playerdiv");
        if (!target || !document.head) return { applied: false, reason: "player_missing" };
        const styles = view === "coastalcoms" ? coastalStyles : publicPageStyles;
        let style = document.getElementById(styleId);
        if (style && style.tagName !== "STYLE") return { applied: false, reason: "style_conflict" };
        if (!style) {
            style = document.createElement("style");
            style.id = styleId;
            style.textContent = styles;
            document.head.appendChild(style);
        } else if (style.textContent !== styles) {
            style.textContent = styles;
        }
        document.documentElement.setAttribute("data-global-pulse-player-view", view);
        return { applied: true, view };
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", apply, { once: true });
        return { applied: false, reason: "document_loading" };
    }
    return apply();
})();
