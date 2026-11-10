// Grow the viewport until the dashboard content fits in it. Grafana lazily renders panels inside its
// own scroll container, so each growth can reveal more panels; a layout that keeps growing past
// `attempts` is refused rather than captured partially.
export async function settleViewport({ measure, resize, initialHeight, attempts = 12 }) {
  let viewport = initialHeight;
  for (let i = 0; i <= attempts; i += 1) {
    const content = await measure();
    // A full-height layout reports the viewport itself, so "fits" rather than "unchanged" is the test.
    if (content <= viewport) return viewport;
    // The last pass only re-measures after the final resize; it never grows the viewport again.
    if (i === attempts) break;
    viewport = content;
    await resize(viewport);
  }
  throw new Error(`dashboard height did not settle (last ${viewport}px); not capturing a partial page`);
}
