// Sending the MCP Map out (D26), all in the browser: nothing leaves the machine until you share the file.

export function svgText(svg: SVGSVGElement): string {
  return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(svg)}`;
}

export function download(name: string, data: Blob | string, type = "text/plain") {
  const blob = typeof data === "string" ? new Blob([data], { type }) : data;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The SVG painted onto a canvas at `scale`× for slides and chat. Fonts fall back to the system's: an SVG drawn as
 * an image can't load web fonts. */
export function toPng(svg: SVGSVGElement, scale = 2): Promise<Blob> {
  const { width, height } = svg.viewBox.baseVal;
  const url = URL.createObjectURL(new Blob([svgText(svg)], { type: "image/svg+xml" }));
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return reject(new Error("This browser can't draw a PNG."));
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("This browser can't draw a PNG."))), "image/png");
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("The map couldn't be drawn as a PNG.")); };
    img.src = url;
  });
}

/** A file name from the app's name: "trip-planner-mcp-map.svg". */
export const fileName = (app: string, ext: string) =>
  `${app.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "app"}-mcp-map.${ext}`;
