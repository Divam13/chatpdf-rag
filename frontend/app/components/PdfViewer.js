"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

import styles from "./PdfViewer.module.css";

// The worker must be configured in the same module that uses <Document>.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const DOC_OPTIONS = {
  // Disable auto-fetch of resources that need extra CORS configuration.
  disableAutoFetch: true,
  disableStream: false,
};

/**
 * Renders a PDF inside a scrollable column, scaled to the container width.
 * When `highlight` is provided ({page, bbox:[x0,y0,x1,y1], page_width, page_height}),
 * the matching page scrolls into view and a coloured rectangle is overlaid.
 */
export default function PdfViewer({ fileUrl, highlight }) {
  const containerRef = useRef(null);
  const pageRefs = useRef({});
  const [numPages, setNumPages] = useState(0);
  const [containerWidth, setContainerWidth] = useState(800);
  const [error, setError] = useState(null);

  // Track the container width so pages render at the right scale.
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const observer = new ResizeObserver(([entry]) => {
      // Subtract a bit for padding/scrollbar.
      setContainerWidth(Math.max(320, entry.contentRect.width - 16));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Scroll to the highlighted page whenever a citation is clicked.
  useEffect(() => {
    if (!highlight || !numPages) return;
    const el = pageRefs.current[highlight.page];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [highlight, numPages]);

  const onLoadSuccess = useCallback(({ numPages }) => {
    setNumPages(numPages);
    setError(null);
  }, []);

  const onLoadError = useCallback((err) => {
    console.error("[PdfViewer] load error:", err);
    setError(err?.message || "Failed to load PDF.");
  }, []);

  const file = useMemo(() => ({ url: fileUrl }), [fileUrl]);

  return (
    <div ref={containerRef} className={styles.viewer}>
      {error && (
        <div className={styles.errorBox}>
          <strong>Couldn&apos;t load this PDF.</strong>
          <span>{error}</span>
        </div>
      )}

      <Document
        file={file}
        onLoadSuccess={onLoadSuccess}
        onLoadError={onLoadError}
        options={DOC_OPTIONS}
        loading={<div className={styles.loading}>Loading PDF…</div>}
        error={null}
      >
        {Array.from({ length: numPages }, (_, idx) => {
          const pageNumber = idx + 1;
          const isHighlighted = highlight?.page === pageNumber;

          return (
            <div
              key={pageNumber}
              ref={(el) => {
                if (el) pageRefs.current[pageNumber] = el;
              }}
              className={styles.pageWrapper}
              data-page={pageNumber}
            >
              <Page
                pageNumber={pageNumber}
                width={containerWidth}
                renderAnnotationLayer={false}
                renderTextLayer={false}
              />
              {isHighlighted && (
                <Highlight
                  key={highlight.key ?? `${pageNumber}-default`}
                  bbox={highlight.bbox}
                  pdfWidth={highlight.page_width}
                  pdfHeight={highlight.page_height}
                  renderedWidth={containerWidth}
                />
              )}
              <div className={styles.pageNumber}>Page {pageNumber}</div>
            </div>
          );
        })}
      </Document>
    </div>
  );
}

/**
 * Draws a translucent rectangle on top of a rendered page using the bbox
 * supplied by the backend (PDF points). PyMuPDF's y-axis grows downward,
 * which matches react-pdf's rendered canvas — so no Y inversion is needed.
 */
function Highlight({ bbox, pdfWidth, pdfHeight, renderedWidth }) {
  if (!bbox || bbox.length !== 4 || !pdfWidth || !pdfHeight) return null;
  const scale = renderedWidth / pdfWidth;
  const [x0, y0, x1, y1] = bbox;
  const style = {
    left: x0 * scale,
    top: y0 * scale,
    width: Math.max(2, (x1 - x0) * scale),
    height: Math.max(2, (y1 - y0) * scale),
  };
  return <div className={styles.highlight} style={style} aria-hidden="true" />;
}
